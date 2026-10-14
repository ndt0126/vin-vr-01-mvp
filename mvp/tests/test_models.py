"""W3-02: package -> Triton model repository. Them model khong sua source; package sai bi tu choi co ly do."""
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tools'))
import build_triton_repo as btr  # noqa: E402

try:
    import numpy as np
    import onnxruntime as ort
except ImportError:  # pragma: no cover
    ort = None

EXAMPLES = btr.PACKAGES_ROOT / 'examples'


def sha(data):
    return hashlib.sha256(data).hexdigest()


class TestTritonRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='w302-'))
        self.examples = self.tmp / 'examples'
        shutil.copytree(EXAMPLES, self.examples)
        self.out = self.tmp / 'repo'

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, kind='KIND_CPU'):
        return btr.build(self.examples / 'packages', self.out, kind)

    def add_package(self, name, gain, bias):
        """Them mot package moi chi bang file du lieu (khong sua source)."""
        d = self.examples / 'packages' / name
        shutil.copytree(self.examples / 'packages' / 'model-a', d)
        model = json.dumps({'gain': gain, 'bias': bias}).encode()
        (d / 'model.json').write_bytes(model)
        m = json.loads((d / 'manifest.json').read_text())
        golden = json.loads((d / 'golden-input.json').read_text())
        m['name'] = name
        m['artifact']['sha256'] = sha(model)
        m['golden']['expected_score'] = min(1.0, max(0.0, gain * sum(golden) / 4 + bias))
        (d / 'manifest.json').write_text(json.dumps(m, indent=2))
        return d

    def test_two_sample_packages_become_triton_models(self):
        accepted, rejected = self.build()
        self.assertEqual([m['name'] for m in accepted], ['model-a', 'model-b'])
        self.assertEqual(rejected, [])
        for m in accepted:
            self.assertTrue((self.out / m['name'] / '1' / 'model.onnx').is_file())
            cfg = (self.out / m['name'] / 'config.pbtxt').read_text()
            self.assertIn('backend: "onnxruntime"', cfg)
            self.assertIn('kind: KIND_CPU', cfg)
            pkg = (self.examples / 'packages' / m['name'] / 'manifest.json').read_bytes()
            self.assertEqual(m['manifest_sha256'], sha(pkg))  # digest trong repo = digest package
        manifest = json.loads((self.out / 'REPO-MANIFEST.json').read_text())
        self.assertEqual(len(manifest['models']), 2)

    def test_rebuild_keeps_the_mounted_directory_and_untouched_files(self):
        self.build()
        before = (self.out.stat().st_ino, (self.out / 'model-a' / '1' / 'model.onnx').stat().st_ino)
        self.build()  # noi dung khong doi: khong dung toi file nao
        self.assertEqual(before, (self.out.stat().st_ino, (self.out / 'model-a' / '1' / 'model.onnx').stat().st_ino))
        self.add_package('model-c', 0.8, 0.1)
        self.build()  # noi dung doi: thay file ben trong nhung GIU thu muc (bind mount cua Triton con hieu luc)
        self.assertEqual(before[0], self.out.stat().st_ino)
        self.assertTrue((self.out / 'model-c' / '1' / 'model.onnx').is_file())
        self.assertFalse((self.out.parent / '.repo.building').exists())

    def test_gpu_placement_is_written_explicitly(self):
        accepted, _ = self.build('KIND_GPU')
        self.assertIn('kind: KIND_GPU', (self.out / 'model-a' / 'config.pbtxt').read_text())
        self.assertEqual({m['instance_kind'] for m in accepted}, {'KIND_GPU'})

    def test_slow_fixture_stays_on_cpu_when_models_go_to_gpu(self):
        shutil.copytree(Path(__file__).parent / 'fixtures' / 'slow' / 'packages' / 'model-slow',
                        self.examples / 'packages' / 'model-slow')
        accepted, rejected = self.build('KIND_GPU')
        self.assertEqual(rejected, [])
        kinds = {m['name']: m['instance_kind'] for m in accepted}
        self.assertEqual(kinds['model-slow'], 'KIND_CPU')  # fixture mo phong do cham: GPU qua nhanh (phien 14/10)
        self.assertEqual(kinds['model-a'], 'KIND_GPU')
        self.assertIn('kind: KIND_CPU', (self.out / 'model-slow' / 'config.pbtxt').read_text())

    def test_new_valid_package_is_added_without_source_change(self):
        self.add_package('model-c', 0.8, 0.1)
        accepted, rejected = self.build()
        self.assertEqual([m['name'] for m in accepted], ['model-a', 'model-b', 'model-c'])
        self.assertEqual(rejected, [])

    def test_invalid_packages_are_rejected_with_reason_and_left_out(self):
        bad = self.add_package('bad-checksum', 0.8, 0.1)
        (bad / 'model.json').write_text('{"gain": 0.7, "bias": 0.1}')  # artifact doi, checksum khong doi
        io = self.add_package('bad-io', 0.8, 0.1)
        m = json.loads((io / 'manifest.json').read_text())
        m['io']['input']['shape'] = [1, 3, 224, 224]
        (io / 'manifest.json').write_text(json.dumps(m))
        be = self.add_package('bad-backend', 0.8, 0.1)
        m = json.loads((be / 'manifest.json').read_text())
        m['runtime']['backend'] = 'tensorrt-plan-v1'
        (be / 'manifest.json').write_text(json.dumps(m))
        gd = self.add_package('bad-golden', 0.8, 0.1)
        m = json.loads((gd / 'manifest.json').read_text())
        m['golden']['expected_score'] = 0.9
        (gd / 'manifest.json').write_text(json.dumps(m))
        accepted, rejected = self.build()
        self.assertEqual([m['name'] for m in accepted], ['model-a', 'model-b'])
        codes = {r['package']: r['code'] for r in rejected}
        self.assertEqual(codes['bad-checksum'], 'E_CHECKSUM')
        self.assertEqual(codes['bad-io'], 'E_IO')
        self.assertEqual(codes['bad-golden'], 'E_GOLDEN')
        self.assertIn('bad-backend', codes)
        for name in codes:
            self.assertFalse((self.out / name).exists(), name)
            self.assertTrue(all(r['reason'] for r in rejected))

    @unittest.skipIf(ort is None, 'onnxruntime not installed')
    def test_onnx_output_equals_package_formula(self):
        self.add_package('model-c', 0.8, 0.1)
        self.build()
        for name in ('model-a', 'model-b', 'model-c'):
            params = json.loads((self.examples / 'packages' / name / 'model.json').read_text())
            sess = ort.InferenceSession((self.out / name / '1' / 'model.onnx').read_bytes(),
                                        providers=['CPUExecutionProvider'])
            for g in range(0, 256, 5):
                v = round(g / 255.0, 6)
                got = float(sess.run(['SCORE'], {'IMAGE': np.full((1, 1, 2, 2), v, dtype=np.float32)})[0][0])
                want = min(1.0, max(0.0, params['gain'] * v + params['bias']))
                self.assertAlmostEqual(got, want, delta=1e-6, msg=f'{name} gray {g}')


if __name__ == '__main__':
    unittest.main()
