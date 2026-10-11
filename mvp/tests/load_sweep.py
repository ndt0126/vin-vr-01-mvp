"""Quet tai toi bao hoa (W4-04): tang dan toc do gui, ghi throughput, do tre, loi, hang doi. Chi dung thu vien chuan.

Usage: python3 tests/load_sweep.py --run-dir run --rates 5,10,20,40,80 --step-seconds 20 [--concurrency 16]

Moi buoc: gui theo lich co dinh (open loop) bang nhieu luong; request bi 429 (hang doi day) KHONG duoc gui lai,
de thay ro diem bao hoa. Sau moi buoc, doc lai ket qua tung request da duoc nhan.
Bao hoa = throughput hoan tat < 90% toc do gui, hoac > 5% bi 429/timeout. Dung som khi 2 buoc lien tiep bao hoa.
Ket qua: JSON + bang Markdown. So do phu thuoc may va model: chi co nghia khi chay tren may dich voi model that.
"""
import argparse
import base64
import json
import ssl
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(HERE))
from load_cutover import Client, png, ts, STATION, TERMINAL  # noqa: E402


def pct(values, p):
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(round(p / 100 * (len(v) - 1))))], 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--inference-port', type=int, default=8443)
    ap.add_argument('--management-port', type=int, default=9443)
    ap.add_argument('--rates', default='5,10,20,40,80')
    ap.add_argument('--step-seconds', type=float, default=20)
    ap.add_argument('--concurrency', type=int, default=16)
    ap.add_argument('--recipe', default='recipe-a')
    ap.add_argument('--output', type=Path)
    a = ap.parse_args()
    tokens = {v['role']: v['token'] for v in
              json.loads((a.run_dir / 'auth' / 'lab-tokens.secret.json').read_text()).values()}
    ports = {'inference': a.inference_port, 'management': a.management_port}
    admin = Client(a.host, ports, tokens, a.run_dir / 'tls' / 'ca.crt')
    st, act = admin.call('POST', f'/v1/admin/stations/{STATION}/activation', 'admin',
                         {'recipe_name': a.recipe, 'recipe_version': '0.1.0', 'reason': 'load sweep'}, 'management')
    if st != 200:
        raise SystemExit(f'cannot activate {a.recipe}: {st} {act}')
    recipe = f'{a.recipe}@0.1.0'
    run_id = time.strftime('%Y%m%dT%H%M%S')
    image = base64.b64encode(png(90)).decode()
    steps, saturated_in_a_row = [], 0
    for rate in [float(x) for x in a.rates.split(',')]:
        n = int(rate * a.step_seconds)
        results, lock, idx = [], threading.Lock(), [0]
        t0 = time.time() + 0.2

        def worker():
            c = Client(a.host, ports, tokens, a.run_dir / 'tls' / 'ca.crt')
            c.timeout = 15
            while True:
                with lock:
                    i = idx[0]
                    idx[0] += 1
                if i >= n:
                    return
                due = t0 + i / rate
                time.sleep(max(0.0, due - time.time()))
                rid = f'sweep-{run_id}-{int(rate)}-{i:06d}'
                body = {'request_id': rid, 'product_id': f'PCB1-SWEEP-{i % 100:03d}', 'product_type': 'PCB1',
                        'recipe_version': recipe, 'captured_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                        'station_id': STATION, 'retry_of': None,
                        'image': {'content_type': 'image/png', 'data_base64': image}}
                sent_at = time.time()
                try:
                    s, b = c.call('POST', '/v1/inspections', 'operator', body)
                except OSError as exc:
                    s, b = 0, {'code': type(exc).__name__}
                with lock:
                    results.append({'rid': rid, 'status': s, 'code': (b or {}).get('code'), 'late_s': sent_at - due,
                                    'submit_s': time.time() - sent_at})

        threads = [threading.Thread(target=worker) for _ in range(a.concurrency)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        send_elapsed = time.time() - t0
        accepted = [r for r in results if r['status'] == 202]
        states, total_ms, inf_ms, queue_ms, last_finish = {}, [], [], [], t0
        for r in accepted:
            res = None
            for _ in range(400):
                s, res = admin.call('GET', f"/v1/inspections/{r['rid']}/result", 'viewer')
                if s == 200:
                    break
                time.sleep(0.05)
            st_ = res['state'] if res and 'state' in res else 'UNKNOWN'
            states[st_] = states.get(st_, 0) + 1
            if res and res.get('finished_at'):
                last_finish = max(last_finish, ts(res['finished_at']))
            if st_ == 'COMPLETED':
                tm = res['timing_ms']
                total_ms.append(tm['total'])
                inf_ms.append(tm['inference'])
                queue_ms.append(tm['queue'])
        codes = {}
        for r in results:
            if r['status'] != 202:
                key = f"{r['status']} {r['code']}"
                codes[key] = codes.get(key, 0) + 1
        completed = states.get('COMPLETED', 0)
        achieved = completed / max(send_elapsed, last_finish - t0, 1e-9)  # tinh ca thoi gian xu ly not hang doi
        bad = len(results) - completed
        saturated = achieved < 0.9 * rate or bad > 0.05 * len(results)
        steps.append({'target_rps': rate, 'sent': len(results), 'accepted': len(accepted), 'completed': completed,
                      'achieved_completed_rps': round(achieved, 2), 'rejected_or_failed': codes, 'terminal_states': states,
                      'latency_total_ms': {'p50': pct(total_ms, 50), 'p95': pct(total_ms, 95), 'p99': pct(total_ms, 99),
                                           'max': pct(total_ms, 100)},
                      'inference_ms_p50': pct(inf_ms, 50), 'queue_ms_p95': pct(queue_ms, 95),
                      'client_send_lag_s_p95': pct([r['late_s'] for r in results], 95), 'saturated': saturated})
        s_ = steps[-1]
        print(f"rate {rate:>6.1f}/s  sent {s_['sent']:>5}  completed {completed:>5}  achieved {s_['achieved_completed_rps']:>7.2f}/s  "
              f"p95 {s_['latency_total_ms']['p95']} ms  rejected {codes}  {'SATURATED' if saturated else ''}", flush=True)
        saturated_in_a_row = saturated_in_a_row + 1 if saturated else 0
        if saturated_in_a_row >= 2:
            break
        time.sleep(2)
    ok_steps = [s for s in steps if not s['saturated']]
    report = {'run_id': run_id, 'recipe': recipe, 'config': {'rates': a.rates, 'step_seconds': a.step_seconds,
                                                             'concurrency': a.concurrency, 'mode': 'open loop, no retry on 429'},
              'max_unsaturated_rps': max((s['achieved_completed_rps'] for s in ok_steps), default=None),
              'first_saturated_target_rps': next((s['target_rps'] for s in steps if s['saturated']), None),
              'steps': steps,
              'caveat': 'So do cua may va model dang chay. Voi model mau chay vai mili giay tren CPU, day KHONG phai nang luc cua may dich.'}
    out = a.output or a.run_dir / 'load-sweep-report.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    md = ['| Tốc độ gửi (req/s) | Gửi | Hoàn tất | Throughput hoàn tất (req/s) | p50 (ms) | p95 (ms) | p99 (ms) | Chờ hàng đợi p95 (ms) | Bị từ chối / lỗi | Bão hòa |',
          '|---|---|---|---|---|---|---|---|---|---|']
    for s in steps:
        lt = s['latency_total_ms']
        md.append(f"| {s['target_rps']} | {s['sent']} | {s['completed']} | {s['achieved_completed_rps']} | {lt['p50']} | {lt['p95']} | "
                  f"{lt['p99']} | {s['queue_ms_p95']} | {s['rejected_or_failed'] or '—'} | {'có' if s['saturated'] else 'không'} |")
    out.with_suffix('.md').write_text('\n'.join(md) + '\n', encoding='utf-8')
    print(f"SWEEP done: max unsaturated {report['max_unsaturated_rps']} req/s, first saturated target "
          f"{report['first_saturated_target_rps']}  -> {out}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
