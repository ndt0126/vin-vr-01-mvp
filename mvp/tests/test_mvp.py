"""Test cho phan MVP them vao so voi server tham chieu W2-04:
G1-G5 cua W2-03 va lifecycle load -> golden -> cutover -> drain -> unload -> rollback (W3-04).
"""
import hashlib
import json
import time
import unittest

import inspection_api as ra
from test_contract import Base, FakeKServe, png, submit_body


def wait_until(fn, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(0.02)
    return False


class TestW203Gaps(Base):
    overrides = {'execution_timeout_s': 0.3}

    def test_G1_terminal_row_cannot_be_overwritten_by_a_second_writer(self):
        self.backend.delay_s = 0.6
        self.submit(submit_body('g1'))
        self.assertEqual(self.wait_terminal('g1').body['state'], 'TIMEOUT')
        self.app.wait_idle()
        before = dict(self.app.ledger.one('SELECT * FROM inspections WHERE request_id=?', ('g1',)))
        self.app._finish('g1', 'stale-writer', 'COMPLETED', 'OK', None, 0.1, None, time.monotonic(), 1.0)
        after = dict(self.app.ledger.one('SELECT * FROM inspections WHERE request_id=?', ('g1',)))
        self.assertEqual(before, after)
        self.assertIn('request.stale_write_ignored', [e['event'] for e in self.trace_events()])

    def test_G3_captured_at_is_stored_and_returned(self):
        self.submit(submit_body('g3', captured_at='2026-10-10T01:02:03Z'))
        self.wait_terminal('g3')
        self.assertEqual(self.result('g3').body['captured_at'], '2026-10-10T01:02:03Z')
        row = self.app.ledger.one('SELECT captured_at FROM inspections WHERE request_id=?', ('g3',))
        self.assertEqual(row['captured_at'], '2026-10-10T01:02:03Z')

    def test_G4_list_by_state(self):
        self.submit(submit_body('ok-1', product='PCB1-SN-0001'))
        self.wait_terminal('ok-1')
        self.backend.fail_next = 1
        self.submit(submit_body('bad-1', product='PCB1-SN-0002'))
        self.wait_terminal('bad-1')

        def ids(query):
            r = self.client.call('listInspections', role='viewer', query=query)
            self.assertEqual(r.status, 200, r.body)
            return [i['request_id'] for i in r.body['items']]

        self.assertEqual(ids('state=FAILED'), ['bad-1'])
        self.assertEqual(ids('state=COMPLETED'), ['ok-1'])
        self.assertEqual(ids('state=FAILED&product_id=PCB1-SN-0001'), [])
        self.assertEqual(ids('product_id=PCB1-SN-0002'), ['bad-1'])
        for bad in ('state=DONE', 'limit=5'):
            self.assertEqual(self.client.call('listInspections', role='viewer', query=bad).status, 400)

    def test_G5_original_image_is_stored_once_by_sha256(self):
        image = png(gray=77)
        sha = hashlib.sha256(image).hexdigest()
        self.submit(submit_body('g5-1', image=image))
        self.submit(submit_body('g5-2', product='PCB1-SN-0002', image=image))
        self.wait_terminal('g5-2')
        files = [p for p in (self.tmp / 'data' / 'images').iterdir() if not p.name.startswith('.')]
        self.assertEqual([p.name for p in files], [sha + '.png'])
        self.assertEqual(files[0].read_bytes(), image)
        row = self.app.ledger.one('SELECT image_path, input_sha256 FROM inspections WHERE request_id=?', ('g5-1',))
        self.assertEqual((row['image_path'], row['input_sha256']), (f'images/{sha}.png', sha))


class TestLifecycle(Base):
    overrides = {'rollback_error_threshold': 3, 'rollback_window_s': 60, 'drain_timeout_s': 5}

    def active(self):
        return self.client.call('getActiveRecipe', role='viewer',
                                path_params={'station_id': 'station-sim'}).body['recipe_version']

    def test_boot_loads_active_model(self):
        self.assertEqual(self.backend.lifecycle, [('load', 'model-a')])
        self.assertEqual(self.backend.loaded, {'model-a'})

    def test_cutover_drains_pinned_requests_then_unloads_old_model(self):
        self.backend.delay_s = 0.3
        self.submit(submit_body('lc-a1'))
        self.submit(submit_body('lc-a2', product='PCB1-SN-0002'))
        self.wait_state('lc-a1', 'PROCESSING')
        self.backend.delay_s = 0.05
        self.activate('recipe-b')
        self.assertIn('model-a', self.backend.loaded)  # A con request da pin: chua duoc unload
        self.submit(submit_body('lc-b1', recipe='recipe-b@0.1.0'))
        for rid, model in (('lc-a1', 'model-a'), ('lc-a2', 'model-a'), ('lc-b1', 'model-b')):
            self.assertEqual(self.wait_terminal(rid).body['state'], 'COMPLETED')
            self.assertEqual(self.result(rid).body['lineage']['model']['name'], model)
        self.assertTrue(wait_until(lambda: ('unload', 'model-a') in self.backend.lifecycle))
        events = self.trace_events()
        order = [(e['event'], e.get('request_id') or e.get('model', {}).get('name')) for e in events
                 if e['event'] in ('request.terminal', 'lifecycle.unloaded')]
        self.assertLess(order.index(('request.terminal', 'lc-a2')), order.index(('lifecycle.unloaded', 'model-a')))
        self.assertEqual(self.backend.loaded, {'model-b'})

    def test_candidate_load_failure_keeps_old_recipe(self):
        self.backend.fail_load = {'model-b'}
        self.activate('recipe-b', expect=422)
        self.assertEqual(self.active(), 'recipe-a@0.1.0')
        self.assertEqual(self.backend.loaded, {'model-a'})
        self.submit(submit_body('lf-1'))
        self.assertEqual(self.wait_terminal('lf-1').body['state'], 'COMPLETED')

    def test_auto_rollback_after_consecutive_errors_right_after_cutover(self):
        self.activate('recipe-b')
        self.backend.fail_next = 3
        for i in range(3):
            self.submit(submit_body(f'rb-{i}', product=f'PCB1-SN-000{i}', recipe='recipe-b@0.1.0'))
        for i in range(3):
            r = self.wait_terminal(f'rb-{i}').body
            self.assertEqual((r['state'], r['decision']), ('FAILED', None))
        self.assertTrue(wait_until(lambda: self.active() == 'recipe-a@0.1.0'))
        audit = self.client.call('listAudit', role='admin').body['items']
        self.assertTrue(any(a['action'] == 'auto_rollback' and a['outcome'] == 'OK' for a in audit))
        self.submit(submit_body('rb-after'))
        self.assertEqual(self.wait_terminal('rb-after').body['state'], 'COMPLETED')
        self.assertEqual(self.result('rb-after').body['lineage']['model']['name'], 'model-a')
        self.assertTrue(wait_until(lambda: self.backend.loaded == {'model-a'}))
        # 3 request loi van giu lineage model-b va khong bi chay lai.
        self.assertEqual(self.result('rb-0').body['lineage']['model']['name'], 'model-b')
        self.assertEqual([c['request_id'] for c in self.backend.calls].count('rb-0'), 1)

    def test_single_error_after_cutover_does_not_roll_back(self):
        self.activate('recipe-b')
        self.backend.fail_next = 1
        self.submit(submit_body('one-0', recipe='recipe-b@0.1.0'))
        self.wait_terminal('one-0')
        self.submit(submit_body('one-1', product='PCB1-SN-0002', recipe='recipe-b@0.1.0'))
        self.assertEqual(self.wait_terminal('one-1').body['state'], 'COMPLETED')
        self.assertEqual(self.active(), 'recipe-b@0.1.0')

    def test_model_is_reloaded_after_inference_server_restart(self):
        self.backend.loaded.clear()  # Triton explicit mode khoi dong lai: khong con model nao duoc nap
        self.assertEqual(self.client.call('getReadiness').status, 200)  # readiness tu nap lai dung model active
        self.assertEqual(self.backend.lifecycle[-1], ('load', 'model-a'))
        self.submit(submit_body('heal-1'))
        self.assertEqual(self.wait_terminal('heal-1').body['state'], 'COMPLETED')
        self.assertIn('lifecycle.model_restored', [e['event'] for e in self.trace_events()])

    def test_not_ready_while_model_cannot_be_loaded_then_recovers(self):
        self.backend.loaded.clear()
        self.backend.fail_load = {'model-a'}
        rz = self.client.call('getReadiness')
        self.assertEqual((rz.status, rz.body['reasons']), (503, ['WARMUP_FAILED']))
        self.assertEqual(self.submit(submit_body('heal-x')).status, 503)
        self.assertEqual(self.active(), 'recipe-a@0.1.0')  # khong tu doi sang recipe khac
        self.backend.fail_load = set()
        self.assertTrue(wait_until(lambda: self.client.call('getReadiness').status == 200, timeout=6))

    def test_active_recipe_and_model_restored_after_crash(self):
        self.activate('recipe-b')
        self.restart(crash=True, backend=ra.StubBackend())
        self.assertEqual(self.active(), 'recipe-b@0.1.0')
        self.assertEqual(self.backend.lifecycle, [('load', 'model-b')])


class TestTritonProtocol(Base):
    """Adapter KServe v2 + explicit model control, voi inference server gia."""

    def setUp(self):
        params = {n: json.loads((ra.W205 / 'examples' / 'packages' / n / 'model.json').read_text())
                  for n in ('model-a', 'model-b')}
        self.fake = FakeKServe(params)
        self.backend = ra.KServeV2Backend(self.fake.url)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.fake.close()

    def test_load_infer_switch_unload_over_kserve(self):
        self.assertEqual(self.fake.lifecycle, [('load', 'model-a')])
        self.submit(submit_body('tp-1'))
        self.assertEqual(self.wait_terminal('tp-1').body['state'], 'COMPLETED')
        self.activate('recipe-b')
        self.assertTrue(wait_until(lambda: self.fake.loaded == {'model-b'}))
        self.submit(submit_body('tp-2', recipe='recipe-b@0.1.0'))
        self.assertEqual(self.wait_terminal('tp-2').body['state'], 'COMPLETED')
        self.assertEqual([c['path'] for c in self.fake.calls if c['body']['id'] == 'tp-2'],
                         ['/v2/models/model-b/infer'])

    def test_G2_backend_response_with_another_id_is_never_completed(self):
        self.fake.wrong_id = True
        self.submit(submit_body('g2'))
        r = self.wait_terminal('g2').body
        self.assertEqual((r['state'], r['decision'], r['reason']), ('FAILED', None, 'BACKEND_ID_MISMATCH'))
        self.assertIsNone(self.result('g2').body['score'])


if __name__ == '__main__':
    unittest.main()


class TestCutoverUnderLoad(Base):
    """Hoi quy cho loi tim thay bang tests/load_cutover.py: request pin model cu ngay luc cutover
    bi chay sau khi model cu da unload."""

    def test_no_request_runs_on_an_unloaded_model_during_repeated_cutover(self):
        import threading
        orig = self.backend.infer

        def strict_infer(model, params, tensor, trace_id, request_id):
            if request_id != 'golden' and model['name'] not in self.backend.loaded:
                raise RuntimeError(f"model {model['name']} is not loaded")
            return orig(model, params, tensor, trace_id, request_id)

        self.backend.infer = strict_infer
        stop, accepted = threading.Event(), []

        def traffic():
            recipe, i = 'recipe-a@0.1.0', 0
            while not stop.is_set():
                rid = f'cl-{i:05d}'
                r = self.submit(submit_body(rid, product=f'PCB1-SN-{i % 20:04d}', recipe=recipe))
                if r.status == 202:
                    accepted.append((rid, recipe))
                    i += 1
                elif r.status == 409:
                    recipe = r.body['details']['active_recipe_version']
                else:
                    time.sleep(0.005)

        t = threading.Thread(target=traffic)
        t.start()
        for k in range(30):
            time.sleep(0.03)
            self.activate('recipe-b' if k % 2 == 0 else 'recipe-a')
        stop.set()
        t.join()
        self.assertGreater(len(accepted), 100)
        for rid, recipe in accepted:
            res = self.wait_terminal(rid).body
            self.assertEqual(res['state'], 'COMPLETED', (rid, res))
            lin = self.result(rid).body['lineage']
            self.assertEqual(f"{lin['recipe']['name']}@{lin['recipe']['version']}", recipe)
        self.assertEqual(self.count(), len(accepted))


class TestCancellation(Base):
    overrides = {'execution_timeout_s': 5}

    def cancel(self, rid, role='operator', reason='san pham bi lay khoi bang chuyen', **kw):
        return self.client.call('cancelInspection', role=role, path_params={'request_id': rid},
                                body={'reason': reason}, **kw)

    def test_cancel_while_queued_never_reaches_backend(self):
        self.backend.delay_s = 0.4
        self.submit(submit_body('cq-0'))
        self.submit(submit_body('cq-1', product='PCB1-SN-0002'))
        r = self.cancel('cq-1')
        self.assertEqual((r.status, r.body['state'], r.body['decision'], r.body['reason']),
                         (200, 'CANCELLED', None, 'CANCELLED_BY_CLIENT'))
        self.assertEqual(self.wait_terminal('cq-0').body['state'], 'COMPLETED')
        self.app.wait_idle()
        self.assertNotIn('cq-1', [c['request_id'] for c in self.backend.calls])
        res = self.result('cq-1')
        self.assertEqual((res.status, res.body['state'], res.body['score'], res.body['started_at']),
                         (200, 'CANCELLED', None, None))
        self.assertIn('request.dequeued_already_terminal',
                      [e['event'] for e in self.trace_events() if e.get('request_id') == 'cq-1'])

    def test_cancel_while_processing_discards_the_late_result(self):
        self.backend.delay_s = 0.5
        self.submit(submit_body('cp-1'))
        self.wait_state('cp-1', 'PROCESSING')
        r = self.cancel('cp-1')
        self.assertEqual((r.status, r.body['state']), (200, 'CANCELLED'))
        cancelled_at = self.result('cp-1').body['finished_at']
        self.app.wait_idle()  # backend da tra ket qua muon
        res = self.result('cp-1').body
        self.assertEqual((res['state'], res['decision'], res['score'], res['reason'], res['finished_at']),
                         ('CANCELLED', None, None, 'CANCELLED_BY_CLIENT', cancelled_at))
        ev = [e for e in self.trace_events() if e.get('request_id') == 'cp-1']
        discarded = [e for e in ev if e['event'] == 'inference.result_discarded_after_cancel']
        self.assertEqual(len(discarded), 1)
        self.assertEqual(discarded[0]['discarded_state'], 'COMPLETED')
        self.assertIsNotNone(discarded[0]['discarded_score'])
        # he thong van phuc vu request tiep theo
        self.backend.delay_s = 0
        self.submit(submit_body('cp-2', product='PCB1-SN-0002'))
        self.assertEqual(self.wait_terminal('cp-2').body['state'], 'COMPLETED')

    def test_cancel_is_idempotent_and_refused_once_terminal(self):
        self.backend.delay_s = 0.3
        self.submit(submit_body('ci-1'))
        self.assertEqual(self.cancel('ci-1').status, 200)
        again = self.cancel('ci-1')
        self.assertEqual((again.status, again.body['state']), (200, 'CANCELLED'))
        self.app.wait_idle()
        self.backend.delay_s = 0
        self.submit(submit_body('ci-2', product='PCB1-SN-0002'))
        done = self.wait_terminal('ci-2').body
        before = self.result('ci-2').body
        r = self.cancel('ci-2')
        self.assertEqual((r.status, r.body['code'], r.body['details']['state']), (409, 'ALREADY_TERMINAL', 'COMPLETED'))
        self.assertEqual(self.result('ci-2').body, before)
        self.assertEqual(done['state'], 'COMPLETED')
        self.assertEqual(self.cancel('nope').status, 404)

    def test_cancel_permissions_validation_and_audit(self):
        self.backend.delay_s = 0.3
        self.submit(submit_body('ca-1'))
        self.assertEqual(self.cancel('ca-1', role='viewer').status, 403)
        self.assertEqual(self.cancel('ca-1', role='admin').status, 403)
        self.assertEqual(self.cancel('ca-1', role=None).status, 401)
        self.assertEqual(self.cancel('ca-1', reason='x').status, 400)
        self.assertEqual(self.client.call('getInspectionStatus', role='viewer',
                                          path_params={'request_id': 'ca-1'}).body['state'] in ('RECEIVED', 'PROCESSING'), True)
        self.assertEqual(self.cancel('ca-1').status, 200)
        audit = self.client.call('listAudit', role='admin').body['items']
        ok = [a for a in audit if a['action'] == 'cancel' and a['outcome'] == 'OK']
        self.assertEqual((len(ok), ok[0]['target'], ok[0]['actor']), (1, 'ca-1', 'cam-sim-01'))
        self.app.wait_idle()

    def test_replay_and_retry_after_cancel(self):
        self.backend.delay_s = 0.3
        body = submit_body('cr-1')
        self.submit(body)
        self.cancel('cr-1')
        self.app.wait_idle()
        self.backend.delay_s = 0
        replay = self.submit(body)
        self.assertEqual((replay.status, replay.body['state']), (200, 'CANCELLED'))  # khong chay lai
        self.assertEqual([c['request_id'] for c in self.backend.calls].count('cr-1'), 1)
        self.submit(submit_body('cr-2', retry_of='cr-1'))
        self.assertEqual(self.wait_terminal('cr-2').body['state'], 'COMPLETED')
        ids = self.client.call('listInspections', role='viewer', query='state=CANCELLED').body['items']
        self.assertEqual([i['request_id'] for i in ids], ['cr-1'])

    def test_cancel_racing_with_completion_has_exactly_one_winner(self):
        import threading
        outcomes = {'cancelled': 0, 'completed': 0}
        for i in range(40):
            rid = f'race-{i:02d}'
            self.backend.delay_s = 0.002 * (i % 5)
            self.submit(submit_body(rid, product=f'PCB1-SN-{i:04d}'))
            box = {}
            t = threading.Thread(target=lambda: box.update(r=self.cancel(rid)))
            t.start()
            t.join()
            final = self.wait_terminal(rid).body
            self.app.wait_idle()
            self.assertEqual(self.result(rid).body['state'], final['state'])  # khong doi sau khi backend tra ve
            if box['r'].status == 200:
                self.assertEqual((final['state'], final['decision']), ('CANCELLED', None))
                outcomes['cancelled'] += 1
            else:
                self.assertEqual((box['r'].status, final['state']), (409, 'COMPLETED'))
                self.assertIsNotNone(final['decision'])
                outcomes['completed'] += 1
        self.assertEqual(sum(outcomes.values()), 40)

    def test_cancelled_request_survives_restart_and_cutover_waits_for_it(self):
        self.backend.delay_s = 0.8
        self.submit(submit_body('cs-1'))
        self.wait_state('cs-1', 'PROCESSING')
        self.assertTrue(wait_until(lambda: any(c['request_id'] == 'cs-1' for c in self.backend.calls)))
        time.sleep(0.05)  # backend da bat dau ngu 0.8 s cho cs-1
        self.backend.delay_s = 0.01  # golden check cua lan chuyen khong bi cham
        self.cancel('cs-1')
        self.activate('recipe-b')
        self.assertIn('model-a', self.backend.loaded)  # backend van dang chay request da huy tren model-a
        self.assertTrue(wait_until(lambda: self.backend.loaded == {'model-b'}))
        self.restart()
        self.assertEqual(self.result('cs-1').body['state'], 'CANCELLED')
