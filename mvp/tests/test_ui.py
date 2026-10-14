"""Test phia server cho UI W5-02/W5-03: trang tinh, CORS cong quan tri, /v1/me, so dem, lich su chuyen recipe.

Hanh vi trinh duyet (dang nhap, man hinh theo vai tro, hop thoai) duoc kiem rieng bang Playwright: tests/e2e/ui.e2e.mjs.
"""
import http.client
import json
import unittest

from test_contract import Base, submit_body


class UiBase(Base):
    def raw(self, method, path, plane='inference', headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.server.port(plane), timeout=10)
        c.request(method, path, headers=headers or {})
        r = c.getresponse()
        body = r.read()
        c.close()
        return r.status, {k.lower(): v for k, v in r.getheaders()}, body


class TestStaticUi(UiBase):
    def test_ui_served_anonymously_with_security_headers(self):
        for name, ctype in (('', 'text/html'), ('index.html', 'text/html'), ('app.js', 'text/javascript'),
                            ('app.css', 'text/css')):
            status, h, body = self.raw('GET', '/ui/' + name)
            self.assertEqual(status, 200, name)
            self.assertTrue(h['content-type'].startswith(ctype), name)
            self.assertIn("frame-ancestors 'none'", h['content-security-policy'])
            self.assertEqual(h['x-content-type-options'], 'nosniff')
            self.assertGreater(len(body), 100)
        status, h, _ = self.raw('GET', '/')
        self.assertEqual((status, h['location']), (302, '/ui/'))

    def test_ui_has_no_secrets_and_no_inline_script(self):
        _, _, html = self.raw('GET', '/ui/index.html')
        _, _, js = self.raw('GET', '/ui/app.js')
        for tok in self.tokens.values():
            self.assertNotIn(tok.encode(), html + js)
        self.assertNotIn(b'<script>', html)  # CSP chi cho script tu 'self'

    def test_only_allowlisted_files_and_not_on_management_plane(self):
        for path in ('/ui/../backend/inspection_api.py', '/ui/%2e%2e/backend/openapi.v1.yaml', '/ui/README.md',
                     '/ui/app.js.map'):
            self.assertEqual(self.raw('GET', path)[0], 404, path)
        self.assertEqual(self.raw('GET', '/ui/', plane='management')[0], 404)
        self.assertEqual(self.raw('GET', '/', plane='management')[0], 404)

    def test_config_exposes_only_management_port(self):
        status, _, body = self.raw('GET', '/ui/config.json')
        self.assertEqual((status, set(json.loads(body))), (200, {'management_port'}))


class TestCors(UiBase):
    def test_management_plane_allows_same_host_origin_only(self):
        ok = {'Origin': 'https://127.0.0.1:8443', 'Authorization': f"Bearer {self.tokens['admin']}"}
        status, h, _ = self.raw('GET', '/v1/admin/recipes', 'management', ok)
        self.assertEqual((status, h.get('access-control-allow-origin')), (200, 'https://127.0.0.1:8443'))
        self.assertIn('X-Trace-Id', h['access-control-expose-headers'])
        bad = {**ok, 'Origin': 'https://evil.example:8443'}
        status, h, _ = self.raw('GET', '/v1/admin/recipes', 'management', bad)
        self.assertNotIn('access-control-allow-origin', h)

    def test_preflight(self):
        status, h, _ = self.raw('OPTIONS', '/v1/admin/stations/station-sim/activation', 'management',
                                {'Origin': 'https://127.0.0.1:8443', 'Access-Control-Request-Method': 'POST',
                                 'Access-Control-Request-Headers': 'authorization,content-type,if-match'})
        self.assertEqual(status, 204)
        self.assertIn('If-Match', h['access-control-allow-headers'])
        self.assertEqual(self.raw('OPTIONS', '/v1/admin/recipes', 'management', {'Origin': 'https://x.example'})[0], 404)
        # Cong inference khong can CORS (UI cung origin)
        self.assertEqual(self.raw('OPTIONS', '/v1/me', 'inference', {'Origin': 'https://127.0.0.1:8443'})[0], 404)

    def test_explicit_origin_list_overrides_same_host(self):
        self.app.ui_origins = ('https://edge.local:30443',)
        h = self.raw('GET', '/healthz', 'management', {'Origin': 'https://127.0.0.1:8443'})[1]
        self.assertNotIn('access-control-allow-origin', h)
        h = self.raw('GET', '/healthz', 'management', {'Origin': 'https://edge.local:30443'})[1]
        self.assertEqual(h['access-control-allow-origin'], 'https://edge.local:30443')


class TestUiEndpoints(Base):
    sp = {'station_id': 'station-sim'}

    def test_me_returns_role_without_token(self):
        for role in ('viewer', 'operator', 'admin'):
            r = self.client.call('getMe', role=role)
            self.assertEqual((r.status, r.body['role'], r.body['station_id']), (200, role, 'station-sim'))
            self.assertNotIn(self.tokens[role], json.dumps(r.body))

    def test_summary_never_counts_technical_errors_as_ok_ng(self):
        for i in range(3):
            self.submit(submit_body(f'sum-{i}'))
        self.app.wait_idle()
        self.app.ledger.write("UPDATE inspections SET state='INDETERMINATE', decision=NULL WHERE request_id='sum-2'")
        r = self.client.call('getStationSummary', role='viewer', path_params=self.sp,
                             query='since=2000-01-01T00:00:00Z')
        b = r.body
        self.assertEqual(b['total'], 3)
        self.assertEqual(b['technical_error'], 1)
        self.assertEqual(b['ok'] + b['ng'] + b['review'], 2)
        direct = self.app.ledger.one("SELECT COUNT(*) AS n FROM inspections WHERE state='COMPLETED'")['n']
        self.assertEqual(b['ok'] + b['ng'] + b['review'], direct)
        r = self.client.call('getStationSummary', role='viewer', path_params=self.sp, query='since=2999-01-01T00:00:00Z')
        self.assertEqual(r.body['total'], 0)
        for q in ('since=yesterday', 'since=2026-01-01T00:00:00', 'foo=1'):
            self.assertEqual(self.client.call('getStationSummary', role='viewer', path_params=self.sp, query=q).status,
                             400, q)
        self.assertEqual(self.client.call('getStationSummary', role='viewer', path_params={'station_id': 'nope'}).status,
                         404)

    def test_activation_history_kinds_visible_to_viewer(self):
        a = self.client.call('activateRecipe', role='admin', path_params=self.sp,
                             body={'recipe_name': 'recipe-b', 'recipe_version': '0.1.0', 'reason': 'ui test b'})
        self.assertEqual(a.status, 200)
        self.assertEqual(self.client.call('rollbackRecipe', role='admin', path_params=self.sp,
                                          body={'reason': 'ui test rollback'}).status, 200)
        r = self.client.call('listStationActivations', role='viewer', path_params=self.sp)
        kinds = [(i['kind'], i['to_recipe_version'], i['reason']) for i in r.body['items']]
        self.assertEqual(kinds, [('rollback', 'recipe-a@0.1.0', 'ui test rollback'),
                                 ('activate', 'recipe-b@0.1.0', 'ui test b'),
                                 ('initial', 'recipe-a@0.1.0', 'bootstrap default recipe')])
        self.assertNotIn('golden', json.dumps(r.body))  # viewer khong thay chi tiet golden/audit
        self.assertEqual(self.client.call('listStationActivations', role='viewer', path_params=self.sp,
                                          query='limit=1').body['items'][0]['kind'], 'rollback')
        for q in ('limit=0', 'limit=51', 'x=1'):
            self.assertEqual(self.client.call('listStationActivations', role='viewer', path_params=self.sp,
                                              query=q).status, 400, q)

    def test_list_without_filter_returns_latest(self):
        for i in range(3):
            self.submit(submit_body(f'all-{i}', product=f'PCB1-SN-ALL-{i}'))
        self.app.wait_idle()
        r = self.client.call('listInspections', role='viewer', query='limit=2')
        self.assertEqual([i['request_id'] for i in r.body['items']], ['all-2', 'all-1'])
        self.assertIsNotNone(r.body['next_cursor'])


if __name__ == '__main__':
    unittest.main()
