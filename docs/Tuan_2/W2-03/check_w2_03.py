"""W2-03 reviewer check: state-machine consistency + probes on the W2-04 reference server.

Usage:  python3 -I check_w2_03.py --output reviewer-result.json

Needs Python 3.10+ and the three packages in W2-04/requirements.txt (jsonschema, PyYAML, Pillow).
No GPU, Docker, Internet or SSH. Runs on macOS/Linux (one probe sends SIGKILL). Takes about 15 s.

PASS means:
  1. the transition table is self-consistent and the Markdown lists the same rows as state-machine.json;
  2. every transition T1-T8 and invariant I1-I8 was OBSERVED on the running reference server
     (one probe kills the server process with SIGKILL and starts it again on the same data dir);
  3. every gap G1-G5 is confirmed to still be a gap (the label is true, not optimistic).
PASS does NOT mean W2-03 is accepted, nor that the gateway/controller on Kubernetes implements it.
"""
import argparse
import base64
import hashlib
import io
import json
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATION = 'station-sim'


def find_w204():
    for cand in (HERE.parent / 'W2-04', HERE / 'W2-04'):
        if (cand / 'reference_api.py').is_file():
            return cand
    raise SystemExit('cannot find W2-04/reference_api.py next to W2-03')


W204 = find_w204()
sys.dont_write_bytecode = True  # leave the W2-04 folder byte-identical
sys.path.insert(0, str(W204))
import reference_api as ra  # noqa: E402  (W2-04 reference server, not modified)
from PIL import Image  # noqa: E402


# ------------------------------------------------------------------ static consistency


def check_spec(spec, md_text, w201):
    errors, notes = [], []
    st = spec['states']
    terminal, non_terminal, technical = set(st['terminal']), set(st['non_terminal']), set(st['technical'])
    if not technical <= terminal:
        errors.append('technical states must be terminal')
    ids = [t['id'] for t in spec['transitions']]
    if len(ids) != len(set(ids)):
        errors.append('duplicate transition id')
    for t in spec['transitions']:
        if t['from'] in terminal:
            errors.append(f"{t['id']}: terminal state {t['from']} has an outgoing transition")
        if t['from'] not in non_terminal | {'NONE'} or t['to'] not in terminal | non_terminal:
            errors.append(f"{t['id']}: unknown state")
        if t['decision'] != (t['to'] == 'COMPLETED'):
            errors.append(f"{t['id']}: decision is allowed only when the target is COMPLETED")
        if t['to'] in technical and not t['reason']:
            errors.append(f"{t['id']}: technical state needs a reason code")
    reach = {t['to'] for t in spec['transitions']}
    for s in terminal | non_terminal:
        if s not in reach:
            errors.append(f'state {s} is unreachable')
    for s in non_terminal:
        if not any(t['from'] == s and t['to'] in terminal for t in spec['transitions']) and \
                not any(t['from'] == s for t in spec['transitions']):
            errors.append(f'non-terminal state {s} has no way out')
    # Every non-terminal state must have a crash exit, otherwise a request can stay unfinished forever.
    for s in non_terminal:
        if not any(t['from'] == s and t['to'] == 'INDETERMINATE' for t in spec['transitions']):
            errors.append(f'non-terminal state {s} has no crash/restart transition')
    # W2-03 must contain every transition of W2-01 section 6; additions are reported.
    if w201 is not None:
        mine = {(t['from'].replace('NONE', 'START'), t['to']) for t in spec['transitions']}
        theirs = {tuple(x) for x in w201['transitions']}
        theirs -= {tuple(x) for x in spec.get('mvp_only_transitions', [])}  # muc 8b: chi co o MVP
        if theirs - mine:
            errors.append(f'missing W2-01 transitions: {sorted(theirs - mine)}')
        notes.append({'added_to_w2_01': sorted(f'{a}->{b}' for a, b in mine - theirs)})
    # Markdown rows must equal JSON rows.
    md_rows = {}
    for line in md_text.splitlines():
        m = re.match(r'\|\s*(T\d+)\s*\|([^|]*)\|([^|]*)\|', line)
        if m:
            clean = [re.sub(r'[`*\s]', '', c) for c in m.groups()[1:]]
            md_rows[m.group(1)] = (clean[0].replace('—', 'NONE'), clean[1])
    js_rows = {t['id']: (t['from'], t['to']) for t in spec['transitions']}
    if md_rows != js_rows:
        errors.append(f'markdown/json transition tables differ: md={md_rows} json={js_rows}')
    for group, prefix in (('invariants', 'I'), ('gaps', 'G')):
        md_ids = set(re.findall(rf'^\|\s*({prefix}\d+)\s*\|', md_text, flags=re.M))
        js_ids = {x['id'] for x in spec[group]}
        if md_ids != js_ids:
            errors.append(f'markdown/json {group} differ: {sorted(md_ids ^ js_ids)}')
    for group in ('transitions', 'invariants', 'gaps'):
        for x in spec[group]:
            if x['probe'] not in PROBES:
                errors.append(f"{x['id']}: probe {x['probe']} does not exist")
    return errors, notes


# ------------------------------------------------------------------ helpers


def png(gray):
    b = io.BytesIO()
    Image.new('L', (4, 4), gray).save(b, 'PNG')
    return b.getvalue()


def model_params():
    """Read gain/bias straight from the W2-05 package files (independent of the server code)."""
    out = {}
    for manifest in sorted((ra.W205 / 'examples' / 'packages').glob('*/manifest.json')):
        m = json.loads(manifest.read_text())
        out[m['name']] = json.loads((manifest.parent / m['artifact']['path']).read_text())
    return out


def recipe_thresholds():
    out = {}
    for p in sorted((ra.W205 / 'examples' / 'recipes').glob('*.json')):
        r = json.loads(p.read_text())
        out[f"{r['name']}@{r['version']}"] = {'threshold': r['decision']['threshold'], 'model': r['package']['name']}
    return out


def expected_score(params, gray):
    mean = round(gray / 255.0, 6)
    return round(min(1.0, max(0.0, params['gain'] * mean + params['bias'])), 6)


def expected_decision(score, threshold, band):
    if threshold - band <= score < threshold + band:
        return 'REVIEW'
    return 'NG' if score >= threshold else 'OK'


def submit_body(rid, product, gray, recipe='recipe-a@0.1.0', retry_of=None):
    return {'request_id': rid, 'product_id': product, 'product_type': 'PCB1', 'recipe_version': recipe,
            'captured_at': '2026-10-10T03:00:00Z', 'station_id': STATION, 'retry_of': retry_of,
            'image': {'content_type': 'image/png', 'data_base64': base64.b64encode(png(gray)).decode()}}


class Http:
    def __init__(self, ports, tokens):
        self.ports, self.tokens = ports, tokens

    def call(self, method, path, role=None, body=None, plane='inference'):
        headers = {}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        if role:
            headers['Authorization'] = 'Bearer ' + self.tokens[role]
        req = urllib.request.Request(f'http://127.0.0.1:{self.ports[plane]}{path}', data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                raw, status, hdr = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw, status, hdr = e.read(), e.code, e.headers
        return status, (json.loads(raw) if raw else None), {k.lower(): v for k, v in hdr.items()}

    def submit(self, body):
        return self.call('POST', '/v1/inspections', 'operator', body)

    def status(self, rid):
        return self.call('GET', f'/v1/inspections/{rid}', 'viewer')[1]

    def result(self, rid):
        return self.call('GET', f'/v1/inspections/{rid}/result', 'viewer')

    def activate(self, name, version='0.1.0'):
        return self.call('POST', f'/v1/admin/stations/{STATION}/activation', 'admin',
                         {'recipe_name': name, 'recipe_version': version, 'reason': 'W2-03 probe'}, 'management')

    def wait_terminal(self, rid, timeout=15, seen=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            s = self.status(rid)
            if seen is not None and (not seen or seen[-1] != s['state']):
                seen.append(s['state'])
            if s['state'] in ra.TERMINAL:
                return s
            time.sleep(0.01)
        raise AssertionError(f'{rid} not terminal after {timeout}s')

    def wait_state(self, rid, state, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.status(rid)['state'] == state:
                return
            time.sleep(0.01)
        raise AssertionError(f'{rid} never reached {state}')


def make_auth(tmp):
    tok_file, pr_file = ra.init_lab_principals(tmp / 'auth')
    tokens = {v['role']: v['token'] for v in json.loads(tok_file.read_text()).values()}
    return tokens, pr_file


class InProc:
    """Reference server inside this process (lets a probe shorten timeouts and inject backend faults)."""

    def __init__(self, overrides=None, backend=None):
        self.tmp = Path(tempfile.mkdtemp(prefix='w203-'))
        tokens, pr_file = make_auth(self.tmp)
        self.backend = backend or ra.StubBackend()
        self.app = ra.App(self.tmp / 'data', ra.load_principals(pr_file), backend=self.backend,
                          overrides=overrides or {})
        self.server = ra.Server(self.app, inference_port=0, management_port=0)
        self.http = Http({p: self.server.port(p) for p in ('inference', 'management')}, tokens)

    def rows(self):
        return {r['request_id']: dict(r) for r in self.app.ledger.all('SELECT * FROM inspections')}

    def trace(self, rid):
        lines = (self.tmp / 'data' / 'trace.jsonl').read_text().splitlines()
        return [e for e in map(json.loads, lines) if e.get('request_id') == rid]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.server.close()
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)


class FakeKServe:
    """Controllable inference server speaking KServe v2 (the HTTP protocol of Triton). Lives in this process."""

    def __init__(self):
        self.params, self.calls = model_params(), []
        self.gate = threading.Event()
        self.gate.set()
        self.wrong_id = False
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, obj):
                data = json.dumps(obj).encode()
                try:
                    self.send_response(status)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except OSError:
                    pass  # caller was killed

            def do_GET(self):
                self._send(200 if self.path == '/v2/health/ready' else 404, {})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                name = self.path.split('/')[3]
                outer.calls.append({'id': body['id'], 'model': name})
                if body['id'] != 'golden':
                    outer.gate.wait(30)
                p, x = outer.params[name], body['inputs'][0]['data']
                score = min(1.0, max(0.0, p['gain'] * sum(x) / len(x) + p['bias']))
                rid = 'another-request' if outer.wrong_id and body['id'] != 'golden' else body['id']
                self._send(200, {'model_name': name, 'id': rid,
                                 'outputs': [{'name': 'SCORE', 'datatype': 'FP32', 'shape': [1], 'data': [score]}]})

        class S(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass

        self.httpd = S(('127.0.0.1', 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def ids(self, start=0):
        return [c['id'] for c in self.calls[start:]]

    def close(self):
        self.gate.set()
        self.httpd.shutdown()
        self.httpd.server_close()


def decision_invariant(rows):
    """I5 on a whole ledger: decision != NULL  <=>  state == COMPLETED."""
    return [r['request_id'] for r in rows.values() if (r['decision'] is not None) != (r['state'] == 'COMPLETED')]


def need(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ------------------------------------------------------------------ probes: transitions


def probe_happy_path():
    """T1, T2, T4: RECEIVED -> PROCESSING -> COMPLETED, each step durable and visible to a consumer."""
    with InProc() as s:
        s.backend.delay_s = 0.3
        s.http.submit(submit_body('hp-1', 'PCB1-SN-0001', 64))
        st, body, _ = s.http.submit(submit_body('hp-2', 'PCB1-SN-0002', 200))
        need(st == 202 and body['state'] == 'RECEIVED', f'hp-2 submit: {st} {body}')
        seen = ['RECEIVED']
        final = s.http.wait_terminal('hp-2', seen=seen)
        row = s.rows()['hp-2']
        events = [e['event'] for e in s.trace('hp-2')]
        need(seen == ['RECEIVED', 'PROCESSING', 'COMPLETED'], f'states seen by consumer: {seen}')
        need(final['decision'] in ('OK', 'NG', 'REVIEW'), 'COMPLETED must carry a decision')
        need(row['received_at'] <= row['started_at'] <= row['finished_at'], 'timestamps out of order')
        need(events == ['request.admitted', 'inference.started', 'inference.finished', 'request.terminal'],
             f'trace: {events}')
        need(not decision_invariant(s.rows()), 'decision invariant')
        return {'observed': ['T1', 'T2', 'T4'], 'states_seen_by_consumer': seen, 'trace_events': events,
                'decision': final['decision'],
                'timestamps': {k: row[k] for k in ('received_at', 'started_at', 'finished_at')}}


def probe_queue_timeout():
    """T3: a request that waits longer than queue_timeout_s ends as TIMEOUT without touching the backend."""
    with InProc({'queue_timeout_s': 0.2}) as s:
        s.backend.delay_s = 0.6
        s.http.submit(submit_body('q-1', 'PCB1-SN-0001', 64))
        s.http.submit(submit_body('q-2', 'PCB1-SN-0002', 64))
        final = s.http.wait_terminal('q-2')
        row = s.rows()['q-2']
        events = [e['event'] for e in s.trace('q-2')]
        called = [c['request_id'] for c in s.backend.calls]
        need((final['state'], final['reason'], final['decision']) == ('TIMEOUT', 'QUEUE_TIMEOUT', None), str(final))
        need(row['started_at'] is None and 'q-2' not in called, 'q-2 must never reach the backend')
        need(events == ['request.admitted', 'request.terminal'], f'trace: {events}')
        s.app.wait_idle()
        return {'observed': ['T3'], 'state': final['state'], 'reason': final['reason'],
                'started_at': row['started_at'], 'backend_calls_for_q2': called.count('q-2')}


def probe_backend_error():
    """T5 + I5: backend failure -> FAILED, decision null, lineage kept, service keeps running."""
    with InProc() as s:
        s.backend.fail_next = 1
        s.http.submit(submit_body('be-1', 'PCB1-SN-0001', 200))
        final = s.http.wait_terminal('be-1')
        _, res, _ = s.http.result('be-1')
        need((final['state'], final['reason'], final['decision']) == ('FAILED', 'BACKEND_ERROR', None), str(final))
        need(res['score'] is None and res['lineage']['model']['name'] == 'model-a', 'lineage must be kept')
        s.http.submit(submit_body('be-2', 'PCB1-SN-0001', 200, retry_of='be-1'))
        retry = s.http.wait_terminal('be-2')
        need(retry['state'] == 'COMPLETED' and retry['retry_of'] == 'be-1', str(retry))
        bad = decision_invariant(s.rows())
        need(not bad, f'decision invariant violated by {bad}')
        return {'observed': ['T5', 'I5'], 'state': final['state'], 'reason': final['reason'],
                'decision': final['decision'], 'retry_with_new_id': {'request_id': 'be-2', 'retry_of': 'be-1',
                                                                    'state': retry['state'],
                                                                    'decision': retry['decision']}}


def probe_execution_timeout_late_result():
    """T6 + I4: execution timeout -> TIMEOUT; the result that arrives later is logged and ignored."""
    with InProc({'execution_timeout_s': 0.3}) as s:
        s.backend.delay_s = 0.9
        s.http.submit(submit_body('et-1', 'PCB1-SN-0001', 200))
        final = s.http.wait_terminal('et-1')
        need((final['state'], final['reason'], final['decision']) == ('TIMEOUT', 'EXECUTION_TIMEOUT', None), str(final))
        finished = s.rows()['et-1']['finished_at']
        s.app.wait_idle()  # backend has now returned its late score
        row = s.rows()['et-1']
        late = [e for e in s.trace('et-1') if e['event'] == 'inference.late_result_ignored']
        need(late and late[0]['late_score'] is not None, 'late result must be logged')
        need((row['state'], row['decision'], row['score'], row['finished_at']) == ('TIMEOUT', None, None, finished),
             f'terminal row changed after late result: {row}')
        return {'observed': ['T6', 'I4'], 'state': row['state'], 'reason': row['reason'],
                'late_score_logged': late[0]['late_score'], 'row_after_late_result': {
                    'state': row['state'], 'decision': row['decision'], 'score': row['score']}}


# ------------------------------------------------------------------ probe: wrong product / stale result


def probe_wrong_product():
    """I1, I2, I3: results never cross between requests/products/models, also across a recipe switch."""
    params, recipes = model_params(), recipe_thresholds()
    products = [f'PCB1-SN-100{i}' for i in range(1, 5)]
    plan = [('recipe-a@0.1.0', g) for g in (20, 60, 120, 135, 150, 200)] + \
           [('recipe-b@0.1.0', g) for g in (30, 90, 140, 180, 220, 250)]
    with InProc() as s:
        s.backend.delay_s = 0.1
        sent, retried_429 = [], 0
        for i, (recipe, gray) in enumerate(plan):
            if i == 6:
                st, act, _ = s.http.activate('recipe-b')
                need(st == 200 and act['changed'], f'activation: {st} {act}')
                switch_at = act['at']
            rid, product = f'wp-{i:02d}', products[i % 4]
            for _ in range(200):  # queue full (429) -> retry with the SAME request_id, as the contract says
                st, body, _ = s.http.submit(submit_body(rid, product, gray, recipe))
                if st != 429:
                    break
                retried_429 += 1
                time.sleep(0.05)
            need(st == 202, f'{rid}: {st} {body}')
            sent.append({'rid': rid, 'product': product, 'gray': gray, 'recipe': recipe,
                         'input_sha256': hashlib.sha256(png(gray)).hexdigest()})
        for x in sent:
            s.http.wait_terminal(x['rid'])
        decisions, mismatches = {}, []
        for x in reversed(sent):  # consumer reads in a different order than it submitted
            _, res, _ = s.http.result(x['rid'])
            model = recipes[x['recipe']]['model']
            score = expected_score(params[model], x['gray'])
            want = {'request_id': x['rid'], 'state': 'COMPLETED', 'product_id': x['product'],
                    'input_sha256': x['input_sha256'], 'recipe': x['recipe'], 'model': model,
                    'threshold': recipes[x['recipe']]['threshold'],
                    'decision': expected_decision(score, recipes[x['recipe']]['threshold'], res['review_band'])}
            got = {'request_id': res['request_id'], 'state': res['state'], 'product_id': res['lineage']['product_id'],
                   'input_sha256': res['lineage']['input_sha256'],
                   'recipe': f"{res['lineage']['recipe']['name']}@{res['lineage']['recipe']['version']}",
                   'model': res['lineage']['model']['name'], 'threshold': res['threshold'],
                   'decision': res['decision']}
            if got != want or abs(res['score'] - score) > 1e-6:
                mismatches.append({'want': want, 'got': got, 'score': [score, res['score']]})
            decisions[res['decision']] = decisions.get(res['decision'], 0) + 1
        need(not mismatches, f'results crossed: {mismatches[:2]}')
        rows = s.rows()
        pinned_across = sorted(r for r in rows if rows[r]['started_at'] > switch_at
                               and json.loads(rows[r]['pin_json'])['recipe']['name'] == 'recipe-a')
        need(pinned_across, 'no recipe-a request was still queued at the switch; probe cannot show pinning')
        # I2: same request_id for another product is refused and nothing changes.
        before = dict(rows['wp-00'])
        st, body, _ = s.http.submit(submit_body('wp-00', 'PCB1-SN-9999', 20))
        need(st == 409 and body['code'] == 'IDEMPOTENCY_CONFLICT', f'I2: {st} {body}')
        # I3: replay of an old request while recipe-b is active returns the stored record, no new inference.
        st, body, hdr = s.http.submit(submit_body('wp-00', products[0], 20))
        need(st == 200 and hdr.get('idempotent-replay') == 'true', f'I3: {st} {hdr}')
        need(dict(s.rows()['wp-00']) == before, 'record changed by conflict/replay')
        need([c['request_id'] for c in s.backend.calls].count('wp-00') == 1, 'replay must not re-run inference')
        need(len(s.rows()) == len(plan), 'unexpected extra record')
        # Listing by product returns only that product's requests, newest first.
        _, lst, _ = s.http.call('GET', f'/v1/inspections?product_id={products[0]}', 'viewer')
        mine = [x['rid'] for x in sent if x['product'] == products[0]]
        need([i['request_id'] for i in lst['items']] == mine[::-1], f"list: {lst['items']}")
        need(not decision_invariant(s.rows()), 'decision invariant')
        return {'observed': ['I1', 'I2', 'I3'], 'requests': len(sent), 'products': len(products),
                'results_matching_own_product_image_recipe_model_score': len(sent), 'decisions': decisions,
                'recipe_a_requests_processed_after_switch_to_b': pinned_across,
                'queue_full_429_retried_with_same_id': retried_429,
                'conflict_same_id_other_product': 409, 'replay_after_switch': 200,
                'backend_calls_for_replayed_id': 1}


# ------------------------------------------------------------------ probe: SIGKILL + restart


def start_server(data_dir, principals, kserve_url, log):
    proc = subprocess.Popen(
        [sys.executable, '-I', '-B', str(W204 / 'reference_api.py'), '--data-dir', str(data_dir),
         '--principals', str(principals), '--inference-port', '0', '--management-port', '0',
         '--kserve-url', kserve_url], stdout=subprocess.PIPE, stderr=log, text=True)
    line = proc.stdout.readline()
    if not line:
        raise AssertionError('reference server did not start; see server.stderr.log')
    info = json.loads(line)
    return proc, {'inference': info['inference_port'], 'management': info['management_port']}


def ledger_states(path):
    db = sqlite3.connect(str(path))
    try:
        return {r[0]: {'state': r[1], 'reason': r[2], 'decision': r[3], 'started': r[4] is not None}
                for r in db.execute('SELECT request_id, state, reason, decision, started_at FROM inspections')}
    finally:
        db.close()


def probe_sigkill_recovery():
    """T7, T8, I6, I7, I8: kill -9 the server while one request is on the backend and two are queued."""
    tmp = Path(tempfile.mkdtemp(prefix='w203-kill-'))
    fake = FakeKServe()
    procs = []
    try:
        tokens, pr_file = make_auth(tmp)
        data = tmp / 'data'
        log = open(tmp / 'server.stderr.log', 'w')
        proc, ports = start_server(data, pr_file, fake.url, log)
        procs.append(proc)
        http = Http(ports, tokens)
        http.submit(submit_body('c0', 'PCB1-SN-2000', 64))
        c0 = http.wait_terminal('c0')
        need(c0['state'] == 'COMPLETED', str(c0))
        _, c0_result, _ = http.result('c0')
        st, act, _ = http.activate('recipe-b')
        need(st == 200 and act['changed'], f'activate B: {st} {act}')
        fake.gate.clear()  # backend now holds every inference call
        for rid, product in (('c1', 'PCB1-SN-2001'), ('c2', 'PCB1-SN-2002'), ('c3', 'PCB1-SN-2003')):
            st, body, _ = http.submit(submit_body(rid, product, 200, 'recipe-b@0.1.0'))
            need(st == 202, f'{rid}: {st} {body}')
        http.wait_state('c1', 'PROCESSING')
        need(http.status('c2')['state'] == 'RECEIVED' and http.status('c3')['state'] == 'RECEIVED', 'c2/c3 queued')
        calls_before_kill = fake.ids()
        t_kill = time.monotonic()
        proc.send_signal(signal.SIGKILL)
        proc.wait(10)
        on_disk = ledger_states(data / 'ledger.sqlite3')  # what an operator can read while the service is down
        need({k: v['state'] for k, v in on_disk.items()} == {'c0': 'COMPLETED', 'c1': 'PROCESSING',
                                                              'c2': 'RECEIVED', 'c3': 'RECEIVED'}, str(on_disk))
        fake.gate.set()  # the held backend call answers a dead process
        time.sleep(0.3)
        mark = len(fake.calls)
        proc2, ports2 = start_server(data, pr_file, fake.url, log)
        procs.append(proc2)
        restart_s = round(time.monotonic() - t_kill, 2)
        http2 = Http(ports2, tokens)
        after = {rid: http2.status(rid) for rid in ('c0', 'c1', 'c2', 'c3')}
        for rid in ('c1', 'c2', 'c3'):
            need((after[rid]['state'], after[rid]['reason'], after[rid]['decision']) ==
                 ('INDETERMINATE', 'RESTARTED_DURING_PROCESSING', None), f'{rid}: {after[rid]}')
        _, c0_again, _ = http2.result('c0')
        need(c0_again == c0_result, 'result completed before the crash changed')
        disk2 = ledger_states(data / 'ledger.sqlite3')
        unfinished = sorted(k for k, v in disk2.items() if v['state'] in ('RECEIVED', 'PROCESSING'))
        need(not unfinished, f'non-terminal rows after restart: {unfinished}')
        need(disk2['c1']['started'] and not disk2['c2']['started'] and not disk2['c3']['started'],
             'T8 needs started_at, T7 must not have it')
        # I8: active recipe restored from the ledger, service ready.
        readyz, _, _ = http2.call('GET', '/readyz')
        _, active, _ = http2.call('GET', f'/v1/stations/{STATION}/active-recipe', 'viewer')
        need(readyz == 200 and active['recipe_version'] == 'recipe-b@0.1.0', f'I8: {readyz} {active}')
        # I7: replay does not re-run; only a NEW request_id with retry_of runs again.
        st, body, hdr = http2.submit(submit_body('c1', 'PCB1-SN-2001', 200, 'recipe-b@0.1.0'))
        need(st == 200 and hdr.get('idempotent-replay') == 'true' and body['state'] == 'INDETERMINATE',
             f'replay: {st} {body}')
        time.sleep(0.3)
        need(not set(fake.ids(mark)) & {'c1', 'c2', 'c3'}, f'inference re-run after restart: {fake.ids(mark)}')
        need('c2' not in fake.ids() and 'c3' not in fake.ids(), 'queued requests must never reach the backend')
        st, body, _ = http2.submit(submit_body('c1-retry', 'PCB1-SN-2001', 200, 'recipe-b@0.1.0', retry_of='c1'))
        need(st == 202, f'retry: {st} {body}')
        retry = http2.wait_terminal('c1-retry')
        _, retry_res, _ = http2.result('c1-retry')
        need(retry['state'] == 'COMPLETED' and retry_res['lineage']['model']['name'] == 'model-b', str(retry))
        # I6: three ways to identify what did not finish.
        _, lst, _ = http2.call('GET', '/v1/inspections?product_id=PCB1-SN-2001', 'viewer')
        by_product = [(i['request_id'], i['state'], i['retry_of']) for i in lst['items']]
        need(by_product == [('c1-retry', 'COMPLETED', 'c1'), ('c1', 'INDETERMINATE', None)], str(by_product))
        by_ledger = sorted(k for k, v in ledger_states(data / 'ledger.sqlite3').items()
                           if v['state'] == 'INDETERMINATE' and v['reason'] == 'RESTARTED_DURING_PROCESSING')
        trace = [json.loads(x) for x in (data / 'trace.jsonl').read_text().splitlines()]
        by_trace = sorted(e['request_id'] for e in trace if e['event'] == 'request.terminal'
                          and e.get('reason') == 'RESTARTED_DURING_PROCESSING')
        need(by_ledger == by_trace == ['c1', 'c2', 'c3'], f'{by_ledger} {by_trace}')
        return {'observed': ['T7', 'T8', 'I6', 'I7', 'I8'], 'signal': 'SIGKILL',
                'ledger_while_service_down': {k: v['state'] for k, v in on_disk.items()},
                'after_restart': {k: {'state': v['state'], 'reason': v['reason'], 'decision': v['decision']}
                                  for k, v in after.items()},
                'transition_by_request': {'c1': 'T8 (started_at set)', 'c2': 'T7 (started_at null)',
                                          'c3': 'T7 (started_at null)'},
                'completed_before_crash_unchanged': True,
                'backend_calls_before_kill': calls_before_kill, 'backend_calls_after_restart': fake.ids(mark),
                'active_recipe_after_restart': active['recipe_version'], 'readyz_after_restart': readyz,
                'replay_of_c1': 'HTTP 200, still INDETERMINATE, no inference',
                'retry_with_new_id': {'request_id': 'c1-retry', 'retry_of': 'c1', 'state': retry['state'],
                                      'model': retry_res['lineage']['model']['name']},
                'identified_by': {'request_id': True, 'product_id_listing': by_product, 'ledger_query': by_ledger,
                                  'trace_log': by_trace},
                'kill_to_serving_again_s_lab_only': restart_s}
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                p.wait(10)
        fake.close()
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ probes: gaps (label must be TRUE)


def probe_gap_no_cas_guard():
    """G1: a second writer can still overwrite a terminal row, because UPDATE has no 'AND state=...' guard."""
    with InProc({'execution_timeout_s': 0.2}) as s:
        s.backend.delay_s = 0.4
        s.http.submit(submit_body('g1', 'PCB1-SN-0001', 20))
        s.http.wait_terminal('g1')
        s.app.wait_idle()
        need(s.rows()['g1']['state'] == 'TIMEOUT', 'setup')
        # Simulate a stale/second writer calling the storage layer directly (not reachable through the API).
        s.app._finish('g1', 'w203-stale-writer', 'COMPLETED', 'OK', None, 0.1, None, time.monotonic(), 1.0)
        state = s.rows()['g1']['state']
        return {'gap_confirmed': state == 'COMPLETED', 'terminal_row_after_second_writer': state,
                'how': 'direct call to the ledger write path; the public API has no way to do this'}


def probe_gap_backend_id_not_checked():
    """G2: the adapter accepts a backend response whose id differs from request_id."""
    fake = FakeKServe()
    fake.wrong_id = True
    try:
        with InProc(backend=ra.KServeV2Backend(fake.url)) as s:
            s.http.submit(submit_body('g2', 'PCB1-SN-0001', 20))
            final = s.http.wait_terminal('g2')
            return {'gap_confirmed': final['state'] == 'COMPLETED', 'backend_answered_with_id': 'another-request',
                    'state': final['state'], 'decision': final['decision']}
    finally:
        fake.close()


def probe_gap_captured_at_not_stored():
    """G3: captured_at is hashed into the fingerprint but is not a ledger column nor part of the result."""
    with InProc() as s:
        s.http.submit(submit_body('g3', 'PCB1-SN-0001', 20))
        s.http.wait_terminal('g3')
        cols = [r['name'] for r in s.app.ledger.all('PRAGMA table_info(inspections)')]
        _, res, _ = s.http.result('g3')
        return {'gap_confirmed': 'captured_at' not in cols and 'captured_at' not in json.dumps(res),
                'ledger_columns_with_time': [c for c in cols if c.endswith('_at')]}


def probe_gap_no_list_by_state():
    """G4: the list operation only filters by product_id."""
    with InProc() as s:
        st, body, _ = s.http.call('GET', '/v1/inspections?state=INDETERMINATE', 'viewer')
        return {'gap_confirmed': st == 400, 'http_status': st, 'code': body.get('code')}


def probe_gap_image_not_stored():
    """G5: only input_sha256 is kept; the image bytes are not written anywhere in the data dir."""
    with InProc() as s:
        s.http.submit(submit_body('g5', 'PCB1-SN-0001', 20))
        s.http.wait_terminal('g5')
        raw = png(20)
        files = sorted(p.name for p in (s.tmp / 'data').iterdir())
        found = [p.name for p in (s.tmp / 'data').iterdir() if p.is_file() and raw in p.read_bytes()]
        return {'gap_confirmed': not found, 'data_dir_files': files}


PROBES = {f.__name__: f for f in (
    probe_happy_path, probe_queue_timeout, probe_backend_error, probe_execution_timeout_late_result,
    probe_wrong_product, probe_sigkill_recovery, probe_gap_no_cas_guard, probe_gap_backend_id_not_checked,
    probe_gap_captured_at_not_stored, probe_gap_no_list_by_state, probe_gap_image_not_stored)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--output', default='reviewer-result.json')
    args = ap.parse_args()
    spec = json.loads((HERE / 'state-machine.json').read_text(encoding='utf-8'))
    md = (HERE / 'W2-03-DATA-FLOW-STATE-MACHINE.md').read_text(encoding='utf-8')
    w201_path = next((p for p in (HERE.parent / 'W2-01' / 'usecase-pcb1.json', HERE / 'W2-01' / 'usecase-pcb1.json')
                      if p.is_file()), None)
    w201 = json.loads(w201_path.read_text(encoding='utf-8')) if w201_path else None
    errors, notes = check_spec(spec, md, w201)
    probes = {}
    for name, fn in PROBES.items():
        t0 = time.monotonic()
        try:
            probes[name] = {'status': 'PASS', **fn()}
        except Exception as exc:  # noqa: BLE001 - a failing probe is a finding, not a crash
            probes[name] = {'status': 'FAIL', 'error': f'{type(exc).__name__}: {exc}'[:600]}
            errors.append(f'{name}: {probes[name]["error"]}')
        probes[name]['seconds'] = round(time.monotonic() - t0, 2)
    observed = {x for p in probes.values() for x in p.get('observed', [])}
    rows = []
    for group in ('transitions', 'invariants'):
        for x in spec[group]:
            ok = x['id'] in observed and probes[x['probe']]['status'] == 'PASS'
            rows.append({'id': x['id'], 'probe': x['probe'], 'result': 'OBSERVED' if ok else 'NOT_OBSERVED'})
            if not ok:
                errors.append(f"{x['id']} was not observed by {x['probe']}")
    for g in spec['gaps']:
        p = probes[g['probe']]
        confirmed = p['status'] == 'PASS' and p.get('gap_confirmed') is True
        rows.append({'id': g['id'], 'probe': g['probe'], 'result': 'GAP_CONFIRMED' if confirmed else 'LABEL_STALE',
                     'target': g['target']})
        if not confirmed:
            errors.append(f"{g['id']}: reference server no longer shows this gap; update the spec")
    result = {'check': 'W2-03 data flow + state machine', 'spec_version': spec['version'],
              'verdict': 'PASS' if not errors else 'FAIL', 'errors': errors, 'notes': notes,
              'summary': {'transitions_observed': sum(r['result'] == 'OBSERVED' and r['id'][0] == 'T' for r in rows),
                          'invariants_observed': sum(r['result'] == 'OBSERVED' and r['id'][0] == 'I' for r in rows),
                          'gaps_confirmed': sum(r['result'] == 'GAP_CONFIRMED' for r in rows)},
              'rows': rows, 'probes': probes,
              'meaning': 'PASS = table consistent + behaviour observed on the W2-04 lab reference server. '
                         'It is not mentor acceptance and not evidence about the Kubernetes gateway/controller.'}
    Path(args.output).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"W2-03 check: {result['verdict']}  transitions {result['summary']['transitions_observed']}/8, "
          f"invariants {result['summary']['invariants_observed']}/8, gaps confirmed "
          f"{result['summary']['gaps_confirmed']}/5  -> {args.output}")
    for e in errors:
        print('  ERROR:', e)
    return 0 if not errors else 1


if __name__ == '__main__':
    sys.exit(main())
