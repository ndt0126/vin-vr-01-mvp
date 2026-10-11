"""Sinh docs/OBSERVABILITY.md: danh muc metric (tu backend/metrics.py), luat canh bao (tu alerts.yml), probe, log.
Usage: python3 tools/gen_observability_docs.py [--check]"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))
import metrics  # noqa: E402

OUT = ROOT / 'docs' / 'OBSERVABILITY.md'

INTRO = '''# VR-01 MVP — Observability (W4-01, W4-02)

File này được **sinh tự động** bằng `tools/gen_observability_docs.py` từ `backend/metrics.py` và `deploy/observability/alerts.yml`. Không sửa tay.

## 1. Tổng quan

| Thành phần | Ở đâu | Ghi chú |
|---|---|---|
| Metrics của API | `http://api:9090/metrics` (cổng riêng, HTTP, không token) | Chỉ mở trong mạng nội bộ của Compose, không publish ra host. Không chứa dữ liệu của từng sản phẩm |
| Metrics của Triton | `http://triton:8002/metrics` | Request theo model, CPU/RAM; GPU/VRAM khi máy có GPU |
| Prometheus | `make obs-start`, `http://127.0.0.1:9091` | Scrape 5 giây, giữ 7 ngày hoặc 2 GB |
| Grafana | `http://127.0.0.1:3000` (chỉ xem, không đăng nhập) | Dashboard `VR-01 MVP — tổng quan vận hành`, sinh bằng `tools/gen_dashboard.py` |
| Log có cấu trúc | `run/data/trace.jsonl` (JSON Lines) | Xem mục 5 |

Metric được cập nhật từ chính các sự kiện ghi vào trace log, nên số đếm và log không lệch nhau.

## 2. Health model và probe

| Probe | Endpoint | Trả 200 khi | Dùng cho |
|---|---|---|---|
| Liveness | `GET /healthz` (cả hai cổng, không token) | Tiến trình còn sống và trả lời HTTP | Kubernetes `livenessProbe`: restart khi treo |
| Readiness | `GET /readyz` (cả hai cổng, không token) | Recipe active đã được xác minh digest **và** model của recipe đó đang được nạp trên inference server **và** inference server sống **và** ghi được ledger, ổ còn trống | Kubernetes `readinessProbe`; Compose healthcheck |
| Startup | `GET /readyz` với `failureThreshold` lớn | Như readiness | Kubernetes `startupProbe`: cho phép nạp model lâu lúc khởi động |

Readiness phản ánh **đúng revision mong muốn**: lúc khởi động và mỗi lần kiểm, API đối chiếu digest của recipe active đã lưu bền và hỏi inference server xem đúng model đó có sẵn sàng không. Model active không còn được nạp (ví dụ Triton khởi động lại) thì `readyz` trả 503 với lý do `WARMUP_FAILED`, API tự nạp lại **đúng** model đó và không tự đổi sang recipe khác. Recipe/model đang active nhìn được qua metric `vr01_active_recipe_info` (nhãn gồm 12 ký tự đầu của digest).

Các lý do `readyz` có thể trả: `BACKEND_UNAVAILABLE`, `STORAGE_UNAVAILABLE`, `ACTIVE_RECIPE_UNVERIFIED`, `WARMUP_FAILED`, `SHUTTING_DOWN`. Mỗi lý do là một series của `vr01_not_ready_reason`.

## 3. Danh mục metric của API

Quy tắc nhãn: chỉ dùng nhãn có số giá trị hữu hạn và biết trước (`state`, `reason`, `decision`, `code`, `operation`, `plane`, `status`, `model`, `action`, `outcome`). **Không bao giờ** dùng `request_id`, `product_id`, `trace_id` hay tên người dùng làm nhãn; muốn tra một request thì dùng log (mục 5).

| Metric | Kiểu | Nhãn | Ý nghĩa |
|---|---|---|---|
'''

LOGS = '''
## 5. Log có cấu trúc và truy vết

`run/data/trace.jsonl` là JSON Lines, mỗi dòng một sự kiện:

| Trường | Có ở | Ý nghĩa |
|---|---|---|
| `at` | mọi dòng | Thời điểm, ISO-8601 UTC, mili giây |
| `event` | mọi dòng | Tên sự kiện, ví dụ `request.admitted`, `inference.started`, `inference.finished`, `request.terminal`, `request.rejected`, `request.cancelled`, `activation.committed`, `lifecycle.loaded`, `lifecycle.unloaded`, `http.access`, `audit` |
| `trace_id` | sự kiện gắn với một request HTTP | Nối các dòng của cùng một request; cũng được gửi sang inference server |
| `request_id`, `product_id` | sự kiện của một lần kiểm | Định danh nghiệp vụ |
| `model`, `recipe` | admitted, inference, lifecycle | Tên, version và digest đã pin |
| `state`, `decision`, `reason`, `score` | `request.terminal` | Kết quả cuối |
| `queue_ms`, `inference_ms`, `total_ms`, `duration_ms` | sự kiện tương ứng | Thời gian từng pha |
| `code`, `error` | sự kiện lỗi | Mã lỗi hoặc mô tả lỗi của backend |

Từ một `request_id`, lấy toàn bộ đường đi (ledger + log + audit + các lần kiểm khác của cùng sản phẩm):

```bash
make trace ID=<request_id>
```

Không ghi vào log: token, private key, nội dung ảnh (chỉ có SHA-256). Bộ test quét token trong mọi file dữ liệu sau mỗi test. Log không chứa thông tin cá nhân; `submitted_by` là định danh thiết bị/tài khoản kỹ thuật.

**Retention của log:** `trace.jsonl` xoay vòng khi đạt 64 MiB, giữ 5 file cũ (trần khoảng 384 MiB), file cũ nhất bị xóa. Giá trị là đề xuất, chỉnh bằng giới hạn `trace_max_bytes` và `trace_keep_files`. `make backup` sao lưu cả các file đã xoay vòng. Đề xuất retention chung (14 ngày hoặc 10 GiB) ở W2-02 vẫn chờ Operations chốt.

## 6. Giới hạn

- Ngưỡng cảnh báo là đề xuất cho lab, chưa được Operations duyệt.
- Chưa có Alertmanager: cảnh báo hiện trên Prometheus và Grafana, chưa gửi đi đâu.
- Metric CPU/RAM là của tiến trình API và của Triton tự báo; chưa có metric mức container/node (cAdvisor, node exporter).
- Grafana cho xem không cần đăng nhập và chỉ mở trên loopback; chưa phù hợp để mở ra mạng nhà máy.
'''


def render():
    out = [INTRO.rstrip('\n')]
    for name, (kind, help_text, labels) in metrics.CATALOG.items():
        out.append(f"| `{name}` | {kind} | {', '.join(f'`{x}`' for x in labels) or '—'} | {help_text} |")
    out += ['', 'Histogram dùng các mốc (giây): ' + ', '.join(str(b) for b in metrics.LATENCY_BUCKETS) + '.', '',
            '## 4. Luật cảnh báo', '',
            'Kiểm offline bằng `make alerts-test` (promtool, `deploy/observability/alerts.test.yml`): mỗi cảnh báo chính được chứng minh **bật** khi có sự cố và **tắt** khi hết.', '',
            '| Cảnh báo | Mức | Điều kiện | Giữ trong | Ý nghĩa | Cần làm |', '|---|---|---|---|---|---|']
    doc = yaml.safe_load((ROOT / 'deploy' / 'observability' / 'alerts.yml').read_text(encoding='utf-8'))
    for group in doc['groups']:
        for r in group['rules']:
            expr = ' '.join(r['expr'].split()).replace('|', '\\|')
            out.append(f"| `{r['alert']}` | {r['labels']['severity']} | `{expr}` | {r.get('for', '0s')} | "
                       f"{r['annotations']['summary']} | {r['annotations']['action']} |")
    return '\n'.join(out) + '\n' + LOGS


def main():
    text = render()
    if '--check' in sys.argv:
        ok = OUT.is_file() and OUT.read_text(encoding='utf-8') == text
        print('OBSERVABILITY.md up to date' if ok else 'OBSERVABILITY.md is STALE')
        return 0 if ok else 1
    OUT.write_text(text, encoding='utf-8')
    print(f'wrote {OUT.name} ({len(text.splitlines())} lines)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
