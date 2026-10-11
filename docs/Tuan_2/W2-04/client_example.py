"""Vi du client cho module khac (camera simulator, MES simulator, QC UI) - chi dung business API.

Khong import gi tu reference_api, khong biet Triton o dau: chi can URL inference plane, token va CA.

    python3 client_example.py --url https://edge.local:8443 --token-file tok.txt --cafile ca.pem \
        submit --image pcb1.png --product-id PCB1-SN-000123 --request-id st1-000123
    python3 client_example.py ... result --request-id st1-000123
"""
import argparse
import base64
import json
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ApiProblem(Exception):
    def __init__(self, status, problem):
        super().__init__(f"{status} {problem.get('code')}: {problem.get('detail')}")
        self.status, self.problem = status, problem


class Vr01Client:
    def __init__(self, base_url, token, cafile=None, timeout=15):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.timeout = timeout
        self.ctx = ssl.create_default_context(cafile=cafile) if base_url.startswith('https') else None
        self.last_trace_id = None

    def _call(self, method, path, body=None, trace_id=None):
        headers = {'Authorization': f'Bearer {self.token}', 'X-Trace-Id': trace_id or uuid.uuid4().hex}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                self.last_trace_id = resp.headers.get('X-Trace-Id')
                return resp.status, json.loads(resp.read()), dict(resp.headers)
        except urllib.error.HTTPError as err:
            self.last_trace_id = err.headers.get('X-Trace-Id')
            raise ApiProblem(err.code, json.loads(err.read() or b'{}'))

    def active_recipe(self, station_id):
        return self._call('GET', f'/v1/stations/{station_id}/active-recipe')[1]

    def submit(self, request_id, product_id, image_bytes, content_type, station_id, recipe_version,
               product_type='PCB1', captured_at=None, retry_of=None, trace_id=None):
        body = {'request_id': request_id, 'product_id': product_id, 'product_type': product_type,
                'recipe_version': recipe_version, 'station_id': station_id, 'retry_of': retry_of,
                'captured_at': captured_at or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                'image': {'content_type': content_type, 'data_base64': base64.b64encode(image_bytes).decode()}}
        return self._call('POST', '/v1/inspections', body, trace_id)

    def status(self, request_id):
        return self._call('GET', f'/v1/inspections/{request_id}')[1]

    def result(self, request_id, wait_s=15):
        """Doc ket qua; neu chua xong (409 RESULT_NOT_READY) thi cho theo Retry-After."""
        deadline = time.monotonic() + wait_s
        while True:
            try:
                return self._call('GET', f'/v1/inspections/{request_id}/result')[1]
            except ApiProblem as exc:
                if exc.problem.get('code') != 'RESULT_NOT_READY' or time.monotonic() > deadline:
                    raise
                time.sleep(0.2)

    def by_product(self, product_id, limit=20):
        return self._call('GET', f'/v1/inspections?product_id={product_id}&limit={limit}')[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--url', required=True)
    ap.add_argument('--token-file', required=True, help='file chi chua token (khong truyen token tren command line)')
    ap.add_argument('--cafile')
    ap.add_argument('--station-id', default='station-sim')
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('submit')
    s.add_argument('--image', required=True)
    s.add_argument('--product-id', required=True)
    s.add_argument('--request-id', required=True)
    s.add_argument('--retry-of')
    r = sub.add_parser('result')
    r.add_argument('--request-id', required=True)
    q = sub.add_parser('history')
    q.add_argument('--product-id', required=True)
    args = ap.parse_args()
    client = Vr01Client(args.url, Path(args.token_file).read_text().strip(), args.cafile)
    try:
        if args.cmd == 'submit':
            img = Path(args.image).read_bytes()
            ctype = 'image/png' if img[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
            recipe = client.active_recipe(args.station_id)['recipe_version']
            status, body, _ = client.submit(args.request_id, args.product_id, img, ctype, args.station_id, recipe,
                                            retry_of=args.retry_of)
            print(json.dumps({'http': status, **body}, ensure_ascii=False))
            print(json.dumps(client.result(args.request_id), ensure_ascii=False, indent=2))
        elif args.cmd == 'result':
            print(json.dumps(client.result(args.request_id), ensure_ascii=False, indent=2))
        else:
            print(json.dumps(client.by_product(args.product_id), ensure_ascii=False, indent=2))
    except ApiProblem as exc:
        print(json.dumps({'http': exc.status, **exc.problem}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
