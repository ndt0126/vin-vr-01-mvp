"""Mot lenh chay toan bo test cua MVP va ghi bao cao JSON.

Usage: python3 run_tests.py --output test-report.json
Gom: kiem tinh OpenAPI, contract/negative test (hop dong W2-04), test MVP (G1-G5 + lifecycle),
test model repository. Khong can GPU, Docker hay Internet. Khong thay cho smoke test voi Triton that.
"""
import argparse
import json
import platform
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path[:0] = [str(HERE), str(HERE.parent / 'backend')]


class Collect(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.passed = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.passed.append(test.id())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', default='test-report.json')
    args = ap.parse_args()
    import check_openapi
    import inspection_api
    static = check_openapi.run(server_module=inspection_api)
    static_fail = [c['check'] for c in static['checks'] if c['result'] != 'PASS']
    sys.path.insert(0, str(HERE.parent / 'tools'))
    import gen_api_docs
    docs_ok = gen_api_docs.OUT.is_file() and gen_api_docs.OUT.read_text(encoding='utf-8') == gen_api_docs.render()
    import gen_dashboard
    import gen_observability_docs
    generated = {'docs/API.md': docs_ok,
                 'docs/OBSERVABILITY.md': gen_observability_docs.OUT.is_file()
                 and gen_observability_docs.OUT.read_text(encoding='utf-8') == gen_observability_docs.render(),
                 'grafana dashboard': gen_dashboard.OUT.is_file()
                 and json.loads(gen_dashboard.OUT.read_text(encoding='utf-8')) == gen_dashboard.build()}
    docs_ok = all(generated.values())
    suites = {}
    ok = not static_fail and docs_ok
    t0 = time.monotonic()
    for mod in ('test_contract', 'test_ui', 'test_mvp', 'test_models', 'test_observability', 'test_k8s_manifests', 'test_heavy'):
        suite = unittest.defaultTestLoader.loadTestsFromName(mod)
        res = unittest.TextTestRunner(resultclass=Collect, verbosity=1).run(suite)
        suites[mod] = {'run': res.testsRun, 'passed': len(res.passed), 'failed': len(res.failures),
                       'errors': len(res.errors), 'skipped': [f'{t.id()}: {why}' for t, why in res.skipped],
                       'failing': [t.id() for t, _ in res.failures + res.errors]}
        ok = ok and res.wasSuccessful()
    report = {'verdict': 'PASS' if ok else 'FAIL', 'python': platform.python_version(),
              'platform': platform.platform(), 'seconds': round(time.monotonic() - t0, 1),
              'openapi_static': {'checks': len(static['checks']), 'failed': static_fail},
              'api_docs_match_spec': docs_ok, 'suites': suites,
              'meaning': 'Unit/contract/integration voi backend stub va inference server gia. '
                         'Khong chung minh Triton/GPU that; xem smoke.py.'}
    Path(args.output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if not docs_ok:
        print('FAIL: generated file missing or stale (run make docs):', [k for k, v in generated.items() if not v])
    for name in static_fail:
        print('FAIL: static OpenAPI check', name)
    total = sum(s['run'] for s in suites.values())
    print(f"MVP tests: {report['verdict']}  {sum(s['passed'] for s in suites.values())}/{total} passed, "
          f"static {len(static['checks']) - len(static_fail)}/{len(static['checks'])}  -> {args.output}")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
