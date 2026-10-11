"""Bounded lab controller: immutable routing snapshots and durable dedup ledger."""
import base64
import hashlib
import json
import shutil
import sqlite3
import subprocess
import threading
import time
from pathlib import Path
from common import Log, utc, atomic


class Controller:
    def __init__(self, root, backend, config, image, telemetry=True):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend, self.config, self.image = backend, config, image
        self.events, self.resources = Log(self.root/'events.jsonl'), Log(self.root/'resources.jsonl')
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.activation = threading.Lock()
        self.gpu = threading.Lock()  # serialize forwards including warm-up, not HTTP submissions
        self.db = sqlite3.connect(self.root/'ledger.sqlite', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, fingerprint TEXT, state TEXT, route TEXT, result TEXT)')
        self.db.execute("UPDATE requests SET state='INDETERMINATE' WHERE state='PROCESSING'")
        self.db.commit()
        self.active, self.revision, self.brightness = 'A', 1, 100
        saved = self.root/'parameters.json'
        if saved.exists():
            params = json.loads(saved.read_text())
            self.revision, self.brightness = params['revision'], params['brightness']
        self.inflight = {'A': 0, 'B': 0}
        self.loaded, self.pending = set(), {}
        self.executing = None
        self.previous, self.rollback_until = None, 0
        self.switches, self.telemetry = [], telemetry
        self.oom_count = 0
        self.stop_sampler = threading.Event()
        self.sampler = threading.Thread(target=self.sample_loop, daemon=True)
        self.sampler.start()

    def initialize(self):
        for key in ('B', 'A'):
            try:
                self.backend.unload(self.config[key]['name'])
            except Exception as exc:
                self.events.write(event='startup_unload_notice', model=key, error=str(exc))
        stage = 'load'
        try:
            self.backend.load(self.config['A']['name'])
            self.loaded.add('A')
            stage = 'warm'
            self.warm('A')
        except Exception as exc:
            if 'out of memory' in str(exc).lower() or 'cuda oom' in str(exc).lower():
                self.oom_count += 1
            self.events.write(event='startup_failed', model='A', stage=stage, error=str(exc))
            raise
        self.events.write(event='initialized', active='A')

    def sample(self, phase, request_id=None):
        if not self.telemetry:
            return
        with self.lock:
            row = {'phase': phase, 'request_id': request_id, 'executing': self.executing,
                   'inflight': dict(self.inflight), 'active': self.active}
        try:
            value = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw',
                                             '--format=csv,noheader,nounits'], text=True, timeout=3).strip()
            row['gpu'] = value
            row['disk_free_bytes'] = shutil.disk_usage(self.root).free
        except Exception as exc:
            row['telemetry_error'] = str(exc)
        self.resources.write(**row)

    def sample_loop(self):
        while not self.stop_sampler.wait(.2):
            self.sample('during' if self.executing else 'idle')

    def memory_admit(self):
        if not self.telemetry:
            return
        if shutil.disk_usage(self.root).free < 2*1024**3:
            raise RuntimeError('disk reserve below 2GiB')
        # Fail closed when telemetry is unavailable; configured envelopes remain essential.
        used, total = map(int, subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used,memory.total',
                                                       '--format=csv,noheader,nounits'], text=True, timeout=3).strip().split(','))
        if total - used < 900:
            raise RuntimeError('VRAM free reserve below 900MiB')

    def warm(self, key):
        cfg = self.config[key]
        with self.gpu:
            if hasattr(self.backend, 'request_context'):
                self.backend.request_context.request_id = ''
            result = self.backend.infer(cfg['name'], self.image, cfg['side'], self.brightness)
        self.events.write(event='warmup_ok', model=key, metrics=result)
        return result

    def parameters(self, expected_revision=None):
        with self.lock:
            if expected_revision is not None:
                if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
                    raise ValueError('expected_revision must be an integer')
                if expected_revision <= self.revision:
                    return {'revision': self.revision, 'applied': False}
                if expected_revision != self.revision + 1:
                    raise ValueError('parameter revision gap')
            self.revision += 1
            self.brightness = (95, 100, 105)[self.revision % 3]
            atomic(self.root/'parameters.json', {'revision': self.revision, 'brightness': self.brightness})
            self.events.write(event='parameters', revision=self.revision, brightness=self.brightness)
            return {'revision': self.revision, 'applied': True}

    def lab_set_side(self, side):
        # Fault-lab only: exercise a larger but valid GPU input after warm-up.
        # service.py exposes this solely when VR01_LAB_OOM=1.
        if not isinstance(side, int) or not 224 <= side <= 6144:
            raise ValueError('side outside validated envelope')
        with self.lock:
            if sum(self.inflight.values()):
                raise RuntimeError('cannot change side with in-flight requests')
            old = self.config['A']['side']
            self.config['A']['side'] = side
            self.revision += 1
            self.events.write(event='lab_side_change', old=old, side=side, revision=self.revision)
            return {'old': old, 'side': side, 'parameter_revision': self.revision}

    def activate(self, target, fault=None, rollback_window=15):
        with self.activation:
            began = time.monotonic()
            old = self.active
            if old == target:
                return {'state': 'NOOP'}
            self.events.write(event='load_begin', old=old, target=target, fault=fault)
            stage = 'admission'
            try:
                self.memory_admit()
                stage = 'load'
                if fault == 'load':
                    raise RuntimeError('injected load failure (not GPU OOM)')
                self.backend.load(self.config[target]['name'])
                self.events.write(event='backend_load_ok', target=target,
                                  elapsed_ms=(time.monotonic()-began)*1000)
                self.loaded.add(target)
                stage = 'warm'
                if fault == 'warm':
                    raise RuntimeError('injected warmup failure')
                self.warm(target)
            except Exception as exc:
                if 'out of memory' in str(exc).lower() or 'cuda oom' in str(exc).lower():
                    self.oom_count += 1
                self.events.write(event='candidate_rejected', target=target, stage=stage, error=str(exc))
                if target in self.loaded:
                    self.backend.unload(self.config[target]['name'])
                    self.loaded.remove(target)
                return {'state': 'REJECTED', 'error': str(exc)}
            with self.lock:
                cutover = time.monotonic()
                self.previous, self.rollback_until = old, cutover+rollback_window
                self.active = target
                record = {'old': old, 'target': target, 'cutover_monotonic': cutover,
                          'load_warm_ms': (cutover-began)*1000, 'old_inflight': self.inflight[old],
                          'fault': fault, 'state': 'CUTOVER'}
                self.switches.append(record)
                self.events.write(event='cutover', **record)
            # Separate probe detects an immediate post-cutover failure. A remains loaded.
            if fault == 'post':
                self.rollback(target, 'injected post-cutover validation failure')
            # Keep the old model through the rollback window AND until pinned traffic drains.
            while time.monotonic() < cutover+rollback_window:
                time.sleep(.05)
            with self.changed:
                retire = old if self.active == target else target
                deadline = time.monotonic()+120
                while self.inflight[retire] and time.monotonic() < deadline:
                    self.changed.wait(.2)
                if self.inflight[retire]:
                    record['state'] = 'DRAIN_TIMEOUT'
                    self.events.write(event='drain_timeout', model=retire)
                    return record
                # activation lock prevents another transition; new admission uses active only.
                self.previous = None
            self.backend.unload(self.config[retire]['name'])
            self.loaded.discard(retire)
            record['state'] = 'ROLLED_BACK' if self.active == old else 'COMPLETED'
            self.events.write(event='drained_unloaded', model=retire, transition=record)
            return record

    def rollback(self, failed, reason):
        with self.lock:
            if self.active == failed and self.previous and time.monotonic() <= self.rollback_until:
                self.active, self.previous = self.previous, None
                self.events.write(event='rollback', failed=failed, active=self.active, reason=reason)
                return True
        return False

    def lookup(self, request_id):
        with self.lock:
            row = self.db.execute('SELECT state,route,result FROM requests WHERE id=?', (request_id,)).fetchone()
            if row is None:
                return 404, {'error': 'unknown request'}
            state, route, result = row
            return (202 if state == 'PROCESSING' else 200), dict(request_id=request_id, state=state,
                    route=json.loads(route), result=json.loads(result) if result else None)

    def submit(self, payload):
        if payload.get('batch', 1) != 1:
            return 400, {'error': 'only batch 1 is supported'}
        request_id = payload.get('request_id')
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            return 400, {'error': 'request_id required (1–128 characters)'}
        try:
            raw = base64.b64decode(payload['image'], validate=True)
        except (ValueError, KeyError, TypeError):
            return 400, {'error': 'invalid image'}
        if not 0 < len(raw) <= 4*1024*1024:
            return 413, {'error': 'image byte limit'}
        # Raw content + business metadata identify retries. Resolved params are pinned once.
        fingerprint = hashlib.sha256(raw + json.dumps(payload.get('product_id'), sort_keys=True).encode()).hexdigest()
        with self.lock:
            row = self.db.execute('SELECT fingerprint FROM requests WHERE id=?', (request_id,)).fetchone()
            if row:
                if row[0] != fingerprint:
                    return 409, {'error': 'request ID payload conflict'}
                return self.lookup(request_id)
            if sum(self.inflight.values()) >= 8:
                return 429, {'error': 'bounded admission full; retry same ID'}
            key = self.active
            route = dict(key=key, model=self.config[key]['name'], version='1',
                         parameter_revision=self.revision, brightness=self.brightness,
                         side=self.config[key]['side'])
            self.db.execute('INSERT INTO requests VALUES(?,?,?,?,NULL)',
                            (request_id, fingerprint, 'PROCESSING', json.dumps(route)))
            self.db.commit()
            self.inflight[key] += 1
            self.pending[request_id] = route
        began = time.monotonic()
        self.events.write(event='admitted', request_id=request_id, route=route)
        try:
            with self.gpu:
                self.memory_admit()
                self.executing = request_id
                self.sample('before', request_id)
                dispatch = time.monotonic()
                self.events.write(event='inference_begin', request_id=request_id, route=route)
                try:
                    if hasattr(self.backend, 'request_context'):
                        self.backend.request_context.request_id = request_id
                    result = self.backend.infer(route['model'], raw, route['side'], route['brightness'])
                finally:
                    self.sample('after', request_id)
                    self.executing = None
                result.update(queue_ms=(dispatch-began)*1000, service_ms=(time.monotonic()-dispatch)*1000)
            state = 'COMPLETED'
        except Exception as exc:
            result, state = {'error': str(exc)}, 'FAILED'
            if 'out of memory' in str(exc).lower() or 'cuda oom' in str(exc).lower():
                with self.lock:
                    self.oom_count += 1
            self.rollback(key, 'real inference error: '+str(exc))
        with self.changed:
            self.db.execute('UPDATE requests SET state=?,result=? WHERE id=?',
                            (state, json.dumps(result), request_id))
            self.db.commit()
            self.inflight[key] -= 1
            self.pending.pop(request_id, None)
            self.changed.notify_all()
        self.events.write(event='inference_end', request_id=request_id, route=route, state=state, result=result)
        return self.lookup(request_id)

    def status(self):
        with self.lock:
            counts = dict(self.db.execute('SELECT state,count(*) FROM requests GROUP BY state').fetchall())
            return {'utc': utc(), 'active': self.active, 'parameter_revision': self.revision,
                    'brightness': self.brightness, 'inflight': dict(self.inflight),
                    'loaded': sorted(self.loaded), 'counts': counts, 'oom_count': self.oom_count,
                    'executing': self.executing, 'pending': dict(self.pending),
                    'switches': self.switches[-50:]}

    def readiness(self):
        """Admission health only; a successful inference remains the recovery proof."""
        with self.lock:
            if self.active not in self.loaded:
                return 503, {'ready': False, 'reason': 'active model not loaded'}
            if sum(self.inflight.values()) >= 8:
                return 503, {'ready': False, 'reason': 'admission full'}
        try:
            self.memory_admit()
        except Exception as exc:
            return 503, {'ready': False, 'reason': str(exc)}
        return 200, {'ready': True, 'scope': 'admission; not an inference probe'}

    def close(self):
        self.stop_sampler.set()
        self.sampler.join(timeout=4)
        self.db.close()
