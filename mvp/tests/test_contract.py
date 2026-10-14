"""Contract + negative tests cho W2-04 (openapi.v1.yaml <-> reference_api.py).

Moi response di qua ContractClient: status phai duoc khai bao trong spec cho operation do, va body phai
dung schema cua status/content-type do. Neu server tra status khong co trong spec -> test FAIL ngay.

Bien moi truong VR01_EVIDENCE_DIR (tuy chon): ghi transcript.jsonl (token da che) va coverage.json.
"""
import base64
import http.client
import io
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
from PIL import Image

import inspection_api as ra

SPEC = ra.Spec()
DOC = SPEC.doc
TRANSCRIPT = []
OBSERVED = set()
SECRETS = set()


def png(gray=64, size=(4, 4), mode='L'):
    im = Image.new(mode, size, gray if mode == 'L' else (gray, gray, gray))
    b = io.BytesIO()
    im.save(b, 'PNG')
    return b.getvalue()


def jpeg(gray=64, size=(8, 8)):
    b = io.BytesIO()
    Image.new('RGB', size, (gray, gray, gray)).save(b, 'JPEG', quality=95)
    return b.getvalue()


def b64(data):
    return base64.b64encode(data).decode()


def submit_body(rid, product='PCB1-SN-0001', image=None, recipe='recipe-a@0.1.0', ctype='image/png', **extra):
    body = {'request_id': rid, 'product_id': product, 'product_type': 'PCB1', 'recipe_version': recipe,
            'captured_at': '2026-10-06T08:15:30Z', 'station_id': 'station-sim', 'retry_of': None,
            'image': {'content_type': ctype, 'data_base64': b64(png() if image is None else image)}}
    body.update(extra)
    return body


# ------------------------------------------------------------------ spec lookup


def _resolve(node):
    while isinstance(node, dict) and '$ref' in node:
        cur = DOC
        for part in node['$ref'][2:].split('/'):
            cur = cur[part]
        node = cur
    return node


OPS = {}
for _path, _item in DOC['paths'].items():
    for _m, _op in _item.items():
        if _m in ('get', 'post'):
            OPS[_op['operationId']] = (_m.upper(), _path, _op)


def response_schema(op_id, status, ctype):
    _, _, op = OPS[op_id]
    responses = op['responses']
    if str(status) not in responses:
        raise AssertionError(f'{op_id}: status {status} not documented in spec')
    resp = _resolve(responses[str(status)])
    content = resp.get('content', {})
    if ctype not in content:
        raise AssertionError(f'{op_id} {status}: content-type {ctype} not documented ({list(content)})')
    return {'components': DOC['components'], **_resolve(content[ctype]['schema'])}


# ------------------------------------------------------------------ client


class Resp:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def __repr__(self):
        return f'<Resp {self.status} {self.body}>'


class ContractClient:
    def __init__(self, server, tokens, tls_ctx=None):
        self.server, self.tokens, self.tls_ctx = server, tokens, tls_ctx

    def conn(self, plane):
        port = self.server.port(plane)
        if self.tls_ctx:
            return http.client.HTTPSConnection('127.0.0.1', port, timeout=20, context=self.tls_ctx)
        return http.client.HTTPConnection('127.0.0.1', port, timeout=20)

    def call(self, op_id, plane=None, role=None, path_params=None, query='', body=None, raw_body=None,
             headers=None, token=None, expect_op=True, method=None, path=None):
        m, tmpl, op = OPS[op_id] if op_id in OPS else (method, path, None)
        method = method or m
        url = (path or tmpl).format(**(path_params or {})) + (('?' + query) if query else '')
        plane = plane or ('management' if url.startswith('/v1/admin') else 'inference')
        hdrs = dict(headers or {})
        if role:
            hdrs['Authorization'] = f"Bearer {self.tokens[role]}"
        if token is not None:
            hdrs['Authorization'] = f'Bearer {token}'
        data = raw_body
        if body is not None:
            data = json.dumps(body).encode()
            hdrs.setdefault('Content-Type', 'application/json')
        c = self.conn(plane)
        c.request(method, url, body=data, headers=hdrs)
        r = c.getresponse()
        raw = r.read()
        c.close()
        ctype = (r.getheader('Content-Type') or '').split(';')[0]
        parsed = json.loads(raw) if raw else None
        resp = Resp(r.status, {k.lower(): v for k, v in r.getheaders()}, parsed)
        TRANSCRIPT.append({'op': op_id, 'plane': plane, 'method': method, 'path': url.split('?')[0],
                           'role': role or ('custom-token' if token is not None else None),
                           'status': r.status, 'trace_id': resp.headers.get('x-trace-id'),
                           'response': _truncate(parsed)})
        assert 'x-trace-id' in resp.headers, 'every response must carry X-Trace-Id'
        if op is not None and expect_op:
            schema = response_schema(op_id, r.status, ctype)
            jsonschema.Draft202012Validator(schema, format_checker=ra.FORMATS).validate(parsed)
            OBSERVED.add((op_id, r.status))
        elif ctype == 'application/problem+json':
            jsonschema.Draft202012Validator({'components': DOC['components'],
                                             '$ref': '#/components/schemas/Problem'}).validate(parsed)
        return resp


def _truncate(obj):
    s = json.dumps(obj, ensure_ascii=False)
    return obj if len(s) < 2000 else {'_truncated': s[:2000]}


# ------------------------------------------------------------------ fixtures


class FakeKServe:
    """Inference server gia lap theo KServe v2 (giao thuc HTTP cua Triton), chi de test adapter."""

    def __init__(self, models):
        self.models, self.calls = models, []
        self.loaded, self.lifecycle, self.wrong_id = set(), [], False
        self.delays = {}  # ten model -> giay ngu them (gia lap model cham)
        self.fail_above = {}  # ten model -> nguong mean; >= nguong thi tra 400 (gia lap model hong)
        self.onnx, self.sessions = {}, {}  # ten model -> duong dan model.onnx (model anh that)
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                parts = self.path.split('/')
                if self.path == '/v2/health/ready':
                    return self._send(200, {})
                if len(parts) == 5 and parts[2] == 'models' and parts[4] == 'ready':
                    return self._send(200 if parts[3] in outer.loaded else 400, {})
                self._send(404, {})

            def do_POST(self):
                payload = self.rfile.read(int(self.headers['Content-Length']))
                hlen = self.headers.get('Inference-Header-Content-Length')
                raw = payload[int(hlen):] if hlen else None       # KServe binary tensor extension
                body = json.loads(payload[:int(hlen)] if hlen else payload)
                parts = self.path.split('/')
                if parts[2] == 'repository':  # Triton explicit model control
                    outer.lifecycle.append((parts[5], parts[4]))
                    if parts[5] == 'load':
                        if parts[4] not in outer.models and parts[4] not in outer.onnx:
                            return self._send(400, {'error': 'unknown model'})
                        outer.loaded.add(parts[4])
                    else:
                        outer.loaded.discard(parts[4])
                    return self._send(200, {})
                name = parts[3]
                if name not in outer.loaded:
                    return self._send(400, {'error': 'model not loaded'})
                outer.calls.append({'path': self.path, 'trace': self.headers.get('X-Trace-Id'), 'body': body})
                time.sleep(outer.delays.get(name, 0))
                if raw is not None:   # model anh that: chay file ONNX bang onnxruntime (may test phai co cai)
                    import numpy as np
                    import onnxruntime as ort
                    sess = outer.sessions.get(name)
                    if sess is None:
                        sess = outer.sessions[name] = ort.InferenceSession(outer.onnx[name], providers=['CPUExecutionProvider'])
                    shape = body['inputs'][0]['shape']
                    score = float(sess.run(['SCORE'], {'IMAGE': np.frombuffer(raw, dtype=np.uint8).reshape(shape)})[0][0])
                    outer.calls[-1]['binary_bytes'] = len(raw)
                    return self._send(200, {'model_name': name, 'id': body['id'], 'outputs': [
                        {'name': 'SCORE', 'datatype': 'FP32', 'shape': [1], 'data': [score]}]})
                p = outer.models[name]
                x = body['inputs'][0]['data']
                if name in outer.fail_above and body['id'] != 'golden' and sum(x) / len(x) >= outer.fail_above[name]:
                    return self._send(400, {'error': 'injected runtime failure'})
                score = min(1.0, max(0.0, p['gain'] * sum(x) / len(x) + p['bias']))
                self._send(200, {'model_name': name, 'id': 'another-request' if outer.wrong_id and body['id'] != 'golden' else body['id'],
                                 'outputs': [{'name': 'SCORE', 'datatype': 'FP32', 'shape': [1], 'data': [score]}]})

        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class Base(unittest.TestCase):
    overrides = {}
    backend_factory = staticmethod(ra.StubBackend)
    registry_copy = False

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='w204-'))
        tok_file, pr_file = ra.init_lab_principals(self.tmp / 'auth')
        self.tokens = {v['role']: v['token'] for v in json.loads(tok_file.read_text()).values()}
        SECRETS.update(self.tokens.values())
        self.principals = ra.load_principals(pr_file)
        self.examples = ra.W205 / 'examples'
        if self.registry_copy:
            self.examples = self.tmp / 'examples'
            shutil.copytree(ra.W205 / 'examples', self.examples)
        self.start()

    def start(self, backend=None, tls=None, overrides=None):
        self.backend = backend or getattr(self, 'backend', None) or self.backend_factory()
        self.app = ra.App(self.tmp / 'data', self.principals, backend=self.backend,
                          registry=ra.Registry(self.examples), spec=SPEC,
                          overrides={**self.overrides, **(overrides or {})})
        self.server = ra.Server(self.app, inference_port=0, management_port=0, tls=tls)
        self.client = ContractClient(self.server, self.tokens, getattr(self, 'tls_ctx', None))

    def restart(self, crash=False, **kw):
        if crash:
            for s in self.server.httpd.values():
                s.shutdown()
                s.server_close()
            self.app.stopping = True
            self.app.ledger.close()  # mo phong mat tien trinh: worker cu khong ghi them duoc
        else:
            self.server.close()
        self.start(**kw)

    def tearDown(self):
        try:
            self.server.close()
        except Exception:  # noqa: BLE001
            pass
        self._scan_secrets()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _scan_secrets(self):
        for f in (p for p in (self.tmp / 'data').rglob('*') if p.is_file()):
            data = f.read_bytes()
            for s in self.tokens.values():
                assert s.encode() not in data, f'token leaked into {f.name}'

    # helpers
    def submit(self, body, role='operator', **kw):
        return self.client.call('submitInspection', role=role, body=body, **kw)

    def wait_terminal(self, rid, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            r = self.client.call('getInspectionStatus', role='viewer', path_params={'request_id': rid})
            if r.body['state'] in ra.TERMINAL:
                return r
            time.sleep(0.02)
        self.fail(f'{rid} not terminal after {timeout}s')

    def wait_state(self, rid, state, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = self.app.ledger.one('SELECT state FROM inspections WHERE request_id=?', (rid,))
            if row and row['state'] == state:
                return
            time.sleep(0.01)
        self.fail(f'{rid} never reached {state}')

    def result(self, rid):
        return self.client.call('getInspectionResult', role='viewer', path_params={'request_id': rid})

    def count(self, rid=None):
        if rid is None:
            return self.app.ledger.one('SELECT COUNT(*) c FROM inspections')['c']
        return self.app.ledger.one('SELECT COUNT(*) c FROM inspections WHERE request_id=?', (rid,))['c']

    def trace_events(self):
        return [json.loads(x) for x in (self.tmp / 'data' / 'trace.jsonl').read_text().splitlines()]

    def activate(self, name='recipe-b', version='0.1.0', headers=None, expect=200):
        r = self.client.call('activateRecipe', role='admin', path_params={'station_id': 'station-sim'},
                             body={'recipe_name': name, 'recipe_version': version, 'reason': 'test switch'},
                             headers=headers)
        self.assertEqual(r.status, expect, r.body)
        return r


# ------------------------------------------------------------------ tests: happy path & decisions


class TestHappyPath(Base):
    def test_health_both_planes_without_token(self):
        for plane in ('inference', 'management'):
            self.assertEqual(self.client.call('getLiveness', plane=plane).status, 200)
            r = self.client.call('getReadiness', plane=plane)
            self.assertEqual((r.status, r.body), (200, {'ready': True, 'reasons': []}))

    def test_N1_submit_status_result_with_lineage(self):
        r = self.submit(submit_body('n1-0001'))
        self.assertEqual(r.status, 202)
        self.assertEqual(r.body['state'], 'RECEIVED')
        self.assertEqual(r.headers['location'], '/v1/inspections/n1-0001')
        st = self.wait_terminal('n1-0001')
        self.assertEqual(st.body['state'], 'COMPLETED')
        res = self.result('n1-0001')
        self.assertEqual(res.status, 200)
        self.assertIn(res.body['decision'], ('OK', 'NG', 'REVIEW'))
        lin = res.body['lineage']
        self.assertEqual((lin['product_id'], lin['recipe']['name'], lin['model']['name']),
                         ('PCB1-SN-0001', 'recipe-a', 'model-a'))
        self.assertEqual(lin['model']['manifest_sha256'], self.app.registry.packages[('model-a', '0.1.0')]['sha256'])
        self.assertEqual(lin['submitted_by'], 'cam-sim-01')

    def test_N1_decisions_ok_review_ng_from_recipe_threshold(self):
        # recipe-a: score = mean gray, threshold 0.5, review band 0.05
        cases = {'OK': 40, 'REVIEW': 128, 'NG': 220}
        for expected, gray in cases.items():
            rid = f'dec-{expected}'
            self.assertEqual(self.submit(submit_body(rid, image=png(gray))).status, 202)
            self.wait_terminal(rid)
            res = self.result(rid).body
            self.assertEqual(res['decision'], expected, res)
            self.assertEqual(res['threshold'], 0.5)

    def test_N1_jpeg_accepted(self):
        self.assertEqual(self.submit(submit_body('jpg-1', image=jpeg(), ctype='image/jpeg')).status, 202)
        self.assertEqual(self.wait_terminal('jpg-1').body['state'], 'COMPLETED')

    def test_trace_end_to_end_request_product_model_config(self):
        trace = 'trace-e2e-0001'
        r = self.submit(submit_body('e2e-1', product='PCB1-SN-E2E'), headers={'X-Trace-Id': trace})
        self.assertEqual(r.headers['x-trace-id'], trace)
        self.wait_terminal('e2e-1')
        res = self.result('e2e-1').body
        row = self.app.ledger.one('SELECT * FROM inspections WHERE request_id=?', ('e2e-1',))
        pin = json.loads(row['pin_json'])
        # 1) API result == ledger
        self.assertEqual(res['lineage']['trace_id'], trace)
        self.assertEqual(res['lineage']['recipe'], pin['recipe'])
        self.assertEqual(res['lineage']['model'], pin['model'])
        self.assertEqual(res['score'], row['score'])
        # 2) recipe/model digest == file thuc te tren dia (W2-05)
        self.assertEqual(pin['recipe']['sha256'],
                         ra.sha256((self.examples / 'recipes' / 'recipe-a.json').read_bytes()))
        self.assertEqual(pin['model']['manifest_sha256'],
                         ra.sha256((self.examples / 'packages' / 'model-a' / 'manifest.json').read_bytes()))
        self.assertEqual(res['lineage']['input_sha256'], ra.sha256(png()))
        # 3) trace log: admitted -> started -> finished -> terminal, cung trace/request/product/model
        ev = [e for e in self.trace_events() if e.get('request_id') == 'e2e-1']
        names = [e['event'] for e in ev]
        for needed in ('request.admitted', 'inference.started', 'inference.finished', 'request.terminal'):
            self.assertIn(needed, names)
        self.assertTrue(all(e['trace_id'] == trace for e in ev))
        adm = next(e for e in ev if e['event'] == 'request.admitted')
        self.assertEqual((adm['product_id'], adm['model'], adm['recipe']),
                         ('PCB1-SN-E2E', pin['model'], pin['recipe']))
        # 4) backend nhan dung trace id
        self.assertIn({'model': 'model-a', 'trace_id': trace, 'request_id': 'e2e-1'}, self.backend.calls)
        # 5) tra cuu theo product_id
        lst = self.client.call('listInspections', role='viewer', query='product_id=PCB1-SN-E2E')
        self.assertEqual([i['request_id'] for i in lst.body['items']], ['e2e-1'])

    def test_active_recipe_lookup_for_camera(self):
        r = self.client.call('getActiveRecipe', role='operator', path_params={'station_id': 'station-sim'})
        self.assertEqual(r.body['recipe_version'], 'recipe-a@0.1.0')
        self.assertNotIn('IMAGE', json.dumps(r.body))  # khong lo ten tensor
        self.assertEqual(self.client.call('getActiveRecipe', role='operator',
                                          path_params={'station_id': 'nope'}).status, 404)

    def test_list_pagination_and_query_validation(self):
        for i in range(3):
            self.submit(submit_body(f'pg-{i}', product='PCB1-SN-PAGE'))
        self.app.wait_idle()
        p1 = self.client.call('listInspections', role='viewer', query='product_id=PCB1-SN-PAGE&limit=2')
        self.assertEqual([i['request_id'] for i in p1.body['items']], ['pg-2', 'pg-1'])
        p2 = self.client.call('listInspections', role='viewer',
                              query=f"product_id=PCB1-SN-PAGE&limit=2&cursor={p1.body['next_cursor']}")
        self.assertEqual([i['request_id'] for i in p2.body['items']], ['pg-0'])
        self.assertIsNone(p2.body['next_cursor'])
        for q in ('product_id=bad%20id', 'product_id=X&limit=0', 'product_id=X&limit=101', 'product_id=X&foo=1'):
            self.assertEqual(self.client.call('listInspections', role='viewer', query=q).status, 400, q)


# ------------------------------------------------------------------ tests: rejection before admission


class TestAdmissionErrors(Base):
    def assert_rejected(self, r, status, code, rid=None):
        self.assertEqual(r.status, status, r.body)
        self.assertEqual(r.body['code'], code, r.body)
        self.assertEqual(r.headers['content-type'], 'application/problem+json')
        if rid:
            self.assertEqual(self.count(rid), 0, 'rejected request must not create a record')

    def test_F1_malformed_json_missing_fields_bad_base64(self):
        bad = [
            (b'{not json', 'raw'),
            (submit_body('f1-a', image=b'') | {'product_id': 'PCB1 SN/1'}, 'json'),
            ({k: v for k, v in submit_body('f1-b').items() if k != 'product_id'}, 'json'),
            (submit_body('f1-c') | {'extra': 1}, 'json'),
            (submit_body('f1-d') | {'captured_at': '06/10/2026'}, 'json'),
            (submit_body('f1-e') | {'image': {'content_type': 'image/png', 'data_base64': 'abc$'}}, 'json'),
            (submit_body('f1-f') | {'image': {'content_type': 'image/png', 'data_base64': 'abcde'}}, 'json'),
            (submit_body('f1-g') | {'image': {'content_type': 'image/gif', 'data_base64': 'R0lG'}}, 'json'),
            (b'{"request_id": NaN}', 'raw'),
        ]
        for body, kind in bad:
            if kind == 'raw':
                r = self.submit(None, raw_body=body, headers={'Content-Type': 'application/json'})
            else:
                r = self.submit(body)
            self.assert_rejected(r, 400, 'INVALID_REQUEST')
        self.assertEqual(self.count(), 0)

    def test_F2_payload_too_large(self):
        big = b'\0' * (4 * 1024 * 1024 + 1)
        r = self.submit(submit_body('f2-a', image=big))
        self.assert_rejected(r, 413, 'PAYLOAD_TOO_LARGE', 'f2-a')
        # body > max_body_bytes: tu choi tu Content-Length, khong doc body
        c = self.client.conn('inference')
        c.putrequest('POST', '/v1/inspections')
        c.putheader('Authorization', f"Bearer {self.tokens['operator']}")
        c.putheader('Content-Type', 'application/json')
        c.putheader('Content-Length', str(7 * 1024 * 1024))
        c.endheaders()
        resp = c.getresponse()
        body = json.loads(resp.read())
        c.close()
        self.assertEqual((resp.status, body['code']), (413, 'PAYLOAD_TOO_LARGE'))
        OBSERVED.add(('submitInspection', 413))

    def test_F3_undecodable_or_wrong_format_or_dimensions(self):
        self.assert_rejected(self.submit(submit_body('f3-a', image=b'\x89PNG\r\n\x1a\nnot really')), 422,
                             'IMAGE_UNDECODABLE', 'f3-a')
        self.assert_rejected(self.submit(submit_body('f3-b', image=jpeg(), ctype='image/png')), 422,
                             'IMAGE_UNDECODABLE', 'f3-b')
        truncated = png(size=(64, 64))[:-20]
        self.assert_rejected(self.submit(submit_body('f3-c', image=truncated)), 422, 'IMAGE_UNDECODABLE', 'f3-c')
        wide = png(size=(4097, 1))
        self.assert_rejected(self.submit(submit_body('f3-d', image=wide)), 422, 'IMAGE_TOO_LARGE_DIMENSIONS', 'f3-d')

    def test_F6_unknown_product_type_or_recipe_mismatch_never_scored(self):
        self.assert_rejected(self.submit(submit_body('f6-a') | {'product_type': 'PCB9'}), 422, 'RECIPE_NOT_FOUND',
                             'f6-a')
        r = self.submit(submit_body('f6-b', recipe='recipe-b@0.1.0'))
        self.assert_rejected(r, 409, 'RECIPE_VERSION_MISMATCH', 'f6-b')
        self.assertEqual(r.body['details'], {'active_recipe_version': 'recipe-a@0.1.0'})
        self.assert_rejected(self.submit(submit_body('f6-c') | {'station_id': 'station-x'}), 422,
                             'RECIPE_NOT_FOUND', 'f6-c')
        self.assertEqual([c for c in self.backend.calls if c['request_id'] != 'golden'], [])

    def test_unsupported_media_type_chunked_and_method(self):
        r = self.submit(None, raw_body=b'request_id=1', headers={'Content-Type': 'application/x-www-form-urlencoded'})
        self.assert_rejected(r, 415, 'UNSUPPORTED_MEDIA_TYPE')
        r = self.client.call('submitInspection', role='operator', method='DELETE', path='/v1/inspections',
                             expect_op=False)
        self.assertEqual((r.status, r.body['code']), (405, 'METHOD_NOT_ALLOWED'))
        c = self.client.conn('inference')
        c.putrequest('POST', '/v1/inspections')
        c.putheader('Authorization', f"Bearer {self.tokens['operator']}")
        c.putheader('Content-Type', 'application/json')
        c.putheader('Transfer-Encoding', 'chunked')
        c.endheaders()
        c.send(b'0\r\n\r\n')
        resp = c.getresponse()
        self.assertEqual(resp.status, 400)
        resp.read()
        c.close()

    def test_retry_of_rules(self):
        self.assertEqual(self.submit(submit_body('rt-1', retry_of='does-not-exist')).status, 400)
        self.backend.fail_next = 1
        self.submit(submit_body('rt-2'))
        self.assertEqual(self.wait_terminal('rt-2').body['state'], 'FAILED')
        r = self.submit(submit_body('rt-3', retry_of='rt-2'))
        self.assertEqual(r.status, 202)
        self.assertEqual(r.body['retry_of'], 'rt-2')
        self.assertEqual(self.wait_terminal('rt-3').body['state'], 'COMPLETED')
        self.assertEqual(self.submit(submit_body('rt-4', retry_of='rt-3')).status, 400)  # rt-3 COMPLETED


class TestSlowBody(Base):
    overrides = {'body_read_timeout_s': 0.5}

    def test_slow_client_body_gets_408(self):
        s = socket.create_connection(('127.0.0.1', self.server.port('inference')))
        s.sendall(b'POST /v1/inspections HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n'
                  b'Authorization: Bearer ' + self.tokens['operator'].encode() + b'\r\nContent-Length: 100\r\n\r\n{')
        s.settimeout(5)
        data = b''
        while b'\r\n\r\n' not in data:
            data += s.recv(4096)
        s.close()
        self.assertIn(b' 408 ', data.split(b'\r\n')[0])
        OBSERVED.add(('submitInspection', 408))


# ------------------------------------------------------------------ tests: idempotency


class TestIdempotency(Base):
    def test_F4_same_id_same_payload_returns_old_record_without_reinference(self):
        body = submit_body('f4-1')
        self.assertEqual(self.submit(body).status, 202)
        self.wait_terminal('f4-1')
        calls = len(self.backend.calls)
        r = self.submit(body)
        self.assertEqual(r.status, 200)
        self.assertEqual(r.headers['idempotent-replay'], 'true')
        self.assertEqual(r.body['state'], 'COMPLETED')
        self.assertEqual(len(self.backend.calls), calls, 'replay must not re-run inference')
        self.assertEqual(self.count('f4-1'), 1)

    def test_F5_same_id_different_payload_conflict(self):
        self.submit(submit_body('f5-1'))
        r = self.submit(submit_body('f5-1', image=png(200)))
        self.assertEqual((r.status, r.body['code'], r.body['request_id']), (409, 'IDEMPOTENCY_CONFLICT', 'f5-1'))
        r = self.submit(submit_body('f5-1', product='PCB1-SN-OTHER'))
        self.assertEqual(r.status, 409)
        self.assertEqual(self.count('f5-1'), 1)

    def test_concurrent_duplicate_submits_create_one_record(self):
        body = submit_body('dup-par')
        results = []
        ths = [threading.Thread(target=lambda: results.append(self.submit(body).status)) for _ in range(6)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self.assertEqual(results.count(202), 1, results)
        self.assertEqual(set(results) - {202, 200}, set())
        self.app.wait_idle()
        self.assertEqual(self.count('dup-par'), 1)
        self.assertEqual(len([c for c in self.backend.calls if c['request_id'] == 'dup-par']), 1)


# ------------------------------------------------------------------ tests: capacity / readiness / storage


class TestCapacity(Base):
    overrides = {'queue_capacity': 2}

    def test_F7_queue_full_429_with_retry_after_then_retry_same_id(self):
        self.backend.delay_s = 0.4
        self.assertEqual(self.submit(submit_body('q-1')).status, 202)
        self.assertEqual(self.submit(submit_body('q-2')).status, 202)
        r = self.submit(submit_body('q-3'))
        self.assertEqual((r.status, r.body['code'], r.headers['retry-after']), (429, 'QUEUE_FULL', '1'))
        self.assertTrue(r.body['retryable'])
        self.assertEqual(self.count('q-3'), 0)
        self.backend.delay_s = 0
        self.app.wait_idle()
        self.assertEqual(self.submit(submit_body('q-3')).status, 202)


class TestQueueTimeout(Base):
    overrides = {'queue_timeout_s': 0.2}

    def test_queue_timeout_is_separate_from_execution_timeout(self):
        self.backend.delay_s = 0.5
        self.submit(submit_body('qt-1'))
        self.submit(submit_body('qt-2'))
        self.backend.delay_s = 0
        self.assertEqual(self.wait_terminal('qt-1').body['state'], 'COMPLETED')
        res = self.result('qt-2')
        self.assertEqual((res.body['state'], res.body['reason'], res.body['decision']),
                         ('TIMEOUT', 'QUEUE_TIMEOUT', None))
        self.assertIsNone(res.body['started_at'])


class TestReadiness(Base):
    def test_F8_backend_unavailable_stops_admission_but_reads_still_work(self):
        self.submit(submit_body('f8-0'))
        self.wait_terminal('f8-0')
        self.backend.available = False
        rz = self.client.call('getReadiness')
        self.assertEqual((rz.status, rz.body['reasons']), (503, ['BACKEND_UNAVAILABLE']))
        r = self.submit(submit_body('f8-1'))
        self.assertEqual((r.status, r.body['code'], r.headers['retry-after']), (503, 'NOT_READY', '5'))
        self.assertEqual(self.count('f8-1'), 0)
        self.assertEqual(self.result('f8-0').status, 200)  # consumer van doc ket qua cu
        self.assertEqual(self.submit(submit_body('f8-0')).status, 200)  # replay van tra record cu
        self.backend.available = True
        self.assertEqual(self.client.call('getReadiness').status, 200)
        self.assertEqual(self.submit(submit_body('f8-1')).status, 202)

    def test_F9_storage_write_failure_rejects_with_503(self):
        self.app.ledger.fail_writes = True
        r = self.submit(submit_body('f9-1'))
        self.assertEqual((r.status, r.body['code']), (503, 'STORAGE_UNAVAILABLE'))
        self.app.ledger.fail_writes = False
        rz = self.client.call('getReadiness')
        self.assertEqual((rz.status, rz.body['reasons']), (503, ['STORAGE_UNAVAILABLE']))
        r = self.submit(submit_body('f9-2'))
        self.assertEqual((r.status, r.body['code']), (503, 'STORAGE_UNAVAILABLE'))
        self.assertEqual(self.count(), 0)

    def test_F9_low_disk_space_rejects_with_503(self):
        self.app.limits['min_free_bytes'] = 1 << 62
        r = self.submit(submit_body('f9-3'))
        self.assertEqual((r.status, r.body['code']), (503, 'STORAGE_UNAVAILABLE'))

    def test_F9_result_never_returned_if_not_persisted(self):
        self.backend.delay_s = 0.4
        self.submit(submit_body('f9-4'))
        self.wait_state('f9-4', 'PROCESSING')
        self.app.ledger.fail_writes = True
        time.sleep(0.6)
        self.app.ledger.fail_writes = False
        r = self.result('f9-4')
        self.assertEqual((r.status, r.body['code']), (409, 'RESULT_NOT_READY'))
        self.assertEqual(self.client.call('getReadiness').status, 503)
        self.restart()
        res = self.result('f9-4').body
        self.assertEqual((res['state'], res['decision'], res['reason']),
                         ('INDETERMINATE', None, 'RESTARTED_DURING_PROCESSING'))


# ------------------------------------------------------------------ tests: failures after admission


class TestTechnicalStates(Base):
    overrides = {'execution_timeout_s': 0.3}

    def test_F10_backend_error_failed_decision_null_lineage_kept(self):
        self.backend.fail_next = 1
        self.submit(submit_body('f10-1'))
        res = self.wait_terminal('f10-1')
        self.assertEqual((res.body['state'], res.body['decision'], res.body['reason']),
                         ('FAILED', None, 'BACKEND_ERROR'))
        full = self.result('f10-1').body
        self.assertIsNone(full['score'])
        self.assertEqual(full['lineage']['model']['name'], 'model-a')
        self.assertEqual(self.client.call('getReadiness').status, 200)  # 1 loi khong lam server ngung

    def test_F11_execution_timeout_late_result_ignored(self):
        self.backend.delay_s = 0.6
        self.submit(submit_body('f11-1'))
        res = self.wait_terminal('f11-1')
        self.assertEqual((res.body['state'], res.body['reason'], res.body['decision']),
                         ('TIMEOUT', 'EXECUTION_TIMEOUT', None))
        self.app.wait_idle()
        self.assertEqual(self.result('f11-1').body['state'], 'TIMEOUT')
        ev = [e['event'] for e in self.trace_events() if e.get('request_id') == 'f11-1']
        self.assertIn('inference.late_result_ignored', ev)

    def test_result_not_ready_409(self):
        self.backend.delay_s = 0.2
        self.submit(submit_body('nr-1'))
        r = self.result('nr-1')
        self.assertEqual((r.status, r.body['code'], r.headers['retry-after']), (409, 'RESULT_NOT_READY', '1'))
        self.app.wait_idle()

    def test_F15_unknown_request_id_404(self):
        self.assertEqual(self.client.call('getInspectionStatus', role='viewer',
                                          path_params={'request_id': 'nope'}).status, 404)
        self.assertEqual(self.result('nope').status, 404)


class TestRestart(Base):
    def test_F12_restart_while_processing_becomes_indeterminate_not_rerun(self):
        self.backend.delay_s = 1.0
        self.submit(submit_body('f12-1'))
        self.wait_state('f12-1', 'PROCESSING')
        old_backend = self.backend
        self.restart(crash=True, backend=ra.StubBackend())
        res = self.result('f12-1').body
        self.assertEqual((res['state'], res['decision'], res['reason']),
                         ('INDETERMINATE', None, 'RESTARTED_DURING_PROCESSING'))
        time.sleep(1.2)  # worker cu tra ve muon: khong duoc ghi de
        self.assertEqual(self.result('f12-1').body['state'], 'INDETERMINATE')
        self.assertEqual([c for c in self.backend.calls if c['request_id'] == 'f12-1'], [])
        self.assertTrue(old_backend.calls)

    def test_F13_active_recipe_survives_restart(self):
        self.activate('recipe-b')
        self.restart()
        r = self.client.call('getActiveRecipe', role='viewer', path_params={'station_id': 'station-sim'})
        self.assertEqual(r.body['recipe_version'], 'recipe-b@0.1.0')
        self.assertEqual(self.client.call('getReadiness').status, 200)
        self.submit(submit_body('f13-1', recipe='recipe-b@0.1.0'))
        self.assertEqual(self.wait_terminal('f13-1').body['state'], 'COMPLETED')
        self.assertEqual(self.result('f13-1').body['lineage']['model']['name'], 'model-b')

    def test_F14_consumer_disconnects_result_still_readable(self):
        body = json.dumps(submit_body('f14-1')).encode()
        s = socket.create_connection(('127.0.0.1', self.server.port('inference')))
        s.sendall(b'POST /v1/inspections HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n'
                  b'Authorization: Bearer ' + self.tokens['operator'].encode() +
                  f'\r\nContent-Length: {len(body)}\r\n\r\n'.encode() + body)
        s.close()  # dong ket noi khong doc response
        deadline = time.monotonic() + 5
        while self.count('f14-1') == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertEqual(self.wait_terminal('f14-1').body['state'], 'COMPLETED')
        self.assertEqual(self.result('f14-1').status, 200)


class TestRestartUnverified(Base):
    registry_copy = True

    def test_F13_changed_active_recipe_blocks_admission_no_silent_fallback(self):
        self.activate('recipe-b')
        p = self.examples / 'recipes' / 'recipe-b.json'
        r = json.loads(p.read_text())
        r['decision']['threshold'] = 0.31  # recipe B bi sua ngoai quy trinh -> digest khac
        p.write_text(json.dumps(r, indent=2))
        self.restart()
        rz = self.client.call('getReadiness')
        self.assertEqual((rz.status, rz.body['reasons']), (503, ['ACTIVE_RECIPE_UNVERIFIED']))
        self.assertEqual(self.submit(submit_body('f13-x', recipe='recipe-a@0.1.0')).status, 503)
        self.assertEqual(self.client.call('getActiveRecipe', role='viewer',
                                          path_params={'station_id': 'station-sim'}).status, 503)
        audit = self.client.call('listAudit', role='admin').body['items']
        self.assertTrue(any(a['action'] == 'restore_active_recipe' and a['outcome'] == 'UNVERIFIED' for a in audit))
        self.assertEqual(self.client.call('getStation', role='admin', path_params={'station_id': 'station-sim'}).status,
                         503)
        self.activate('recipe-a')  # admin xac nhan lai
        self.assertEqual(self.client.call('getReadiness').status, 200)


# ------------------------------------------------------------------ tests: cutover / management


class TestManagement(Base):
    registry_copy = True

    def test_F16_activation_during_processing_keeps_pinned_model(self):
        self.backend.delay_s = 0.5
        self.submit(submit_body('f16-1'))
        self.wait_state('f16-1', 'PROCESSING')
        self.backend.delay_s = 0
        act = self.activate('recipe-b').body
        self.assertEqual((act['from_recipe']['name'], act['to_recipe']['name'], act['golden']['passed']),
                         ('recipe-a', 'recipe-b', True))
        self.wait_terminal('f16-1')
        self.assertEqual(self.result('f16-1').body['lineage']['model']['name'], 'model-a')
        self.assertEqual(self.submit(submit_body('f16-2')).status, 409)  # client van gui recipe-a
        self.submit(submit_body('f16-3', recipe='recipe-b@0.1.0'))
        self.wait_terminal('f16-3')
        res = self.result('f16-3').body
        self.assertEqual((res['lineage']['model']['name'], res['threshold']), ('model-b', 0.3))

    def test_activation_noop_if_match_busy_golden_and_rollback(self):
        cur = self.client.call('getActiveRecipe', role='viewer', path_params={'station_id': 'station-sim'}).body
        r = self.activate('recipe-a')
        self.assertFalse(r.body['changed'])
        self.activate('recipe-b', headers={'If-Match': '0' * 64}, expect=412)
        self.app.transition_lock.acquire()
        try:
            r = self.activate('recipe-b', expect=409)
            self.assertEqual(r.body['code'], 'TRANSITION_BUSY')
        finally:
            self.app.transition_lock.release()
        self.backend.fail_next = 1
        r = self.activate('recipe-b', expect=422)
        self.assertEqual(r.body['code'], 'ACTIVATION_GOLDEN_FAILED')
        self.assertEqual(self.app.active['recipe']['name'], 'recipe-a')
        self.activate('recipe-b', headers={'If-Match': f'"{cur["active_revision"]}"'})
        self.activate('recipe-z', expect=422)
        rb = self.client.call('rollbackRecipe', role='admin', path_params={'station_id': 'station-sim'},
                              body={'reason': 'rollback test'})
        self.assertEqual((rb.status, rb.body['to_recipe']['name']), (200, 'recipe-a'))
        st = self.client.call('getStation', role='admin', path_params={'station_id': 'station-sim'}).body
        self.assertEqual([h['to_recipe']['name'] for h in st['history']], ['recipe-a', 'recipe-b', 'recipe-a'])
        self.assertEqual(self.client.call('getStation', role='admin', path_params={'station_id': 'x'}).status, 404)
        actions = [(a['action'], a['outcome']) for a in self.client.call('listAudit', role='admin').body['items']]
        for needed in [('activate', 'OK'), ('activate', 'PRECONDITION_FAILED'), ('activate', 'TRANSITION_BUSY'),
                       ('activate', 'ACTIVATION_GOLDEN_FAILED'), ('rollback', 'OK'), ('activate', 'NO_CHANGE')]:
            self.assertIn(needed, actions)

    def test_rollback_errors_and_storage_failure_during_activation(self):
        sp = {'station_id': 'station-sim'}
        for kw, status in (({'body': {}}, 400), ({'raw_body': b'x', 'headers': {'Content-Type': 'text/plain'}}, 415)):
            r = self.client.call('rollbackRecipe', role='admin', path_params=sp, **kw)
            self.assertEqual(r.status, status)
        r = self.client.call('rollbackRecipe', role='admin', path_params={'station_id': 'x'}, body={'reason': 'abc'})
        self.assertEqual(r.status, 404)
        r = self.client.call('activateRecipe', role='admin', path_params={'station_id': 'x'},
                             body={'recipe_name': 'recipe-b', 'recipe_version': '0.1.0', 'reason': 'abc'})
        self.assertEqual(r.status, 404)
        r = self.client.call('validatePackage', role='admin', raw_body=b'x', headers={'Content-Type': 'text/plain'})
        self.assertEqual(r.status, 415)
        self.app.ledger.fail_writes = True
        r = self.activate('recipe-b', expect=503)
        self.assertEqual(r.body['code'], 'STORAGE_UNAVAILABLE')
        self.app.ledger.fail_writes = False
        self.assertEqual(self.app.active['recipe']['name'], 'recipe-a')
        self.app.storage_unhealthy = False
        self.activate('recipe-b')
        self.app.ledger.fail_writes = True
        r = self.client.call('rollbackRecipe', role='admin', path_params=sp, body={'reason': 'disk down'})
        self.assertEqual((r.status, r.body['code']), (503, 'STORAGE_UNAVAILABLE'))
        self.app.ledger.fail_writes = False
        self.app.storage_unhealthy = False
        # rollback toi recipe ma package da bi sua -> 422, recipe hien tai giu nguyen
        (self.examples / 'packages' / 'model-a' / 'model.json').write_text('{"gain": 0.9, "bias": 0.0}')
        r = self.client.call('rollbackRecipe', role='admin', path_params=sp, body={'reason': 'tampered target'})
        self.assertEqual((r.status, r.body['code']), (422, 'PACKAGE_REJECTED'))
        self.assertEqual(self.app.active['recipe']['name'], 'recipe-b')

    def test_rollback_without_history_409(self):
        r = self.client.call('rollbackRecipe', role='admin', path_params={'station_id': 'station-sim'},
                             body={'reason': 'nothing to roll back'})
        self.assertEqual((r.status, r.body['code']), (409, 'NO_ROLLBACK_TARGET'))

    def test_packages_recipes_and_validation(self):
        pk = self.client.call('listPackages', role='admin').body['items']
        self.assertEqual({p['name'] for p in pk}, {'model-a', 'model-b'})
        rc = self.client.call('listRecipes', role='admin').body['items']
        self.assertEqual({r['recipe']['name']: r['active'] for r in rc}, {'recipe-a': True, 'recipe-b': False})
        ok = self.client.call('validatePackage', role='admin', body={'package_name': 'model-b',
                                                                     'package_version': '0.1.0'})
        self.assertEqual((ok.status, ok.body['golden_score']), (200, 0.3125))
        nf = self.client.call('validatePackage', role='admin', body={'package_name': 'model-x',
                                                                     'package_version': '0.1.0'})
        self.assertEqual(nf.status, 404)
        bad = self.client.call('validatePackage', role='admin', body={'package_name': 'model-b'})
        self.assertEqual(bad.status, 400)
        (self.examples / 'packages' / 'model-b' / 'model.json').write_text('{"gain": 0.9, "bias": 0.0}')
        rej = self.client.call('validatePackage', role='admin', body={'package_name': 'model-b',
                                                                      'package_version': '0.1.0'})
        self.assertEqual((rej.status, rej.body['code'], rej.body['details']['validator_code']),
                         (422, 'PACKAGE_REJECTED', 'E_CHECKSUM'))
        act = self.activate('recipe-b', expect=422)
        self.assertEqual(act.body['code'], 'PACKAGE_REJECTED')
        self.assertEqual(self.app.active['recipe']['name'], 'recipe-a')

    def test_management_validation_errors(self):
        r = self.client.call('activateRecipe', role='admin', path_params={'station_id': 'station-sim'},
                             body={'recipe_name': 'recipe-b'})
        self.assertEqual(r.status, 400)
        r = self.client.call('activateRecipe', role='admin', path_params={'station_id': 'station-sim'},
                             raw_body=b'x', headers={'Content-Type': 'text/plain'})
        self.assertEqual(r.status, 415)
        r = self.client.call('listAudit', role='admin', query='limit=0')
        self.assertEqual(r.status, 400)


# ------------------------------------------------------------------ tests: auth / RBAC / plane separation


class TestSecurity(Base):
    def test_unauthenticated_401(self):
        for kw in ({}, {'token': 'wrong-token'}, {'headers': {'Authorization': 'Basic abc'}}):
            r = self.submit(submit_body('a-1'), role=None, **kw)
            self.assertEqual((r.status, r.body['code']), (401, 'UNAUTHENTICATED'))
            r = self.client.call('listRecipes', **kw)
            self.assertEqual(r.status, 401)
        self.assertEqual(self.count(), 0)

    def test_every_secured_operation_requires_token(self):
        sp = {'station_id': 'station-sim'}
        calls = {
            'submitInspection': {'body': submit_body('tk-1')},
            'listInspections': {'query': 'product_id=X'},
            'getInspectionStatus': {'path_params': {'request_id': 'tk-1'}},
            'getInspectionResult': {'path_params': {'request_id': 'tk-1'}},
            'getActiveRecipe': {'path_params': sp},
            'getMe': {}, 'getStationSummary': {'path_params': sp}, 'listStationActivations': {'path_params': sp},
            'listPackages': {}, 'listRecipes': {}, 'listAudit': {}, 'getStation': {'path_params': sp},
            'validatePackage': {'body': {'package_name': 'model-a', 'package_version': '0.1.0'}},
            'activateRecipe': {'path_params': sp, 'body': {'recipe_name': 'recipe-b', 'recipe_version': '0.1.0',
                                                           'reason': 'no token'}},
            'rollbackRecipe': {'path_params': sp, 'body': {'reason': 'no token'}},
        }
        for op, kw in calls.items():
            r = self.client.call(op, **kw)
            self.assertEqual((r.status, r.body['code']), (401, 'UNAUTHENTICATED'), op)
        self.assertEqual(self.count(), 0)
        self.assertEqual(self.app.active['recipe']['name'], 'recipe-a')

    def test_rbac_matrix(self):
        sp = {'station_id': 'station-sim'}
        rid = {'request_id': 'rb-1'}
        self.submit(submit_body('rb-1'))
        self.app.wait_idle()
        matrix = {
            # op: (kwargs, allowed roles)
            'submitInspection': ({'body': submit_body('rb-2')}, {'operator'}),
            'listInspections': ({'query': 'product_id=PCB1-SN-0001'}, {'viewer', 'operator', 'admin'}),
            'getInspectionStatus': ({'path_params': rid}, {'viewer', 'operator', 'admin'}),
            'getInspectionResult': ({'path_params': rid}, {'viewer', 'operator', 'admin'}),
            'getActiveRecipe': ({'path_params': sp}, {'viewer', 'operator', 'admin'}),
            'getMe': ({}, {'viewer', 'operator', 'admin'}),
            'getStationSummary': ({'path_params': sp}, {'viewer', 'operator', 'admin'}),
            'listStationActivations': ({'path_params': sp}, {'viewer', 'operator', 'admin'}),
            'cancelInspection': ({'path_params': rid, 'body': {'reason': 'rbac check'}}, {'operator'}),  # rb-1 da xong -> 409
            'listPackages': ({}, {'admin'}),
            'validatePackage': ({'body': {'package_name': 'model-a', 'package_version': '0.1.0'}}, {'admin'}),
            'listRecipes': ({}, {'admin'}),
            'getStation': ({'path_params': sp}, {'admin'}),
            'activateRecipe': ({'path_params': sp, 'body': {'recipe_name': 'recipe-a', 'recipe_version': '0.1.0',
                                                            'reason': 'rbac'}}, {'admin'}),
            'rollbackRecipe': ({'path_params': sp, 'body': {'reason': 'rbac'}}, {'admin'}),
            'listAudit': ({}, {'admin'}),
        }
        self.assertEqual(set(matrix), {o for o, (_, _, op) in OPS.items() if op['tags'] != ['health']})
        table = {}
        for op, (kw, allowed) in matrix.items():
            spec_roles = set(OPS[op][2]['x-roles'])
            self.assertEqual(spec_roles, allowed, f'{op}: spec x-roles differ from test matrix')
            for role in ('viewer', 'operator', 'admin'):
                r = self.client.call(op, role=role, **kw)
                table[f'{op}:{role}'] = r.status
                if role in allowed:
                    self.assertNotIn(r.status, (401, 403), f'{op} {role}: {r.body}')
                else:
                    self.assertEqual((r.status, r.body['code']), (403, 'FORBIDDEN'), f'{op} {role}')
        if os.environ.get('VR01_EVIDENCE_DIR'):
            Path(os.environ['VR01_EVIDENCE_DIR'], 'rbac-matrix-observed.json').write_text(
                json.dumps(table, indent=2, sort_keys=True))
        audit = self.client.call('listAudit', role='admin').body['items']
        self.assertTrue(any(a['outcome'] == 'FORBIDDEN' and a['role'] == 'viewer' for a in audit))
        self.assertNotIn(self.tokens['viewer'], json.dumps(audit))

    def test_plane_separation_and_no_triton_passthrough(self):
        # management path tren cong inference -> 404, va nguoc lai
        r = self.client.call('listRecipes', plane='inference', role='admin', expect_op=False)
        self.assertEqual((r.status, r.body['code']), (404, 'NOT_FOUND'))
        r = self.client.call('getActiveRecipe', plane='management', role='admin',
                             path_params={'station_id': 'station-sim'}, expect_op=False)
        self.assertEqual(r.status, 404)
        r = self.client.call('submitInspection', plane='management', role='operator', body=submit_body('pl-1'),
                             expect_op=False)
        self.assertEqual(r.status, 404)
        for plane in ('inference', 'management'):
            for path in ('/v2/models/model-a/infer', '/v2/health/ready', '/v2/repository/index', '/metrics'):
                r = self.client.call('x', plane=plane, role='admin', method='POST' if 'infer' in path else 'GET',
                                     path=path, expect_op=False)
                self.assertEqual(r.status, 404, path)
        self.assertEqual(self.count(), 0)

    def test_tokens_never_logged(self):
        self.submit(submit_body('sec-1'))
        self.submit(submit_body('sec-2'), role=None, token=self.tokens['admin'] + 'x')
        self.app.wait_idle()
        blob = (self.tmp / 'data' / 'trace.jsonl').read_text()
        for t in self.tokens.values():
            self.assertNotIn(t, blob)
        principals = (self.tmp / 'auth' / 'principals.json').read_text()
        for t in self.tokens.values():
            self.assertNotIn(t, principals)


class TestTLS(Base):
    def setUp(self):
        if not shutil.which('openssl'):
            self.skipTest('openssl not installed')
        self.pki = Path(tempfile.mkdtemp(prefix='w204-pki-'))
        run = lambda *a: subprocess.run(a, cwd=self.pki, check=True, capture_output=True)  # noqa: E731
        run('openssl', 'req', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
            '-keyout', 'ca.key', '-out', 'ca.pem', '-days', '2', '-subj', '/CN=vr01-lab-ca',
            '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign')
        run('openssl', 'req', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes', '-keyout',
            'srv.key', '-out', 'srv.csr', '-subj', '/CN=127.0.0.1')
        (self.pki / 'ext.cnf').write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n'
                                          'extendedKeyUsage=serverAuth\nsubjectAltName=IP:127.0.0.1\n'
                                          'subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n')
        run('openssl', 'x509', '-req', '-in', 'srv.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
            '-out', 'srv.pem', '-days', '2', '-extfile', 'ext.cnf')
        self.tls_ctx = ssl.create_default_context(cafile=str(self.pki / 'ca.pem'))
        self.tls_ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        super().setUp()

    def start(self, **kw):
        super().start(tls={'cert': str(self.pki / 'srv.pem'), 'key': str(self.pki / 'srv.key')}, **kw)

    def tearDown(self):
        super().tearDown()
        shutil.rmtree(self.pki, ignore_errors=True)

    def test_https_both_planes_and_plain_http_refused(self):
        self.assertEqual(self.submit(submit_body('tls-1')).status, 202)
        self.assertEqual(self.wait_terminal('tls-1').body['state'], 'COMPLETED')
        self.assertEqual(self.client.call('listRecipes', role='admin').status, 200)
        plain = http.client.HTTPConnection('127.0.0.1', self.server.port('inference'), timeout=3)
        with self.assertRaises((http.client.HTTPException, ConnectionError, OSError)):
            plain.request('GET', '/healthz')
            plain.getresponse().read()
        plain.close()
        c = http.client.HTTPSConnection('127.0.0.1', self.server.port('inference'), timeout=3,
                                        context=ssl.create_default_context())  # khong tin CA lab
        with self.assertRaises(ssl.SSLError):
            c.request('GET', '/healthz')
        c.close()


class TestKServeAdapter(Base):
    """Business API -> adapter -> inference server KServe v2 (giao thuc Triton). Client khong goi Triton."""

    def setUp(self):
        reg = ra.Registry()
        models = {}
        for (name, _), entry in reg.packages.items():
            models[name] = json.loads((entry['path'].parent / entry['manifest']['artifact']['path']).read_bytes())
        self.fake = FakeKServe(models)
        self.backend = ra.KServeV2Backend(self.fake.url)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.fake.close()

    def test_business_api_translates_to_kserve_v2_and_propagates_trace(self):
        r = self.submit(submit_body('ks-1', image=png(220)), headers={'X-Trace-Id': 'trace-kserve-01'})
        self.assertEqual(r.status, 202)
        self.wait_terminal('ks-1')
        res = self.result('ks-1').body
        self.assertEqual(res['decision'], 'NG')
        call = [c for c in self.fake.calls if c['body']['id'] == 'ks-1'][0]
        self.assertEqual(call['path'], '/v2/models/model-a/infer')
        self.assertEqual(call['trace'], 'trace-kserve-01')
        self.assertEqual(call['body']['inputs'][0]['shape'], [1, 1, 2, 2])
        stub_score = ra.StubBackend().infer({'name': 'model-a'}, {'gain': 1.0, 'bias': 0.0},
                                            ra.preprocess(png(220)), 't', 'x')
        self.assertAlmostEqual(res['score'], stub_score, places=5)
        # response nghiep vu khong lo endpoint/tensor noi bo
        blob = json.dumps(res)
        for internal in (self.fake.url, '/v2/models', '"IMAGE"', '"SCORE"', 'datatype'):
            self.assertNotIn(internal, blob)
        self.fake.httpd.shutdown()  # inference server mat -> readiness 503, khong nhan request moi
        self.fake.httpd.server_close()
        self.assertEqual(self.client.call('getReadiness').status, 503)
        self.assertEqual(self.submit(submit_body('ks-2')).status, 503)


# ------------------------------------------------------------------ coverage (chay cuoi)


class TestZZCoverage(unittest.TestCase):
    def test_every_operation_exercised(self):
        ops_seen = {op for op, _ in OBSERVED}
        missing = set(OPS) - ops_seen
        if os.environ.get('VR01_EVIDENCE_DIR'):
            d = Path(os.environ['VR01_EVIDENCE_DIR'])
            documented = sorted((o, int(s)) for o, (_, _, op) in OPS.items() for s in op['responses'])
            (d / 'coverage.json').write_text(json.dumps({
                'operations_total': len(OPS), 'operations_exercised': len(ops_seen & set(OPS)),
                'observed_status_pairs': sorted([list(x) for x in OBSERVED]),
                'documented_not_observed': [list(x) for x in documented if x not in OBSERVED],
            }, indent=2))
            with open(d / 'transcript.jsonl', 'w', encoding='utf-8') as fh:
                for rec in TRANSCRIPT:
                    line = json.dumps(rec, ensure_ascii=False)
                    for s in SECRETS:
                        line = line.replace(s, '<redacted>')
                    fh.write(line + '\n')
        self.assertEqual(missing, set(), f'operations never called: {missing}')


if __name__ == '__main__':
    unittest.main(verbosity=2)
