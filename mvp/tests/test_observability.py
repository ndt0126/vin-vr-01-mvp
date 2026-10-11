"""W4-01/W4-02: /metrics, nhan co cardinality kiem soat, readiness trong metric, xoay vong log."""
import http.client
import json
import re
import time
import unittest

import inspection_api as ra
import metrics as mx
from test_contract import Base, png, submit_body

SAMPLE = re.compile(r'^([a-z_][a-z0-9_]*)(\{[^}]*\})? (-?[0-9.e+-]+|NaN)$')


def parse(text):
    out = {}
    for line in text.splitlines():
        if line.startswith('#') or not line:
            continue
        m = SAMPLE.match(line)
        assert m, f'bad exposition line: {line!r}'
        out[m.group(1) + (m.group(2) or '')] = float(m.group(3))
    return out


class TestMetrics(Base):
    overrides = {'execution_timeout_s': 0.3}

    def scrape(self):
        return self.app.metrics.render(self.app.metric_gauges())

    def test_counters_follow_the_request_lifecycle(self):
        self.submit(submit_body('m-ok', image=png(gray=20)))                                   # OK
        self.submit(submit_body('m-ng', product='PCB1-SN-0002', image=png(gray=220)))          # NG
        self.wait_terminal('m-ng')
        self.submit(submit_body('m-ok', image=png(gray=20)))                                   # replay
        self.assertEqual(self.submit(submit_body('m-bad', image=b'not an image')).status, 422)  # tu choi truoc admission
        self.assertEqual(self.submit(submit_body('m-old', recipe='recipe-b@0.1.0')).status, 409)
        self.backend.fail_next = 1
        self.submit(submit_body('m-fail', product='PCB1-SN-0003'))
        self.wait_terminal('m-fail')
        self.backend.delay_s = 0.6
        self.submit(submit_body('m-timeout', product='PCB1-SN-0004'))
        self.wait_terminal('m-timeout')
        self.app.wait_idle()
        self.backend.delay_s = 0.25
        self.submit(submit_body('m-cancel', product='PCB1-SN-0005'))
        self.wait_state('m-cancel', 'PROCESSING')
        self.client.call('cancelInspection', role='operator', path_params={'request_id': 'm-cancel'},
                         body={'reason': 'metrics test'})
        self.app.wait_idle()
        self.backend.delay_s = 0
        self.client.call('getActiveRecipe', path_params={'station_id': 'station-sim'})        # 401
        self.activate('recipe-b')
        m = parse(self.scrape())
        self.assertEqual(m['vr01_inspections_admitted_total{model="model-a"}'], 5)
        self.assertEqual(m['vr01_inspections_terminal_total{state="COMPLETED",reason="none"}'], 2)
        self.assertEqual(m['vr01_inspections_terminal_total{state="FAILED",reason="BACKEND_ERROR"}'], 1)
        self.assertEqual(m['vr01_inspections_terminal_total{state="TIMEOUT",reason="EXECUTION_TIMEOUT"}'], 1)
        self.assertEqual(m['vr01_inspections_terminal_total{state="CANCELLED",reason="CANCELLED_BY_CLIENT"}'], 1)
        self.assertEqual(m['vr01_inspection_decisions_total{decision="OK"}'], 1)
        self.assertEqual(m['vr01_inspection_decisions_total{decision="NG"}'], 1)
        self.assertEqual(m['vr01_inspections_replayed_total'], 1)
        self.assertEqual(m['vr01_inspections_rejected_total{code="RECIPE_VERSION_MISMATCH"}'], 1)
        self.assertEqual(m['vr01_inspections_cancelled_total{was_started="true"}'], 1)
        self.assertEqual(m['vr01_late_results_discarded_total{cause="timeout"}'], 1)
        self.assertEqual(m['vr01_late_results_discarded_total{cause="cancelled"}'], 1)
        self.assertEqual(m['vr01_http_requests_total{plane="inference",operation="submitInspection",status="422"}'], 1)
        self.assertEqual(m['vr01_auth_denied_total{outcome="UNAUTHENTICATED"}'], 1)
        self.assertEqual(m['vr01_activations_total{action="activate",outcome="OK"}'], 1)
        self.assertEqual(m['vr01_model_load_total{model="model-b",result="ok"}'], 1)
        # 2 lan COMPLETED + 1 lan da huy nhung suy luan van chay het (huy khong dung duoc inference server)
        self.assertEqual(m['vr01_inference_seconds_count{model="model-a"}'], 3)
        self.assertEqual(m['vr01_inspection_total_seconds_count'], 2)
        self.assertGreaterEqual(m['vr01_queue_wait_seconds_count'], 5)
        self.assertEqual(m['vr01_inference_seconds_bucket{model="model-a",le="+Inf"}'], 3)
        # so dem khop voi ledger
        rows = dict(self.app.ledger.all('SELECT state, COUNT(*) FROM inspections GROUP BY state'))
        for state, n in rows.items():
            total = sum(v for k, v in m.items() if k.startswith(f'vr01_inspections_terminal_total{{state="{state}"'))
            self.assertEqual(total, n, state)

    def test_exposition_is_valid_complete_and_has_no_high_cardinality_or_secret(self):
        self.submit(submit_body('card-REQ-0001', product='PCB1-SN-CARD-9'))
        self.wait_terminal('card-REQ-0001')
        text = self.scrape()
        parse(text)
        for name, (kind, help_text, labels) in mx.CATALOG.items():
            self.assertIn(f'# TYPE {name} {kind}', text)
            self.assertIn(f'# HELP {name} ', text)
            self.assertFalse({'request_id', 'product_id', 'trace_id', 'actor', 'principal'} & set(labels), name)
        for forbidden in ('card-REQ-0001', 'PCB1-SN-CARD-9', *self.tokens.values()):
            self.assertNotIn(forbidden, text)
        self.assertLess(len(text.splitlines()), 400)

    def test_readiness_and_active_revision_are_visible(self):
        m = parse(self.scrape())
        self.assertEqual((m['vr01_ready'], m['vr01_not_ready_reason{reason="BACKEND_UNAVAILABLE"}']), (1, 0))
        act = [k for k in m if k.startswith('vr01_active_recipe_info')]
        self.assertEqual(len(act), 1)
        self.assertIn('recipe="recipe-a"', act[0])
        self.assertIn('model="model-a"', act[0])
        self.backend.available = False
        m = parse(self.scrape())
        self.assertEqual((m['vr01_ready'], m['vr01_not_ready_reason{reason="BACKEND_UNAVAILABLE"}']), (0, 1))
        self.backend.available = True
        self.activate('recipe-b')
        act = [k for k in parse(self.scrape()) if k.startswith('vr01_active_recipe_info')]
        self.assertEqual(len(act), 1)  # khong de lai series cua recipe cu
        self.assertIn('recipe="recipe-b"', act[0])
        self.assertRegex(act[0], r'model_sha256="[a-f0-9]{12}"')

    def test_queue_depth_and_inflight_gauges(self):
        self.backend.delay_s = 0.3
        for i in range(3):
            self.submit(submit_body(f'q-{i}', product=f'PCB1-SN-000{i}'))
        m = parse(self.scrape())
        self.assertEqual((m['vr01_queue_depth'], m['vr01_inflight_requests{model="model-a"}'], m['vr01_queue_capacity']),
                         (3, 3, 8))
        self.app.wait_idle()
        self.assertEqual(parse(self.scrape())['vr01_queue_depth'], 0)

    def test_metrics_listener_is_separate_and_serves_only_metrics(self):
        self.server.close()
        self.start()
        srv = ra.Server(self.app, inference_port=0, management_port=0, metrics_port=0)
        try:
            c = http.client.HTTPConnection('127.0.0.1', srv.port('metrics'), timeout=5)
            c.request('GET', '/metrics')
            r = c.getresponse()
            body = r.read().decode()
            self.assertEqual((r.status, r.getheader('Content-Type').split(';')[0]), (200, 'text/plain'))
            self.assertIn('vr01_ready 1', body)
            for path in ('/v1/inspections', '/readyz', '/'):
                c.request('GET', path)
                r = c.getresponse()
                r.read()
                self.assertEqual(r.status, 404, path)
            for plane in ('inference', 'management'):  # cong nghiep vu khong lo metrics
                b = http.client.HTTPConnection('127.0.0.1', srv.port(plane), timeout=5)
                b.request('GET', '/metrics')
                self.assertEqual(b.getresponse().status, 404)
        finally:
            for s in srv.httpd.values():
                s.shutdown()
                s.server_close()


class TestTraceRotation(Base):
    overrides = {'trace_max_bytes': 4000, 'trace_keep_files': 2}

    def test_trace_log_is_capped_and_rotated(self):
        for i in range(40):
            self.submit(submit_body(f'rot-{i:03d}', product=f'PCB1-SN-{i:04d}'))
        self.wait_terminal('rot-039')
        self.app.wait_idle()
        files = sorted(p.name for p in (self.tmp / 'data').glob('trace.jsonl*'))
        self.assertEqual(files, ['trace.jsonl', 'trace.jsonl.1', 'trace.jsonl.2'])
        total = sum((self.tmp / 'data' / f).stat().st_size for f in files)
        self.assertLess(total, 3 * 4000 + 2000)
        for f in files:  # moi file van la JSON Lines hop le
            for line in (self.tmp / 'data' / f).read_text().splitlines():
                json.loads(line)
        self.assertEqual(self.result('rot-000').status, 200)  # ledger khong bi anh huong boi viec xoay log


if __name__ == '__main__':
    unittest.main()
