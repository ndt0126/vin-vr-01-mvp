"""Sinh trang HTML xem video E2E giao dien (W5) tu evidence phien GPU 14/10/2026.

Usage: python3 tools/make_video_index.py   -> evidence/XEM-VIDEO-W5.html (mo bang Chrome/Firefox, video .webm)
Timestamps duoc SUY RA tu log server (run/data/trace.jsonl: gio cua tung lan UI goi API), moc 0 = luc trang mo
(lan dang nhap tru LOGIN_LEAD_S). Day la UOC TINH (+-0,5 s), khong phai moc ghi trong video.
"""
import html
import json
from datetime import datetime
from pathlib import Path

EV = Path(__file__).resolve().parent.parent / 'evidence'
GPU = EV / 'vps-w5-2026-10-14T0649Z'
RUN = GPU / 'run'
OUT = EV / 'XEM-VIDEO-W5.html'
LOGIN_LEAD_S = 0.35  # mo trang + go token truoc khi /v1/me toi server (uoc tinh)

# Video minh hoa: lan quay bi hut khung cuoi -> hien THEM video cua luot khac, ghi nhan ro. File goc giu nguyen.
# E01: 4 luot deu PASS (test chi dat khi trinh duyet da thay "Token khong dung"); 3 luot GPU co dung 1 lan 401 trong log server.
ILLUSTRATE = {'E01': ('reboot', 'Video lượt này kết thúc 0,16–0,2 s, trước khi dòng báo lỗi kịp vẽ. Kết quả vẫn đạt: test chỉ PASS khi trình duyệt '
                               'đã thấy chữ "Token không đúng", và log máy chủ ghi đúng một lần từ chối 401 ở lượt này (lượt người B không có log máy chủ). '
                               'Bên dưới là VIDEO MINH HỌA quay ở lượt "Sau reboot cả máy", cùng mã giao diện, để thấy dòng báo lỗi.')}

SETS = [  # (khoa, nhan, thu muc video, file ket qua, co log server)
    ('before', 'Trước sự cố', RUN / 'w5/e2e/e2e', True),
    ('after', 'Sau toàn bộ bài sự cố + nâng cấp', RUN / 'w5/e2e-again/e2e', True),
    ('reboot', 'Sau reboot cả máy', RUN / 'w5/e2e-after-reboot', True),
    ('personb', 'Lượt người B (cài từ README)', EV / 'person-b-2026-10-14-w5/server-logs/e2e', False),
]

GROUPS = [
    ('Đăng nhập và phân quyền', ['E01', 'E02', 'E06']),
    ('Trạng thái hệ thống', ['E03', 'E09']),
    ('Kiểm tra sản phẩm', ['E04', 'E07', 'E08']),
    ('Quản trị model', ['E05']),
    ('Hiển thị trên màn hẹp', ['E10']),
]

SCEN = {
    'E01': ('Token sai bị từ chối',
            'Nhập một token sai vào màn đăng nhập. Hệ thống báo "Token không đúng" và không mở màn hình nào.',
            'Ô token là trường mật khẩu nên không lộ ký tự; sau khi bấm Đăng nhập, dòng báo lỗi đỏ hiện ra. '
            'Lưu ý: video kịch bản này chỉ dài 0,16–0,24 s vì test đóng trình duyệt ngay khi thấy dòng báo lỗi; ở 3/4 lượt, '
            'khung cuối được ghi là ngay trước khi dòng lỗi kịp vẽ (chỉ lượt "Sau reboot cả máy" bắt được). Kết quả PASS vẫn đúng: '
            'test chỉ đạt khi trình duyệt đã thấy chữ "Token không đúng". Đã sửa test để giữ trình duyệt thêm 1,5 s trước khi đóng cho các lần quay sau.'),
    'E02': ('Viewer chỉ xem, không có quyền quản trị (B1, B5)',
            'Đăng nhập vai trò viewer: thấy trạng thái sẵn sàng, recipe/model đang dùng kèm digest, số đếm trong ngày. '
            'Menu chỉ có Tổng quan và Lịch sử; trình duyệt không gọi cổng quản trị 9443 lần nào.',
            'Thanh menu bên trái chỉ có 2 mục; thẻ "Recipe và model đang dùng".'),
    'E03': ('Hệ thống chưa sẵn sàng thì không cho gửi ảnh (B1)',
            'Giả lập máy chủ báo chưa sẵn sàng (lý do BACKEND_UNAVAILABLE). Màn hình hiện băng đỏ kèm lý do, '
            'nút "Gửi kiểm tra" bị tắt.',
            'Băng đỏ "CHƯA SẴN SÀNG"; vào màn Kiểm tra thì nút gửi mờ. Kịch bản này giả lập trong trình duyệt, không dừng Triton thật.'),
    'E04': ('Gửi ảnh, xem kết quả và truy vết (B2, B3)',
            'Operator chọn ảnh mẫu, nhập mã sản phẩm, gửi. Màn hình hiện OK/NG/REVIEW kèm thẻ truy vết '
            '(request, trace, recipe, model + digest, SHA-256 ảnh, thời gian). Sau đó lọc Lịch sử theo mã sản phẩm và mở lại đúng chi tiết đó.',
            'Chữ kết quả cỡ lớn; thẻ "Truy vết" bên phải; bảng Lịch sử sau khi lọc.'),
    'E05': ('Admin chuyển recipe và rollback, bắt buộc ghi lý do (B4)',
            'Admin vào "Recipe và model", chuyển sang recipe-b qua hộp thoại có ô lý do, rồi rollback về recipe trước. '
            'Hệ thống nạp model mới, kiểm golden rồi mới chuyển; audit ghi người, lúc, lý do.',
            'Hộp thoại xác nhận; dòng xanh "Đã chuyển sang…"; thẻ recipe đổi từ recipe-a sang recipe-b rồi về lại.'),
    'E06': ('Gọi thẳng API quản trị bằng vai trò thấp → 403 (B5)',
            'Viewer và operator gọi thẳng các endpoint quản trị đều bị 403; admin được 200.',
            None),
    'E07': ('Lỗi kỹ thuật hiện "CHƯA CÓ KẾT LUẬN" và hệ thống tự rollback (B2, B7)',
            'Recipe đang chọn dùng model cố tình lỗi. Operator gửi 3 ảnh: cả 3 lần màn hình hiện "CHƯA CÓ KẾT LUẬN", '
            'không bao giờ hiện OK/NG. Sau 3 lỗi liên tiếp, hệ thống tự quay về recipe cũ; màn Tổng quan hiện cảnh báo vàng "Hệ thống đã TỰ ROLLBACK".',
            'Thẻ kết quả màu xanh tím (khác hẳn đỏ NG/xanh OK); cuối video là cảnh báo tự rollback trên Tổng quan.'),
    'E08': ('Hủy lần kiểm đang chạy',
            'Operator gửi ảnh với model chậm (~1 s), bấm "Hủy lần kiểm này", nhập lý do. Kết quả hiện "ĐÃ HỦY", không có kết luận.',
            'Vòng xoay "Đang kiểm" rồi hộp thoại hủy; thẻ kết quả "ĐÃ HỦY".'),
    'E09': ('Dừng Triton thật → giao diện báo chưa sẵn sàng (B1)',
            'Trong lúc viewer đang xem Tổng quan, test dừng container Triton thật. Trang tự kiểm mỗi 5 giây và chuyển sang '
            '"CHƯA SẴN SÀNG" kèm lý do (tiêu chí ≤ 10 s). Bật lại Triton thì trang tự về "SẴN SÀNG".',
            'Băng xanh đổi sang đỏ rồi về xanh; chip trạng thái góc trên cũng đổi theo. Video dài nhất bộ.'),
    'E10': ('Màn hẹp 390 px (điện thoại, tablet dọc)',
            'Operator xem lần lượt Tổng quan, Kiểm tra, Lịch sử ở bề ngang 390 px: không có thanh cuộn ngang, menu chuyển lên trên.',
            'Đoạn đầu ở màn rộng, sau đó khung hẹp lại.'),
}

# Su kien server -> nhan moc thoi gian. (plane, operation) -> nhan
LABELS = {
    ('inference', 'getMe', 200): 'Đăng nhập xong',
    ('inference', 'getMe', 401): 'Bấm Đăng nhập với token sai → bị từ chối',
    ('inference', 'submitInspection', 202): 'Bấm "Gửi kiểm tra" (máy chủ nhận ảnh)',
    ('inference', 'cancelInspection', 200): 'Xác nhận hủy',
    ('management', 'activateRecipe', 200): 'Xác nhận chuyển recipe (golden đạt, đã chuyển)',
    ('management', 'rollbackRecipe', 200): 'Xác nhận rollback (đã quay về recipe trước)',
    ('management', 'getStation', 200): 'Mở màn "Recipe và model"',
}


def ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def load_trace():
    ev = []
    with open(RUN / 'data' / 'trace.jsonl', encoding='utf-8') as f:
        for line in f:
            e = json.loads(line)
            if e['event'] in ('http.access', 'lifecycle.auto_rollback', 'request.terminal'):
                e['t'] = ts(e['at'])
                ev.append(e)
    return ev


def windows(trace, results, has_video):
    """Chia log server thanh cac cua so, moi cua so = mot context trinh duyet co video (bat dau bang /v1/me)."""
    end = ts(results['at'])
    total = sum(r.get('ms', 0) for r in results['results']) / 1000
    lo = end - total - 8
    logins = [e for e in trace if lo <= e['t'] <= end and e['event'] == 'http.access' and e.get('operation') == 'getMe']
    logins = logins[1:]  # lan /v1/me dau tien la cua before() trong test, khong co video
    order = [n for n in ('E01', 'E02', 'E03', 'E04', 'E05', 'E07', 'E08', 'E09', 'E10') if n in has_video]
    dur = {r['name'].split(' ')[0]: r['ms'] / 1000 for r in results['results'] if 'ms' in r}
    out = {}
    for i, name in enumerate(order):
        if i >= len(logins):
            break
        start = logins[i]['t']
        # het cua so = luc video ket thuc (uoc tinh bang thoi gian cua test), khong lan sang buoc chuan bi cua kich ban sau
        stop = min(logins[i + 1]['t'] if i + 1 < len(logins) else end, start + dur.get(name, 60) + 0.1)
        out[name] = (start - LOGIN_LEAD_S, start, stop)
    return out


LOC = 'Mở Lịch sử, lọc theo mã sản phẩm'
DETAIL = 'Mở chi tiết lần kiểm từ Lịch sử → thẻ truy vết'


def marks_for(trace, name, w, measured=None):
    t0, start, stop = w
    m, seen_ready, submits, waiting_result, rolled = [], None, 0, False, False
    for e in trace:
        if not start - 0.01 <= e['t'] < stop:
            continue
        rel = e['t'] - t0
        if e['event'] == 'lifecycle.auto_rollback':
            m.append((rel, 'Hệ thống TỰ ROLLBACK về recipe cũ (3 lỗi liên tiếp)'))
            rolled = True
            continue
        if e['event'] == 'request.terminal':
            if name in ('E04', 'E07', 'E08') and e.get('request_id', '').startswith('ui-'):
                m.append((rel, f"Máy chủ kết thúc lần kiểm: {e['state']}" + (f" / {e['decision']}" if e.get('decision') else '')))
            continue
        key = (e['plane'], e.get('operation'), e['status'])
        if e.get('operation') == 'getReadiness' and name == 'E09':
            # Chi lay lan /readyz cua TRANG: trang kiem luc dang nhap roi moi 5 s. Healthcheck cua Docker cung goi /readyz
            # (log khong phan biet duoc nguon), nen bo moi lan khong roi vao nhip 5 s tinh tu luc dang nhap.
            phase = (e['t'] - start) % 5.0
            if not (phase < 0.4 or phase > 4.8):
                continue
            ready = e['status'] == 200
            if seen_ready is not None and ready != seen_ready:
                if not ready and measured:
                    m.append((max(0.0, rel - measured), f'Triton đã dừng xong (test dừng container; suy từ số đo {measured:.1f} s)'.replace('.', ',')))
                m.append((rel, 'Trang kiểm lại → "SẴN SÀNG"' if ready else 'Trang kiểm lại → băng đỏ "CHƯA SẴN SÀNG"'))
            seen_ready = ready
            continue
        labels = [x for _, x in m]
        if e.get('operation') == 'listInspections' and name == 'E04' and LOC not in labels:
            m.append((rel, LOC))
            continue
        if e.get('operation') == 'getInspectionResult' and e['status'] == 200:
            if name == 'E04' and LOC in labels and DETAIL not in labels:
                m.append((rel, DETAIL))
            elif waiting_result:
                m.append((rel, 'Màn hình hiện kết quả' + (' "CHƯA CÓ KẾT LUẬN"' if name == 'E07' else
                                                         (' "ĐÃ HỦY"' if name == 'E08' else ' + thẻ truy vết'))))
                waiting_result = False
            continue
        if e.get('operation') == 'listStationActivations' and name == 'E07' and rolled:
            m.append((rel, 'Mở Tổng quan → cảnh báo vàng "Hệ thống đã TỰ ROLLBACK"'))
            rolled = False
            continue
        if key == ('inference', 'submitInspection', 202):
            submits += 1
            waiting_result = True
            m.append((rel, LABELS[key] + (f' — lần {submits}' if name == 'E07' else '')))
            continue
        if key[0] == 'management' and name != 'E05':
            continue  # cac kich ban khac: lenh quan tri la do script test goi thang API de don trang thai, khong phai thao tac UI
        if key in LABELS and not (key[1] == 'getStation' and any('Recipe và model' in x for _, x in m)):
            m.append((rel, LABELS[key]))
    # bo trung lien tiep cung nhan, sap xep
    out, last = [], None
    for rel, lab in sorted(m):
        if lab != last:
            out.append((max(0.0, rel), lab))
        last = lab
    return out


def main():
    trace = load_trace()
    data = {}  # name -> list of variants
    for key, label, d, with_log in SETS:
        res = json.loads((d / 'e2e-results.json').read_text(encoding='utf-8'))
        vids = {p.name.split('-')[0]: p for p in sorted((d / 'video').glob('E*-1.webm'))}
        status = {r['name'].split(' ')[0]: r['result'] for r in res['results'] if 'result' in r}
        extra = {r['name'].split(' ')[0]: r['value'] for r in res['results'] if 'value' in r}
        wins = windows(trace, res, set(vids)) if with_log else {}
        for name in SCEN:
            v = {'key': key, 'label': label, 'result': status.get(name, '—'), 'video': None, 'marks': [], 'note': ''}
            if name in vids:
                v['video'] = vids[name].relative_to(EV).as_posix()
                if name in wins:
                    v['marks'] = marks_for(trace, name, wins[name], extra.get(name))
            if name == 'E09' and name in extra:
                v['note'] = f"Đo được: {extra[name]:.1f} s từ lúc dừng Triton tới khi trang báo chưa sẵn sàng.".replace(".", ",", 1)
            if not with_log and v['video']:
                v['note'] = (v['note'] + ' ' if v['note'] else '') + 'Lượt này không có log server trên laptop nên không có mốc thời gian.'
            if name in ('E07', 'E08') and key == 'personb':
                v['note'] = 'Bị bỏ qua ở lượt người B: stack bật bằng "make start" thường, thiếu model giả cần cho kịch bản này (đã ghi trong README).'
            data.setdefault(name, []).append(v)
    render(data)
    print(OUT)


def fmt(t):
    return f'{int(t // 60)}:{t % 60:04.1f}'


def render(data):
    groups_html, toc = [], []
    for gi, (gname, names) in enumerate(GROUPS):
        toc.append(f'<li><a href="#g{gi}">{html.escape(gname)}</a><ul>' +
                   ''.join(f'<li><a href="#{n}">{n} · {html.escape(SCEN[n][0])}</a></li>' for n in names) + '</ul></li>')
        cards = []
        for n in names:
            title, desc, watch = SCEN[n]
            variants = data[n]
            tabs, panes = [], []
            for i, v in enumerate(variants):
                badge = {'PASS': 'ok', 'FAIL': 'ng'}.get(v['result'], 'muted')
                tabs.append(f'<button role="tab" aria-selected="{str(i == 0).lower()}" data-pane="{n}-{v["key"]}">'
                            f'{html.escape(v["label"])} <span class="badge {badge}">{html.escape(v["result"])}</span></button>')
                if v['video']:
                    marks = ''.join(f'<li><button class="ts" data-t="{t:.2f}">{fmt(t)}</button> {html.escape(lab)}</li>'
                                    for t, lab in v['marks'])
                    marks_html = (f'<h4>Diễn biến (≈, suy ra từ log server, sai số ±0,5 s)</h4><ol class="marks">{marks}</ol>'
                                  if marks else '')
                    body = (f'<video controls preload="auto" src="{html.escape(v["video"])}#t=0.4"></video>'
                            f'<div class="speed">Tốc độ: <button data-rate="0.25">0,25×</button><button data-rate="0.5">0,5×</button>'
                            f'<button data-rate="1">1×</button></div>{marks_html}')
                else:
                    body = '<p class="muted">Không có video cho kịch bản này ở lượt này.</p>'
                if v['note']:
                    body += f'<p class="note">{html.escape(v["note"])}</p>'
                ill = ILLUSTRATE.get(n)
                if ill and v['key'] != ill[0] and v['video']:
                    src = next(x for x in variants if x['key'] == ill[0])
                    body += (f'<div class="illus"><p class="note"><b>Vì sao có thêm video:</b> {html.escape(ill[1])}</p>'
                             f'<p class="illus-label">VIDEO MINH HỌA — quay ở lượt "{html.escape(src["label"])}", không phải lượt này</p>'
                             f'<video controls preload="auto" src="{html.escape(src["video"])}#t=0.05"></video></div>')
                panes.append(f'<div class="pane" id="{n}-{v["key"]}" {"" if i == 0 else "hidden"}>{body}</div>')
            if n == 'E06':
                tabs, panes = [], ['<p class="muted">Kịch bản kiểm bằng cách gọi thẳng API, không mở giao diện nên không có video. '
                                   'Kết quả: ' + ', '.join(f'{html.escape(v["label"])}: {v["result"]}' for v in variants) + '.</p>']
            cards.append(f'<article class="card" id="{n}"><header><span class="code">{n}</span><h3>{html.escape(title)}</h3></header>'
                         f'<p>{html.escape(desc)}</p>' + (f'<p class="watch"><b>Xem gì:</b> {html.escape(watch)}</p>' if watch else '') +
                         (f'<div class="tabs" role="tablist">{"".join(tabs)}</div>' if tabs else '') + ''.join(panes) + '</article>')
        groups_html.append(f'<section id="g{gi}"><h2>{gi + 1}. {html.escape(gname)}</h2>{"".join(cards)}</section>')
    page = TEMPLATE.replace('{{TOC}}', ''.join(toc)).replace('{{GROUPS}}', ''.join(groups_html))
    OUT.write_text(page, encoding='utf-8')


TEMPLATE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video giao diện W5</title>
<style>
:root{--bg:#f4f5f2;--panel:#fff;--ink:#1b1f1d;--muted:#5d6661;--line:#d5d9d4;--accent:#0f5c4d;--ok:#1d6b3a;--okbg:#e2f3e7;--ng:#a3231f;--ngbg:#fbe4e2}
@media (prefers-color-scheme:dark){:root{--bg:#141716;--panel:#1e2321;--ink:#eef1ee;--muted:#a3ada7;--line:#353c38;--accent:#49b89f;--ok:#7fd39a;--okbg:#183524;--ng:#ff9a94;--ngbg:#43201e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{display:grid;grid-template-columns:280px 1fr;gap:24px;max-width:1280px;margin:0 auto;padding:24px 16px}
nav{position:sticky;top:16px;align-self:start;max-height:calc(100vh - 32px);overflow:auto;font-size:14px}
nav ul{list-style:none;margin:0;padding-left:0}nav ul ul{padding-left:12px;margin:4px 0 10px}nav a{color:var(--ink);text-decoration:none}nav a:hover{color:var(--accent)}
nav>ul>li>a{font-weight:650}
h1{font-size:24px;margin:0 0 6px}h2{font-size:20px;margin:32px 0 12px}h3{font-size:17px;margin:0}h4{font-size:14px;margin:14px 0 6px;color:var(--muted)}
.lead{color:var(--muted);margin:0 0 8px;max-width:75ch}ul.lead{padding-left:20px}ul.lead li{margin:4px 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:16px 18px;margin-bottom:16px}
.card header{display:flex;gap:10px;align-items:baseline}.code{font:600 13px ui-monospace,Menlo,monospace;color:var(--accent)}
.watch{font-size:14px;color:var(--muted)}
.tabs{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
.tabs button{border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:999px;padding:6px 12px;cursor:pointer;font:inherit;font-size:14px}
.tabs button[aria-selected=true]{background:var(--accent);color:#fff;border-color:var(--accent)}
.badge{font-size:12px;padding:1px 7px;border-radius:999px;margin-left:4px}.badge.ok{background:var(--okbg);color:var(--ok)}.badge.ng{background:var(--ngbg);color:var(--ng)}.badge.muted{opacity:.7}
.tabs button[aria-selected=true] .badge{background:rgba(255,255,255,.25);color:#fff}
video{width:100%;max-height:70vh;background:#000;border-radius:8px}
.speed{margin:6px 0;font-size:14px;color:var(--muted)}.speed button,.ts{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:2px 8px;margin-left:4px;cursor:pointer;font:inherit;font-size:13px}
.ts{font-family:ui-monospace,Menlo,monospace;margin:0 6px 0 0}.marks{padding-left:20px;margin:0}.marks li{margin:3px 0}
.note,.muted{color:var(--muted);font-size:14px}.illus{margin-top:14px;border:2px dashed var(--line);border-radius:10px;padding:10px 12px}.illus-label{font-weight:700;font-size:13px;letter-spacing:.03em;margin:0 0 6px}
@media (max-width:800px){.wrap{grid-template-columns:1fr}nav{position:static;max-height:none}}
</style></head><body><div class="wrap">
<nav><h1>Video giao diện</h1><p class="lead">Tuần 5 · phiên GPU 14/10/2026</p><ul>{{TOC}}</ul></nav>
<main>
<h1>Video kiểm thử giao diện trạm QC (E2E)</h1>
<p class="lead">Trình duyệt tự động (Playwright) thao tác như người dùng thật trên stack thật: Triton chạy GPU RTX A6000 thuê, bản 0.5.0-rc1.
Mỗi kịch bản có tối đa 4 lượt quay (các tab trong từng thẻ):</p>
<ul class="lead">
<li><b>Trước sự cố:</b> chạy ngay sau khi bật hệ thống trên máy GPU, khi chưa có bài sự cố nào. Đây là lượt "sạch", cho thấy giao diện hoạt động bình thường.</li>
<li><b>Sau toàn bộ bài sự cố + nâng cấp:</b> chạy lại đúng 10 kịch bản sau khi hệ thống đã trải qua 27 bước kiểm (phần lớn là làm hỏng có chủ đích): kill -9 API và Triton, tắt Triton 24 s, cắt mạng 10 s, ổ đầy, model lỗi và tự rollback, hết thời gian suy luận, sao lưu/khôi phục dữ liệu, nâng cấp rồi quay lại phiên bản app. Mục đích: giao diện vẫn đúng sau khi hệ thống đã qua sự cố.</li>
<li><b>Sau reboot cả máy:</b> khởi động lại toàn bộ máy chủ (không chỉ container), để hệ thống tự bật lại, rồi chạy lại 10 kịch bản. Mục đích: không cần ai đăng nhập vào máy, giao diện và recipe đang chọn vẫn như trước.</li>
<li><b>Lượt người B (cài từ README):</b> trước các lượt trên, một agent AI độc lập, chưa biết gì về dự án, chỉ đọc README rồi tự cài hệ thống trên máy sạch và chạy test giao diện. Mục đích: kiểm tài liệu cài đặt có đủ để người khác làm theo. Lượt này dùng bản trước khi sửa hai lỗi tài liệu nên kết quả khác ba lượt kia (xem ghi chú trong từng thẻ).</li>
</ul>
<p class="lead">Trình duyệt tự động thao tác rất nhanh nên video chỉ dài 1–13 giây: dùng nút 0,25× để xem. Mốc thời gian được suy ra từ log máy chủ
(giờ của từng lần giao diện gọi API), là ước tính sai số khoảng ±0,5 s; bấm vào mốc để tua tới đó. Các video này được quay khi test đóng trình duyệt ngay lúc đạt điều kiện, nên khung cuối của một số video có thể hụt (rõ nhất ở E01). Mở trang bằng Chrome hoặc Firefox (video .webm).</p>
{{GROUPS}}
</main></div>
<script>
document.querySelectorAll('.card').forEach(card=>{
  card.querySelectorAll('[role=tab]').forEach(tab=>tab.addEventListener('click',()=>{
    card.querySelectorAll('[role=tab]').forEach(t=>t.setAttribute('aria-selected',String(t===tab)));
    card.querySelectorAll('.pane').forEach(p=>{p.hidden=p.id!==tab.dataset.pane;if(p.hidden){const v=p.querySelector('video');if(v)v.pause();}});
  }));
});
document.querySelectorAll('.pane').forEach(p=>{
  const v=p.querySelector('video'); if(!v) return;
  p.querySelectorAll('[data-rate]').forEach(b=>b.addEventListener('click',()=>{v.playbackRate=+b.dataset.rate;}));
  p.querySelectorAll('.ts').forEach(b=>b.addEventListener('click',()=>{v.pause();const go=()=>{v.currentTime=Math.min(+b.dataset.t,(v.duration||1e9)-0.05);};if(v.readyState>=1)go();else v.addEventListener('loadedmetadata',go,{once:true});}));
});
</script></body></html>
"""

if __name__ == '__main__':
    main()
