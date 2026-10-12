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
        for sess in [x for x in (d / 'session-report.json', d / 'session-extra-report.json') if x.is_file()]:
            r = json.loads(sess.read_text())
            host = (d / 'host-info.txt').read_text().split('\n') if (d / 'host-info.txt').is_file() else []
            cf = next((x for x in (d / 'git-commit.txt', d / 'git-commit-extra.txt') if x.is_file()), None)
            commit = cf.read_text().strip()[:12] if cf else '?'
            out += [f'## Phiên kiểm trên Triton thật — {d.name}', '', f'Nguồn: {src(sess)} · repo công khai commit `{commit}`', '',
                    'Môi trường: ' + ' · '.join(x.strip() for x in host if x.strip())[:300], '',
                    f"Kết luận: **{r['verdict']}**, {sum(s['result'] == 'PASS' for s in r['steps'])}/{len(r['steps'])} bước.", '',
                    '| Bước | Kết quả | Số liệu ghi nhận |', '|---|---|---|']
            for s in r['steps']:
                detail = {k: v for k, v in s.items() if k not in ('step', 'result', 'at', 'note', 'last')}
                out.append(f"| {s['step']} | {s['result']} | {json.dumps(detail, ensure_ascii=False).replace('|', '/')[:330]} |")
            out.append('')
        # Phien Tuan 4 (CPU va GPU): ket qua nam trong compose/ va k8s/ cua thu muc phien.
        staged = sorted((d / 'compose').glob('session-*-report.json')) + sorted((d / 'rerun').glob('session-*-report.json'))
        for sess in [x for x in staged if 'steps' in json.loads(x.read_text())]:
            r = json.loads(sess.read_text())
            host = (d / 'host-info.txt').read_text().split('\n') if (d / 'host-info.txt').is_file() else []
            out += [f'## Phiên Tuần 4 trên Triton thật — {d.name} / {sess.parent.name}/{sess.name}', '', f'Nguồn: {src(sess)}', '',
                    'Môi trường: ' + ' · '.join(x.strip() for x in host if x.strip())[:300], '',
                    f"Kết luận: **{r['verdict']}**, {sum(x['result'] == 'PASS' for x in r['steps'])}/{len(r['steps'])} bước.", '',
                    '| Bước | Kết quả | Số liệu ghi nhận |', '|---|---|---|']
            for x in r['steps']:
                detail = {k: v for k, v in x.items() if k not in ('step', 'result', 'at', 'note', 'last')}
                out.append(f"| {x['step']} | {x['result']} | {json.dumps(detail, ensure_ascii=False).replace('|', '/')[:330]} |")
            out.append('')
        for rep, title in [(x, 'Kubernetes (kubeadm)') for x in sorted(d.glob('k8s/**/k8s-report.txt'))] + \
                          [(x, 'Gói offline lớp ứng dụng') for x in sorted(d.glob('k8s/**/offline-report.txt'))]:
            lines = [x for x in rep.read_text().splitlines() if x.strip()]
            out += [f'## {title} — {d.name} / {rep.relative_to(d)}', '', f'Nguồn: {src(rep)}', '', f'Kết luận: **{lines[-1][:80]}**', '',
                    '| Bước | Kết quả |', '|---|---|']
            out += [f"| {x[6:].replace('|', '/')[:200]} | {x[:4]} |" for x in lines[:-1] if x[:4] in ('PASS', 'FAIL')] + ['']
        sweep = d / 'compose' / 'load-sweep-gpu-heavy-report.json'
        if sweep.is_file():
            r = json.loads(sweep.read_text())
            out += [f'## Quét tải model nặng trên GPU — {d.name}', '', f'Nguồn: {src(sweep)}', '',
                    f"Throughput cao nhất chưa bão hòa: **{r['max_unsaturated_rps']} req/s**; bước đầu tiên bão hòa: {r['first_saturated_target_rps']} req/s. "
                    'Model là mạng tích chập tự sinh, không phải model QC; số chỉ có nghĩa trên máy thử.', '']
        soak = d / 'compose' / 'soak-report.json'
        if soak.is_file():
            r = json.loads(soak.read_text())
            out += [f'## Soak — {d.name}', '', f'Nguồn: {src(soak)}', '',
                    f"Kết luận của công cụ: **{r.get('verdict')}** · {r.get('duration_h')} giờ · {r.get('samples')} mẫu · "
                    f"không restart trong soak: {r.get('no_restart_during_soak')} · chuỗi tăng quá 10%: {r.get('memory_growth_over_10pct')}", '']
            if r.get('series'):
                out += ['| Chuỗi | Đơn vị | Nhỏ nhất | Lớn nhất | TB giờ đầu | TB giờ cuối | Cuối so với đầu (%) | Độ dốc/giờ (cả lượt) | Độ dốc/giờ (sau giờ đầu) |',
                        '|---|---|---|---|---|---|---|---|---|']
                out += [f"| `{k}` | {v['unit']} | {v['min']} | {v['max']} | {v['first_window_avg']} | {v['last_window_avg']} | {v['last_vs_first_pct']} | "
                        f"{v['slope_per_hour']} | {v.get('slope_per_hour_after_first_hour')} |" for k, v in r['series'].items() if v] + ['']
            if r.get('load'):
                q, c = r['load']['requests'], r['load']['cutovers']
                out += [f"Tải: **{r['load']['verdict']}** · gửi {q['sent']} · có kết quả {q['with_terminal_result']} · thiếu/sai {q['missing_or_wrong']} · "
                        f"trùng {q['duplicate_or_extra_products']} · cutover {c['succeeded']}/{c['requested']} · p95 {r['load']['latency_total_ms']['p95']} ms", '']
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
            '- Máy đích của nhà máy (cấu hình chưa được IT duyệt); air gap đầy đủ (lớp nền Kubernetes vẫn cài online); model QC thật.',
            '- Người vận hành (không phải agent AI) tự chạy theo README/runbook trên máy sạch.',
            '- Mất điện thật; soak dài hơn 8 giờ.', '']
    (ROOT / 'TEST-REPORT.md').write_text('\n'.join(out), encoding='utf-8')
    print(f"wrote TEST-REPORT.md ({len(out)} lines)")


if __name__ == '__main__':
    main()
