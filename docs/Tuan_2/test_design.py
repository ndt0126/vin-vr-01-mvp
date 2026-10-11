"""Targeted draft admission checks; all mutations use temporary copies."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from validate_design import ROOT, Rejected, validate_bundle


class DraftChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'examples'
        shutil.copytree(ROOT / 'examples', self.root)

    def edit(self, rel, update):
        path = self.root / rel
        value = json.loads(path.read_text())
        update(value)
        path.write_text(json.dumps(value, indent=2) + '\n')
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def reject(self, code):
        with self.assertRaises(Rejected) as result:
            validate_bundle(self.root)
        self.assertEqual(result.exception.code, code, str(result.exception))

    def test_two_packages_and_recipes(self):
        result = validate_bundle(self.root)
        self.assertEqual(result['packages'], 2)
        self.assertEqual([(x['score'], x['decision']) for x in result['results']], [(0.375, 'OK'), (0.3125, 'NG')])

    def test_changed_artifact_checksum(self):
        (self.root / 'packages/model-a/model.json').write_text('{"gain": 2, "bias": 0}')
        self.reject('E_CHECKSUM')

    def test_wrong_io(self):
        self.edit('packages/model-a/manifest.json', lambda x: x['io']['input'].update(shape=[1, 3, 224, 224]))
        self.reject('E_IO')

    def test_unsupported_backend(self):
        self.edit('packages/model-a/manifest.json', lambda x: x['runtime'].update(backend='triton-onnx-v1'))
        self.reject('E_BACKEND')

    def test_wrong_golden_score(self):
        self.edit('packages/model-a/manifest.json', lambda x: x['golden'].update(expected_score=0.9))
        self.reject('E_GOLDEN')

    def test_path_traversal(self):
        self.edit('packages/model-a/manifest.json', lambda x: x['artifact'].update(path='../model-b/model.json'))
        self.reject('E_PATH')

    def test_symlink_artifact(self):
        path = self.root / 'packages/model-a/model.json'
        path.unlink()
        path.symlink_to('../model-b/model.json')
        self.reject('E_PATH')

    def test_missing_required_field(self):
        self.edit('packages/model-a/manifest.json', lambda x: x.pop('compatibility'))
        self.reject('E_SCHEMA')

    def test_wrong_package_reference(self):
        self.edit('recipes/recipe-a.json', lambda x: x['package'].update(manifest_sha256='0' * 64))
        self.reject('E_REFERENCE')

    def test_missing_rollback_package(self):
        self.edit('packages/model-b/manifest.json', lambda x: x['rollback_candidates'][0].update(name='missing-model'))
        self.reject('E_ROLLBACK')

    def test_missing_rollback_recipe(self):
        self.edit('recipes/recipe-b.json', lambda x: x['rollback_recipe'].update(name='missing-recipe'))
        self.reject('E_ROLLBACK')

    def test_resource_budget(self):
        self.edit('site-config.json', lambda x: x['capacity'].update(ram_mib=1))
        self.reject('E_RESOURCE')

    def test_production_is_not_silently_accepted(self):
        self.edit('site-config.json', lambda x: x.update(mode='production'))
        self.reject('E_PROTOTYPE_ONLY')

    def test_required_signature_is_not_skipped(self):
        self.edit('site-config.json', lambda x: x['policy'].update(require_signature=True))
        self.reject('E_SIGNATURE')

    def test_duplicate_package_identity(self):
        shutil.copytree(self.root / 'packages/model-a', self.root / 'packages/duplicate')
        self.reject('E_DUPLICATE')

    def test_add_supported_model_without_source_change(self):
        shutil.copytree(self.root / 'packages/model-b', self.root / 'packages/model-c')
        model = self.root / 'packages/model-c/model.json'
        model.write_text('{"gain": 2, "bias": 0}\n')
        model_sha = hashlib.sha256(model.read_bytes()).hexdigest()
        def change_package(x):
            x['name'] = 'model-c'
            x['artifact']['sha256'] = model_sha
            x['golden']['expected_score'] = 0.75
        digest = self.edit('packages/model-c/manifest.json', change_package)
        shutil.copyfile(self.root / 'recipes/recipe-b.json', self.root / 'recipes/recipe-c.json')
        def change_recipe(x):
            x['name'] = 'recipe-c'
            x['package'].update(name='model-c', manifest_sha256=digest)
        self.edit('recipes/recipe-c.json', change_recipe)
        result = validate_bundle(self.root)
        self.assertEqual(result['packages'], 3)
        self.assertEqual(result['results'][-1]['score'], 0.75)


if __name__ == '__main__':
    unittest.main(verbosity=2)
