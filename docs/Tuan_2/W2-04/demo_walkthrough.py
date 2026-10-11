"""Chay reference server nhu mot tien trinh that (HTTPS, hai cong) va ghi example payload that vao examples/.

    python3 demo_walkthrough.py [--out examples]

Kich ban giong mot ngay tich hop: camera hoi recipe active -> gui anh -> MES doc ket qua -> gui lai (retry)
-> loi thuong gap -> admin doi sang recipe B -> request cu/moi -> rollback -> audit.
Token va khoa TLS chi nam trong thu muc tam va bi xoa khi xong; examples/ chi chua '<redacted>'.
"""
import argparse
import base64
import http.client
import io
import json
import shutil
import ssl
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from client_example import ApiProblem, Vr01Client  # noqa: E402


def png(gray, size=(64, 48)):
    b = io.BytesIO()
    Image.new('L', size, gray).save(b, 'PNG')
    return b.getvalue()


def make_pki(d):
    run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True)  # noqa: E731
    run('openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-keyout',
        'ca.key', '-out', 'ca.pem', '-days', '2', '-subj', '/CN=vr01-lab-ca', '-addext',
        'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
    run('openssl', 'req', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-keyout', 'srv.key',
        '-out', 'srv.csr', '-subj', '/CN=127.0.0.1')
    (d / 'ext.cnf').write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n'
                               'extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n'
                               'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n')
    run('openssl', 'x509', '-req', '-in', 'srv.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
        '-out', 'srv.pem', '-days', '2', '-extfile', 'ext.cnf')


class Recorder:
    def __init__(self, out, secrets):
        self.out, self.secrets, self.n = out, secrets, 0
        self.index = []

    def save(self, name, op, plane, method, path, role, body, status, headers, response):
        self.n += 1
        rec = {'operationId': op, 'plane': plane, 'method': method, 'path': path,
               'request_headers': {'Authorization': f'Bearer <redacted:{role}>' if role else None,
                                   'Content-Type': 'application/json' if body is not None else None},
               'request_body': body, 'status': status,
               'response_headers': {k: v for k, v in headers.items()
                                    if k.lower() in ('x-trace-id', 'location', 'idempotent-replay', 'retry-after',
                                                     'content-type')},
               'response_body': response}
        text = json.dumps(rec, indent=2, ensure_ascii=False)
        for s in self.secrets:
            text = text.replace(s, '<redacted>')
        fname = f'{self.n:02d}-{name}.json'
        (self.out / fname).write_text(text + '\n', encoding='utf-8')
        self.index.append({'file': fname, 'operationId': op, 'status': status})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(HERE / 'examples'))
    args = ap.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix='w204-demo-'))
    proc = None
    try:
        make_pki(tmp)
        init = subprocess.run([sys.executable, str(HERE / 'reference_api.py'), '--init-lab-principals',
                               str(tmp / 'auth')], check=True, capture_output=True, text=True)
        files = json.loads(init.stdout)
        tokens = {v['role']: v['token'] for v in json.loads(Path(files['tokens_file']).read_text()).values()}
        proc = subprocess.Popen([sys.executable, str(HERE / 'reference_api.py'), '--data-dir', str(tmp / 'data'),
                                 '--principals', files['principals_file'], '--inference-port', '0',
                                 '--management-port', '0', '--tls-cert', str(tmp / 'srv.pem'),
                                 '--tls-key', str(tmp / 'srv.key')], stdout=subprocess.PIPE, text=True)
        ports = json.loads(proc.stdout.readline())
        inf = f"https://127.0.0.1:{ports['inference_port']}"
        ctx = ssl.create_default_context(cafile=str(tmp / 'ca.pem'))
        rec = Recorder(out, set(tokens.values()))

        def raw(name, op, plane, method, path, role, body=None, extra_headers=None):
            port = ports['inference_port' if plane == 'inference' else 'management_port']
            c = http.client.HTTPSConnection('127.0.0.1', port, context=ctx, timeout=15)
            h = dict(extra_headers or {})
            if role:
                h['Authorization'] = f'Bearer {tokens[role]}'
            data = None
            if body is not None:
                h['Content-Type'] = 'application/json'
                data = json.dumps(body).encode()
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            resp = json.loads(r.read() or b'null')
            rec.save(name, op, plane, method, path, role, body, r.status, dict(r.getheaders()), resp)
            c.close()
            return r.status, resp

        cam = Vr01Client(inf, tokens['operator'], str(tmp / 'ca.pem'))
        ar = cam.active_recipe('station-sim')
        raw('camera-get-active-recipe', 'getActiveRecipe', 'inference', 'GET',
            '/v1/stations/station-sim/active-recipe', 'operator')
        img = png(60)
        submit = {'request_id': 'st1-20261006-000123', 'product_id': 'PCB1-SN-000123', 'product_type': 'PCB1',
                  'recipe_version': ar['recipe_version'], 'captured_at': '2026-10-06T08:15:30Z',
                  'station_id': 'station-sim', 'retry_of': None,
                  'image': {'content_type': 'image/png', 'data_base64': base64.b64encode(img).decode()}}
        raw('camera-submit-202', 'submitInspection', 'inference', 'POST', '/v1/inspections', 'operator', submit)
        cam.result('st1-20261006-000123')
        raw('mes-get-status', 'getInspectionStatus', 'inference', 'GET',
            '/v1/inspections/st1-20261006-000123', 'viewer')
        raw('mes-get-result-ok', 'getInspectionResult', 'inference', 'GET',
            '/v1/inspections/st1-20261006-000123/result', 'viewer')
        raw('camera-retry-same-payload-200', 'submitInspection', 'inference', 'POST', '/v1/inspections',
            'operator', submit)
        raw('camera-same-id-other-image-409', 'submitInspection', 'inference', 'POST', '/v1/inspections',
            'operator', {**submit, 'image': {'content_type': 'image/png',
                                             'data_base64': base64.b64encode(png(200)).decode()}})
        bad = {**submit, 'request_id': 'st1-20261006-000124',
               'image': {'content_type': 'image/png', 'data_base64': base64.b64encode(b'not an image').decode()}}
        raw('camera-undecodable-image-422', 'submitInspection', 'inference', 'POST', '/v1/inspections', 'operator',
            bad)
        raw('camera-missing-field-400', 'submitInspection', 'inference', 'POST', '/v1/inspections', 'operator',
            {k: v for k, v in submit.items() if k != 'product_id'} | {'request_id': 'st1-20261006-000125'})
        raw('no-token-401', 'submitInspection', 'inference', 'POST', '/v1/inspections', None,
            {**submit, 'request_id': 'st1-20261006-000126'})
        raw('viewer-submit-403', 'submitInspection', 'inference', 'POST', '/v1/inspections', 'viewer',
            {**submit, 'request_id': 'st1-20261006-000127'})
        raw('ng-sample-submit', 'submitInspection', 'inference', 'POST', '/v1/inspections', 'operator',
            {**submit, 'request_id': 'st1-20261006-000128', 'product_id': 'PCB1-SN-000128',
             'image': {'content_type': 'image/png', 'data_base64': base64.b64encode(png(230)).decode()}})
        cam.result('st1-20261006-000128')
        raw('mes-get-result-ng', 'getInspectionResult', 'inference', 'GET',
            '/v1/inspections/st1-20261006-000128/result', 'viewer')
        raw('admin-list-recipes', 'listRecipes', 'management', 'GET', '/v1/admin/recipes', 'admin')
        raw('admin-validate-package-b', 'validatePackage', 'management', 'POST', '/v1/admin/packages/validate',
            'admin', {'package_name': 'model-b', 'package_version': '0.1.0'})
        raw('admin-activate-recipe-b', 'activateRecipe', 'management', 'POST',
            '/v1/admin/stations/station-sim/activation', 'admin',
            {'recipe_name': 'recipe-b', 'recipe_version': '0.1.0', 'reason': 'chuyển sang model B cho lô thử'},
            {'If-Match': ar['active_revision']})
        raw('camera-old-recipe-409', 'submitInspection', 'inference', 'POST', '/v1/inspections', 'operator',
            {**submit, 'request_id': 'st1-20261006-000129'})
        raw('camera-submit-recipe-b', 'submitInspection', 'inference', 'POST', '/v1/inspections', 'operator',
            {**submit, 'request_id': 'st1-20261006-000130', 'recipe_version': 'recipe-b@0.1.0'})
        cam.result('st1-20261006-000130')
        raw('mes-get-result-recipe-b', 'getInspectionResult', 'inference', 'GET',
            '/v1/inspections/st1-20261006-000130/result', 'viewer')
        raw('qc-history-by-product', 'listInspections', 'inference', 'GET',
            '/v1/inspections?product_id=PCB1-SN-000123&limit=10', 'viewer')
        raw('admin-rollback', 'rollbackRecipe', 'management', 'POST', '/v1/admin/stations/station-sim/rollback',
            'admin', {'reason': 'kết thúc lô thử, quay lại recipe A'})
        raw('admin-station-history', 'getStation', 'management', 'GET', '/v1/admin/stations/station-sim', 'admin')
        raw('operator-on-management-403', 'listRecipes', 'management', 'GET', '/v1/admin/recipes', 'operator')
        raw('admin-path-on-inference-port-404', 'listRecipes', 'inference', 'GET', '/v1/admin/recipes', 'admin')
        raw('triton-path-not-exposed-404', None, 'inference', 'POST', '/v2/models/model-a/infer', 'operator',
            {'inputs': []})
        raw('admin-audit', 'listAudit', 'management', 'GET', '/v1/admin/audit?limit=20', 'admin')
        raw('readiness', 'getReadiness', 'inference', 'GET', '/readyz', None)
        trace = (tmp / 'data' / 'trace.jsonl').read_text(encoding='utf-8')
        for s in tokens.values():
            assert s not in trace, 'token leaked into trace log'
        (out / 'demo-trace.jsonl').write_text(trace, encoding='utf-8')
        (out / 'INDEX.json').write_text(json.dumps({'server': 'reference_api.py subprocess, HTTPS (lab CA), '
                                                              'two ports', 'examples': rec.index}, indent=2),
                                        encoding='utf-8')
        print(json.dumps({'examples': len(rec.index), 'out': str(out)}))
    except ApiProblem as exc:
        print(f'demo failed: {exc}', file=sys.stderr)
        return 1
    finally:
        if proc:
            proc.terminate()
            proc.wait(timeout=10)
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
