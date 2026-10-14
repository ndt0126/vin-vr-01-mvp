"""Sinh bang ket qua UAT tu dong (W5-04) tu raw evidence cua mot phien VPS Tuan 5.

Usage: python3 tools/make_uat_result.py <thu muc evidence vps-w5-...>   -> <thu muc>/UAT-RESULT.md + uat-result.json
Moi dong checklist (docs/Tuan_5/W5-04-UAT-CHECKLIST.md) duoc noi voi cac buoc tu dong da chay trong phien:
real_session (P*), E2E giao dien (E*), smoke, make test. Dong khong co bang chung trong phien ghi CHUA CHAY, khong ghi PASS.
Day la UAT TU DONG; phan "nguoi dung noi bo thao tac tren UI" can buoi UAT co nguoi, ghi rieng.
"""
import json
import sys
from pathlib import Path

CHECKLIST = [
    ('A1', 'Simulator gửi một sản phẩm kèm ảnh: đúng một kết quả, đúng sản phẩm/ảnh/recipe/model', ['P1', 'SMOKE']),
    ('A2', 'Gửi nhiều sản phẩm liên tiếp: không thiếu, không trùng', ['P2']),
    ('A3', 'UI hiện kết quả, lịch sử và trạng thái khớp API', ['E02', 'E04']),
    ('B1', 'Ảnh hỏng/sai định dạng/quá lớn bị từ chối trước khi ghi nhận', ['TEST']),
    ('B2', 'Gửi lại cùng request_id, cùng nội dung: trả bản ghi cũ', ['TEST', 'SMOKE']),
    ('B3', 'Cùng request_id, nội dung khác: 409', ['TEST']),
    ('B4', 'Recipe cũ ngay sau khi đổi: 409, gửi lại đúng recipe, không sai phiên bản', ['P2']),
    ('C1', 'Suy luận quá thời gian: TIMEOUT, kết quả muộn bị bỏ', ['P11', 'P11b']),
    ('C2', 'Hàng đợi đầy: 429, không treo', ['TEST']),
    ('C3', 'Restart API khi có request đang chạy/chờ: INDETERMINATE, không tự chạy lại', ['P7']),
    ('C4', 'Restart Triton khi có tải: không sai/trùng, tự nạp lại model', ['P8', 'P12']),
    ('C5', 'Reboot cả máy: recipe giữ nguyên, tự sẵn sàng', ['R1', 'R2']),
    ('C6', 'Hủy lần kiểm đang chờ/đang chạy: CANCELLED, kết quả muộn bị bỏ', ['P4', 'P5', 'E08']),
    ('D1', 'Chuyển recipe khi có tải: mỗi kết quả đúng model đã ghim', ['P2', 'P6']),
    ('D2', 'Model mới không qua golden: giữ model cũ', ['TEST']),
    ('D3', 'Model mới lỗi 3 lần: tự rollback, có audit; UI cảnh báo', ['P14', 'E07']),
    ('D4', 'Rollback thủ công: lịch sử ghi người, lúc, lý do', ['E05']),
    ('E1', 'viewer/operator gọi chuyển recipe: 403, có audit', ['E06', 'TEST']),
    ('E2', 'Không token/token sai: 401', ['E01', 'TEST']),
    ('E3', 'UI viewer/operator không hiện nút quản trị, không gọi management API', ['E02', 'E04']),
    ('U1', '(bổ sung) UI báo chưa sẵn sàng trong 10 s khi dừng Triton thật', ['E09']),
    ('U2', '(bổ sung) UI dùng được ở màn hẹp 390 px', ['E10']),
    ('U3', '(bổ sung) UI vẫn đúng sau toàn bộ bài sự cố/nâng cấp', ['E2E_AGAIN']),
    ('U4', '(bổ sung) UI vẫn đúng sau reboot cả máy', ['E2E_REBOOT']),
]


def load(p):
    try:
        return json.loads(Path(p).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def collect(ev):
    run = ev / 'run' if (ev / 'run').is_dir() else ev
    found = {}
    for rep in ('session-report.json', 'session-w4-report.json', 'session-extra-report.json'):
        d = load(run / rep)
        for s in (d or {}).get('steps', []):
            key = s['step'].split(' ')[0]
            # neu cung buoc chay o hai phase thi lay lan cuoi
            found[key] = {'result': s['result'], 'source': f'run/{rep}', 'name': s['step']}
    smoke = load(run / 'smoke-report.json')
    if smoke:
        found['SMOKE'] = {'result': 'PASS' if smoke.get('verdict') == 'PASS' else 'FAIL', 'source': 'run/smoke-report.json',
                          'name': f"smoke {smoke.get('verdict')}"}
    test = load(run / 'test-report-container.json')
    if test:
        n = sum(v['run'] for v in test['suites'].values())
        ok = sum(v['passed'] for v in test['suites'].values())
        found['TEST'] = {'result': test['verdict'], 'source': 'run/test-report-container.json',
                         'name': f'make test {ok}/{n} (contract/unit)'}
    for sub, tag in (('e2e', ''), ('e2e-again', 'AGAIN'), ('e2e-after-reboot', 'REBOOT')):
        d = load(run / 'w5' / sub / 'e2e-results.json')
        if not d:
            continue
        if tag:
            found['E2E_' + tag] = {'result': 'PASS' if d['failed'] == 0 and d['passed'] > 0 else 'FAIL',
                                  'source': f'run/w5/{sub}/e2e-results.json', 'name': f"E2E {sub}: {d['passed']} PASS, {d['failed']} FAIL"}
            continue
        for r in d['results']:
            if 'result' in r:
                found[r['name'].split(' ')[0]] = {'result': r['result'], 'source': f'run/w5/{sub}/e2e-results.json',
                                                  'name': r['name']}
    return found


def main():
    ev = Path(sys.argv[1])
    found = collect(ev)
    rows, out = [], []
    for cid, text, keys in CHECKLIST:
        got = [(k, found.get(k)) for k in keys]
        have = [g for _, g in got if g and g['result'] != 'SKIP']
        if not have:
            status = 'CHƯA CHẠY trong phiên này'
        elif all(g['result'] == 'PASS' for g in have):
            status = 'ĐẠT (tự động)' if len(have) == len(keys) else 'ĐẠT một phần (tự động)'
        else:
            status = 'KHÔNG ĐẠT'
        ev_text = '; '.join(f"{k}={g['result'] if g else '—'}" for k, g in got)
        rows.append({'id': cid, 'scenario': text, 'status': status, 'evidence': {k: g for k, g in got}})
        out.append(f'| {cid} | {text} | {status} | {ev_text} |')
    commit = (ev / 'run' / 'w5' / 'git-commit.txt')
    head = commit.read_text().split() if commit.is_file() else ['?']
    md = ['# W5-04 — Kết quả UAT tự động', '',
          f'Sinh bởi `tools/make_uat_result.py` từ raw evidence trong thư mục này. Mã nguồn: `{" ".join(head)}`.', '',
          '**Phạm vi:** đây là các bài tự động chạy trên stack thật (Triton + API + UI qua trình duyệt headless). '
          'Phần "người dùng nội bộ thao tác trên UI" của W5-04 cần một buổi UAT có người; chưa có trong bảng này.', '',
          '| # | Kịch bản | Kết quả | Bằng chứng (bước=kết quả) |', '|---|---|---|---|', *out, '',
          'Mã bằng chứng: P*/R* = `tests/real_session.py` (`run/session-*.json`), E* = `tests/e2e/ui.e2e.mjs` '
          '(`run/w5/e2e*/e2e-results.json`, ảnh chụp cùng thư mục), SMOKE = `make smoke`, TEST = `make test` trong container.', '']
    (ev / 'UAT-RESULT.md').write_text('\n'.join(md), encoding='utf-8')
    (ev / 'uat-result.json').write_text(json.dumps(rows, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    bad = [r['id'] for r in rows if r['status'] == 'KHÔNG ĐẠT']
    print(f"UAT: {sum(r['status'].startswith('ĐẠT') for r in rows)}/{len(rows)} đạt, không đạt: {bad or 'không'}, "
          f"chưa chạy: {[r['id'] for r in rows if r['status'].startswith('CHƯA')]}")


if __name__ == '__main__':
    main()
