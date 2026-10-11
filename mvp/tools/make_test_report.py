"""Sinh TEST-REPORT.md tu raw evidence (JSON/log) trong mvp/evidence/. Khong co so nao duoc go tay.

Usage: python3 tools/make_test_report.py
"""
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EV = ROOT / 'evidence'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def src(p):
    return f'`{p.relative_to(ROOT)}` (sha256 {sha(p)}…)'


def main():
    out = ['# VR-01 MVP — Test report', '',
           'File này được **sinh tự động** bằng `tools/make_test_report.py` từ các file trong `evidence/`. '
           'Mỗi bảng ghi file nguồn và 16 ký tự đầu SHA-256 của file đó. Chạy lại lệnh sẽ ra cùng nội dung.', '']
    for d in sorted(EV.glob('*/')):
        tr = d / 'test-report.json'
        if tr.is_file():
            r = json.loads(tr.read_text())
            out += [f'## Unit / contract / integration — {d.name}', '', f'Nguồn: {src(tr)}', '',
                    f"Kết luận: **{r['verdict']}** · Python {r['python']} · {r['platform']} · {r['seconds']} s · "
                    f"kiểm tĩnh OpenAPI {r['openapi_static']['checks'] - len(r['openapi_static']['failed'])}/{r['openapi_static']['checks']}"
                    + (f" · API.md khớp spec: {r['api_docs_match_spec']}" if 'api_docs_match_spec' in r else ''), '',
                    '| Bộ test | Chạy | Đạt | Lỗi | Bỏ qua |', '|---|---|---|---|---|']
            for name, s in r['suites'].items():
                out.append(f"| `{name}` | {s['run']} | {s['passed']} | {s['failed'] + s['errors']} | {len(s['skipped'])} |")
            out += ['', 'Backend stub và inference server giả. Không chứng minh Triton/GPU.', '']
        loads = sorted(d.glob('load-*.json')) + sorted(d.glob('load-cutover-report.json'))
        if loads:
            out += [f'## Chuyển recipe dưới tải liên tục — {d.name}', '',
                    '| Nguồn | Kết luận | Tải | Gửi | Có kết quả | Thiếu/sai | Trùng | Cutover đạt | Gap max (s) | 409 gửi lại | p95 (ms) |',
                    '|---|---|---|---|---|---|---|---|---|---|---|']
            for f in loads:
                r = json.loads(f.read_text())
                q, c = r['requests'], r['cutovers']
                out.append(f"| {src(f)} | **{r['verdict']}** | {r['config']['rate_per_s']}/s × {r['config']['duration_s']} s, "
                           f"chuyển mỗi {r['config']['cutover_every_s']} s | {q['sent']} | {q['with_terminal_result']} | "
                           f"{q['missing_or_wrong']} | {q['duplicate_or_extra_products']} | {c['succeeded']}/{c['requested']} | "
                           f"{c['max_gap_s']} | {r['client_retries_same_request_id']['recipe_refresh_409']} | {r['latency_total_ms']['p95']} |")
            out += ['', 'Gap = kết quả cuối của recipe cũ → kết quả đầu của recipe mới. Gap không thể nhỏ hơn chu kỳ gửi, '
                    'nên đây **không** phải số đo downtime. "409 gửi lại" là request gặp đúng lúc recipe đổi: server chưa tạo '
                    'record, client lấy recipe mới và gửi lại cùng `request_id`.', '']
        sm = d / 'smoke-report.json'
        if sm.is_file():
            r = json.loads(sm.read_text())
            out += [f'## Smoke flow — {d.name}', '', f'Nguồn: {src(sm)} (lượt smoke cuối của phiên)', '',
                    f"Kết luận: **{r['verdict']}**, {sum(s['result'] == 'PASS' for s in r['steps'])}/{len(r['steps'])} bước.", '']
        sess = d / 'session-report.json'
        if sess.is_file():
            r = json.loads(sess.read_text())
            host = (d / 'host-info.txt').read_text().split('\n') if (d / 'host-info.txt').is_file() else []
            commit = (d / 'git-commit.txt').read_text().strip()[:12] if (d / 'git-commit.txt').is_file() else '?'
            out += [f'## Phiên kiểm trên Triton thật — {d.name}', '', f'Nguồn: {src(sess)} · repo công khai commit `{commit}`', '',
                    'Môi trường: ' + ' · '.join(x.strip() for x in host if x.strip())[:300], '',
                    f"Kết luận: **{r['verdict']}**, {sum(s['result'] == 'PASS' for s in r['steps'])}/{len(r['steps'])} bước.", '',
                    '| Bước | Kết quả | Số liệu ghi nhận |', '|---|---|---|']
            for s in r['steps']:
                detail = {k: v for k, v in s.items() if k not in ('step', 'result', 'at', 'note', 'last')}
                out.append(f"| {s['step']} | {s['result']} | {json.dumps(detail, ensure_ascii=False).replace('|', '/')[:330]} |")
            out.append('')
        log = d / 'vps-session.log'
        if log.is_file():
            text = log.read_text()
            host = (d / 'host-info.txt').read_text().split('\n') if (d / 'host-info.txt').is_file() else []
            out += [f'## Kịch bản trên Triton thật — {d.name}', '', f'Nguồn: {src(log)}', '',
                    'Môi trường: ' + ' · '.join(x for x in host[:4] if x), '', '| Kịch bản | Dòng kết quả trong log |', '|---|---|']
            for block in re.split(r'^### ', text, flags=re.M)[1:]:
                lines = [x for x in block.strip().split('\n') if x]
                out.append(f"| {lines[0]} | {'<br>'.join(x.replace('|', '/')[:150] for x in lines[1:5])} |")
            out.append('')
    out += ['## Chưa có trong báo cáo này', '',
            '- Chuyển recipe dưới tải liên tục trên **Triton thật** (mới chạy với inference server giả).',
            '- Reboot cả máy; GPU (`KIND_GPU`); người khác tự chạy theo README trên máy sạch.',
            '- Stress tới bão hòa, soak dài, fault injection có hệ thống (W4-04).', '']
    (ROOT / 'TEST-REPORT.md').write_text('\n'.join(out), encoding='utf-8')
    print(f"wrote TEST-REPORT.md ({len(out)} lines)")


if __name__ == '__main__':
    main()
