import base64
import tempfile
import threading
import time
import unittest
from controller import Controller


class Fake:
    def __init__(self):
        self.loaded = set()
        self.calls = 0
        self.block = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def load(self, name): self.loaded.add(name)
    def unload(self, name): self.loaded.remove(name)
    def infer(self, name, image, side, brightness):
        assert name in self.loaded
        self.calls += 1
        if self.block:
            self.entered.set()
            self.release.wait(3)
        return {'gpu_forward_ms': 1000, 'output_sha256': name}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = Fake()
        self.c = Controller(self.tmp.name, self.b, {'A': {'name': 'A', 'side': 224}, 'B': {'name': 'B', 'side': 256}}, b'img', telemetry=False)
        self.c.initialize()
        self.payload = {'request_id': 'one', 'image': base64.b64encode(b'img').decode(), 'product_id': 'p'}

    def tearDown(self):
        self.b.release.set()
        self.c.close()
        self.tmp.cleanup()

    def test_dedup_and_conflict(self):
        first = self.c.submit(self.payload)
        calls = self.b.calls
        self.c.parameters()
        self.assertEqual(first, self.c.submit(self.payload))
        self.assertEqual(calls, self.b.calls)
        self.assertEqual(409, self.c.submit(dict(self.payload, product_id='different'))[0])

    def test_parameter_revision_retry_is_idempotent(self):
        self.assertEqual({'revision': 2, 'applied': True}, self.c.parameters(2))
        self.assertEqual({'revision': 2, 'applied': False}, self.c.parameters(2))
        self.assertEqual(2, self.c.status()['parameter_revision'])
        with self.assertRaisesRegex(ValueError, 'gap'):
            self.c.parameters(4)

    def test_concurrent_retry_is_processing(self):
        self.b.block = True
        t = threading.Thread(target=self.c.submit, args=(self.payload,))
        t.start()
        self.assertTrue(self.b.entered.wait(1))
        self.assertEqual(202, self.c.submit(self.payload)[0])
        self.c.parameters()
        self.b.release.set()
        t.join(3)
        self.assertEqual(1, self.c.lookup('one')[1]['route']['parameter_revision'])

    def test_faults_keep_or_restore_A(self):
        for fault in ('load', 'warm', 'post'):
            result = self.c.activate('B', fault=fault, rollback_window=.01)
            self.assertIn(result['state'], ('REJECTED', 'ROLLED_BACK'))
            self.assertEqual('A', self.c.active)
            self.assertEqual({'A'}, self.b.loaded)

    def test_switch(self):
        self.assertEqual('COMPLETED', self.c.activate('B', rollback_window=.01)['state'])
        result = self.c.submit(self.payload)[1]
        self.assertEqual('B', result['route']['key'])
        self.assertEqual({'B'}, self.b.loaded)

    def test_old_is_not_unloaded_before_drain(self):
        with self.c.lock:
            self.c.inflight['A'] = 1
        t = threading.Thread(target=self.c.activate, args=('B',), kwargs={'rollback_window': .01})
        t.start()
        end = time.monotonic()+1
        while self.c.active != 'B' and time.monotonic() < end:
            time.sleep(.005)
        self.assertEqual('B', self.c.active)
        self.assertIn('A', self.b.loaded)
        self.assertTrue(t.is_alive())
        with self.c.changed:
            self.c.inflight['A'] = 0
            self.c.changed.notify_all()
        t.join(2)
        self.assertEqual({'B'}, self.b.loaded)

    def test_admission_is_bounded_without_ledger_side_effect(self):
        self.c.inflight['A'] = 8
        self.assertEqual(429, self.c.submit(self.payload)[0])
        self.assertEqual(404, self.c.lookup('one')[0])
        self.c.inflight['A'] = 0

    def test_invalid_payload(self):
        self.assertEqual(400, self.c.submit({})[0])
        self.assertEqual(400, self.c.submit(dict(self.payload, image='%%%'))[0])

    def test_crash_recovery_does_not_reexecute_uncertain(self):
        self.c.db.execute('INSERT INTO requests VALUES(?,?,?,?,NULL)', ('uncertain', 'x', 'PROCESSING', '{}'))
        self.c.db.commit()
        self.c.close()
        self.c = Controller(self.tmp.name, self.b, self.c.config, b'img', telemetry=False)
        self.assertEqual('INDETERMINATE', self.c.lookup('uncertain')[1]['state'])

    def test_oom_counter_tracks_inference_failure(self):
        def fail(*_):
            raise RuntimeError('CUDA out of memory')
        self.b.infer = fail
        self.assertEqual('FAILED', self.c.submit(self.payload)[1]['state'])
        self.assertEqual(1, self.c.status()['oom_count'])


if __name__ == '__main__': unittest.main()
