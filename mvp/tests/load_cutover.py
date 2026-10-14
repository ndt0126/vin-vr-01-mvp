"""Chuyen recipe/model DUOI TAI LIEN TUC tren stack dang chay (W3-04), chi dung thu vien chuan.

Usage: python3 tests/load_cutover.py --run-dir run [--rate 10] [--duration 60] [--cutover-every 10]

Client gui request deu dan, KHONG dung lai khi admin chuyen recipe A <-> B. Sau khi het tai, moi request
duoc doc lai va kiem:
  - khong thieu: moi request da gui deu co dung mot ket qua, o trang thai ket thuc;
  - khong trung: moi request_id chi co mot record (gui lai cung ID tra replay);
  - khong sai version: lineage recipe/model = recipe ma request da gui kem luc duoc nhan;
  - dung anh, dung model: input_sha256 = SHA-256 anh da gui; score = cong thuc cua model da pin.
Khi recipe vua doi, server tra 409 RECIPE_VERSION_MISMATCH (chua tao record); client lay recipe moi va gui
lai CUNG request_id - dung nhu hop dong. Bao cao ghi so lan nhu vay va "completion gap" quanh moi lan chuyen.
"""
import argparse
import base64
import hashlib
import json
import ssl
import struct
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATION = 'station-sim'
TERMINAL = {'COMPLETED', 'FAILED', 'TIMEOUT', 'INDETERMINATE', 'CANCELLED'}


def png(gray, size=8):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b''.join(b'\x00' + bytes([gray]) * size for _ in range(size))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


def ts(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


class Client:
    def __init__(self, host, ports, tokens, ca):
        self.host, self.ports, self.tokens = host, ports, tokens
        self.ctx = ssl.create_default_context(cafile=str(ca))
        self.timeout = 30

    def call(self, method, path, role=None, body=None, plane='inference'):
        headers, data = {}, None
        if body is not None:
            data, headers['Content-Type'] = json.dumps(body).encode(), 'application/json'
        if role:
            headers['Authorization'] = 'Bearer ' + self.tokens[role]
        req = urllib.request.Request(f'https://{self.host}:{self.ports[plane]}{path}', data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                raw, status = r.read(), r.status
        except urllib.error.HTTPError as e:
            raw, status = e.read(), e.code
        return status, (json.loads(raw) if raw else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--inference-port', type=int, default=8443)
    ap.add_argument('--management-port', type=int, default=9443)
    ap.add_argument('--rate', type=float, default=10, help='request moi giay')
    ap.add_argument('--duration', type=float, default=60, help='so giay phat tai')
    ap.add_argument('--cutover-every', type=float, default=10, help='so giay giua hai lan chuyen recipe')
    ap.add_argument('--allow-technical', action='store_true',
                    help='dung khi co chu y gay su co: FAILED/TIMEOUT/INDETERMINATE va request bi tu choi duoc DEM, '
                         'khong tinh la loi; van bat buoc khong thieu/trung/sai lineage')
    ap.add_argument('--recipes', default='recipe-a,recipe-b', help='hai recipe de chuyen qua lai (cai dau duoc kich hoat luc bat dau)')
    ap.add_argument('--journal', type=Path, help='ghi tung request da gui ra JSONL ngay khi gui (cho luot chay dai: client chet van con bang chung)')
    ap.add_argument('--progress', type=Path, help='file JSON trang thai, cap nhat moi 30 giay (cho watcher)')
    ap.add_argument('--client-timeout', type=float, default=30, help='timeout moi HTTP call cua client (giay)')
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    tokens = {v['role']: v['token'] for v in
              json.loads((args.run_dir / 'auth' / 'lab-tokens.secret.json').read_text()).values()}
    c = Client(args.host, {'inference': args.inference_port, 'management': args.management_port}, tokens,
               args.run_dir / 'tls' / 'ca.crt')
    c.timeout = args.client_timeout
    pk = HERE.parent / 'packages' / 'examples'
    if (args.run_dir / 'examples' / 'packages').is_dir():
        pk = args.run_dir / 'examples'   # kho package luc chay (co ca fixture)
    params = {d.name: json.loads((d / 'model.json').read_text()) for d in (pk / 'packages').iterdir()
              if (d / 'model.json').is_file()}   # model ONNX khong co model.json: khong tinh lai diem o client
    recipes = {}
    for f in (pk / 'recipes').glob('*.json'):
        r = json.loads(f.read_text())
        recipes[f"{r['name']}@{r['version']}"] = {'model': r['package']['name'], 'threshold': r['decision']['threshold']}
    run_id = time.strftime('%Y%m%dT%H%M%S')
    first, second = args.recipes.split(',')
    st, act = c.call('POST', f'/v1/admin/stations/{STATION}/activation', 'admin',
                     {'recipe_name': first, 'recipe_version': '0.1.0', 'reason': f'load {run_id} start'}, 'management')
    if st != 200:
        raise SystemExit(f'cannot activate {first}: {st} {act}')
    current = {'recipe': f'{first}@0.1.0'}
    journal = open(args.journal, 'a', buffering=1) if args.journal else None
    sent, cutovers, stop = [], [], threading.Event()
    counters = {'recipe_refresh_409': 0, 'queue_full_429': 0, 'not_ready_503': 0, 'send_errors': 0}

    def switcher():
        target = second
        while not stop.wait(args.cutover_every):
            t0 = time.time()
            s, a = c.call('POST', f'/v1/admin/stations/{STATION}/activation', 'admin',
                          {'recipe_name': target, 'recipe_version': '0.1.0', 'reason': f'load {run_id} cutover'},
                          'management')
            cutovers.append({'to': f'{target}@0.1.0', 'status': s, 'changed': a and a.get('changed'),
                             'requested_at': t0, 'returned_at': time.time(),
                             'golden_passed': a and (a.get('golden') or {}).get('passed')})
            if journal:
                journal.write(json.dumps({'cutover': cutovers[-1]}) + '\n')
            if s == 200:
                target = first if target == second else second

    th = threading.Thread(target=switcher, daemon=True)
    th.start()
    period, t_start, i = 1.0 / args.rate, time.time(), 0
    while time.time() - t_start < args.duration:
        due = t_start + i * period
        time.sleep(max(0.0, due - time.time()))
        gray = (i * 37) % 256
        image = png(gray)
        rid, product = f'load-{run_id}-{i:06d}', f'PCB1-LOAD-{i % 50:03d}'
        rec = {'rid': rid, 'product': product, 'gray': gray, 'sha': hashlib.sha256(image).hexdigest(),
               'attempts': 0, 'accepted_recipe': None}
        # captured_at co dinh cho MOI lan gui lai: payload phai giong het, neu khong server tra 409 IDEMPOTENCY_CONFLICT
        # (loi client lo ra o phien GPU 14/10, P17: lan gui lai roi qua ranh gioi giay).
        captured_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        for _ in range(50):  # cung request_id cho moi lan thu lai
            recipe = current['recipe']
            body = {'request_id': rid, 'product_id': product, 'product_type': 'PCB1', 'recipe_version': recipe,
                    'captured_at': captured_at, 'station_id': STATION,
                    'retry_of': None, 'image': {'content_type': 'image/png',
                                                'data_base64': base64.b64encode(image).decode()}}
            rec['attempts'] += 1
            try:
                s, b = c.call('POST', '/v1/inspections', 'operator', body)
            except OSError:
                counters['send_errors'] += 1
                time.sleep(0.05)
                continue
            if s in (200, 202):
                rec['accepted_recipe'], rec['submit_status'] = recipe, s
                break
            if s == 409 and b.get('code') == 'RECIPE_VERSION_MISMATCH':
                counters['recipe_refresh_409'] += 1
                current['recipe'] = b['details']['active_recipe_version']
            elif s == 429:
                counters['queue_full_429'] += 1
                time.sleep(0.05)
            elif s == 503:
                counters['not_ready_503'] += 1
                time.sleep(0.1)
            else:
                rec['submit_status'], rec['error'] = s, b
                break
        sent.append(rec)
        if journal:
            journal.write(json.dumps({'sent': rec, 'at': time.time()}) + '\n')
        if args.progress and i % max(1, int(args.rate * 30)) == 0:
            args.progress.write_text(json.dumps({'run_id': run_id, 'elapsed_s': round(time.time() - t_start, 1),
                                                 'planned_s': args.duration, 'sent': len(sent), 'cutovers': len(cutovers),
                                                 'cutovers_failed': sum(1 for x in cutovers if x['status'] != 200),
                                                 'client_counters': counters, 'updated_at': time.time()}))
        i += 1
    stop.set()
    th.join()

    # ---- doc lai tung request va kiem
    problems, results, technical, not_accepted = [], {}, {}, 0
    for rec in sent:
        if rec['accepted_recipe'] is None:
            if args.allow_technical:
                not_accepted += 1
                s, _ = c.call('GET', f"/v1/inspections/{rec['rid']}", 'viewer')
                if s != 404:
                    problems.append({'rid': rec['rid'], 'problem': f'client saw rejection but a record exists ({s})'})
            else:
                problems.append({'rid': rec['rid'], 'problem': 'never accepted', 'detail': rec.get('error')})
            continue
        res = None
        for _ in range(600):
            s, res = c.call('GET', f"/v1/inspections/{rec['rid']}/result", 'viewer')
            if s == 200:
                break
            time.sleep(0.05)
        if not res or res.get('state') not in TERMINAL:
            problems.append({'rid': rec['rid'], 'problem': 'missing: no terminal result'})
            continue
        results[rec['rid']] = res
        lin = res['lineage']
        want = recipes[rec['accepted_recipe']]
        p = params.get(want['model'])
        score = None if p is None else round(min(1.0, max(0.0, p['gain'] * round(rec['gray'] / 255.0, 6) + p['bias'])), 6)
        checks = {
            'state COMPLETED': res['state'] == 'COMPLETED',
            'request_id': res['request_id'] == rec['rid'],
            'product_id': lin['product_id'] == rec['product'],
            'input_sha256': lin['input_sha256'] == rec['sha'],
            'recipe = recipe accepted with': f"{lin['recipe']['name']}@{lin['recipe']['version']}" == rec['accepted_recipe'],
            'model of that recipe': lin['model']['name'] == want['model'],
            'score of that model': res['score'] is not None and (score is None or abs(res['score'] - score) <= 1e-5),
        }
        if args.allow_technical and res['state'] != 'COMPLETED':
            technical[res['state']] = technical.get(res['state'], 0) + 1
            checks = {k: v for k, v in checks.items() if k not in ('state COMPLETED', 'score of that model')}
            checks['decision is null'] = res['decision'] is None and res['score'] is None
        bad = [k for k, ok in checks.items() if not ok]
        if bad:
            problems.append({'rid': rec['rid'], 'problem': 'wrong: ' + ', '.join(bad), 'state': res['state'],
                             'reason': res.get('reason')})
    # trung: moi product chi co dung cac request da gui, moi request_id xuat hien mot lan
    dup = []
    for product in sorted({r['product'] for r in sent}):
        ids, cursor = [], None
        while True:
            q = f'/v1/inspections?product_id={product}&limit=100' + (f'&cursor={cursor}' if cursor else '')
            s, page = c.call('GET', q, 'viewer')
            ids += [x['request_id'] for x in page['items'] if x['request_id'].startswith(f'load-{run_id}-')]
            cursor = page['next_cursor']
            if not cursor:
                break
        mine = [r['rid'] for r in sent if r['product'] == product and r['accepted_recipe']]
        if sorted(ids) != sorted(mine):
            dup.append({'product': product, 'listed': len(ids), 'sent': len(mine)})
    # completion gap quanh moi lan chuyen: ket qua cuoi cua recipe cu -> ket qua dau cua recipe moi
    done = sorted(((ts(r['finished_at']), f"{r['lineage']['recipe']['name']}@{r['lineage']['recipe']['version']}")
                   for r in results.values() if r['state'] == 'COMPLETED'))
    gaps, prev = [], f'{first}@0.1.0'
    for cut in [x for x in cutovers if x['status'] == 200 and x['changed']]:
        new = cut['to']
        first_new = next((t for t, rcp in done if rcp == new and t >= cut['requested_at'] - 0.001), None)
        last_old = max((t for t, rcp in done if rcp == prev and (first_new is None or t <= first_new)), default=None)
        gaps.append({'to': new, 'activation_s': round(cut['returned_at'] - cut['requested_at'], 3),
                     'gap_last_old_to_first_new_s': None if None in (first_new, last_old) else round(first_new - last_old, 3)})
        prev = new
    measured = [g['gap_last_old_to_first_new_s'] for g in gaps if g['gap_last_old_to_first_new_s'] is not None]
    by_recipe = {}
    for r in results.values():
        k = f"{r['lineage']['recipe']['name']}@{r['lineage']['recipe']['version']}"
        by_recipe[k] = by_recipe.get(k, 0) + 1
    lat = sorted(r['timing_ms']['total'] for r in results.values() if r['timing_ms']['total'] is not None)
    ok_cut = [x for x in cutovers if x['status'] == 200 and x['changed'] and x['golden_passed']]
    if args.allow_technical:
        verdict = not problems and not dup and len(results) + not_accepted == len(sent)
    else:
        verdict = not problems and not dup and len(ok_cut) == len(cutovers) and len(cutovers) >= 1 \
            and len(results) == len(sent)
    scored = sum(1 for r in sent if r['accepted_recipe'] and params.get(recipes[r['accepted_recipe']]['model']) is not None)
    report = {
        'verdict': 'PASS' if verdict else 'FAIL', 'run_id': run_id, 'recipes': [first, second],
        'score_recomputed_by_client_for': scored,
        'config': {'rate_per_s': args.rate, 'duration_s': args.duration, 'cutover_every_s': args.cutover_every,
                   'send_period_s': round(period, 4)},
        'requests': {'sent': len(sent), 'with_terminal_result': len(results),
                     'completed': sum(r['state'] == 'COMPLETED' for r in results.values()), 'by_recipe': by_recipe,
                     'missing_or_wrong': len(problems), 'duplicate_or_extra_products': len(dup),
                     'technical_states': technical, 'not_accepted': not_accepted},
        'cutovers': {'requested': len(cutovers), 'succeeded': len(ok_cut), 'detail': gaps,
                     'max_gap_s': max(measured) if measured else None,
                     'gap_resolution_note': f'gap khong the nho hon chu ky gui {round(period, 3)} s; day khong phai so do downtime'},
        'client_retries_same_request_id': counters,
        'latency_total_ms': {'p50': lat[len(lat) // 2] if lat else None,
                             'p95': lat[int(len(lat) * 0.95) - 1] if lat else None, 'max': lat[-1] if lat else None},
        'problems': problems[:20], 'duplicates': dup[:20],
    }
    out = args.output or args.run_dir / 'load-cutover-report.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"LOAD-CUTOVER {report['verdict']}  sent {len(sent)}, results {len(results)}, problems {len(problems)}, "
          f"cutovers {len(ok_cut)}/{len(cutovers)}, max gap {report['cutovers']['max_gap_s']} s, "
          f"409-refresh {counters['recipe_refresh_409']}  -> {out}")
    return 0 if verdict else 1


if __name__ == '__main__':
    sys.exit(main())
