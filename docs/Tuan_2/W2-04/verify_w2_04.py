"""Mot lenh kiem toan bo W2-04 cho reviewer.

    python3 -I verify_w2_04.py --output reviewer-result.json [--evidence-dir evidence]

Chay: kiem tinh spec -> test cua bo kiem -> contract/negative tests -> doi chieu tung yeu cau mentor
va tung tinh huong W2-01 voi test PASS. Exit 0 chi khi moi muc PASS.
PASS nghia la spec nhat quan va reference implementation dung hop dong trong lab; KHONG phai nghiem thu.
"""
import argparse
import hashlib
import io
import json
import os
import platform
import sys
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Collector(unittest.TextTestResult):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.outcomes = {}

    @staticmethod
    def key(test):
        return f'{type(test).__name__}.{test._testMethodName}'

    def addSuccess(self, test):
        super().addSuccess(test)
        self.outcomes[self.key(test)] = 'PASS'

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.outcomes[self.key(test)] = 'FAIL'

    def addError(self, test, err):
        super().addError(test, err)
        self.outcomes[self.key(test)] = 'ERROR'

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.outcomes[self.key(test)] = 'SKIP'


def run_tests(module_name, stream):
    suite = unittest.defaultTestLoader.loadTestsFromName(module_name)
    runner = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Collector)
    t0 = time.monotonic()
    res = runner.run(suite)
    return res.outcomes, round(time.monotonic() - t0, 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='reviewer-result.json')
    ap.add_argument('--evidence-dir', default=None, help='ghi transcript/coverage/rbac/test log vao day')
    args = ap.parse_args()
    ev = Path(args.evidence_dir).resolve() if args.evidence_dir else None
    if ev:
        ev.mkdir(parents=True, exist_ok=True)
        os.environ['VR01_EVIDENCE_DIR'] = str(ev)
    try:
        import jsonschema, yaml, PIL  # noqa: F401,E401
    except ImportError as exc:
        print(f'missing dependency: {exc}. Install: python3 -m pip install -r requirements.txt', file=sys.stderr)
        return 2

    import check_openapi
    import reference_api
    static = check_openapi.run(server_module=reference_api)
    demo = None
    if ev:
        # Tai tao example tren may reviewer (tien trinh that, HTTPS) va kiem lai voi spec; khong sua examples/.
        import subprocess
        proc = subprocess.run([sys.executable, str(HERE / 'demo_walkthrough.py'), '--out', str(ev / 'demo-examples')],
                              capture_output=True, text=True, timeout=180)
        demo_static = check_openapi.run(server_module=reference_api, examples_dir=ev / 'demo-examples') \
            if proc.returncode == 0 else None
        demo_ok = proc.returncode == 0 and {c['check']: c['result'] for c in demo_static['checks']}.get(
            'example_files_match_spec') == 'PASS'
        demo = {'result': 'PASS' if demo_ok else 'FAIL', 'stdout': proc.stdout.strip()[-300:],
                'stderr': proc.stderr.strip()[-300:]}
    log = io.StringIO()
    checker_tests, t1 = run_tests('test_check_openapi', log)
    contract_tests, t2 = run_tests('test_contract', log)
    outcomes = {**contract_tests, **{f'checker:{k}': v for k, v in checker_tests.items()}}
    static_by_name = {c['check']: c['result'] for c in static['checks']}

    mapping = json.loads((HERE / 'contract-cases.json').read_text(encoding='utf-8'))

    def evidence_result(ref):
        if ref.startswith('static:'):
            return static_by_name.get(ref[7:], 'MISSING')
        if ref.startswith('file:'):
            return 'PASS' if (HERE / ref[5:]).exists() and any((HERE / ref[5:]).iterdir()) else 'MISSING'
        return outcomes.get(ref, 'MISSING')

    def summarize(refs):
        res = {r: evidence_result(r) for r in refs}
        return {'result': 'PASS' if res and all(v == 'PASS' for v in res.values()) else 'FAIL', 'evidence': res}

    usecase = {cid: summarize(refs) for cid, refs in mapping['usecase_cases'].items()}
    w201 = json.loads((HERE.parent / 'W2-01' / 'usecase-pcb1.json').read_text(encoding='utf-8')) \
        if (HERE.parent / 'W2-01' / 'usecase-pcb1.json').exists() else None
    if w201:
        for case in w201['cases']:
            usecase.setdefault(case['id'], {'result': 'FAIL', 'evidence': {'mapping': 'MISSING'}})
    requirements = {rid: {'text': r['text'], **summarize(r['evidence'])}
                    for rid, r in mapping['mentor_requirements'].items()}
    failed_tests = sorted(k for k, v in outcomes.items() if v not in ('PASS', 'SKIP'))
    skipped = sorted(k for k, v in outcomes.items() if v == 'SKIP')
    ok = (static['result'] == 'PASS' and not failed_tests and not skipped and (demo is None or demo['result'] == 'PASS')
          and all(v['result'] == 'PASS' for v in usecase.values())
          and all(v['result'] == 'PASS' for v in requirements.values()))
    files = ['openapi.v1.yaml', 'reference_api.py', 'test_contract.py', 'check_openapi.py',
             'test_check_openapi.py', 'contract-cases.json', 'verify_w2_04.py', 'client_example.py',
             'demo_walkthrough.py', 'requirements.txt']
    result = {
        'status': 'PASS' if ok else 'FAIL',
        'meaning': 'spec consistent + lab reference implementation honours the contract; NOT mentor/production acceptance',
        'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z'),
        'environment': {'python': platform.python_version(), 'platform': platform.platform(),
                        'jsonschema': __import__('importlib.metadata').metadata.version('jsonschema'),
                        'pyyaml': __import__('yaml').__version__, 'pillow': __import__('PIL').__version__},
        'spec': {'file': 'openapi.v1.yaml', 'sha256': sha(HERE / 'openapi.v1.yaml'),
                 'version': static and __import__('yaml').safe_load((HERE / 'openapi.v1.yaml').read_text(
                     encoding='utf-8'))['info']['version'],
                 'operations': static['operations'], 'examples_validated': static['examples_validated']},
        'static_checks': static['checks'],
        'tests': {'contract': {'total': len(contract_tests), 'pass': sum(v == 'PASS' for v in contract_tests.values()),
                               'seconds': t2},
                  'checker_self_tests': {'total': len(checker_tests),
                                         'pass': sum(v == 'PASS' for v in checker_tests.values()), 'seconds': t1},
                  'failed': failed_tests, 'skipped': skipped},
        'demo_rerun_https_subprocess': demo or 'not run (use --evidence-dir)',
        'mentor_requirements': requirements,
        'w2_01_cases': usecase,
        'file_sha256': {f: sha(HERE / f) for f in files},
    }
    out = Path(args.output)
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
    if ev:
        (ev / 'test-log.txt').write_text(log.getvalue(), encoding='utf-8')
        (ev / 'static-checks.json').write_text(json.dumps(static, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f"W2-04 verify: {result['status']}  static={static['result']}  "
          f"contract={result['tests']['contract']['pass']}/{result['tests']['contract']['total']}  "
          f"checker={result['tests']['checker_self_tests']['pass']}/{result['tests']['checker_self_tests']['total']}  "
          f"W2-01 cases={sum(v['result'] == 'PASS' for v in usecase.values())}/{len(usecase)}  "
          f"mentor reqs={sum(v['result'] == 'PASS' for v in requirements.values())}/{len(requirements)}  "
          f"demo={demo['result'] if demo else 'skipped'}")
    for rid, v in requirements.items():
        if v['result'] != 'PASS':
            print('requirement not met:', rid, v['evidence'])
    if failed_tests:
        print('failed:', ', '.join(failed_tests))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
