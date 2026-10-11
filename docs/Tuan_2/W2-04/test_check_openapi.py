"""Bo kiem tinh phai bat duoc spec sai (khong chi PASS voi spec dung)."""
import copy
import tempfile
import unittest
from pathlib import Path

import yaml

import check_openapi
import reference_api

GOOD = yaml.safe_load(check_openapi.HERE.joinpath('openapi.v1.yaml').read_text(encoding='utf-8'))


def run_with(mutate):
    doc = copy.deepcopy(GOOD)
    mutate(doc)
    with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False, encoding='utf-8') as fh:
        yaml.safe_dump(doc, fh, allow_unicode=True, sort_keys=False)
    try:
        out = check_openapi.run(Path(fh.name), server_module=reference_api)
    finally:
        Path(fh.name).unlink()
    return out['result'], {c['check'] for c in out['checks'] if c['result'] == 'FAIL'}


class TestChecker(unittest.TestCase):
    def test_good_spec_passes(self):
        self.assertEqual(run_with(lambda d: None), ('PASS', set()))

    def test_detects_missing_403(self):
        def m(d):
            del d['paths']['/v1/inspections']['post']['responses']['403']
        self.assertIn('operation_rules', run_with(m)[1])

    def test_detects_triton_passthrough_path(self):
        def m(d):
            d['paths']['/v2/models/{name}/infer'] = copy.deepcopy(d['paths']['/v1/admin/recipes'])
            d['paths']['/v2/models/{name}/infer']['get']['operationId'] = 'tritonInfer'
        self.assertIn('no_triton_internal_api_exposed', run_with(m)[1])

    def test_detects_tensor_field_in_business_schema(self):
        def m(d):
            d['components']['schemas']['InspectionSubmit']['properties']['inputs'] = {'type': 'array'}
        self.assertIn('no_triton_internal_api_exposed', run_with(m)[1])

    def test_detects_admin_op_on_inference_port(self):
        def m(d):
            d['paths']['/v1/admin/recipes']['servers'][0]['url'] = 'https://{edge_host}:8443'
        self.assertIn('operation_rules', run_with(m)[1])

    def test_detects_role_drift_between_spec_and_server(self):
        def m(d):
            d['paths']['/v1/inspections']['post']['x-roles'] = ['operator', 'admin']
        self.assertIn('spec_matches_reference_routes_and_roles', run_with(m)[1])

    def test_detects_invalid_example(self):
        def m(d):
            d['components']['examples']['SubmitPcb1']['value']['product_id'] = 'bad id/1'
        self.assertIn('examples_match_schemas', run_with(m)[1])

    def test_detects_non_problem_error_body(self):
        def m(d):
            d['components']['responses']['NotFound']['content'] = {'application/json': {'schema': {'type': 'object'}}}
        self.assertIn('operation_rules', run_with(m)[1])

    def test_detects_broken_ref(self):
        def m(d):
            d['paths']['/v1/inspections']['post']['responses']['429'] = {'$ref': '#/components/responses/Nope'}
        self.assertIn('all_refs_resolve', run_with(m)[1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
