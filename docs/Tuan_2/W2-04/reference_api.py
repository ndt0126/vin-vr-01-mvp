"""W2-04 reference implementation of openapi.v1.yaml (lab only).

Muc dich: chung minh hop dong API chay duoc va test duoc (contract/negative/trace).
Day KHONG phai implementation production:
- backend mac dinh la stub tuyen tinh tren package W2-05 (khong phai model QC);
- auth lab = bearer token (server chi luu SHA-256), production thay bang mTLS/PKI;
- SQLite thay PostgreSQL (W2-02 ADR con mo).

Hai plane chay tren hai cong rieng; route cua plane nay khong ton tai o plane kia.
Request body duoc kiem bang chinh schema trong openapi.v1.yaml (nguon chuan duy nhat).
"""
import argparse
import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import queue
import re
import shutil
import sqlite3
import ssl
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import jsonschema
import yaml
from PIL import Image, UnidentifiedImageError

HERE = Path(__file__).resolve().parent
SPEC_PATH = HERE / 'openapi.v1.yaml'
TERMINAL = {'COMPLETED', 'FAILED', 'TIMEOUT', 'INDETERMINATE'}
TRACE_RE = re.compile(r'^[A-Za-z0-9-]{8,64}$')
Image.MAX_IMAGE_PIXELS = 4096 * 4096


def find_w205_root():
    """W2-05 validator/examples: ../ trong repo, hoac ../W2-05 trong goi ZIP."""
    for cand in (HERE.parent, HERE.parent / 'W2-05'):
        if (cand / 'validate_design.py').is_file() and (cand / 'examples').is_dir():
            return cand
    raise SystemExit('cannot find W2-05 validate_design.py/examples')


W205 = find_w205_root()
sys.path.insert(0, str(W205))
import validate_design  # noqa: E402  (W2-05 validator, khong sua)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


class ApiError(Exception):
    TITLES = {400: 'Invalid request', 401: 'Unauthenticated', 403: 'Forbidden', 404: 'Not found',
              405: 'Method not allowed', 408: 'Request timeout', 409: 'Conflict', 412: 'Precondition failed',
              413: 'Payload too large', 415: 'Unsupported media type', 422: 'Unprocessable content',
              429: 'Too many requests', 500: 'Internal error', 503: 'Service unavailable'}

    def __init__(self, status, code, detail, retryable=False, request_id=None, details=None, retry_after=None):
        super().__init__(f'{status} {code}: {detail}')
        self.status, self.code, self.detail = status, code, detail
        self.retryable, self.request_id, self.details = retryable, request_id, details
        self.retry_after = retry_after

    def body(self, trace_id):
        out = {'type': f'urn:vr01:problem:{self.code}', 'title': self.TITLES.get(self.status, 'Error'),
               'status': self.status, 'code': self.code, 'detail': self.detail, 'trace_id': trace_id,
               'request_id': self.request_id, 'retryable': self.retryable}
        if self.details is not None:
            out['details'] = self.details
        return out


# ---------------------------------------------------------------- spec

FORMATS = jsonschema.FormatChecker(formats=())


@FORMATS.checks('date-time', raises=ValueError)
def _is_datetime(value):
    """RFC 3339 date-time co mui gio (khong phu thuoc goi rfc3339-validator)."""
    if not isinstance(value, str):
        return True
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})', value):
        raise ValueError('not RFC 3339 date-time')
    datetime.fromisoformat(value)  # Python >= 3.11 doc duoc 'Z' va phan le giay
    return True


class Spec:
    def __init__(self, path=SPEC_PATH):
        self.doc = yaml.safe_load(path.read_text(encoding='utf-8'))
        self.limits = self.doc['info']['x-limits']

    def validator(self, name):
        schema = {'$ref': f'#/components/schemas/{name}', 'components': self.doc['components']}
        return jsonschema.Draft202012Validator(schema, format_checker=FORMATS)


# ---------------------------------------------------------------- registry (W2-05 packages/recipes)


class Registry:
    """Doc package/recipe W2-05 va kiem bang validator W2-05 (schema, checksum, I/O, golden)."""

    def __init__(self, examples=W205 / 'examples'):
        self.examples = Path(examples)
        self.config = validate_design.parse(validate_design.read(self.examples / 'site-config.json'))
        self.station_id = self.config['station_id']
        self.product_types = ['PCB1']
        self.packages = {}
        for manifest in sorted((self.examples / 'packages').glob('*/manifest.json')):
            raw = manifest.read_bytes()
            pkg = json.loads(raw)
            self.packages[(pkg['name'], pkg['version'])] = {'path': manifest, 'manifest': pkg, 'sha256': sha256(raw)}
        self.recipes = {}
        for path in sorted((self.examples / 'recipes').glob('*.json')):
            raw = path.read_bytes()
            r = json.loads(raw)
            self.recipes[(r['name'], r['version'])] = {'recipe': r, 'sha256': sha256(raw)}

    def validate_package(self, name, version):
        """Tra ve (model_ref, params, golden) hoac raise ApiError 404/422."""
        entry = self.packages.get((name, version))
        if entry is None:
            raise ApiError(404, 'NOT_FOUND', f'package {name}@{version} not found')
        try:
            pkg, digest, golden_score = validate_design.validate_package(entry['path'], self.config)
        except validate_design.Rejected as exc:
            raise ApiError(422, 'PACKAGE_REJECTED', str(exc), details={'validator_code': exc.code})
        params = json.loads((entry['path'].parent / pkg['artifact']['path']).read_bytes())
        golden_input = json.loads((entry['path'].parent / pkg['golden']['input']['path']).read_bytes())
        model = {'name': pkg['name'], 'version': pkg['version'], 'manifest_sha256': digest}
        golden = {'input': golden_input, 'expected': pkg['golden']['expected_score'],
                  'atol': pkg['golden']['atol'], 'rtol': pkg['golden']['rtol'], 'validator_score': golden_score}
        return model, params, golden

    def resolve_recipe(self, name, version):
        """Recipe + package da kiem; raise 422 neu recipe/package khong hop le."""
        entry = self.recipes.get((name, version))
        if entry is None:
            raise ApiError(422, 'RECIPE_NOT_FOUND', f'recipe {name}@{version} is not registered')
        r = entry['recipe']
        try:
            validate_design.validate_schema(r, 'recipe')
        except validate_design.Rejected as exc:
            raise ApiError(422, 'PACKAGE_REJECTED', f'recipe invalid: {exc}', details={'validator_code': exc.code})
        model, params, golden = self.validate_package(r['package']['name'], r['package']['version'])
        if model['manifest_sha256'] != r['package']['manifest_sha256']:
            raise ApiError(422, 'PACKAGE_REJECTED', 'recipe references a different package digest',
                           details={'validator_code': 'E_REFERENCE'})
        return {'recipe': {'name': r['name'], 'version': r['version'], 'sha256': entry['sha256']},
                'model': model, 'params': params, 'golden': golden,
                'threshold': r['decision']['threshold'],
                'rollback': (f"{r['rollback_recipe']['name']}@{r['rollback_recipe']['version']}"
                             if r['rollback_recipe'] else None)}


# ---------------------------------------------------------------- backends


def preprocess(image_bytes):
    """Fixture preprocess: anh -> xam -> 2x2 trung binh -> [0,1] (khop I/O IMAGE FP32 [1,1,2,2] cua W2-05)."""
    with Image.open(io.BytesIO(image_bytes)) as im:
        gray = im.convert('L').resize((2, 2), Image.Resampling.BOX)
        return [round(v / 255.0, 6) for v in gray.getdata()]


class StubBackend:
    """Backend tuyen tinh 'reference-linear-score-v1' cua W2-05 chay trong tien trinh."""

    name = 'stub-linear'

    def __init__(self):
        self.available = True
        self.delay_s = 0.0
        self.fail_next = 0
        self.calls = []

    def infer(self, model, params, tensor, trace_id, request_id):
        self.calls.append({'model': model['name'], 'trace_id': trace_id, 'request_id': request_id})
        if not self.available:
            raise RuntimeError('backend unavailable')
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail_next:
            self.fail_next -= 1
            raise RuntimeError('injected backend failure')
        return min(1.0, max(0.0, params['gain'] * sum(tensor) / len(tensor) + params['bias']))

    def health(self):
        return self.available


class KServeV2Backend:
    """Adapter goi inference server noi bo theo KServe v2 (giao thuc HTTP cua Triton).

    Chi business API goi URL nay; URL nam trong mang noi bo cluster, client khong biet toi.
    """

    name = 'kserve-v2'

    def __init__(self, base_url, timeout_s=10):
        self.base_url = base_url.rstrip('/')
        self.timeout_s = timeout_s

    def _call(self, method, path, body=None, headers=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base_url + path, data=data, method=method,
                                     headers={'Content-Type': 'application/json', **(headers or {})})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return resp.status, (json.loads(resp.read() or b'{}'))

    def infer(self, model, params, tensor, trace_id, request_id):
        body = {'id': request_id,
                'inputs': [{'name': 'IMAGE', 'shape': [1, 1, 2, 2], 'datatype': 'FP32', 'data': tensor}],
                'outputs': [{'name': 'SCORE'}]}
        status, out = self._call('POST', f"/v2/models/{model['name']}/infer", body, {'X-Trace-Id': trace_id})
        outputs = {o['name']: o for o in out.get('outputs', [])}
        if status != 200 or 'SCORE' not in outputs:
            raise RuntimeError(f'bad inference response {status}')
        return float(outputs['SCORE']['data'][0])

    def health(self):
        try:
            return self._call('GET', '/v2/health/ready')[0] == 200
        except (OSError, urllib.error.URLError, ValueError):
            return False


# ---------------------------------------------------------------- ledger


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS inspections (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  request_id TEXT UNIQUE NOT NULL,
  fingerprint TEXT NOT NULL,
  product_id TEXT NOT NULL, product_type TEXT NOT NULL, station_id TEXT NOT NULL,
  retry_of TEXT, submitted_by TEXT NOT NULL, trace_id TEXT NOT NULL,
  input_sha256 TEXT NOT NULL, pin_json TEXT NOT NULL,
  state TEXT NOT NULL, decision TEXT, reason TEXT, score REAL,
  received_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, updated_at TEXT NOT NULL,
  queue_ms REAL, inference_ms REAL, total_ms REAL
);
CREATE INDEX IF NOT EXISTS ix_product ON inspections(product_id, seq);
CREATE TABLE IF NOT EXISTS activations (
  activation_id INTEGER PRIMARY KEY AUTOINCREMENT,
  station_id TEXT NOT NULL, from_json TEXT, to_json TEXT NOT NULL, active_revision TEXT NOT NULL,
  golden_json TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, at TEXT NOT NULL, trace_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL,
  action TEXT NOT NULL, target TEXT NOT NULL, outcome TEXT NOT NULL, trace_id TEXT NOT NULL, details TEXT NOT NULL
);
"""


class Ledger:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript(SCHEMA_SQL)
        self.fail_writes = False  # fault hook cho test F9

    def write(self, sql, args=()):
        with self.lock:
            if self.fail_writes:
                raise sqlite3.OperationalError('disk I/O error (injected)')
            cur = self.db.execute(sql, args)
            return cur.lastrowid

    def one(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchone()

    def all(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def close(self):
        with self.lock:
            self.db.close()


# ---------------------------------------------------------------- application


class App:
    def __init__(self, data_dir, principals, backend=None, registry=None, spec=None, overrides=None,
                 default_recipe=('recipe-a', '0.1.0')):
        self.spec = spec or Spec()
        self.limits = dict(self.spec.limits, min_free_bytes=64 * 1024 * 1024, **(overrides or {}))
        self.registry = registry or Registry()
        self.backend = backend or StubBackend()
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = Ledger(self.data_dir / 'ledger.sqlite3')
        self.trace_path = self.data_dir / 'trace.jsonl'
        self.trace_lock = threading.Lock()
        self.principals = {p['token_sha256']: p for p in principals}
        self.submit_validator = self.spec.validator('InspectionSubmit')
        self.activation_validator = self.spec.validator('ActivationRequest')
        self.rollback_validator = self.spec.validator('RollbackRequest')
        self.package_ref_validator = self.spec.validator('PackageRef')
        self.queue = queue.Queue()
        self.pending = 0
        self.pending_lock = threading.Lock()
        self.transition_lock = threading.Lock()
        self.active_lock = threading.Lock()
        self.active = None
        self.not_ready = set()
        self.storage_unhealthy = False
        self.stopping = False
        self._recover(default_recipe)
        self.worker = threading.Thread(target=self._worker, name='inference-worker', daemon=True)
        self.worker.start()

    # ---------- logging / audit
    def trace(self, event, **fields):
        line = json.dumps({'at': now_iso(), 'event': event, **fields}, ensure_ascii=False, sort_keys=True)
        with self.trace_lock, open(self.trace_path, 'a', encoding='utf-8') as fh:
            fh.write(line + '\n')

    def audit(self, principal, action, target, outcome, trace_id, **details):
        actor = principal['id'] if principal else 'anonymous'
        role = principal['role'] if principal else 'none'
        try:
            self.ledger.write('INSERT INTO audit(at,actor,role,action,target,outcome,trace_id,details)'
                              ' VALUES(?,?,?,?,?,?,?,?)',
                              (now_iso(), actor, role, action, target, outcome, trace_id, json.dumps(details)))
        except sqlite3.Error:
            pass  # audit loi khong lam request khac fail; storage health xu ly rieng
        self.trace('audit', actor=actor, role=role, action=action, target=target, outcome=outcome,
                   trace_id=trace_id, **details)

    # ---------- startup recovery (F12, F13)
    def _recover(self, default_recipe):
        stuck = self.ledger.all("SELECT request_id, trace_id FROM inspections WHERE state IN ('RECEIVED','PROCESSING')")
        ts = now_iso()
        for row in stuck:
            self.ledger.write("UPDATE inspections SET state='INDETERMINATE', reason='RESTARTED_DURING_PROCESSING',"
                              " decision=NULL, finished_at=?, updated_at=? WHERE request_id=?",
                              (ts, ts, row['request_id']))
            self.trace('request.terminal', request_id=row['request_id'], trace_id=row['trace_id'],
                       state='INDETERMINATE', reason='RESTARTED_DURING_PROCESSING')
        station = self.registry.station_id
        last = self.ledger.one('SELECT * FROM activations WHERE station_id=? ORDER BY activation_id DESC LIMIT 1',
                               (station,))
        boot_trace = uuid.uuid4().hex
        system = {'id': 'system', 'role': 'system'}
        if last is None:
            name, version = default_recipe
            try:
                resolved = self.registry.resolve_recipe(name, version)
                golden = self._golden_check(resolved, boot_trace)
                if not golden['passed']:
                    raise ApiError(422, 'ACTIVATION_GOLDEN_FAILED', 'bootstrap golden failed')
                self._persist_activation(station, None, resolved, golden, system, 'bootstrap default recipe',
                                         boot_trace)
                self.active = resolved
                self.audit(system, 'bootstrap_activation', f'{station}:{name}@{version}', 'OK', boot_trace)
            except ApiError as exc:
                self.not_ready.add('ACTIVE_RECIPE_UNVERIFIED')
                self.audit(system, 'bootstrap_activation', station, 'FAILED', boot_trace, code=exc.code)
            return
        to = json.loads(last['to_json'])
        try:
            resolved = self.registry.resolve_recipe(to['name'], to['version'])
            if resolved['recipe']['sha256'] != to['sha256'] or last['active_revision'] != to['sha256']:
                raise ApiError(422, 'PACKAGE_REJECTED', 'persisted active recipe digest changed')
            golden = self._golden_check(resolved, boot_trace)
            if not golden['passed']:
                self.not_ready.add('WARMUP_FAILED')
            self.active = resolved
            self.audit(system, 'restore_active_recipe', f"{station}:{to['name']}@{to['version']}",
                       'OK' if golden['passed'] else 'WARMUP_FAILED', boot_trace)
        except ApiError as exc:
            # Khong tu doi sang recipe khac: dung nhan request cho toi khi admin xac nhan (F13).
            self.not_ready.add('ACTIVE_RECIPE_UNVERIFIED')
            self.audit(system, 'restore_active_recipe', station, 'UNVERIFIED', boot_trace, code=exc.code)

    def _persist_activation(self, station, previous, resolved, golden, principal, reason, trace_id):
        at = now_iso()
        aid = self.ledger.write(
            'INSERT INTO activations(station_id,from_json,to_json,active_revision,golden_json,actor,reason,at,trace_id)'
            ' VALUES(?,?,?,?,?,?,?,?,?)',
            (station, json.dumps(previous['recipe']) if previous else None, json.dumps(resolved['recipe']),
             resolved['recipe']['sha256'], json.dumps(golden), principal['id'], reason, at, trace_id))
        return aid

    def _golden_check(self, resolved, trace_id):
        g = resolved['golden']
        try:
            actual = self.backend.infer(resolved['model'], resolved['params'], g['input'], trace_id, 'golden')
        except Exception:  # noqa: BLE001 - backend loi = golden fail
            return {'expected': g['expected'], 'actual': None, 'passed': False}
        passed = abs(actual - g['expected']) <= g['atol'] + g['rtol'] * abs(g['expected'])
        return {'expected': g['expected'], 'actual': actual, 'passed': passed}

    # ---------- readiness
    def readiness(self):
        reasons = set(self.not_ready)
        if self.stopping:
            reasons.add('SHUTTING_DOWN')
        if not self.backend.health():
            reasons.add('BACKEND_UNAVAILABLE')
        if self.storage_unhealthy or self._free_bytes() < self.limits['min_free_bytes']:
            reasons.add('STORAGE_UNAVAILABLE')
        if self.active is None:
            reasons.add('ACTIVE_RECIPE_UNVERIFIED')
        return sorted(reasons)

    def _free_bytes(self):
        try:
            return shutil.disk_usage(self.data_dir).free
        except OSError:
            return 0

    # ---------- inspections
    def active_recipe_view(self, station_id):
        if station_id != self.registry.station_id:
            raise ApiError(404, 'NOT_FOUND', f'station {station_id} not found')
        with self.active_lock:
            act = self.active
        if act is None:
            raise ApiError(503, 'NOT_READY', 'ACTIVE_RECIPE_UNVERIFIED', retryable=True, retry_after=5)
        row = self.ledger.one('SELECT at FROM activations WHERE station_id=? ORDER BY activation_id DESC LIMIT 1',
                              (station_id,))
        return {'station_id': station_id,
                'recipe_version': f"{act['recipe']['name']}@{act['recipe']['version']}",
                'recipe': act['recipe'], 'model': act['model'], 'product_types': self.registry.product_types,
                'active_revision': act['recipe']['sha256'], 'activated_at': row['at'] if row else now_iso()}

    def submit(self, principal, body, trace_id):
        errors = sorted(self.submit_validator.iter_errors(body), key=lambda e: list(e.absolute_path))
        if errors:
            e = errors[0]
            path = '$' + ''.join(f'[{p}]' if isinstance(p, int) else f'.{p}' for p in e.absolute_path)
            rid = body.get('request_id') if isinstance(body, dict) and isinstance(body.get('request_id'), str) else None
            raise ApiError(400, 'INVALID_REQUEST', f'{path}: {e.message}'[:300], request_id=rid)
        rid = body['request_id']
        try:
            image = base64.b64decode(body['image']['data_base64'], validate=True)
        except (binascii.Error, ValueError):
            raise ApiError(400, 'INVALID_REQUEST', '$.image.data_base64: invalid base64', request_id=rid)
        if len(image) > self.limits['max_image_bytes']:
            raise ApiError(413, 'PAYLOAD_TOO_LARGE', f"image exceeds {self.limits['max_image_bytes']} bytes",
                           request_id=rid)
        tensor = self._decode(image, body['image']['content_type'], rid)
        input_sha = sha256(image)
        fp_fields = {k: body.get(k) for k in ('product_id', 'product_type', 'recipe_version', 'captured_at',
                                              'station_id', 'retry_of')}
        fingerprint = sha256(canonical({**fp_fields, 'content_type': body['image']['content_type'],
                                        'input_sha256': input_sha}))
        existing = self.ledger.one('SELECT * FROM inspections WHERE request_id=?', (rid,))
        if existing is not None:
            if existing['fingerprint'] != fingerprint:
                self.trace('request.rejected', request_id=rid, trace_id=trace_id, code='IDEMPOTENCY_CONFLICT')
                raise ApiError(409, 'IDEMPOTENCY_CONFLICT', 'request_id already used with a different payload',
                               request_id=rid)
            self.trace('request.replayed', request_id=rid, trace_id=trace_id, original_trace_id=existing['trace_id'])
            return 200, self.status_view(existing), {'Idempotent-Replay': 'true'}
        reasons = self.readiness()
        if reasons:
            code = 'STORAGE_UNAVAILABLE' if reasons == ['STORAGE_UNAVAILABLE'] else 'NOT_READY'
            self.trace('request.rejected', request_id=rid, trace_id=trace_id, code=code, reasons=reasons)
            raise ApiError(503, code, ','.join(reasons), retryable=True, request_id=rid, retry_after=5)
        if body['station_id'] != self.registry.station_id:
            raise ApiError(422, 'RECIPE_NOT_FOUND', f"station {body['station_id']} has no recipe", request_id=rid)
        if body['product_type'] not in self.registry.product_types:
            self.trace('request.rejected', request_id=rid, trace_id=trace_id, code='RECIPE_NOT_FOUND')
            raise ApiError(422, 'RECIPE_NOT_FOUND', f"no recipe for product_type {body['product_type']}",
                           request_id=rid)
        if body.get('retry_of'):
            prev = self.ledger.one('SELECT state, product_id FROM inspections WHERE request_id=?', (body['retry_of'],))
            if prev is None or prev['product_id'] != body['product_id'] or prev['state'] not in (
                    'FAILED', 'TIMEOUT', 'INDETERMINATE'):
                raise ApiError(400, 'INVALID_REQUEST',
                               'retry_of must reference a FAILED/TIMEOUT/INDETERMINATE request of the same product_id',
                               request_id=rid)
        with self.active_lock:
            pinned = self.active  # pin mot lan duy nhat luc admission (F16)
        active_ref = f"{pinned['recipe']['name']}@{pinned['recipe']['version']}"
        if body['recipe_version'] != active_ref:
            self.trace('request.rejected', request_id=rid, trace_id=trace_id, code='RECIPE_VERSION_MISMATCH')
            raise ApiError(409, 'RECIPE_VERSION_MISMATCH',
                           f"requested {body['recipe_version']} but {self.registry.station_id} has {active_ref} active",
                           request_id=rid, details={'active_recipe_version': active_ref})
        with self.pending_lock:
            if self.pending >= self.limits['queue_capacity']:
                self.trace('request.rejected', request_id=rid, trace_id=trace_id, code='QUEUE_FULL')
                raise ApiError(429, 'QUEUE_FULL', 'admission queue is full; retry with the same request_id',
                               retryable=True, request_id=rid, retry_after=1)
            self.pending += 1
        pin = {'recipe': pinned['recipe'], 'model': pinned['model'], 'threshold': pinned['threshold'],
               'review_band': self.limits['review_band']}
        ts = now_iso()
        try:
            self.ledger.write(
                'INSERT INTO inspections(request_id,fingerprint,product_id,product_type,station_id,retry_of,'
                'submitted_by,trace_id,input_sha256,pin_json,state,received_at,updated_at)'
                " VALUES(?,?,?,?,?,?,?,?,?,?,'RECEIVED',?,?)",
                (rid, fingerprint, body['product_id'], body['product_type'], body['station_id'], body.get('retry_of'),
                 principal['id'], trace_id, input_sha, json.dumps(pin), ts, ts))
        except sqlite3.IntegrityError:
            with self.pending_lock:
                self.pending -= 1
            return self.submit(principal, body, trace_id)  # dua song song cung ID -> xu ly nhu replay/conflict
        except sqlite3.Error as exc:
            with self.pending_lock:
                self.pending -= 1
            self.storage_unhealthy = True
            self.trace('request.rejected', request_id=rid, trace_id=trace_id, code='STORAGE_UNAVAILABLE',
                       error=str(exc))
            raise ApiError(503, 'STORAGE_UNAVAILABLE', 'ledger write failed; request not admitted',
                           retryable=True, request_id=rid, retry_after=5)
        self.trace('request.admitted', request_id=rid, trace_id=trace_id, product_id=body['product_id'],
                   station_id=body['station_id'], recipe=pin['recipe'], model=pin['model'],
                   input_sha256=input_sha, submitted_by=principal['id'])
        self.queue.put((rid, time.monotonic(), pinned['params'], tensor))
        row = self.ledger.one('SELECT * FROM inspections WHERE request_id=?', (rid,))
        return 202, self.status_view(row), {'Location': f'/v1/inspections/{rid}'}

    def _decode(self, image, content_type, rid):
        fmt = {'image/png': 'PNG', 'image/jpeg': 'JPEG'}[content_type]
        try:
            with Image.open(io.BytesIO(image)) as im:
                if im.format != fmt:
                    raise ApiError(422, 'IMAGE_UNDECODABLE', f'content is not a decodable {content_type}',
                                   request_id=rid)
                w, h = im.size
                if w > self.limits['max_image_width'] or h > self.limits['max_image_height']:
                    raise ApiError(422, 'IMAGE_TOO_LARGE_DIMENSIONS', f'{w}x{h} exceeds limit', request_id=rid)
                im.load()
            return preprocess(image)
        except ApiError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
            raise ApiError(422, 'IMAGE_UNDECODABLE', f'content is not a decodable {content_type}', request_id=rid)

    def _worker(self):
        while True:
            item = self.queue.get()
            if item is None:
                return
            rid, enq, params, tensor = item
            try:
                self._process(rid, enq, params, tensor)
            finally:
                with self.pending_lock:
                    self.pending -= 1

    def _finish(self, rid, trace_id, state, decision, reason, score, started, enq, inference_ms):
        ts = now_iso()
        total = (time.monotonic() - enq) * 1000
        try:
            self.ledger.write('UPDATE inspections SET state=?, decision=?, reason=?, score=?, finished_at=?,'
                              ' updated_at=?, inference_ms=?, total_ms=? WHERE request_id=?',
                              (state, decision, reason, score, ts, ts, inference_ms, total, rid))
        except sqlite3.Error as exc:
            # Khong tra ket qua chua ghi ben (F9): record giu PROCESSING, restart se thanh INDETERMINATE.
            self.storage_unhealthy = True
            self.trace('request.persist_failed', request_id=rid, trace_id=trace_id, error=str(exc))
            return
        self.trace('request.terminal', request_id=rid, trace_id=trace_id, state=state, decision=decision,
                   reason=reason, score=score)

    def _process(self, rid, enq, params, tensor):
        row = self.ledger.one('SELECT * FROM inspections WHERE request_id=?', (rid,))
        pin = json.loads(row['pin_json'])
        trace_id = row['trace_id']
        queue_ms = (time.monotonic() - enq) * 1000
        if queue_ms > self.limits['queue_timeout_s'] * 1000:
            self._finish(rid, trace_id, 'TIMEOUT', None, 'QUEUE_TIMEOUT', None, None, enq, None)
            return
        ts = now_iso()
        try:
            self.ledger.write("UPDATE inspections SET state='PROCESSING', started_at=?, updated_at=?, queue_ms=?"
                              ' WHERE request_id=?', (ts, ts, queue_ms, rid))
        except sqlite3.Error as exc:
            self.storage_unhealthy = True
            self.trace('request.persist_failed', request_id=rid, trace_id=trace_id, error=str(exc))
            return
        self.trace('inference.started', request_id=rid, trace_id=trace_id, model=pin['model'],
                   backend=self.backend.name)
        box = {}

        def run():
            try:
                box['score'] = self.backend.infer(pin['model'], params, tensor, trace_id, rid)
            except Exception as exc:  # noqa: BLE001
                box['error'] = f'{type(exc).__name__}: {exc}'

        t0 = time.monotonic()
        th = threading.Thread(target=run, daemon=True)
        th.start()
        th.join(self.limits['execution_timeout_s'])
        inference_ms = (time.monotonic() - t0) * 1000
        if th.is_alive():
            self._finish(rid, trace_id, 'TIMEOUT', None, 'EXECUTION_TIMEOUT', None, ts, enq, None)
            th.join()  # max_inflight=1: cho backend tra lai truoc khi lay request tiep; ket qua muon chi log
            self.trace('inference.late_result_ignored', request_id=rid, trace_id=trace_id,
                       late_score=box.get('score'), error=box.get('error'))
            return
        if 'error' in box:
            self.trace('inference.failed', request_id=rid, trace_id=trace_id, error=box['error'])
            self._finish(rid, trace_id, 'FAILED', None, 'BACKEND_ERROR', None, ts, enq, inference_ms)
            return
        score = round(box['score'], 6)
        thr, band = pin['threshold'], pin['review_band']
        if thr - band <= score < thr + band:
            decision = 'REVIEW'
        elif score >= thr:
            decision = 'NG'
        else:
            decision = 'OK'
        self.trace('inference.finished', request_id=rid, trace_id=trace_id, model=pin['model'], score=score)
        self._finish(rid, trace_id, 'COMPLETED', decision, None, score, ts, enq, inference_ms)

    def status_view(self, row):
        rid = row['request_id']
        return {'request_id': rid, 'state': row['state'], 'decision': row['decision'], 'reason': row['reason'],
                'product_id': row['product_id'], 'product_type': row['product_type'],
                'station_id': row['station_id'], 'retry_of': row['retry_of'],
                'received_at': row['received_at'], 'updated_at': row['updated_at'],
                'links': {'self': f'/v1/inspections/{rid}', 'result': f'/v1/inspections/{rid}/result'}}

    def result_view(self, row):
        pin = json.loads(row['pin_json'])
        return {'request_id': row['request_id'], 'state': row['state'], 'decision': row['decision'],
                'score': row['score'], 'threshold': pin['threshold'], 'review_band': pin['review_band'],
                'reason': row['reason'],
                'lineage': {'product_id': row['product_id'], 'product_type': row['product_type'],
                            'station_id': row['station_id'], 'recipe': pin['recipe'], 'model': pin['model'],
                            'input_sha256': row['input_sha256'], 'trace_id': row['trace_id'],
                            'submitted_by': row['submitted_by']},
                'timing_ms': {k: (None if row[c] is None else round(row[c], 3))
                              for k, c in (('queue', 'queue_ms'), ('inference', 'inference_ms'), ('total', 'total_ms'))},
                'received_at': row['received_at'], 'started_at': row['started_at'],
                'finished_at': row['finished_at']}

    def get_row(self, rid):
        row = self.ledger.one('SELECT * FROM inspections WHERE request_id=?', (rid,))
        if row is None:
            raise ApiError(404, 'NOT_FOUND', f'request {rid} not found', request_id=rid)
        return row

    def list_inspections(self, query):
        def single(name, default=None):
            vals = query.get(name)
            if vals is None:
                return default
            if len(vals) != 1:
                raise ApiError(400, 'INVALID_REQUEST', f'query {name} must appear once')
            return vals[0]

        unknown = set(query) - {'product_id', 'limit', 'cursor'}
        if unknown:
            raise ApiError(400, 'INVALID_REQUEST', f'unknown query parameter {sorted(unknown)[0]}')
        pid = single('product_id')
        if pid is None or not re.fullmatch(r'[A-Za-z0-9._-]{1,64}', pid):
            raise ApiError(400, 'INVALID_REQUEST', 'product_id is required and must match ^[A-Za-z0-9._-]{1,64}$')
        limit_s = single('limit', '20')
        cursor = single('cursor')
        if not re.fullmatch(r'[0-9]{1,3}', limit_s) or not 1 <= int(limit_s) <= self.limits['list_limit_max']:
            raise ApiError(400, 'INVALID_REQUEST', 'limit must be 1..100')
        if cursor is not None and not re.fullmatch(r'[0-9]{1,18}', cursor):
            raise ApiError(400, 'INVALID_REQUEST', 'cursor invalid')
        limit = int(limit_s)
        rows = self.ledger.all('SELECT * FROM inspections WHERE product_id=? AND seq < ? ORDER BY seq DESC LIMIT ?',
                               (pid, int(cursor) if cursor else 2 ** 62, limit + 1))
        nxt = str(rows[limit - 1]['seq']) if len(rows) > limit else None
        return {'items': [self.status_view(r) for r in rows[:limit]], 'next_cursor': nxt}

    # ---------- management
    def station_or_404(self, station_id):
        if station_id != self.registry.station_id:
            raise ApiError(404, 'NOT_FOUND', f'station {station_id} not found')

    def activation_view(self, row, changed=True):
        return {'activation_id': row['activation_id'], 'station_id': row['station_id'], 'changed': changed,
                'from_recipe': json.loads(row['from_json']) if row['from_json'] else None,
                'to_recipe': json.loads(row['to_json']), 'active_revision': row['active_revision'],
                'golden': json.loads(row['golden_json']), 'actor': row['actor'], 'reason': row['reason'],
                'at': row['at'], 'trace_id': row['trace_id']}

    def activate(self, principal, station_id, name, version, reason, if_match, trace_id, action='activate'):
        self.station_or_404(station_id)
        target = f'{station_id}:{name}@{version}'
        if not self.transition_lock.acquire(blocking=False):
            self.audit(principal, action, target, 'TRANSITION_BUSY', trace_id)
            raise ApiError(409, 'TRANSITION_BUSY', 'another activation/rollback is in progress', retryable=True)
        try:
            with self.active_lock:
                current = self.active
            if if_match is not None and (current is None or if_match != current['recipe']['sha256']):
                self.audit(principal, action, target, 'PRECONDITION_FAILED', trace_id)
                raise ApiError(412, 'PRECONDITION_FAILED', 'If-Match does not equal current active_revision')
            try:
                resolved = self.registry.resolve_recipe(name, version)
            except ApiError as exc:
                self.audit(principal, action, target, exc.code, trace_id)
                raise
            if current is not None and current['recipe']['sha256'] == resolved['recipe']['sha256'] \
                    and not self.not_ready & {'ACTIVE_RECIPE_UNVERIFIED', 'WARMUP_FAILED'}:
                row = self.ledger.one('SELECT * FROM activations WHERE station_id=? ORDER BY activation_id DESC'
                                      ' LIMIT 1', (station_id,))
                self.audit(principal, action, target, 'NO_CHANGE', trace_id)
                return self.activation_view(row, changed=False)
            golden = self._golden_check(resolved, trace_id)
            if not golden['passed']:
                self.audit(principal, action, target, 'ACTIVATION_GOLDEN_FAILED', trace_id, golden=golden)
                raise ApiError(422, 'ACTIVATION_GOLDEN_FAILED', 'warm-up/golden check failed; previous recipe kept',
                               details={'golden': golden})
            try:
                aid = self._persist_activation(station_id, current, resolved, golden, principal, reason, trace_id)
            except sqlite3.Error:
                self.storage_unhealthy = True
                self.audit(principal, action, target, 'STORAGE_UNAVAILABLE', trace_id)
                raise ApiError(503, 'STORAGE_UNAVAILABLE', 'activation not persisted; previous recipe kept',
                               retryable=True, retry_after=5)
            with self.active_lock:
                self.active = resolved  # chi request moi dung recipe moi; request cu giu pin (F16)
            self.not_ready -= {'ACTIVE_RECIPE_UNVERIFIED', 'WARMUP_FAILED'}
            self.trace('activation.committed', trace_id=trace_id, station_id=station_id,
                       from_recipe=current['recipe'] if current else None, to_recipe=resolved['recipe'],
                       model=resolved['model'], actor=principal['id'])
            self.audit(principal, action, target, 'OK', trace_id, activation_id=aid)
            row = self.ledger.one('SELECT * FROM activations WHERE activation_id=?', (aid,))
            return self.activation_view(row)
        finally:
            self.transition_lock.release()

    def rollback(self, principal, station_id, reason, trace_id):
        self.station_or_404(station_id)
        rows = self.ledger.all('SELECT to_json FROM activations WHERE station_id=? ORDER BY activation_id DESC',
                               (station_id,))
        current_sha = self.active['recipe']['sha256'] if self.active else None
        for r in rows:
            to = json.loads(r['to_json'])
            if to['sha256'] != current_sha:
                return self.activate(principal, station_id, to['name'], to['version'], reason, None, trace_id,
                                     action='rollback')
        self.audit(principal, 'rollback', station_id, 'NO_ROLLBACK_TARGET', trace_id)
        raise ApiError(409, 'NO_ROLLBACK_TARGET', 'no previous recipe in activation history')

    def station_detail(self, station_id):
        self.station_or_404(station_id)
        rows = self.ledger.all('SELECT * FROM activations WHERE station_id=? ORDER BY activation_id DESC LIMIT 50',
                               (station_id,))
        return {'station_id': station_id, 'active': self.active_recipe_view(station_id),
                'history': [self.activation_view(r) for r in rows]}

    def list_recipes(self):
        items = []
        for (name, version) in sorted(self.registry.recipes):
            entry = self.registry.recipes[(name, version)]
            r = entry['recipe']
            pkg = self.registry.packages.get((r['package']['name'], r['package']['version']))
            items.append({'recipe': {'name': name, 'version': version, 'sha256': entry['sha256']},
                          'model': {'name': r['package']['name'], 'version': r['package']['version'],
                                    'manifest_sha256': pkg['sha256'] if pkg else r['package']['manifest_sha256']},
                          'threshold': r['decision']['threshold'],
                          'active': bool(self.active and self.active['recipe']['sha256'] == entry['sha256']),
                          'rollback_recipe': (f"{r['rollback_recipe']['name']}@{r['rollback_recipe']['version']}"
                                              if r['rollback_recipe'] else None)})
        return {'items': items}

    def list_packages(self):
        items = []
        for (name, version), entry in sorted(self.registry.packages.items()):
            m = entry['manifest']
            items.append({'name': name, 'version': version, 'manifest_sha256': entry['sha256'],
                          'backend': m['runtime']['backend'], 'device': m['runtime']['device'],
                          'purpose': m['purpose']})
        return {'items': items}

    def validate_package(self, principal, body, trace_id):
        model, _, golden = self.registry.validate_package(body['package_name'], body['package_version'])
        self.audit(principal, 'validate_package', f"{model['name']}@{model['version']}", 'PASS', trace_id)
        return {'package': model, 'outcome': 'PASS', 'golden_score': golden['validator_score']}

    def list_audit(self, query):
        unknown = set(query) - {'limit'}
        if unknown:
            raise ApiError(400, 'INVALID_REQUEST', f'unknown query parameter {sorted(unknown)[0]}')
        vals = query.get('limit', ['50'])
        if len(vals) != 1 or not re.fullmatch(r'[0-9]{1,3}', vals[0]) or not 1 <= int(vals[0]) <= 100:
            raise ApiError(400, 'INVALID_REQUEST', 'limit must be 1..100')
        rows = self.ledger.all('SELECT * FROM audit ORDER BY seq DESC LIMIT ?', (int(vals[0]),))
        return {'items': [{'seq': r['seq'], 'at': r['at'], 'actor': r['actor'], 'role': r['role'],
                           'action': r['action'], 'target': r['target'], 'outcome': r['outcome'],
                           'trace_id': r['trace_id'], 'details': json.loads(r['details'])} for r in rows]}

    def wait_idle(self, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.pending_lock:
                if self.pending == 0:
                    return True
            time.sleep(0.01)
        return False

    def close(self):
        self.stopping = True
        self.queue.put(None)
        self.worker.join(timeout=15)
        self.ledger.close()


# ---------------------------------------------------------------- HTTP layer

ANON = None
INFERENCE_ROUTES = [
    ('GET', r'/healthz', 'getLiveness', ANON),
    ('GET', r'/readyz', 'getReadiness', ANON),
    ('POST', r'/v1/inspections', 'submitInspection', {'operator'}),
    ('GET', r'/v1/inspections', 'listInspections', {'viewer', 'operator', 'admin'}),
    ('GET', r'/v1/inspections/(?P<request_id>[A-Za-z0-9._:-]{1,128})', 'getInspectionStatus',
     {'viewer', 'operator', 'admin'}),
    ('GET', r'/v1/inspections/(?P<request_id>[A-Za-z0-9._:-]{1,128})/result', 'getInspectionResult',
     {'viewer', 'operator', 'admin'}),
    ('GET', r'/v1/stations/(?P<station_id>[a-z][a-z0-9-]{0,63})/active-recipe', 'getActiveRecipe',
     {'viewer', 'operator', 'admin'}),
]
MANAGEMENT_ROUTES = [
    ('GET', r'/healthz', 'getLiveness', ANON),
    ('GET', r'/readyz', 'getReadiness', ANON),
    ('GET', r'/v1/admin/packages', 'listPackages', {'admin'}),
    ('POST', r'/v1/admin/packages/validate', 'validatePackage', {'admin'}),
    ('GET', r'/v1/admin/recipes', 'listRecipes', {'admin'}),
    ('GET', r'/v1/admin/stations/(?P<station_id>[a-z][a-z0-9-]{0,63})', 'getStation', {'admin'}),
    ('POST', r'/v1/admin/stations/(?P<station_id>[a-z][a-z0-9-]{0,63})/activation', 'activateRecipe', {'admin'}),
    ('POST', r'/v1/admin/stations/(?P<station_id>[a-z][a-z0-9-]{0,63})/rollback', 'rollbackRecipe', {'admin'}),
    ('GET', r'/v1/admin/audit', 'listAudit', {'admin'}),
]
JSON_BODY_OPS = {'submitInspection', 'validatePackage', 'activateRecipe', 'rollbackRecipe'}


def make_handler(app, plane, routes):
    compiled = [(m, re.compile('^' + p + '$'), op, roles) for m, p, op, roles in routes]

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'
        server_version = 'vr01-business-api/1.0'
        sys_version = ''
        timeout = app.limits['body_read_timeout_s']

        def log_message(self, fmt, *args):  # access log vao trace, khong in stderr
            pass

        def _send(self, status, body, trace_id, headers=None, problem=False, close=False):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/problem+json' if problem else 'application/json')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('X-Trace-Id', trace_id)
            self.send_header('Cache-Control', 'no-store')
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            if close:
                self.send_header('Connection', 'close')
                self.close_connection = True
            try:
                self.end_headers()
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                # Client mat ket noi truoc khi nhan response; ket qua van nam trong ledger (F14).
                self.close_connection = True
                app.trace('http.client_disconnected', plane=plane, status=status, trace_id=trace_id)

        def _route(self, method, path):
            path_ok = False
            for m, rx, op, roles in compiled:
                match = rx.match(path)
                if match:
                    path_ok = True
                    if m == method:
                        return op, roles, match.groupdict()
            if path_ok:
                raise ApiError(405, 'METHOD_NOT_ALLOWED', f'{method} not allowed on {path}')
            raise ApiError(404, 'NOT_FOUND', f'no route {path} on {plane} plane')

        def _auth(self, op, roles, trace_id):
            if roles is ANON:
                return None
            header = self.headers.get('Authorization', '')
            principal = None
            if header.startswith('Bearer ') and len(header) < 512:
                digest = sha256(header[7:].strip().encode())
                for known, p in app.principals.items():
                    if hmac.compare_digest(known, digest):
                        principal = p
            if principal is None:
                app.audit(None, 'auth', f'{plane}:{op}', 'UNAUTHENTICATED', trace_id)
                raise ApiError(401, 'UNAUTHENTICATED', 'missing or invalid bearer token')
            if principal['role'] not in roles:
                app.audit(principal, 'authorize', f'{plane}:{op}', 'FORBIDDEN', trace_id)
                raise ApiError(403, 'FORBIDDEN', f"role {principal['role']} is not allowed to call {op}")
            return principal

        def _read_json(self):
            ctype = self.headers.get('Content-Type', '').split(';')[0].strip().lower()
            if ctype != 'application/json':
                raise ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Content-Type must be application/json')
            if self.headers.get('Transfer-Encoding'):
                raise ApiError(400, 'INVALID_REQUEST', 'chunked bodies are not supported; send Content-Length')
            length_s = self.headers.get('Content-Length')
            if length_s is None or not length_s.isdigit():
                raise ApiError(400, 'INVALID_REQUEST', 'Content-Length required')
            length = int(length_s)
            if length > app.limits['max_body_bytes']:
                raise ApiError(413, 'PAYLOAD_TOO_LARGE', f"body exceeds {app.limits['max_body_bytes']} bytes")
            try:
                raw = self.rfile.read(length)
            except (TimeoutError, OSError):
                raise ApiError(408, 'REQUEST_TIMEOUT', 'request body not received within body_read_timeout_s')
            if len(raw) != length:
                raise ApiError(408, 'REQUEST_TIMEOUT', 'request body incomplete')
            try:
                return json.loads(raw.decode('utf-8'), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
            except (UnicodeDecodeError, ValueError):
                raise ApiError(400, 'INVALID_REQUEST', 'body is not valid UTF-8 JSON')

        def _dispatch(self, method):
            trace_id = self.headers.get('X-Trace-Id', '')
            if not TRACE_RE.match(trace_id):
                trace_id = uuid.uuid4().hex
            body_read = method == 'GET'
            try:
                url = urlsplit(self.path)
                op, roles, params = self._route(method, url.path)
                principal = self._auth(op, roles, trace_id)
                body = None
                if op in JSON_BODY_OPS:
                    body = self._read_json()
                    body_read = True
                status, payload, headers = self._handle(op, params, parse_qs(url.query, keep_blank_values=True),
                                                        body, principal, trace_id)
                problem = False
            except ApiError as exc:
                status, payload, problem = exc.status, exc.body(trace_id), True
                headers = {'Retry-After': str(exc.retry_after)} if exc.retry_after else {}
            except Exception as exc:  # noqa: BLE001
                app.trace('http.internal_error', trace_id=trace_id, error=f'{type(exc).__name__}: {exc}')
                status, payload, problem, headers = 500, ApiError(500, 'INTERNAL_ERROR', 'internal error').body(
                    trace_id), True, {}
            app.trace('http.access', plane=plane, method=method, path=urlsplit(self.path).path, status=status,
                      trace_id=trace_id)
            self._send(status, payload, trace_id, headers, problem, close=not body_read)

        def _handle(self, op, p, q, body, principal, trace_id):
            if op == 'getLiveness':
                return 200, {'status': 'alive'}, {}
            if op == 'getReadiness':
                reasons = app.readiness()
                return (503 if reasons else 200), {'ready': not reasons, 'reasons': reasons}, {}
            if op == 'submitInspection':
                return app.submit(principal, body, trace_id)
            if op == 'listInspections':
                return 200, app.list_inspections(q), {}
            if op == 'getInspectionStatus':
                return 200, app.status_view(app.get_row(p['request_id'])), {}
            if op == 'getInspectionResult':
                row = app.get_row(p['request_id'])
                if row['state'] not in TERMINAL:
                    raise ApiError(409, 'RESULT_NOT_READY', f"request is {row['state']}", retryable=True,
                                   request_id=row['request_id'], retry_after=1)
                return 200, app.result_view(row), {}
            if op == 'getActiveRecipe':
                return 200, app.active_recipe_view(p['station_id']), {}
            if op == 'listPackages':
                return 200, app.list_packages(), {}
            if op == 'validatePackage':
                self._check(app.package_ref_validator, body)
                return 200, app.validate_package(principal, body, trace_id), {}
            if op == 'listRecipes':
                return 200, app.list_recipes(), {}
            if op == 'getStation':
                return 200, app.station_detail(p['station_id']), {}
            if op == 'activateRecipe':
                self._check(app.activation_validator, body)
                if_match = self.headers.get('If-Match')
                if if_match is not None:
                    if_match = if_match.strip().strip('"')
                    if not re.fullmatch(r'[a-f0-9]{64}', if_match):
                        raise ApiError(400, 'INVALID_REQUEST', 'If-Match must be a sha256 active_revision')
                return 200, app.activate(principal, p['station_id'], body['recipe_name'], body['recipe_version'],
                                         body['reason'], if_match, trace_id), {}
            if op == 'rollbackRecipe':
                self._check(app.rollback_validator, body)
                return 200, app.rollback(principal, p['station_id'], body['reason'], trace_id), {}
            if op == 'listAudit':
                return 200, app.list_audit(q), {}
            raise ApiError(404, 'NOT_FOUND', op)

        @staticmethod
        def _check(validator, body):
            err = next(iter(sorted(validator.iter_errors(body), key=lambda e: list(e.absolute_path))), None)
            if err is not None:
                path = '$' + ''.join(f'.{x}' for x in err.absolute_path)
                raise ApiError(400, 'INVALID_REQUEST', f'{path}: {err.message}'[:300])

        def do_GET(self):
            self._dispatch('GET')

        def do_POST(self):
            self._dispatch('POST')

        def do_PUT(self):
            self._dispatch('PUT')

        def do_DELETE(self):
            self._dispatch('DELETE')

        def do_PATCH(self):
            self._dispatch('PATCH')

    return Handler


class _HTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    app = None
    plane = None

    def handle_error(self, request, client_address):
        # Ket noi hong/TLS handshake sai (vd client gui HTTP thuong vao cong HTTPS): ghi trace, khong in traceback.
        exc = sys.exc_info()[1]
        if self.app is not None:
            self.app.trace('http.connection_error', plane=self.plane, error=f'{type(exc).__name__}: {exc}'[:200])


class Server:
    """Hai listener: inference va management. Port 0 = cong ngau nhien (test)."""

    def __init__(self, app, host='127.0.0.1', inference_port=8443, management_port=9443, tls=None):
        self.app = app
        self.httpd = {}
        for plane, port, routes in (('inference', inference_port, INFERENCE_ROUTES),
                                    ('management', management_port, MANAGEMENT_ROUTES)):
            srv = _HTTPServer((host, port), make_handler(app, plane, routes))
            srv.app, srv.plane = app, plane
            if tls:
                ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2
                ctx.load_cert_chain(tls['cert'], tls['key'])
                srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
            self.httpd[plane] = srv
        self.threads = [threading.Thread(target=s.serve_forever, daemon=True, kwargs={'poll_interval': 0.05})
                        for s in self.httpd.values()]
        for t in self.threads:
            t.start()

    def port(self, plane):
        return self.httpd[plane].server_address[1]

    def close(self):
        for s in self.httpd.values():
            s.shutdown()
            s.server_close()
        self.app.close()


def load_principals(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    out = []
    for p in data['principals']:
        if p['role'] not in ('viewer', 'operator', 'admin') or not re.fullmatch(r'[a-f0-9]{64}', p['token_sha256']):
            raise SystemExit(f'invalid principal entry {p.get("id")}')
        out.append(p)
    return out


def init_lab_principals(directory):
    """Tao token lab: file token (mode 600, KHONG dua vao evidence) + file principals chi chua SHA-256."""
    import secrets
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    tokens, principals = {}, []
    for pid, role in (('qc-ui-01', 'viewer'), ('cam-sim-01', 'operator'), ('ops-admin-01', 'admin')):
        tok = secrets.token_urlsafe(32)
        tokens[pid] = {'role': role, 'token': tok}
        principals.append({'id': pid, 'role': role, 'token_sha256': sha256(tok.encode())})
    tok_path = d / 'lab-tokens.secret.json'
    fd = os.open(tok_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as fh:
        json.dump(tokens, fh, indent=2)
    (d / 'principals.json').write_text(json.dumps({'principals': principals}, indent=2), encoding='utf-8')
    return tok_path, d / 'principals.json'


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--data-dir', default='./run-data')
    ap.add_argument('--principals', help='principals.json (token_sha256 + role)')
    ap.add_argument('--init-lab-principals', metavar='DIR', help='tao token lab roi thoat')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--inference-port', type=int, default=8443)
    ap.add_argument('--management-port', type=int, default=9443)
    ap.add_argument('--tls-cert')
    ap.add_argument('--tls-key')
    ap.add_argument('--kserve-url', help='URL noi bo cua inference server KServe v2/Triton; bo trong = stub')
    args = ap.parse_args()
    if args.init_lab_principals:
        tok, pr = init_lab_principals(args.init_lab_principals)
        print(json.dumps({'tokens_file': str(tok), 'principals_file': str(pr)}))
        return
    if not args.principals:
        ap.error('--principals is required')
    backend = KServeV2Backend(args.kserve_url) if args.kserve_url else StubBackend()
    app = App(args.data_dir, load_principals(args.principals), backend=backend)
    tls = {'cert': args.tls_cert, 'key': args.tls_key} if args.tls_cert else None
    srv = Server(app, args.host, args.inference_port, args.management_port, tls)
    print(json.dumps({'inference_port': srv.port('inference'), 'management_port': srv.port('management'),
                      'tls': bool(tls), 'backend': backend.name}), flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        srv.close()


if __name__ == '__main__':
    main()
