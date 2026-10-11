"""vr01ctl - lenh van hanh cho VR-01 MVP (CLI cua admin/operator), chi dung thu vien chuan.

  vr01ctl status                      san sang chua, ly do, recipe/model dang active
  vr01ctl recipes                     cac recipe da dang ky
  vr01ctl activate <recipe> [-v VER] --reason "..."     chuyen recipe/model (golden check truoc khi chuyen)
  vr01ctl rollback --reason "..."     quay ve recipe truoc
  vr01ctl history [-n 10]             lich su chuyen recipe
  vr01ctl audit [-n 20]               nhat ky audit gan nhat
  vr01ctl pending                     cac lan kiem chua co ket luan (FAILED/TIMEOUT/INDETERMINATE/CANCELLED)
  vr01ctl result <request_id>         ket qua + lineage cua mot request

Doc token va CA trong <run-dir>/auth va <run-dir>/tls (file token mode 600). Khong in token.
Ma thoat: 0 = thanh cong; 1 = he thong tu choi/khong san sang; 2 = sai cu phap.
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

STATION = 'station-sim'


class Ctl:
    def __init__(self, run, host, iport, mport):
        self.tokens = {v['role']: v['token'] for v in
                       json.loads((run / 'auth' / 'lab-tokens.secret.json').read_text()).values()}
        self.ctx = ssl.create_default_context(cafile=str(run / 'tls' / 'ca.crt'))
        self.base = {'inference': f'https://{host}:{iport}', 'management': f'https://{host}:{mport}'}

    def call(self, method, path, role=None, body=None, plane='inference'):
        headers, data = {}, None
        if body is not None:
            data, headers['Content-Type'] = json.dumps(body).encode(), 'application/json'
        if role:
            headers['Authorization'] = 'Bearer ' + self.tokens[role]
        req = urllib.request.Request(self.base[plane] + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60, context=self.ctx) as r:
                return r.status, json.loads(r.read() or b'null')
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b'null')


def fail(status, body):
    print(f"KHONG THANH CONG: HTTP {status} {body.get('code', '')} - {body.get('detail', body)}")
    if body.get('details'):
        print('  chi tiet:', json.dumps(body['details'], ensure_ascii=False))
    return 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-dir', type=Path, default=Path('run'))
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--inference-port', type=int, default=8443)
    ap.add_argument('--management-port', type=int, default=9443)
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('status')
    sub.add_parser('recipes')
    p = sub.add_parser('activate')
    p.add_argument('recipe')
    p.add_argument('-v', '--version', default='0.1.0')
    p.add_argument('--reason', required=True)
    p = sub.add_parser('rollback')
    p.add_argument('--reason', required=True)
    p = sub.add_parser('history')
    p.add_argument('-n', type=int, default=10)
    p = sub.add_parser('audit')
    p.add_argument('-n', type=int, default=20)
    sub.add_parser('pending')
    p = sub.add_parser('result')
    p.add_argument('request_id')
    a = ap.parse_args()
    c = Ctl(a.run_dir, a.host, a.inference_port, a.management_port)

    if a.cmd == 'status':
        try:
            st, rz = c.call('GET', '/readyz')
        except OSError as exc:
            print(f'KHONG KET NOI DUOC API: {exc}')
            return 1
        print('SAN SANG' if st == 200 else f"CHUA SAN SANG: {', '.join(rz.get('reasons', []))}")
        s2, act = c.call('GET', f'/v1/stations/{STATION}/active-recipe', 'viewer')
        if s2 == 200:
            print(f"recipe active : {act['recipe_version']}  (sha256 {act['recipe']['sha256'][:12]})")
            print(f"model         : {act['model']['name']}@{act['model']['version']}  (sha256 {act['model']['manifest_sha256'][:12]})")
            print(f"kich hoat luc : {act['activated_at']}")
        else:
            print(f"recipe active : khong xac dinh (HTTP {s2} {act.get('code')})")
        return 0 if st == 200 else 1
    if a.cmd == 'recipes':
        st, b = c.call('GET', '/v1/admin/recipes', 'admin', plane='management')
        if st != 200:
            return fail(st, b)
        for r in b['items']:
            print(f"{'*' if r['active'] else ' '} {r['recipe']['name']}@{r['recipe']['version']:<8} model {r['model']['name']}@{r['model']['version']}"
                  f"  nguong {r['threshold']}  rollback ve {r['rollback_recipe'] or '-'}")
        print('(* = dang active)')
        return 0
    if a.cmd in ('activate', 'rollback'):
        if a.cmd == 'activate':
            st, b = c.call('POST', f'/v1/admin/stations/{STATION}/activation', 'admin',
                           {'recipe_name': a.recipe, 'recipe_version': a.version, 'reason': a.reason}, 'management')
        else:
            st, b = c.call('POST', f'/v1/admin/stations/{STATION}/rollback', 'admin', {'reason': a.reason}, 'management')
        if st != 200:
            return fail(st, b)
        frm = b['from_recipe']
        print(('DA CHUYEN' if b['changed'] else 'KHONG DOI (recipe nay dang active)')
              + f": {frm['name'] + '@' + frm['version'] if frm else '-'} -> {b['to_recipe']['name']}@{b['to_recipe']['version']}")
        g = b['golden']
        print(f"golden: mong doi {g['expected']}, thuc te {g['actual']}, {'DAT' if g['passed'] else 'KHONG DAT'}   activation_id {b['activation_id']}")
        return 0
    if a.cmd == 'history':
        st, b = c.call('GET', f'/v1/admin/stations/{STATION}', 'admin', plane='management')
        if st != 200:
            return fail(st, b)
        for h in b.get('history', [])[:a.n]:
            frm = h.get('from_recipe')
            print(f"{h['at']}  {h['actor']:<14} {frm['name'] + '@' + frm['version'] if frm else '-':<18} -> "
                  f"{h['to_recipe']['name']}@{h['to_recipe']['version']}  \"{h['reason']}\"")
        return 0
    if a.cmd == 'audit':
        st, b = c.call('GET', f'/v1/admin/audit?limit={a.n}', 'admin', plane='management')
        if st != 200:
            return fail(st, b)
        for x in b['items']:
            print(f"{x['at']}  {x['actor']:<14} {x['action']:<22} {x['target']:<40} {x['outcome']}")
        return 0
    if a.cmd == 'pending':
        total = 0
        for state in ('FAILED', 'TIMEOUT', 'INDETERMINATE', 'CANCELLED'):
            st, b = c.call('GET', f'/v1/inspections?state={state}&limit=100', 'viewer')
            if st != 200:
                return fail(st, b)
            for i in b['items']:
                total += 1
                print(f"{i['received_at']}  {i['state']:<13} {i['reason'] or '':<28} {i['product_id']:<24} {i['request_id']}")
        print(f'{total} lan kiem chua co ket luan' + (' (toi da 100 moi trang thai)' if total else ''))
        return 0
    if a.cmd == 'result':
        st, b = c.call('GET', f'/v1/inspections/{a.request_id}/result', 'viewer')
        if st != 200:
            return fail(st, b)
        print(json.dumps(b, indent=2, ensure_ascii=False))
        return 0
    return 2


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (urllib.error.URLError, OSError) as exc:
        print(f'KHONG KET NOI DUOC API: {exc}')
        sys.exit(1)
