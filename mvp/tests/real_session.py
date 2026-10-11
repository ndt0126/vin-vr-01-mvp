"""Mot phien kiem tren stack THAT (Triton that), chay ngay tren may co stack. Chi dung thu vien chuan.

Usage (trong thu muc mvp/, stack da `make start SLOW=1`):
    python3 tests/real_session.py --phase main          # P1..P10, ghi run/session-state.json
    (reboot may)
    python3 tests/real_session.py --phase post-reboot   # R1..R3
--no-docker: bo cac buoc can docker/make (kill, backup/restore) de thu script voi tests/local_stack.py.

Moi buoc ghi PASS/FAIL + so lieu vao run/session-report.json. Script KHONG sua ket qua: buoc nao sai thi FAIL.
"""
import argparse
import base64
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from load_cutover import Client, png, STATION, TERMINAL  # noqa: E402

ROOT = HERE.parent
API, TRITON = 'vr01-mvp-api-1', 'vr01-mvp-triton-1'


class Session:
    def __init__(self, args):
        self.a, self.run = args, args.run_dir
        tokens = {v['role']: v['token'] for v in
                  json.loads((self.run / 'auth' / 'lab-tokens.secret.json').read_text()).values()}
        self.c = Client(args.host, {'inference': args.inference_port, 'management': args.management_port}, tokens,
                        self.run / 'tls' / 'ca.crt')
        self.id = time.strftime('%Y%m%dT%H%M%S')
        self.steps, self.n = [], 0
        self.report_path = self.run / 'session-report.json'
        if self.report_path.is_file() and args.phase == 'post-reboot':
            self.steps = json.loads(self.report_path.read_text())['steps']

    # ---------- helpers
    def step(self, name, ok, **detail):
        self.steps.append({'step': name, 'result': 'PASS' if ok else 'FAIL', 'at': time.strftime('%H:%M:%S'), **detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}  {json.dumps(detail, ensure_ascii=False)[:300]}", flush=True)
        self.save()

    def save(self):
        failed = [s['step'] for s in self.steps if s['result'] != 'PASS']
        self.report_path.write_text(json.dumps({'verdict': 'FAIL' if failed else 'PASS', 'failed': failed,
                                                'steps': self.steps}, indent=2, ensure_ascii=False) + '\n')

    def rid(self, tag):
        self.n += 1
        return f'sess-{self.id}-{tag}-{self.n:03d}'

    def body(self, rid, recipe, gray=40, retry_of=None, product=None):
        return {'request_id': rid, 'product_id': product or f'PCB1-SESS-{self.n:03d}', 'product_type': 'PCB1',
                'recipe_version': recipe, 'captured_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'station_id': STATION, 'retry_of': retry_of,
                'image': {'content_type': 'image/png', 'data_base64': base64.b64encode(png(gray)).decode()}}

    def submit(self, rid, recipe, **kw):
        return self.c.call('POST', '/v1/inspections', 'operator', self.body(rid, recipe, **kw))

    def status(self, rid):
        return self.c.call('GET', f'/v1/inspections/{rid}', 'viewer')[1]

    def wait_state(self, rid, states, timeout=30):
        deadline = time.time() + timeout
        while time.time() < deadline:
            s = self.status(rid)
            if s and s.get('state') in states:
                return s
            time.sleep(0.02)
        raise AssertionError(f'{rid} did not reach {states} within {timeout}s (now {s})')

    def result(self, rid):
        return self.c.call('GET', f'/v1/inspections/{rid}/result', 'viewer')[1]

    def activate(self, name, expect=200):
        s, b = self.c.call('POST', f'/v1/admin/stations/{STATION}/activation', 'admin',
                           {'recipe_name': name, 'recipe_version': '0.1.0', 'reason': f'session {self.id}'}, 'management')
        if s != expect:
            raise AssertionError(f'activate {name}: {s} {b}')
        return b

    def active(self):
        return self.c.call('GET', f'/v1/stations/{STATION}/active-recipe', 'viewer')[1]['recipe_version']

    def trace(self, rid=None):
        out = []
        for line in (self.run / 'data' / 'trace.jsonl').read_text().splitlines():
            e = json.loads(line)
            if rid is None or e.get('request_id') == rid:
                out.append(e)
        return out

    def wait_ready(self, timeout=180):
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                if self.c.call('GET', '/readyz')[0] == 200:
                    return round(time.time() - t0, 1)
            except OSError:
                pass
            time.sleep(0.5)
        raise AssertionError(f'not ready after {timeout}s')

    def sh(self, *cmd, check=True):
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=check)

    def tool(self, script, *extra):
        p = subprocess.run([sys.executable, '-B', str(HERE / script), '--run-dir', str(self.run), '--host', self.a.host,
                            '--inference-port', str(self.a.inference_port),
                            '--management-port', str(self.a.management_port), *extra],
                           cwd=ROOT, capture_output=True, text=True)
        return p.returncode, p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr[-300:]

    def pid(self, container):
        return int(self.sh('docker', 'inspect', '-f', '{{.State.Pid}}', container).stdout.strip())

    def guarded(self, name, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - mot buoc hong khong duoc lam mat cac buoc sau
            self.step(name, False, error=f'{type(exc).__name__}: {exc}'[:400])

    # ---------- main phase
    def p0_calibrate_slow(self):
        """Chinh so vong lap cua model-slow de moi lan suy luan ~1,2 s tren may nay (can cho P4-P8)."""
        self.activate('recipe-slow')
        rid = self.rid('calib')
        self.submit(rid, 'recipe-slow@0.1.0')
        self.wait_state(rid, TERMINAL, 120)
        res = self.result(rid)
        ms = res['timing_ms']['inference'] or (15000 if res['state'] == 'TIMEOUT' else 1)
        rounds = 64
        if not 800 <= ms <= 1800:
            rounds = max(4, min(2000, round(64 * 1200 / ms)))
            os.environ['VR01_SLOW_ROUNDS'] = str(rounds)
            self.activate('recipe-a')
            deadline = time.time() + 60
            while time.time() < deadline and not any(
                    e['event'] == 'lifecycle.unloaded' and e['model']['name'] == 'model-slow' for e in self.trace()):
                time.sleep(0.5)
            self.sh('make', 'init', 'SLOW=1')
        (self.run / 'session-slow-rounds.txt').write_text(str(rounds))
        self.step('P0 calibrate slow fixture for this machine', True, first_measure_ms=ms, rounds=rounds)

    def p1_smoke(self):
        rc, last = self.tool('smoke.py', '--output', str(self.run / 'session-smoke.json'))
        self.step('P1 smoke flow', rc == 0, last=last)

    def p2_load_cutover(self):
        rc, last = self.tool('load_cutover.py', '--rate', str(self.a.rate), '--duration', str(self.a.duration),
                             '--cutover-every', '5', '--output', str(self.run / 'session-load-cutover.json'))
        r = json.loads((self.run / 'session-load-cutover.json').read_text())
        self.step('P2 cutover A<->B under continuous load', rc == 0, sent=r['requests']['sent'],
                  missing_or_wrong=r['requests']['missing_or_wrong'], duplicates=r['requests']['duplicate_or_extra_products'],
                  cutovers=f"{r['cutovers']['succeeded']}/{r['cutovers']['requested']}", max_gap_s=r['cutovers']['max_gap_s'],
                  p95_ms=r['latency_total_ms']['p95'])

    def p3_slow_model(self):
        self.activate('recipe-slow')
        rid = self.rid('slow')
        self.submit(rid, 'recipe-slow@0.1.0')
        self.wait_state(rid, TERMINAL, 60)
        res = self.result(rid)
        self.slow_ms = res['timing_ms']['inference'] or 0
        ok = res['state'] == 'COMPLETED' and res['lineage']['model']['name'] == 'model-slow'
        self.step('P3 slow fixture model runs on the inference server', ok and self.slow_ms >= 300,
                  inference_ms=self.slow_ms, score=res['score'], decision=res['decision'],
                  note='can >= 300 ms de cac buoc P4-P8 bat duoc trang thai PROCESSING')

    def p4_cancel_processing(self):
        rid = self.rid('cancelrun')
        self.submit(rid, 'recipe-slow@0.1.0')
        self.wait_state(rid, {'PROCESSING'}, 10)
        s, b = self.c.call('POST', f'/v1/inspections/{rid}/cancel', 'operator', {'reason': 'session: cancel while running'})
        nxt = self.rid('aftercancel')
        self.submit(nxt, 'recipe-slow@0.1.0')
        after = self.wait_state(nxt, TERMINAL, 60)
        res = self.result(rid)
        ev = [e['event'] for e in self.trace(rid)]
        ok = (s, res['state'], res['decision'], res['score']) == (200, 'CANCELLED', None, None) \
            and 'inference.result_discarded_after_cancel' in ev and after['state'] == 'COMPLETED'
        self.step('P4 cancel while PROCESSING: late result discarded', ok, cancel_http=s, state=res['state'],
                  discarded_logged='inference.result_discarded_after_cancel' in ev, next_request=after['state'])

    def p5_cancel_queued(self):
        ids = [self.rid('q') for _ in range(3)]
        for r in ids:
            self.submit(r, 'recipe-slow@0.1.0')
        s, b = self.c.call('POST', f'/v1/inspections/{ids[2]}/cancel', 'operator', {'reason': 'session: cancel while queued'})
        finals = [self.wait_state(r, TERMINAL, 90)['state'] for r in ids]
        ev = [e['event'] for e in self.trace(ids[2])]
        ok = s == 200 and finals == ['COMPLETED', 'COMPLETED', 'CANCELLED'] and 'inference.started' not in ev \
            and 'request.dequeued_already_terminal' in ev
        self.step('P5 cancel while queued: never sent to the inference server', ok, cancel_http=s, finals=finals,
                  inference_started_for_cancelled='inference.started' in ev)

    def p6_drain_before_unload(self):
        rid = self.rid('drain')
        self.submit(rid, 'recipe-slow@0.1.0')
        self.wait_state(rid, {'PROCESSING'}, 10)
        self.activate('recipe-a')
        fast = self.rid('fast')
        self.submit(fast, 'recipe-a@0.1.0')
        res_slow = self.wait_state(rid, TERMINAL, 60)
        res_fast = self.wait_state(fast, TERMINAL, 60)
        deadline = time.time() + 30
        order = []
        while time.time() < deadline:
            order = [(e['event'], e.get('request_id') or (e.get('model') or {}).get('name')) for e in self.trace()
                     if e['event'] in ('request.terminal', 'lifecycle.unloaded')]
            if ('lifecycle.unloaded', 'model-slow') in order[order.index(('request.terminal', rid)):]:
                break
            time.sleep(0.2)
        idx_done = order.index(('request.terminal', rid))
        unloaded_after = ('lifecycle.unloaded', 'model-slow') in order[idx_done:]
        lin = self.result(rid)['lineage']['model']['name']
        ok = res_slow['state'] == 'COMPLETED' and lin == 'model-slow' and res_fast['state'] == 'COMPLETED' and unloaded_after
        self.step('P6 cutover drains the in-flight request before unloading the old model', ok,
                  in_flight_final=res_slow['state'], in_flight_model=lin, new_recipe_request=res_fast['state'],
                  old_model_unloaded_after_request_finished=unloaded_after)

    def p7_kill_api(self):
        self.activate('recipe-slow')
        ids = [self.rid('kill') for _ in range(3)]
        for r in ids:
            self.submit(r, 'recipe-slow@0.1.0')
        self.wait_state(ids[0], {'PROCESSING'}, 10)
        before = [self.status(r)['state'] for r in ids]
        os.kill(self.pid(API), 9)
        time.sleep(1)
        back = self.wait_ready()
        finals = [self.status(r) for r in ids]
        active = self.active()
        retry = self.rid('retry')
        self.submit(retry, 'recipe-slow@0.1.0', retry_of=ids[0], product=self.status(ids[0])['product_id'])
        retry_final = self.wait_state(retry, TERMINAL, 60)['state']
        ok = all(f['state'] == 'INDETERMINATE' and f['decision'] is None for f in finals) \
            and active == 'recipe-slow@0.1.0' and retry_final == 'COMPLETED'
        self.step('P7 kill -9 API with 1 running + 2 queued', ok, before_kill=before,
                  after_restart=[f['state'] for f in finals], ready_again_s=back, active_recipe=active,
                  retry_with_new_id=retry_final)

    def p8_kill_triton_under_load(self):
        self.activate('recipe-a')
        out = self.run / 'session-load-triton-kill.json'
        proc = subprocess.Popen([sys.executable, '-B', str(HERE / 'load_cutover.py'), '--run-dir', str(self.run),
                                 '--host', self.a.host, '--inference-port', str(self.a.inference_port),
                                 '--management-port', str(self.a.management_port), '--rate', '10', '--duration', '50',
                                 '--cutover-every', '8', '--allow-technical', '--output', str(out)],
                                cwd=ROOT, stdout=subprocess.PIPE, text=True)
        time.sleep(12)
        os.kill(self.pid(TRITON), 9)
        killed_at = time.time()
        proc.wait(600)
        ready_s = self.wait_ready()
        r = json.loads(out.read_text())
        ok = r['requests']['missing_or_wrong'] == 0 and r['requests']['duplicate_or_extra_products'] == 0 \
            and r['requests']['completed'] > 0
        self.step('P8 kill -9 Triton under load: no wrong/duplicate result, service recovers', ok,
                  sent=r['requests']['sent'], completed=r['requests']['completed'],
                  technical=r['requests'].get('technical_states'), not_accepted=r['requests'].get('not_accepted'),
                  wrong=r['requests']['missing_or_wrong'], duplicates=r['requests']['duplicate_or_extra_products'],
                  cutovers=f"{r['cutovers']['succeeded']}/{r['cutovers']['requested']}",
                  ready_after_load_s=ready_s, active_recipe=self.active(),
                  seconds_from_kill_to_end=round(time.time() - killed_at, 1))

    def p9_backup_restore(self):
        probe = self.rid('keep')
        self.submit(probe, self.active())
        self.wait_state(probe, TERMINAL, 60)
        before, active = self.result(probe), self.active()
        trace_before = len(self.trace(probe))
        info = json.loads(self.sh(sys.executable, 'tools/backup.py', 'backup', '--run-dir', str(self.run)).stdout.strip())
        self.sh('make', 'stop')
        data = self.run / 'data'
        lost = self.run / f'data.lost-{self.id}'
        shutil.move(str(data), str(lost))  # gia lap mat du lieu
        data.mkdir()
        self.sh('make', 'start', 'SLOW=1')
        self.wait_ready()
        gone = self.c.call('GET', f'/v1/inspections/{probe}/result', 'viewer')[0]
        t1 = time.time()
        self.sh('make', 'restore', f"BACKUP={info['backup']}")
        self.wait_ready()
        rto = round(time.time() - t1, 1)
        after = self.result(probe)
        trace_after = len(self.trace(probe))
        ok = info['integrity_check'] == 'ok' and info['has_trace'] and gone == 404 and after == before \
            and self.active() == active and trace_after == trace_before and trace_before > 0
        self.step('P9 make backup -> simulated data loss -> make restore (ledger + trace + images)', ok,
                  backup=info, lookup_after_loss_http=gone, result_identical_after_restore=after == before,
                  active_recipe_restored=self.active() == active,
                  trace_events_for_probe_before_after=[trace_before, trace_after], restore_rto_s_lab=rto,
                  note='backup nam tren cung may')

    def p11_execution_timeout(self):
        """Ha execution timeout xuong thap hon do cham cua model-slow de kich hoat TIMEOUT tren inference server that."""
        env = dict(os.environ, VR01_LIMIT_OVERRIDES='{"execution_timeout_s": 0.3}')
        subprocess.run(['make', 'start', 'SLOW=1'], cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        self.wait_ready()
        try:
            self.activate('recipe-slow')
            rid = self.rid('timeout')
            self.submit(rid, 'recipe-slow@0.1.0')
            final = self.wait_state(rid, TERMINAL, 30)
            finished = self.result(rid)['finished_at']
            time.sleep(3)  # ket qua muon da ve
            res = self.result(rid)
            ev = [e['event'] for e in self.trace(rid)]
            ready = self.c.call('GET', '/readyz')[0]
            ok = (final['state'], final['reason'], final['decision']) == ('TIMEOUT', 'EXECUTION_TIMEOUT', None) \
                and 'inference.late_result_ignored' in ev and res['state'] == 'TIMEOUT' and res['score'] is None \
                and res['finished_at'] == finished and ready == 200
            self.step('P11 execution timeout on the real inference server; late result ignored', ok,
                      state=final['state'], reason=final['reason'], late_result_logged='inference.late_result_ignored' in ev,
                      unchanged_after_late_result=res['finished_at'] == finished, readyz=ready,
                      note='execution_timeout_s ha xuong 0.3 s chi cho buoc nay')
        finally:
            subprocess.run(['make', 'start', 'SLOW=1'], cwd=ROOT, capture_output=True, text=True, check=True)
            self.wait_ready()
        normal = self.rid('aftertimeout')
        self.submit(normal, 'recipe-slow@0.1.0')
        back = self.wait_state(normal, TERMINAL, 60)['state']
        self.step('P11b normal limits restored: slow request completes again', back == 'COMPLETED', state=back)

    def p12_long_triton_outage(self):
        """Dung han Triton 30 s khi dang co tai (khong tu khoi dong lai), roi bat lai."""
        import threading
        self.activate('recipe-a')
        out = self.run / 'session-load-triton-outage.json'
        marks = {}

        def outage():
            time.sleep(8)
            self.sh('docker', 'stop', '-t', '0', TRITON)
            marks['stopped'] = time.time()
            rz = []
            for _ in range(6):
                time.sleep(4)
                try:
                    rz.append(self.c.call('GET', '/readyz')[0])
                except OSError:
                    rz.append(None)
            marks['readyz_during_outage'] = rz
            self.sh('docker', 'start', TRITON)
            marks['started'] = time.time()

        th = threading.Thread(target=outage)
        th.start()
        subprocess.run([sys.executable, '-B', str(HERE / 'load_cutover.py'), '--run-dir', str(self.run),
                        '--host', self.a.host, '--inference-port', str(self.a.inference_port),
                        '--management-port', str(self.a.management_port), '--rate', '10', '--duration', '60',
                        '--cutover-every', '100000', '--allow-technical', '--output', str(out)],
                       cwd=ROOT, capture_output=True, text=True)
        th.join()
        ready_s = self.wait_ready()
        after = self.rid('afteroutage')
        self.submit(after, self.active())
        after_state = self.wait_state(after, TERMINAL, 60)['state']
        r = json.loads(out.read_text())
        q = r['requests']
        ok = q['missing_or_wrong'] == 0 and q['duplicate_or_extra_products'] == 0 and after_state == 'COMPLETED' \
            and set(marks['readyz_during_outage']) == {503} and (q['not_accepted'] + sum(q['technical_states'].values())) > 0
        self.step('P12 inference server down ~30 s under load: clean refusals, no wrong result, recovery', ok,
                  sent=q['sent'], completed=q['completed'], technical=q['technical_states'], not_accepted=q['not_accepted'],
                  wrong=q['missing_or_wrong'], duplicates=q['duplicate_or_extra_products'],
                  client_503=r['client_retries_same_request_id']['not_ready_503'],
                  readyz_during_outage=marks['readyz_during_outage'],
                  outage_s=round(marks['started'] - marks['stopped'], 1), ready_after_start_s=ready_s,
                  request_after_recovery=after_state, active_recipe=self.active())

    def p13_observability(self):
        """W4-01/W4-02 tren stack that: scrape, mot request + mot lan chuyen model nhin thay qua Prometheus,
        canh bao BAT khi dung Triton va TAT khi bat lai, truy vet mot request tu log."""
        import urllib.parse
        import urllib.request
        prom = 'http://127.0.0.1:9091'

        def q(expr):
            url = f'{prom}/api/v1/query?query=' + urllib.parse.quote(expr)
            return json.load(urllib.request.urlopen(url, timeout=10))['data']['result']

        def val(expr, default=0.0):
            r = q(expr)
            return float(r[0]['value'][1]) if r else default

        def firing(name):
            return any(a['labels']['alertname'] == name and a['state'] == 'firing' for a in json.load(
                urllib.request.urlopen(f'{prom}/api/v1/alerts', timeout=10))['data']['alerts'])

        def wait(cond, timeout):
            t0 = time.time()
            while time.time() - t0 < timeout:
                if cond():
                    return round(time.time() - t0, 1)
                time.sleep(2)
            return None

        self.sh('make', 'obs-start', 'SLOW=1')
        self.wait_ready()
        up = wait(lambda: {x['labels']['job']: x['health'] for x in json.load(urllib.request.urlopen(
            f'{prom}/api/v1/targets', timeout=10))['data']['activeTargets']} == {'vr01-api': 'up', 'triton': 'up'}, 90)
        self.step('P13a Prometheus scrapes API and Triton', up is not None, both_targets_up_after_s=up)
        self.activate('recipe-a')
        before = {'terminal': val('sum(vr01_inspections_terminal_total)'), 'act': val('sum(vr01_activations_total{outcome="OK"})'),
                  'triton_b': val('sum(nv_inference_request_success{model="model-b"})')}
        rid = self.rid('obs')
        self.submit(rid, 'recipe-a@0.1.0')
        self.wait_state(rid, TERMINAL, 60)
        self.activate('recipe-b')
        rid_b = self.rid('obs')
        self.submit(rid_b, 'recipe-b@0.1.0')
        self.wait_state(rid_b, TERMINAL, 60)
        seen = wait(lambda: val('sum(vr01_inspections_terminal_total)') >= before['terminal'] + 2
                    and val('sum(vr01_activations_total{outcome="OK"})') >= before['act'] + 1
                    and val('sum(nv_inference_request_success{model="model-b"})') > before['triton_b'], 60)
        active = q('vr01_active_recipe_info')
        self.step('P13b one request and one model switch are observable in Prometheus', seen is not None
                  and len(active) == 1 and active[0]['metric']['recipe'] == 'recipe-b', visible_after_s=seen,
                  active_recipe_series=[a['metric'] for a in active],
                  p95_total_s=val('histogram_quantile(0.95, sum by (le) (rate(vr01_inspection_total_seconds_bucket[5m])))'))
        tr = subprocess.run([sys.executable, '-B', 'tools/trace_request.py', '--run-dir', str(self.run), rid, '--json'],
                            cwd=ROOT, capture_output=True, text=True)
        t = json.loads(tr.stdout) if tr.returncode == 0 else {}
        events = [e['event'] for e in t.get('events', [])]
        need = ['request.admitted', 'inference.started', 'inference.finished', 'request.terminal']
        self.step('P13c full execution path of one request from its request_id (ledger + log)',
                  all(x in events for x in need) and t['request']['state'] == 'COMPLETED'
                  and t['pinned']['model']['name'] == 'model-a', events=events, pinned_model=t.get('pinned', {}).get('model'))
        self.sh('docker', 'stop', '-t', '0', TRITON)
        fired = wait(lambda: firing('VR01ModelUnavailable'), 120)
        self.sh('docker', 'start', TRITON)
        self.wait_ready()
        cleared = wait(lambda: not firing('VR01ModelUnavailable'), 120)
        self.step('P13d alert VR01ModelUnavailable fires when Triton is stopped and clears after it is back',
                  fired is not None and cleared is not None, fired_after_stop_s=fired, cleared_after_start_s=cleared)
        g = json.load(urllib.request.urlopen('http://127.0.0.1:3000/api/dashboards/uid/vr01-overview', timeout=10))
        self.step('P13e Grafana serves the provisioned dashboard', len(g['dashboard']['panels']) >= 10,
                  title=g['dashboard']['title'], panels=len(g['dashboard']['panels']))
        m = subprocess.run(['docker', 'exec', API, 'python', '-c',
                            "import urllib.request as u;print(u.urlopen('http://localhost:9090/metrics',timeout=5).read().decode())"],
                           capture_output=True, text=True).stdout
        (self.run / 'metrics-snapshot.txt').write_text(m)
        host = subprocess.run(['sh', '-c', 'curl -s -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:9090/metrics || true'],
                              capture_output=True, text=True).stdout.strip()
        self.step('P13f /metrics is reachable inside the compose network but not published on the host',
                  'vr01_ready' in m and host in ('000', ''), series_lines=len([x for x in m.splitlines() if x and x[0] != '#']),
                  host_port_9090_http=host or 'refused')

    def p14_auto_rollback(self):
        """Model 'hong' qua golden nhung loi khi suy luan anh sang -> 3 loi lien tiep sau cutover -> tu rollback."""
        self.activate('recipe-a')
        self.activate('recipe-bad')
        ids = [self.rid('bad') for _ in range(3)]
        for r in ids:
            self.submit(r, 'recipe-bad@0.1.0', gray=220)
        finals = [self.wait_state(r, TERMINAL, 60) for r in ids]
        deadline, active = time.time() + 30, None
        while time.time() < deadline:
            active = self.active()
            if active == 'recipe-a@0.1.0':
                break
            time.sleep(0.5)
        ev = [e['event'] for e in self.trace() if e['event'].startswith('lifecycle.auto_rollback')]
        after = self.rid('afterrollback')
        self.submit(after, 'recipe-a@0.1.0', gray=220)
        after_final = self.wait_state(after, TERMINAL, 60)
        lineage = self.result(ids[0])['lineage']['model']['name']
        ok = all(f['state'] == 'FAILED' and f['decision'] is None for f in finals) and active == 'recipe-a@0.1.0' \
            and 'lifecycle.auto_rollback' in ev and after_final['state'] == 'COMPLETED' and lineage == 'model-bad'
        self.step('P14 automatic rollback after 3 consecutive inference errors right after cutover', ok,
                  failed_requests=[f['state'] + '/' + str(f['reason']) for f in finals], active_after=active,
                  auto_rollback_logged='lifecycle.auto_rollback' in ev, failed_request_keeps_lineage=lineage,
                  request_after_rollback=after_final['state'] + '/' + str(after_final['decision']))

    def p15_disk_full(self):
        """O luu anh day that (tmpfs 64 KiB gan len run/data/images): he thong tu choi sach, khong tra ket qua chua luu."""
        images = self.run / 'data' / 'images'
        self.activate('recipe-a')
        self.sh('make', 'stop')
        self.sh('mount', '-t', 'tmpfs', '-o', 'size=64k', 'tmpfs', str(images))
        try:
            self.sh('make', 'start', 'SLOW=1')
            self.wait_ready()
            accepted, refused, first_refusal = [], [], None
            for i in range(60):
                rid = self.rid('disk')
                st, b = self.submit(rid, 'recipe-a@0.1.0', gray=i * 4 % 256, product=f'PCB1-DISK-{i:03d}')
                if st == 202:
                    accepted.append(rid)
                else:
                    refused.append((rid, st, b.get('code')))
                    first_refusal = first_refusal or (st, b.get('code'))
                    if len(refused) >= 5:
                        break
            rz = self.c.call('GET', '/readyz')
            no_record = all(self.c.call('GET', f'/v1/inspections/{r}', 'viewer')[0] == 404 for r, _, _ in refused)
            done = [self.wait_state(r, TERMINAL, 60)['state'] for r in accepted]
            old_ok = self.result(accepted[0])['state'] == 'COMPLETED' if accepted else False
        finally:
            self.sh('make', 'stop')
            self.sh('umount', str(images))
            self.sh('make', 'start', 'SLOW=1')
            ready_after = self.wait_ready()
        back = self.rid('afterdisk')
        st, _ = self.submit(back, 'recipe-a@0.1.0', gray=7, product='PCB1-DISK-BACK')
        back_state = self.wait_state(back, TERMINAL, 60)['state'] if st == 202 else f'HTTP {st}'
        ok = bool(accepted) and len(refused) >= 5 and first_refusal == (503, 'STORAGE_UNAVAILABLE') and rz[0] == 503 \
            and 'STORAGE_UNAVAILABLE' in rz[1].get('reasons', []) and no_record and set(done) == {'COMPLETED'} \
            and old_ok and back_state == 'COMPLETED'
        self.step('P15 image store really full (64 KiB tmpfs): clean 503, no record for refused, recovery after space is back',
                  ok, accepted_before_full=len(accepted), refused=len(refused), first_refusal=first_refusal,
                  readyz=rz, refused_have_no_record=no_record, accepted_all_completed=set(done) == {'COMPLETED'},
                  ready_after_space_back_s=ready_after, request_after_recovery=back_state)

    def p16_app_upgrade_rollback(self):
        """Doi phien ban image API (0.1.0 -> 0.1.1-test -> 0.1.0) khi dang co tai; do so request bi tu choi va thoi gian."""
        env_file = ROOT / 'deploy' / '.env'
        original = env_file.read_text()
        self.activate('recipe-a')
        out = self.run / 'session-load-app-upgrade.json'
        proc = subprocess.Popen([sys.executable, '-B', str(HERE / 'load_cutover.py'), '--run-dir', str(self.run),
                                 '--host', self.a.host, '--inference-port', str(self.a.inference_port),
                                 '--management-port', str(self.a.management_port), '--rate', '10', '--duration', '90',
                                 '--cutover-every', '100000', '--allow-technical', '--client-timeout', '5',
                                 '--output', str(out)], cwd=ROOT, stdout=subprocess.PIPE, text=True)
        marks = {}
        try:
            time.sleep(8)
            env_file.write_text(original.replace('MVP_VERSION=0.1.0', 'MVP_VERSION=0.1.1-test'))
            t0 = time.time()
            self.sh('make', 'start', 'SLOW=1')
            self.wait_ready()
            marks['upgrade_s'] = round(time.time() - t0, 1)
            marks['image_after_upgrade'] = self.sh('docker', 'inspect', '-f', '{{.Config.Image}}', API).stdout.strip()
            marks['active_after_upgrade'] = self.active()
            time.sleep(8)
        finally:
            env_file.write_text(original)
        t1 = time.time()
        self.sh('make', 'start', 'SLOW=1')
        self.wait_ready()
        marks['rollback_s'] = round(time.time() - t1, 1)
        marks['image_after_rollback'] = self.sh('docker', 'inspect', '-f', '{{.Config.Image}}', API).stdout.strip()
        proc.wait(600)
        r = json.loads(out.read_text())
        q = r['requests']
        ok = marks['image_after_upgrade'].endswith(':0.1.1-test') and marks['image_after_rollback'].endswith(':0.1.0') \
            and marks['active_after_upgrade'] == 'recipe-a@0.1.0' and self.active() == 'recipe-a@0.1.0' \
            and q['missing_or_wrong'] == 0 and q['duplicate_or_extra_products'] == 0
        self.step('P16 app image upgrade and rollback under load (Compose): no wrong result, active recipe kept', ok,
                  **marks, sent=q['sent'], completed=q['completed'], technical=q['technical_states'],
                  not_accepted=q['not_accepted'], client_retries=r['client_retries_same_request_id'],
                  wrong=q['missing_or_wrong'], duplicates=q['duplicate_or_extra_products'],
                  note='upgrade_s/rollback_s gom ca build image va cho healthy; khong phai thoi gian gian doan')

    def p17_network_interruption(self):
        """Chan cong 8443 bang iptables 10 giay khi dang co tai: client gui lai cung request_id, khong mat/trung."""
        self.activate('recipe-a')
        out = self.run / 'session-load-network-cut.json'
        proc = subprocess.Popen([sys.executable, '-B', str(HERE / 'load_cutover.py'), '--run-dir', str(self.run),
                                 '--host', self.a.host, '--inference-port', str(self.a.inference_port),
                                 '--management-port', str(self.a.management_port), '--rate', '10', '--duration', '40',
                                 '--cutover-every', '100000', '--allow-technical', '--client-timeout', '2',
                                 '--output', str(out)], cwd=ROOT, stdout=subprocess.PIPE, text=True)
        rule = ['-p', 'tcp', '--dport', str(self.a.inference_port), '-j', 'DROP']
        time.sleep(8)
        # Compose publish cong qua DOCKER-USER/nat; chan o ca INPUT (loopback) va DOCKER-USER cho chac.
        applied = []
        for chain in ('INPUT', 'DOCKER-USER', 'OUTPUT'):
            if subprocess.run(['iptables', '-I', chain, *rule], capture_output=True).returncode == 0:
                applied.append(chain)
        try:
            time.sleep(10)
        finally:
            for chain in applied:
                subprocess.run(['iptables', '-D', chain, *rule], capture_output=True)
        proc.wait(600)
        r = json.loads(out.read_text())
        q = r['requests']
        errs = r['client_retries_same_request_id']['send_errors']
        ok = q['missing_or_wrong'] == 0 and q['duplicate_or_extra_products'] == 0 and errs > 0 and q['completed'] > 0
        self.step('P17 network cut between client and API for 10 s under load: retries with same request_id, no loss/duplicate',
                  ok, iptables_chains=applied, sent=q['sent'], completed=q['completed'], not_accepted=q['not_accepted'],
                  client_send_errors=errs, wrong=q['missing_or_wrong'], duplicates=q['duplicate_or_extra_products'])

    def p10_state_for_reboot(self):
        probe = self.rid('reboot')
        self.submit(probe, self.active())
        self.wait_state(probe, TERMINAL, 60)
        state = {'probe': probe, 'result': self.result(probe), 'active': self.active(), 'saved_at': time.time()}
        (self.run / 'session-state.json').write_text(json.dumps(state))
        enabled = self.sh('systemctl', 'is-enabled', 'docker', check=False).stdout.strip()
        self.step('P10 state saved for reboot; docker starts on boot', enabled == 'enabled', docker_service=enabled,
                  active_recipe=state['active'])

    # ---------- post-reboot phase
    def post_reboot(self):
        st = json.loads((self.run / 'session-state.json').read_text())
        up = float(Path('/proc/uptime').read_text().split()[0]) if Path('/proc/uptime').exists() else None
        ready = self.wait_ready(300)
        res = self.result(st['probe'])
        ok = res == st['result'] and self.active() == st['active'] and (up is None or up < 900)
        self.step('R1 after full machine reboot: stack back by itself, active recipe and old result intact', ok,
                  machine_uptime_s=up, waited_for_ready_s=ready, active_recipe=self.active(),
                  result_identical=res == st['result'])
        rc, last = self.tool('smoke.py', '--output', str(self.run / 'session-smoke-after-reboot.json'))
        self.step('R2 smoke flow after reboot', rc == 0, last=last)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--phase', choices=['main', 'post-reboot', 'extra', 'obs', 'w4'], required=True)
    ap.add_argument('--run-dir', type=Path, default=ROOT / 'run')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--inference-port', type=int, default=8443)
    ap.add_argument('--management-port', type=int, default=9443)
    ap.add_argument('--rate', type=float, default=10)
    ap.add_argument('--duration', type=float, default=60)
    ap.add_argument('--no-docker', action='store_true')
    args = ap.parse_args()
    rounds_file = args.run_dir / 'session-slow-rounds.txt'
    if rounds_file.is_file():
        os.environ['VR01_SLOW_ROUNDS'] = rounds_file.read_text().strip()
    s = Session(args)
    if args.phase == 'obs':
        s.report_path = s.run / 'session-obs-report.json'
        s.steps = []
        s.guarded('p13_observability', s.p13_observability)
    elif args.phase == 'w4':
        s.report_path = s.run / 'session-w4-report.json'
        s.steps = []
        for fn in (s.p1_smoke, s.p13_observability, s.p14_auto_rollback, s.p16_app_upgrade_rollback,
                   s.p17_network_interruption, s.p15_disk_full):
            s.guarded(fn.__name__, fn)
    elif args.phase == 'extra':
        if s.report_path.is_file():
            s.report_path = s.run / 'session-extra-report.json'
        for fn in (s.p9_backup_restore, s.p11_execution_timeout, s.p12_long_triton_outage):
            s.guarded(fn.__name__, fn)
    elif args.phase == 'post-reboot':
        s.guarded('R1 after full machine reboot', s.post_reboot)
    else:
        steps = [s.p1_smoke, s.p2_load_cutover, s.p3_slow_model, s.p4_cancel_processing, s.p5_cancel_queued,
                 s.p6_drain_before_unload, s.p14_auto_rollback]
        if not args.no_docker:
            steps.insert(2, s.p0_calibrate_slow)
            steps += [s.p7_kill_api, s.p8_kill_triton_under_load, s.p9_backup_restore, s.p11_execution_timeout,
                      s.p12_long_triton_outage, s.p10_state_for_reboot]
        for fn in steps:
            s.guarded(fn.__name__, fn)
    s.save()
    rep = json.loads(s.report_path.read_text())
    print(f"SESSION {args.phase}: {rep['verdict']}  {sum(x['result'] == 'PASS' for x in rep['steps'])}/{len(rep['steps'])} "
          f"-> {s.report_path}")
    return 0 if rep['verdict'] == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
