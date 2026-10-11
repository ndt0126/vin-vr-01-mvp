"""W2-01 reviewer check: spec consistency + probes against the lab controller snapshot.

Usage:  python3 -I check_w2_01.py --output reviewer-result.json [--lab DIR]

Needs only the Python standard library. No GPU, Docker, Internet or SSH.
PASS here means "the spec is self-consistent and every lab-status label is backed by
an observed behaviour". It does NOT mean W2-01 is accepted by QC/integration.
"""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SYMBOL = {'✅': 'PASS', '⚠️': 'PARTIAL', '❌': 'GAP'}
CONFIG = {'A': {'name': 'A', 'side': 224}, 'B': {'name': 'B', 'side': 256}}


def check_spec(spec, md_text):
    errors = []
    st = spec['states']
    terminal, technical = set(st['terminal']), set(st['technical'])
    if not technical <= terminal:
        errors.append('technical states must be terminal')
    for src, dst in spec['transitions']:
        if src in terminal:
            errors.append(f'terminal state {src} has outgoing transition to {dst}')
    reachable = {dst for _, dst in spec['transitions']}
    for s in terminal:
        if s not in reachable:
            errors.append(f'terminal state {s} unreachable')
    for c in spec['cases']:
        outcome = c['required_outcome']
        if any(t in outcome for t in technical) and c['decision_allowed']:
            errors.append(f"{c['id']}: technical outcome must not carry OK/NG/REVIEW")
        if outcome.startswith('HTTP') and c['creates_record']:
            errors.append(f"{c['id']}: rejection before admission must not create a record")
        if c['lab_status'] not in ('PASS', 'PARTIAL', 'GAP'):
            errors.append(f"{c['id']}: bad lab_status")
    # Markdown table must list the same IDs with the same lab labels.
    md = {}
    for line in md_text.splitlines():
        m = re.match(r'\|\s*([NF]\d+)\s*\|', line)
        if m:
            sym = next((s for s in SYMBOL if s in line.rsplit('|', 2)[-2]), None)
            md[m.group(1)] = SYMBOL.get(sym)
    js = {c['id']: c['lab_status'] for c in spec['cases']}
    if set(md) != set(js):
        errors.append(f'markdown/json case IDs differ: {sorted(set(md) ^ set(js))}')
    for k in set(md) & set(js):
        if md[k] != js[k]:
            errors.append(f'{k}: markdown label {md[k]} != json {js[k]}')
    return errors


class Fake:
    def __init__(self):
        self.loaded, self.calls = set(), 0

    def load(self, name): self.loaded.add(name)
    def unload(self, name): self.loaded.discard(name)

    def infer(self, name, image, side, brightness):
        if name not in self.loaded:
            raise RuntimeError(f'model {name} not loaded')
        self.calls += 1
        return {'gpu_forward_ms': 1, 'output_sha256': name}


def b64(raw):
    return base64.b64encode(raw).decode()


PNG = bytes.fromhex('89504e470d0a1a0a')  # only a signature; the lab never decodes images


def run_probes(Controller):
    out = {}

    def fresh(tmp, backend=None):
        c = Controller(tmp, backend or Fake(), json.loads(json.dumps(CONFIG)), b'warm', telemetry=False)
        c.initialize()
        return c

    def payload(rid='r1', raw=PNG + b'pcb1', **extra):
        return dict(request_id=rid, image=b64(raw), product_id='PCB1-0001', **extra)

    with tempfile.TemporaryDirectory() as tmp:
        c = fresh(tmp)
        code, body = c.submit(payload('n1'))
        out['probe_N1'] = dict(observed=[code, body['state']], has_decision='decision' in (body.get('result') or {}),
                               expected_gap='spec needs decision OK/NG/REVIEW on COMPLETED',
                               confirms_label=code == 200 and body['state'] == 'COMPLETED' and 'decision' not in body['result'])
        r1, r2 = c.submit({})[0], c.submit(dict(payload('f1'), image='%%%'))[0]
        out['probe_F1'] = dict(observed=[r1, r2], confirms_label=r1 == r2 == 400 and c.lookup('f1')[0] == 404)
        r = c.submit(payload('f2', raw=b'x' * (4 * 1024 * 1024 + 1)))[0]
        out['probe_F2'] = dict(observed=r, confirms_label=r == 413 and c.lookup('f2')[0] == 404)
        code, body = c.submit(payload('f3', raw=b'this is not an image'))
        out['probe_F3'] = dict(observed=[code, body.get('state')], expected=422,
                               confirms_label=code != 422)
        calls = c.backend.calls
        first, again = c.submit(payload('f4')), c.submit(payload('f4'))
        out['probe_F4'] = dict(observed=[first[0], again[0]], backend_calls_added=c.backend.calls - calls,
                               confirms_label=first == again and c.backend.calls - calls == 1)
        r = c.submit(dict(payload('f4'), product_id='PCB1-9999'))[0]
        out['probe_F5'] = dict(observed=r, confirms_label=r == 409)
        code, body = c.submit(payload('f6', product_type='PCB9', recipe_version='does-not-exist'))
        out['probe_F6'] = dict(observed=[code, body.get('state')], expected='422/409',
                               confirms_label=code == 200 and body.get('state') == 'COMPLETED')
        c.inflight['A'] = 8
        r = c.submit(payload('f7'))[0]
        c.inflight['A'] = 0
        out['probe_F7'] = dict(observed=r, confirms_label=r == 429 and c.lookup('f7')[0] == 404)
        c.backend.unload('A'); c.loaded.discard('A')
        ready = c.readiness()[0]
        code, body = c.submit(payload('f8'))
        out['probe_F8'] = dict(readiness=ready, submit=[code, body.get('state')], expected_submit=503,
                               confirms_label=ready == 503 and code != 503)
        c.backend.load('A'); c.loaded.add('A')
        def boom(*_): raise RuntimeError('CUDA out of memory (injected)')
        c.backend.infer, saved = boom, c.backend.infer
        code, body = c.submit(payload('f10'))
        c.backend.infer = saved
        out['probe_F10'] = dict(observed=[code, body['state']], route_kept=body['route']['key'],
                                confirms_label=body['state'] == 'FAILED' and 'decision' not in (body['result'] or {}))
        code, body = c.submit(payload('f14'))
        later = c.lookup('f14')
        out['probe_F14'] = dict(observed=later[0], same_record=later[1] == body,
                                confirms_label=later[0] == 200 and later[1] == body)
        out['probe_F15'] = dict(observed=c.lookup('nope')[0], confirms_label=c.lookup('nope')[0] == 404)
        c.db.close()
        try:
            r = c.submit(payload('f9'))[0]
        except Exception as exc:
            r = f'exception {type(exc).__name__}'
        out['probe_F9'] = dict(observed=r, expected=503, confirms_label=r != 503)
        c.stop_sampler.set()

    src = Path(sys.modules[Controller.__module__].__file__).read_text()
    out['probe_F11'] = dict(observed='no TIMEOUT state / execution timeout in controller source',
                            confirms_label="'TIMEOUT'" not in src and 'execution_timeout' not in src)

    with tempfile.TemporaryDirectory() as tmp:
        c = fresh(tmp)
        c.db.execute('INSERT INTO requests VALUES(?,?,?,?,NULL)', ('f12', 'x', 'PROCESSING', '{}'))
        c.db.commit(); c.close()
        b = Fake(); c = fresh(tmp, b)
        before = b.calls
        state = c.lookup('f12')[1]['state']
        out['probe_F12'] = dict(observed=state, reexecuted=b.calls != before,
                                confirms_label=state == 'INDETERMINATE' and b.calls == before)
        c.close()

    with tempfile.TemporaryDirectory() as tmp:
        c = fresh(tmp)
        switched = c.activate('B', rollback_window=.01)['state']
        c.close()
        c = fresh(tmp)
        out['probe_F13'] = dict(switch=switched, active_after_restart=c.active, expected='B or 503',
                                confirms_label=switched == 'COMPLETED' and c.active == 'A')
        c.close()
    return out


def run_unittests(lab):
    sys.path.insert(0, str(lab))
    import test_controller
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_controller)
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return dict(run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                ok=result.wasSuccessful(), log=stream.getvalue())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--output', default='reviewer-result.json')
    default_lab = HERE / 'lab' if (HERE / 'lab').exists() else HERE.parents[2] / 'server-runner-v2'
    p.add_argument('--lab', default=str(default_lab))
    a = p.parse_args()
    lab = Path(a.lab).resolve()
    spec = json.loads((HERE / 'usecase-pcb1.json').read_text(encoding='utf-8'))
    md = (HERE / 'W2-01-USE-CASE-PCB1.md').read_text(encoding='utf-8')
    spec_errors = check_spec(spec, md)
    sys.path.insert(0, str(lab))
    with contextlib.redirect_stderr(io.StringIO()):
        from controller import Controller
        probes = run_probes(Controller)
        tests = run_unittests(lab)
    mismatched = []
    for c in spec['cases']:
        name = c['probe']
        if name.startswith('unittest:'):
            needed = name.split(':', 1)[1].split(',')
            if not tests['ok'] or any(n not in tests['log'] for n in needed):
                mismatched.append(c['id'])
        elif not probes.get(name, {}).get('confirms_label'):
            mismatched.append(c['id'])
    lab_files = {f.name: hashlib.sha256(f.read_bytes()).hexdigest()
                 for f in sorted(lab.glob('*.py')) if f.name in ('controller.py', 'common.py', 'test_controller.py')}
    counts = {}
    for c in spec['cases']:
        counts[c['lab_status']] = counts.get(c['lab_status'], 0) + 1
    verdict = 'PASS' if not spec_errors and not mismatched and tests['ok'] else 'FAIL'
    result = dict(verdict=verdict,
                  meaning='spec consistent and every lab label backed by observed behaviour; NOT QC/integration acceptance',
                  spec_status=spec['status'], spec_errors=spec_errors, label_mismatches=mismatched,
                  lab_status_counts=counts, probes=probes,
                  unittests={k: v for k, v in tests.items() if k != 'log'}, unittest_log=tests['log'],
                  lab_sha256=lab_files, python=sys.version.split()[0])
    Path(a.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"{verdict}: spec_errors={len(spec_errors)} label_mismatches={mismatched} "
          f"unittests={tests['run']} ok={tests['ok']} lab={counts}")
    return 0 if verdict == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
