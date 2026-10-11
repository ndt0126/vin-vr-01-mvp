"""Viec 8: model anh THAT theo chuan ModelPackage (backend triton-onnx-v1, preprocess image-rgb-unit-v1)."""
import io
import json
import shutil
import sys
import unittest
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'tools'))
import build_triton_repo as btr  # noqa: E402
import make_heavy_fixture as mh  # noqa: E402
import inspection_api as ra  # noqa: E402
from test_contract import Base, FakeKServe, b64, submit_body  # noqa: E402

try:
    import onnxruntime  # noqa: F401
    HAVE_ORT = True
except ImportError:  # pragma: no cover
    HAVE_ORT = False

vd = btr.validate_design


def color_png(rgb, size=40):
    b = io.BytesIO()
    Image.new('RGB', (size, size), rgb).save(b, 'PNG')
    return b.getvalue()


class HeavyBase(Base):
    registry_copy = True

    def setUp(self):
        super().setUp()
        self.info = mh.make_preset(self.examples, 'tiny')
        self.server.close()
        self.backend = None
        self.start(backend=self.make_backend())

    def make_backend(self):
        return ra.StubBackend()


class TestHeavyPackageStandard(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix='heavy-'))
        self.examples = self.tmp / 'examples'
        shutil.copytree(btr.PACKAGES_ROOT / 'examples', self.examples)
        self.info = mh.make_preset(self.examples, 'tiny')
        self.manifest = self.examples / 'packages' / 'model-heavy' / 'manifest.json'
        self.config = vd.parse(vd.read(self.examples / 'site-config.json'))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, fn):
        m = json.loads(self.manifest.read_text())
        fn(m)
        self.manifest.write_text(json.dumps(m))

    def code(self):
        try:
            vd.validate_package(self.manifest, self.config)
            return 'ACCEPTED'
        except vd.Rejected as exc:
            return exc.code

    def test_generated_model_is_deterministic_and_pinned(self):
        again = mh.conv_score_onnx(2, 4, 32)
        self.assertEqual(mh.sha(again), mh.PRESETS['tiny']['onnx_sha256'])
        self.assertEqual(self.info['onnx_sha256'], mh.PRESETS['tiny']['onnx_sha256'])

    def test_valid_package_is_accepted_and_original_site_config_untouched(self):
        self.assertEqual(self.code(), 'ACCEPTED')
        original = json.loads((btr.PACKAGES_ROOT / 'examples' / 'site-config.json').read_text())
        self.assertEqual(original['policy']['allowed_preprocess'], ['tensor-json-v1'])  # ban goc khong cho phep model anh

    def test_package_is_rejected_where_the_site_does_not_allow_it(self):
        strict = vd.parse(vd.read(btr.PACKAGES_ROOT / 'examples' / 'site-config.json'))
        with self.assertRaises(vd.Rejected) as ctx:
            vd.validate_package(self.manifest, strict)
        self.assertEqual(ctx.exception.code, 'E_RUNTIME')

    def test_rejections_with_reason(self):
        (self.manifest.parent / 'model.onnx').write_bytes(b'\x08' + b'x' * 100)
        self.assertEqual(self.code(), 'E_CHECKSUM')

    def test_reject_wrong_io_resources_and_golden(self):
        cases = {
            'E_IO': lambda m: m['io']['input'].update(shape=[1, 1, 32, 32]),
            'E_LIMIT': lambda m: m['io']['input'].update(shape=[1, 3, 2048, 2048]),
            'E_RESOURCE': lambda m: m['resources'].update(peak_vram_mib=4096),
            'E_TRANSFORM': lambda m: m.update(preprocess='tensor-json-v1'),
            'E_SCHEMA': lambda m: m['golden'].update(expected_score=1.5),
        }
        original = self.manifest.read_text()
        for want, fn in cases.items():
            self.manifest.write_text(original)
            self.edit(fn)
            self.assertEqual(self.code(), want)

    def test_triton_repository_entry(self):
        out = self.tmp / 'repo'
        accepted, rejected = btr.build(self.examples / 'packages', out, 'KIND_CPU')
        self.assertEqual(rejected, [])
        self.assertIn('model-heavy', [m['name'] for m in accepted])
        cfg = (out / 'model-heavy' / 'config.pbtxt').read_text()
        self.assertIn('data_type: TYPE_UINT8, dims: [1, 3, 32, 32]', cfg)
        self.assertIn('kind: KIND_CPU', cfg)
        self.assertEqual(mh.sha((out / 'model-heavy' / '1' / 'model.onnx').read_bytes()), self.info['onnx_sha256'])
        self.assertTrue((out / 'model-a' / '1' / 'model.onnx').is_file())  # package cu van duoc dung

    def test_gpu_variant_declares_vram_and_gpu_instance(self):
        info = mh.make_preset(self.examples, 'tiny', 'nvidia-gpu')
        self.config = vd.parse(vd.read(self.examples / 'site-config.json'))
        self.assertEqual(self.code(), 'ACCEPTED')
        out = self.tmp / 'repo'
        btr.build(self.examples / 'packages', out, 'KIND_CPU')
        self.assertIn('kind: KIND_GPU', (out / 'model-heavy' / 'config.pbtxt').read_text())  # theo device cua package
        self.assertEqual(info['device'], 'nvidia-gpu')


@unittest.skipUnless(HAVE_ORT, 'onnxruntime not installed')
class TestHeavyEndToEnd(HeavyBase):
    def test_activate_golden_and_inspect_with_real_image_model(self):
        act = self.activate('recipe-heavy').body
        self.assertTrue(act['golden']['passed'])
        self.assertAlmostEqual(act['golden']['actual'], mh.PRESETS['tiny']['expected'], delta=0.002)
        scores = {}
        for name, rgb in (('dark', (5, 5, 5)), ('bright', (250, 250, 250))):
            rid = f'heavy-{name}'
            body = submit_body(rid, product=f'PCB1-SN-{name}', recipe='recipe-heavy@0.1.0', image=color_png(rgb))
            self.assertEqual(self.submit(body).status, 202)
            self.assertEqual(self.wait_terminal(rid).body['state'], 'COMPLETED')
            res = self.result(rid).body
            self.assertEqual(res['lineage']['model']['name'], 'model-heavy')
            expected = mh.run_onnx((self.examples / 'packages' / 'model-heavy' / 'model.onnx').read_bytes(),
                                   mh.rgb_chw_uint8(color_png(rgb), 32), 32)
            self.assertAlmostEqual(res['score'], expected, delta=1e-5)
            scores[name] = res['score']
        self.assertNotEqual(scores['dark'], scores['bright'])  # model thuc su nhin anh

    def test_switch_between_linear_and_image_models_keeps_pinning(self):
        self.backend.delay_s = 0.2
        self.submit(submit_body('mix-a'))                       # pin model-a (tuyen tinh)
        self.wait_state('mix-a', 'PROCESSING')
        self.backend.delay_s = 0
        self.activate('recipe-heavy')
        self.submit(submit_body('mix-h', product='PCB1-SN-0002', recipe='recipe-heavy@0.1.0', image=color_png((9, 99, 199))))
        self.assertEqual(self.wait_terminal('mix-a').body['state'], 'COMPLETED')
        self.assertEqual(self.wait_terminal('mix-h').body['state'], 'COMPLETED')
        self.assertEqual(self.result('mix-a').body['lineage']['model']['name'], 'model-a')
        self.assertEqual(self.result('mix-h').body['lineage']['model']['name'], 'model-heavy')
        self.activate('recipe-a')
        self.restart(backend=ra.StubBackend())
        self.assertEqual(self.result('mix-h').body['state'], 'COMPLETED')


class TestVramProbeFixture(unittest.TestCase):
    """model-vram: fixture tiem loi cho bai G6 (OOM giua luc suy luan). Bo nho cap theo ANH, diem khong doi."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp(prefix='vram-'))
        self.examples = self.tmp / 'examples'
        shutil.copytree(btr.PACKAGES_ROOT / 'examples', self.examples)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pinned_and_accepted_as_a_standard_package(self):
        info = mh.make_vram_probe(self.examples, 'nvidia-gpu')
        self.assertEqual(info['onnx_sha256'], mh.VRAM_PROBE['onnx_sha256'])
        self.assertEqual(info['mib_per_level'], 16)
        out = self.tmp / 'repo'
        accepted, rejected = btr.build(self.examples / 'packages', out, 'KIND_CPU')
        self.assertIn('model-vram', [m['name'] for m in accepted], rejected)
        self.assertIn('kind: KIND_GPU', (out / 'model-vram' / 'config.pbtxt').read_text())

    @unittest.skipUnless(HAVE_ORT, 'onnxruntime not installed')
    def test_memory_follows_the_darkest_pixel_and_score_does_not(self):
        import numpy as np
        import onnxruntime as ort
        probe = ort.InferenceSession(mh.vram_probe_onnx(expose_rows=True), providers=['CPUExecutionProvider'])
        rows = {}
        for gray in (0, 1, 7):
            score, r = probe.run(['SCORE', 'ROWS'], {'IMAGE': np.full((1, 3, 64, 64), gray, np.uint8)})
            rows[gray] = int(r[0])
            self.assertAlmostEqual(float(score[0]), 1 / (1 + 2.718281828459045 ** (0.5 - gray / 255)), places=5)
        self.assertEqual(rows, {0: 2048, 1: 4096, 7: 16384})          # (pixel nho nhat + 1) * 2048 hang x 1024 float
        golden = np.frombuffer(mh.rgb_chw_uint8(mh.golden_png(), 64), np.uint8).reshape(1, 3, 64, 64)
        self.assertEqual(int(probe.run(['ROWS'], {'IMAGE': golden})[0][0]), 2048)  # golden chi can 1 muc -> nap/warm-up nhe
        self.assertAlmostEqual(mh.run_onnx(mh.vram_probe_onnx(), golden.tobytes(), 64), mh.VRAM_PROBE['expected'], places=5)


@unittest.skipUnless(HAVE_ORT, 'onnxruntime not installed')
class TestVramProbeEndToEnd(HeavyBase):
    """Duong di cua bai G6 tren stack that (API + backend chay ONNX), tru phan het VRAM chi GPU moi co."""

    def setUp(self):
        Base.setUp(self)
        self.info = mh.make_preset(self.examples, 'tiny')
        self.probe = mh.make_vram_probe(self.examples, 'nvidia-gpu')   # dung device ma phien GPU dung
        self.server.close()
        self.backend = None
        self.start(backend=self.make_backend())

    def test_recipe_vram_activates_and_serves_light_and_heavier_images(self):
        act = self.activate('recipe-vram')
        self.assertEqual(act.status, 200, act.body)
        self.assertTrue(act.body['golden']['passed'])
        self.assertAlmostEqual(act.body['golden']['actual'], mh.VRAM_PROBE['expected'], delta=0.002)
        for gray in (0, 6):                                             # 16 MiB va 112 MiB tren CPU
            rid = f'vram-{gray}'
            body = submit_body(rid, product=f'PCB1-SN-V{gray}', recipe='recipe-vram@0.1.0', image=color_png((gray,) * 3))
            self.assertEqual(self.submit(body).status, 202)
            self.assertEqual(self.wait_terminal(rid).body['state'], 'COMPLETED')
            self.assertEqual(self.result(rid).body['lineage']['model']['name'], 'model-vram')
        self.assertEqual(self.activate('recipe-a').status, 200)          # buoc G6 ket thuc bang viec quay ve recipe-a


@unittest.skipUnless(HAVE_ORT, 'onnxruntime not installed')
class TestHeavyOverKServeBinary(HeavyBase):
    def make_backend(self):
        params = {n: json.loads((self.examples / 'packages' / n / 'model.json').read_text()) for n in ('model-a', 'model-b')}
        self.fake = FakeKServe(params)
        self.fake.onnx['model-heavy'] = str(self.examples / 'packages' / 'model-heavy' / 'model.onnx')
        return ra.KServeV2Backend(self.fake.url)

    def tearDown(self):
        super().tearDown()
        self.fake.close()

    def test_image_tensor_is_sent_as_kserve_binary_uint8(self):
        self.activate('recipe-heavy')
        self.submit(submit_body('bin-1', recipe='recipe-heavy@0.1.0', image=color_png((200, 30, 30), size=100)))
        self.assertEqual(self.wait_terminal('bin-1').body['state'], 'COMPLETED')
        call = [c for c in self.fake.calls if c['body']['id'] == 'bin-1'][0]
        self.assertEqual(call['path'], '/v2/models/model-heavy/infer')
        self.assertEqual(call['binary_bytes'], 3 * 32 * 32)  # anh 100x100 duoc resize ve 32x32, 3 kenh, uint8
        self.assertEqual(call['body']['inputs'][0]['datatype'], 'UINT8')
        self.assertEqual(call['body']['inputs'][0]['shape'], [1, 3, 32, 32])
        self.assertNotIn('data', call['body']['inputs'][0])   # khong gui JSON so thuc


if __name__ == '__main__':
    unittest.main()
