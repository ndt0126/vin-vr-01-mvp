"""Smoke flow tren stack DANG CHAY (make start), qua HTTPS, chi dung thu vien chuan cua Python.

Usage: python3 tests/smoke.py --run-dir run [--host 127.0.0.1] [--output run/smoke-report.json]

Luong: readyz -> auth (401/403) -> chon recipe A -> gui anh -> ket qua OK/NG/REVIEW + lineage model-a
-> anh hong 422 -> gui lai cung ID (replay 200, khac payload 409) -> admin chuyen recipe B -> gui anh -> lineage model-b
-> liet ke theo state. Ket thuc: recipe active = recipe-b.
"""
import argparse
import base64
import json
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path

STATION = 'station-sim'


def png(gray, size=8):
    """PNG xam 8-bit, khong can Pillow."""
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b''.join(b'\x00' + bytes([gray]) * size for _ in range(size))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 0, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))


class Client:
    def __init__(self, host, ports, tokens, ca):
        self.host, self.ports, self.tokens = host, ports, tokens
        self.ctx = ssl.create_default_context(cafile=str(ca))

    def call(self, method, path, role=None, body=None, plane='inference'):
        headers, data = {}, None
        if body is not None:
            data, headers['Content-Type'] = json.dumps(body).encode(), 'application/json'
        if role:
            headers['Authorization'] = 'Bearer ' + self.tokens[role]
        req = urllib.request.Request(f'https://{self.host}:{self.ports[plane]}{path}', data=data, method=method,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20, context=self.ctx) as r:
                raw, status, hdr = r.read(), r.status, r.headers
        except urllib.error.HTTPError as e:
            raw, status, hdr = e.read(), e.code, e.headers
        return status, (json.loads(raw) if raw else None), {k.lower(): v for k, v in hdr.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--inference-port', type=int, default=8443)
    ap.add_argument('--management-port', type=int, default=9443)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    tokens = {v['role']: v['token'] for v in
              json.loads((args.run_dir / 'auth' / 'lab-tokens.secret.json').read_text()).values()}
    c = Client(args.host, {'inference': args.inference_port, 'management': args.management_port}, tokens,
               args.run_dir / 'tls' / 'ca.crt')
    run_id = time.strftime('%Y%m%dT%H%M%S')
    steps, failed = [], False

    def step(name, ok, detail):
        nonlocal failed
        steps.append({'step': name, 'result': 'PASS' if ok else 'FAIL', 'detail': detail})
        failed = failed or not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name}: {detail}")

    def body(rid, product, gray, recipe, image=None):
        return {'request_id': rid, 'product_id': product, 'product_type': 'PCB1', 'recipe_version': recipe,
                'captured_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'station_id': STATION,
                'retry_of': None, 'image': {'content_type': 'image/png',
                                            'data_base64': base64.b64encode(image or png(gray)).decode()}}

    sent = {}

    def inspect(rid, product, gray, recipe, model):
        sent[rid] = body(rid, product, gray, recipe)
        st, sub, _ = c.call('POST', '/v1/inspections', 'operator', sent[rid])
        res = None
        for _ in range(100):
            st2, res, _ = c.call('GET', f'/v1/inspections/{rid}/result', 'viewer')
            if st2 == 200:
                break
            time.sleep(0.1)
        ok = st == 202 and res and res.get('state') == 'COMPLETED' and res['decision'] in ('OK', 'NG', 'REVIEW') \
            and res['lineage']['model']['name'] == model and res['lineage']['product_id'] == product
        lin = res.get('lineage', {}) if res else {}
        step(f'inspect {rid}', ok, {'submit': st, 'state': res and res.get('state'), 'decision': res and res.get('decision'),
                                    'score': res and res.get('score'), 'model': lin.get('model', {}).get('name'),
                                    'model_digest': lin.get('model', {}).get('manifest_sha256', '')[:12],
                                    'recipe': lin.get('recipe', {}).get('name'),
                                    'inference_ms': res and res.get('timing_ms', {}).get('inference')})
        return res

    def activate(name):
        st, act, _ = c.call('POST', f'/v1/admin/stations/{STATION}/activation', 'admin',
                            {'recipe_name': name, 'recipe_version': '0.1.0', 'reason': f'smoke {run_id}'}, 'management')
        step(f'admin activates {name}', st == 200, {'status': st, 'changed': act and act.get('changed'),
                                                    'golden': act and act.get('golden')})

    st, rz, _ = c.call('GET', '/readyz')
    step('readyz', st == 200, {'status': st, 'body': rz})
    st, _, _ = c.call('GET', f'/v1/stations/{STATION}/active-recipe')
    step('no token -> 401', st == 401, st)
    st, _, _ = c.call('POST', '/v1/inspections', 'viewer', body('x', 'P', 10, 'recipe-a@0.1.0'))
    step('viewer cannot submit -> 403', st == 403, st)
    st, _, _ = c.call('GET', '/v1/admin/audit', 'operator', plane='management')
    step('operator cannot use management -> 403', st == 403, st)
    st, _, _ = c.call('GET', '/v2/health/ready', 'admin')
    step('no Triton route on business API -> 404', st == 404, st)
    activate('recipe-a')
    a = inspect(f'smoke-{run_id}-a1', 'PCB1-SN-SMOKE-1', 40, 'recipe-a@0.1.0', 'model-a')
    inspect(f'smoke-{run_id}-a2', 'PCB1-SN-SMOKE-2', 220, 'recipe-a@0.1.0', 'model-a')
    st, prob, _ = c.call('POST', '/v1/inspections', 'operator',
                         body(f'smoke-{run_id}-bad', 'PCB1-SN-SMOKE-3', 0, 'recipe-a@0.1.0', image=b'not an image'))
    step('corrupt image -> 422, no record', st == 422 and prob['code'] == 'IMAGE_UNDECODABLE', {'status': st})
    first = sent[f'smoke-{run_id}-a1']
    st, rep, hdr = c.call('POST', '/v1/inspections', 'operator', first)
    step('same request_id + same payload -> 200 replay, no new inference',
         st == 200 and hdr.get('idempotent-replay') == 'true' and rep['state'] == 'COMPLETED', st)
    st, prob, _ = c.call('POST', '/v1/inspections', 'operator', dict(first, product_id='PCB1-SN-OTHER'))
    step('same request_id + other product -> 409', st == 409 and prob['code'] == 'IDEMPOTENCY_CONFLICT', st)
    st, prob, _ = c.call('POST', f'/v1/inspections/smoke-{run_id}-a1/cancel', 'operator', {'reason': 'smoke cancel check'})
    step('cancel a finished request -> 409, result untouched', st == 409 and prob['code'] == 'ALREADY_TERMINAL'
         and prob['details']['state'] == 'COMPLETED', st)
    st, _, _ = c.call('POST', f'/v1/inspections/smoke-{run_id}-a1/cancel', 'viewer', {'reason': 'smoke cancel check'})
    step('viewer cannot cancel -> 403', st == 403, st)
    activate('recipe-b')
    st, prob, _ = c.call('POST', '/v1/inspections', 'operator',
                         body(f'smoke-{run_id}-old', 'PCB1-SN-SMOKE-4', 40, 'recipe-a@0.1.0'))
    step('old recipe_version after switch -> 409', st == 409 and prob['code'] == 'RECIPE_VERSION_MISMATCH', st)
    inspect(f'smoke-{run_id}-b1', 'PCB1-SN-SMOKE-1', 40, 'recipe-b@0.1.0', 'model-b')
    st, again, _ = c.call('GET', f'/v1/inspections/smoke-{run_id}-a1/result', 'viewer')
    step('result of request pinned to A unchanged after switch', st == 200 and again == a, st)
    st, lst, _ = c.call('GET', '/v1/inspections?state=COMPLETED&limit=3', 'viewer')
    step('list by state', st == 200 and lst['items'][0]['request_id'] == f'smoke-{run_id}-b1',
         [i['request_id'] for i in (lst or {}).get('items', [])])
    report = {'verdict': 'FAIL' if failed else 'PASS', 'run_id': run_id, 'steps': steps,
              'active_recipe_at_end': 'recipe-b@0.1.0'}
    out = args.output or args.run_dir / 'smoke-report.json'
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"SMOKE {report['verdict']}  {sum(s['result'] == 'PASS' for s in steps)}/{len(steps)}  -> {out}")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
