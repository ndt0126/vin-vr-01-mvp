"""Sinh dashboard Grafana (JSON) cho VR-01 MVP.  Usage: python3 tools/gen_dashboard.py [--check]"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / 'deploy' / 'observability' / 'grafana' / 'dashboards' / 'vr01-overview.json'
DS = {'type': 'prometheus', 'uid': 'vr01-prom'}


def panel(pid, title, kind, x, y, w, h, targets, unit=None, desc=None, **opts):
    p = {'id': pid, 'title': title, 'type': kind, 'datasource': DS, 'gridPos': {'x': x, 'y': y, 'w': w, 'h': h},
         'targets': [{'refId': chr(65 + i), 'expr': e, 'legendFormat': leg, 'datasource': DS,
                      **({'instant': True, 'range': False} if kind == 'stat' else {})}  # stat: chi gia tri HIEN TAI
                     for i, (e, leg) in enumerate(targets)],
         'fieldConfig': {'defaults': {}, 'overrides': []}, 'options': opts.pop('options', {})}
    if unit:
        p['fieldConfig']['defaults']['unit'] = unit
    if desc:
        p['description'] = desc
    p['fieldConfig']['defaults'].update(opts)
    return p


def build():
    P = []
    ready_map = [{'type': 'value', 'options': {'0': {'text': 'CHƯA SẴN SÀNG', 'color': 'red'},
                                                '1': {'text': 'SẴN SÀNG', 'color': 'green'}}}]
    P.append(panel(1, 'Trạng thái hệ thống', 'stat', 0, 0, 5, 4, [('vr01_ready', '')], mappings=ready_map,
                   desc='readyz: 1 = nhận ảnh mới; 0 = không nhận (sản phẩm lúc này chưa được kiểm)'))
    P.append(panel(2, 'Recipe / model đang active', 'stat', 5, 0, 9, 4,
                   [('vr01_active_recipe_info', '{{recipe}}@{{recipe_version}} · {{model}} · {{model_sha256}}')],
                   options={'textMode': 'name', 'colorMode': 'none'}))
    P.append(panel(3, 'Lý do chưa sẵn sàng', 'stat', 14, 0, 5, 4, [('vr01_not_ready_reason == 1', '{{reason}}')],
                   options={'textMode': 'name', 'colorMode': 'background'}, noValue='không có'))
    P.append(panel(4, 'Cảnh báo đang bật', 'stat', 19, 0, 5, 4, [('count(ALERTS{alertstate="firing"}) or vector(0)', '')],
                   thresholds={'mode': 'absolute', 'steps': [{'color': 'green', 'value': None}, {'color': 'red', 'value': 1}]}))
    P.append(panel(5, 'Lần kiểm kết thúc mỗi giây, theo trạng thái', 'timeseries', 0, 4, 12, 7,
                   [('sum by (state) (rate(vr01_inspections_terminal_total[1m]))', '{{state}}')], unit='reqps'))
    P.append(panel(6, 'Kết luận chất lượng mỗi giây (OK / NG / REVIEW)', 'timeseries', 12, 4, 12, 7,
                   [('sum by (decision) (rate(vr01_inspection_decisions_total[1m]))', '{{decision}}')], unit='reqps'))
    P.append(panel(7, 'Thời gian một lần kiểm (nhận → kết thúc)', 'timeseries', 0, 11, 12, 7,
                   [('histogram_quantile(0.5, sum by (le) (rate(vr01_inspection_total_seconds_bucket[1m])))', 'p50'),
                    ('histogram_quantile(0.95, sum by (le) (rate(vr01_inspection_total_seconds_bucket[1m])))', 'p95'),
                    ('histogram_quantile(0.99, sum by (le) (rate(vr01_inspection_total_seconds_bucket[1m])))', 'p99')], unit='s'))
    P.append(panel(8, 'Thời gian suy luận p95 theo model', 'timeseries', 12, 11, 12, 7,
                   [('histogram_quantile(0.95, sum by (le, model) (rate(vr01_inference_seconds_bucket[1m])))', '{{model}}'),
                    ('histogram_quantile(0.95, sum by (le) (rate(vr01_queue_wait_seconds_bucket[1m])))', 'chờ hàng đợi')], unit='s'))
    P.append(panel(9, 'Hàng đợi', 'timeseries', 0, 18, 8, 6,
                   [('vr01_queue_depth', 'đang chờ + đang chạy'), ('vr01_queue_capacity', 'giới hạn')]))
    P.append(panel(10, 'Bị từ chối trước admission, theo mã lỗi', 'timeseries', 8, 18, 8, 6,
                   [('sum by (code) (rate(vr01_inspections_rejected_total[1m]))', '{{code}}')], unit='reqps'))
    P.append(panel(11, 'HTTP theo mã trả về', 'timeseries', 16, 18, 8, 6,
                   [('sum by (status) (rate(vr01_http_requests_total[1m]))', '{{status}}')], unit='reqps'))
    P.append(panel(12, 'Vòng đời model (số sự kiện trong 5 phút)', 'timeseries', 0, 24, 12, 6,
                   [('sum by (model, result) (increase(vr01_model_load_total[5m]))', 'nạp {{model}} {{result}}'),
                    ('sum by (model) (increase(vr01_model_unload_total[5m]))', 'gỡ {{model}}'),
                    ('sum by (action, outcome) (increase(vr01_activations_total[5m]))', '{{action}} {{outcome}}'),
                    ('sum(increase(vr01_auto_rollback_total[5m]))', 'tự rollback'),
                    ('sum by (model) (increase(vr01_model_restored_total[5m]))', 'tự nạp lại {{model}}')]))
    P.append(panel(13, 'Hủy và kết quả về muộn bị bỏ (5 phút)', 'timeseries', 12, 24, 12, 6,
                   [('sum by (was_started) (increase(vr01_inspections_cancelled_total[5m]))', 'hủy, đã chạy={{was_started}}'),
                    ('sum by (cause) (increase(vr01_late_results_discarded_total[5m]))', 'kết quả muộn bị bỏ: {{cause}}')]))
    P.append(panel(14, 'API: RAM và CPU', 'timeseries', 0, 30, 8, 6,
                   [('vr01_process_resident_memory_bytes', 'RSS'), ], unit='bytes'))
    P.append(panel(15, 'API: CPU (lõi)', 'timeseries', 8, 30, 8, 6, [('rate(vr01_process_cpu_seconds_total[1m])', 'CPU')]))
    P.append(panel(16, 'Ổ dữ liệu còn trống', 'timeseries', 16, 30, 8, 6, [('vr01_storage_free_bytes', 'trống')], unit='bytes'))
    P.append(panel(17, 'Triton: request thành công / lỗi mỗi giây, theo model', 'timeseries', 0, 36, 12, 6,
                   [('sum by (model) (rate(nv_inference_request_success[1m]))', '{{model}} ok'),
                    ('sum by (model) (rate(nv_inference_request_failure[1m]))', '{{model}} lỗi')], unit='reqps'))
    P.append(panel(18, 'Triton: CPU, RAM, GPU', 'timeseries', 12, 36, 12, 6,
                   [('nv_cpu_utilization', 'CPU (0-1)'), ('nv_cpu_memory_used_bytes / nv_cpu_memory_total_bytes', 'RAM (0-1)'),
                    ('nv_gpu_utilization', 'GPU {{gpu_uuid}} (0-1)'),
                    ('nv_gpu_memory_used_bytes / nv_gpu_memory_total_bytes', 'VRAM {{gpu_uuid}} (0-1)')], unit='percentunit',
                   desc='Chuỗi GPU chỉ xuất hiện khi Triton chạy trên máy có GPU'))
    return {'uid': 'vr01-overview', 'title': 'VR-01 MVP — tổng quan vận hành', 'schemaVersion': 39, 'version': 1,
            'timezone': 'browser', 'refresh': '5s', 'time': {'from': 'now-15m', 'to': 'now'}, 'tags': ['vr01'],
            'editable': True, 'panels': P, 'templating': {'list': []}, 'annotations': {'list': []}}


def main():
    text = json.dumps(build(), indent=1, ensure_ascii=False) + '\n'
    if '--check' in sys.argv:
        ok = OUT.is_file() and OUT.read_text(encoding='utf-8') == text
        print('dashboard up to date' if ok else 'dashboard is STALE')
        return 0 if ok else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding='utf-8')
    print(f'wrote {OUT.name}: {len(build()["panels"])} panels')
    return 0


if __name__ == '__main__':
    sys.exit(main())
