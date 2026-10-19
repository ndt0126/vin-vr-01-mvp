"""Prometheus metrics cho Inspection API (W4-01), chi dung thu vien chuan.

Nguyen tac:
- Metric duoc cap nhat tu CHINH cac su kien trace (App.trace/audit goi Metrics.observe), nen so dem va log
  khong the lech nhau, va khong phai rai lenh dem khap ma nguon.
- Nhan (label) co so gia tri HUU HAN va biet truoc: state, reason, decision, code, operation, plane, status,
  model, action, outcome. KHONG BAO GIO dung request_id, product_id, trace_id, ten nguoi dung lam nhan.
- /metrics chay tren mot cong rieng (mac dinh 9090), khong can token, chi de Prometheus trong mang noi bo goi.
  No khong chua du lieu nghiep vu cua tung san pham.
"""
import os
import threading
import time

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30)

# ten -> (kieu, mo ta, cac nhan). Day la danh muc metric; docs/OBSERVABILITY.md sinh tu bang nay.
CATALOG = {
    'vr01_build_info': ('gauge', 'Luon bang 1; nhan cho biet phien ban hop dong API dang chay.', ('api_version',)),
    'vr01_process_start_time_seconds': ('gauge', 'Thoi diem tien trinh API khoi dong (Unix time). Doi gia tri = da restart.', ()),
    'vr01_process_resident_memory_bytes': ('gauge', 'RAM (RSS) cua tien trinh API.', ()),
    'vr01_process_cpu_seconds_total': ('counter', 'Tong thoi gian CPU cua tien trinh API.', ()),
    'vr01_ready': ('gauge', '1 neu readyz tra 200 (nhan request moi), 0 neu khong.', ()),
    'vr01_not_ready_reason': ('gauge', '1 cho moi ly do dang lam he thong chua san sang.', ('reason',)),
    'vr01_active_recipe_info': ('gauge', 'Luon bang 1; nhan cho biet recipe/model dang active va 12 ky tu dau digest.',
                                ('recipe', 'recipe_version', 'model', 'model_version', 'recipe_sha256', 'model_sha256')),
    'vr01_queue_depth': ('gauge', 'So request da nhan nhung chua ket thuc (dang cho + dang chay).', ()),
    'vr01_queue_capacity': ('gauge', 'Gioi han hang doi admission.', ()),
    'vr01_inflight_requests': ('gauge', 'So request chua ket thuc theo model da pin.', ('model',)),
    'vr01_storage_free_bytes': ('gauge', 'Dung luong trong cua o chua du lieu.', ()),
    'vr01_http_requests_total': ('counter', 'So HTTP request theo plane, operation va ma tra ve.', ('plane', 'operation', 'status')),
    'vr01_inspections_admitted_total': ('counter', 'So lan kiem da duoc nhan (ghi ben + pin model).', ('model',)),
    'vr01_inspections_rejected_total': ('counter', 'So lan gui bi tu choi TRUOC admission, theo ma loi.', ('code',)),
    'vr01_inspections_replayed_total': ('counter', 'So lan gui lai cung request_id (tra record cu, khong chay lai).', ()),
    'vr01_inspections_terminal_total': ('counter', 'So lan kiem da ket thuc theo trang thai va ly do.', ('state', 'reason')),
    'vr01_inspection_decisions_total': ('counter', 'So ket luan chat luong theo OK/NG/REVIEW.', ('decision',)),
    'vr01_inspections_cancelled_total': ('counter', 'So lan huy, theo viec da bat dau suy luan hay chua.', ('was_started',)),
    'vr01_late_results_discarded_total': ('counter', 'Ket qua ve muon bi bo (sau TIMEOUT hoac sau khi huy).', ('cause',)),
    'vr01_inference_seconds': ('histogram', 'Thoi gian suy luan tren inference server, theo model.', ('model',)),
    'vr01_queue_wait_seconds': ('histogram', 'Thoi gian cho trong hang doi truoc khi suy luan.', ()),
    'vr01_inspection_total_seconds': ('histogram', 'Thoi gian tu luc nhan toi luc ket thuc (COMPLETED).', ()),
    'vr01_model_load_total': ('counter', 'So lan nap model, theo ket qua.', ('model', 'result')),
    'vr01_model_unload_total': ('counter', 'So lan go model.', ('model',)),
    'vr01_model_restored_total': ('counter', 'So lan tu nap lai model active (inference server mat model).', ('model',)),
    'vr01_activations_total': ('counter', 'So lan chuyen recipe/rollback theo hanh dong va ket qua.', ('action', 'outcome')),
    'vr01_auto_rollback_total': ('counter', 'So lan tu rollback sau cutover, theo ket qua.', ('result',)),
    'vr01_auth_denied_total': ('counter', 'So request bi tu choi xac thuc/phan quyen.', ('outcome',)),
    'vr01_storage_errors_total': ('counter', 'So lan ghi ledger that bai.', ()),
    'vr01_stale_writes_ignored_total': ('counter', 'So lan ghi de trang thai ket thuc bi chan (compare-and-set).', ()),
}


def _esc(v):
    return str(v).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def _labels(names, values, extra=''):
    parts = [f'{n}="{_esc(v)}"' for n, v in zip(names, values)]
    if extra:
        parts.append(extra)
    return '{' + ','.join(parts) + '}' if parts else ''


class Metrics:
    def __init__(self, api_version='unknown'):
        self.lock = threading.Lock()
        self.start = time.time()
        self.api_version = api_version
        self.counters = {}    # (name, label values) -> value
        self.hist = {}        # (name, label values) -> [bucket counts..., sum, count]

    def inc(self, name, labels=(), n=1):
        with self.lock:
            key = (name, tuple(str(x) for x in labels))
            self.counters[key] = self.counters.get(key, 0) + n

    def observe_seconds(self, name, labels, seconds):
        if seconds is None:
            return
        with self.lock:
            key = (name, tuple(str(x) for x in labels))
            h = self.hist.setdefault(key, [0] * len(LATENCY_BUCKETS) + [0.0, 0])
            for i, b in enumerate(LATENCY_BUCKETS):
                if seconds <= b:
                    h[i] += 1
            h[-2] += seconds
            h[-1] += 1

    # ---------- anh xa su kien trace -> metric
    def observe(self, event, f):
        model = (f.get('model') or {}).get('name', 'unknown') if isinstance(f.get('model'), dict) else 'unknown'
        if event == 'http.access':
            self.inc('vr01_http_requests_total', (f.get('plane'), f.get('operation') or 'unmatched', f.get('status')))
        elif event == 'request.admitted':
            self.inc('vr01_inspections_admitted_total', (model,))
        elif event == 'request.rejected':
            self.inc('vr01_inspections_rejected_total', (f.get('code'),))
            if f.get('code') == 'STORAGE_UNAVAILABLE':
                self.inc('vr01_storage_errors_total')
        elif event == 'request.replayed':
            self.inc('vr01_inspections_replayed_total')
        elif event == 'request.terminal':
            self.inc('vr01_inspections_terminal_total', (f.get('state'), f.get('reason') or 'none'))
            if f.get('decision'):
                self.inc('vr01_inspection_decisions_total', (f['decision'],))
            if f.get('state') == 'COMPLETED' and f.get('total_ms') is not None:
                self.observe_seconds('vr01_inspection_total_seconds', (), f['total_ms'] / 1000)
        elif event == 'request.cancelled':
            self.inc('vr01_inspections_cancelled_total', (str(bool(f.get('was_started'))).lower(),))
        elif event == 'inference.started':
            if f.get('queue_ms') is not None:
                self.observe_seconds('vr01_queue_wait_seconds', (), f['queue_ms'] / 1000)
        elif event == 'inference.finished':
            if f.get('inference_ms') is not None:
                self.observe_seconds('vr01_inference_seconds', (model,), f['inference_ms'] / 1000)
        elif event == 'inference.late_result_ignored':
            self.inc('vr01_late_results_discarded_total', ('timeout',))
        elif event == 'inference.result_discarded_after_cancel':
            self.inc('vr01_late_results_discarded_total', ('cancelled',))
        elif event == 'request.persist_failed':
            self.inc('vr01_storage_errors_total')
        elif event == 'request.stale_write_ignored':
            self.inc('vr01_stale_writes_ignored_total')
        elif event == 'lifecycle.loaded':
            self.inc('vr01_model_load_total', (model, 'ok'))
        elif event == 'lifecycle.load_failed':
            self.inc('vr01_model_load_total', (model, 'failed'))
        elif event == 'lifecycle.unloaded' or event == 'lifecycle.candidate_unloaded':
            self.inc('vr01_model_unload_total', (model,))
        elif event == 'lifecycle.model_restored':
            self.inc('vr01_model_restored_total', (model,))
        elif event == 'lifecycle.auto_rollback':
            self.inc('vr01_auto_rollback_total', ('ok',))
        elif event == 'lifecycle.auto_rollback_failed':
            self.inc('vr01_auto_rollback_total', ('failed',))
        elif event == 'audit':
            action, outcome = f.get('action'), f.get('outcome')
            if action in ('activate', 'rollback', 'auto_rollback', 'bootstrap_activation', 'restore_active_recipe'):
                self.inc('vr01_activations_total', (action, outcome))
            elif outcome in ('UNAUTHENTICATED', 'FORBIDDEN'):
                self.inc('vr01_auth_denied_total', (outcome,))

    # ---------- xuat van ban Prometheus
    def render(self, gauges):
        """gauges: {(name, label values): value} tinh tai thoi diem scrape (do App cung cap)."""
        with self.lock:
            counters, hist = dict(self.counters), {k: list(v) for k, v in self.hist.items()}
        gauges = dict(gauges)
        gauges[('vr01_build_info', (self.api_version,))] = 1
        gauges[('vr01_process_start_time_seconds', ())] = round(self.start, 3)
        gauges[('vr01_process_resident_memory_bytes', ())] = _rss_bytes()
        t = os.times()
        counters[('vr01_process_cpu_seconds_total', ())] = round(t.user + t.system, 3)
        out = []
        for name, (kind, help_text, label_names) in CATALOG.items():
            series = []
            if kind == 'histogram':
                for (n, lv), h in sorted(hist.items()):
                    if n != name:
                        continue
                    for i, b in enumerate(LATENCY_BUCKETS):
                        le = 'le="%s"' % b  # khong long backslash trong f-string: chay duoc Python 3.10/3.11
                        series.append(f'{name}_bucket{_labels(label_names, lv, le)} {h[i]}')
                    le_inf = 'le="+Inf"'
                    series.append(f'{name}_bucket{_labels(label_names, lv, le_inf)} {h[-1]}')
                    series.append(f'{name}_sum{_labels(label_names, lv)} {round(h[-2], 6)}')
                    series.append(f'{name}_count{_labels(label_names, lv)} {h[-1]}')
            else:
                src = counters if kind == 'counter' else gauges
                for (n, lv), v in sorted(src.items()):
                    if n == name and v is not None:
                        series.append(f'{name}{_labels(label_names, lv)} {v}')
            out.append(f'# HELP {name} {help_text}')
            out.append(f'# TYPE {name} {kind}')
            out.extend(series)
        return '\n'.join(out) + '\n'


def _rss_bytes():
    try:
        with open('/proc/self/statm') as fh:
            return int(fh.read().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, IndexError):
        try:
            import resource
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return rss if os.uname().sysname == 'Darwin' else rss * 1024  # macOS: bytes (dinh), Linux: KiB
        except Exception:  # noqa: BLE001
            return None
