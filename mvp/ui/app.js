// VR-01 UI (W5-02). Trang tinh do Inspection API phuc vu tai /ui/; moi du lieu lay qua API bang token cua nguoi dung.
// Nguyen tac: loi ky thuat (FAILED/TIMEOUT/INDETERMINATE) KHONG BAO GIO hien giong OK/NG; UI chi goi API quan tri
// khi vai tro la admin (B5). Ten truong theo backend/openapi.v1.yaml.
'use strict';

const S = {token: null, me: null, screen: 'overview', active: null, ready: null, mgmt: null, timers: [],
  inspect: {sample: 0, file: null, run: null}, history: {state: '', product: '', items: [], next: null, detail: null}};
const SCREENS = [
  {id: 'overview', title: 'Tổng quan', hint: 'Sẵn sàng? Model nào?', roles: ['viewer', 'operator', 'admin']},
  {id: 'inspect', title: 'Kiểm tra', hint: 'Gửi ảnh, xem kết quả', roles: ['operator']},
  {id: 'history', title: 'Lịch sử', hint: 'Tra theo sản phẩm', roles: ['viewer', 'operator', 'admin']},
  {id: 'recipe', title: 'Recipe và model', hint: 'Chuyển, rollback', roles: ['admin']},
];
const TERMINAL = ['COMPLETED', 'FAILED', 'TIMEOUT', 'INDETERMINATE', 'CANCELLED'];
const STATES = ['RECEIVED', 'PROCESSING', ...TERMINAL];
const REASONS = {
  BACKEND_UNAVAILABLE: 'máy chủ suy luận (Triton) không phản hồi',
  ACTIVE_RECIPE_UNVERIFIED: 'chưa xác minh được recipe/model đang chọn',
  WARMUP_FAILED: 'model đang chọn chưa nạp/kiểm golden được',
  STORAGE_UNAVAILABLE: 'ổ lưu dữ liệu đầy hoặc lỗi ghi',
  SHUTTING_DOWN: 'dịch vụ đang dừng',
  UNREACHABLE: 'trình duyệt không kết nối được máy chủ kiểm tra',
};
const $ = (sel) => document.querySelector(sel);
const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const short = (h, n = 12) => h ? esc(String(h).slice(0, n)) + '…' : '—';
const fmtTime = (iso) => iso ? new Date(iso).toLocaleString('vi-VN', {hour12: false}) : '—';
const store = {
  get() { try { return sessionStorage.getItem('vr01.token'); } catch (e) { return null; } },
  set(v) { try { v ? sessionStorage.setItem('vr01.token', v) : sessionStorage.removeItem('vr01.token'); } catch (e) { /* bo qua */ } },
};

class HttpError extends Error {
  constructor(status, body) { super(body?.detail || body?.title || `HTTP ${status}`); this.status = status; this.body = body || {}; }
}

async function api(path, {method = 'GET', body, plane = 'inference', headers = {}} = {}) {
  const base = plane === 'management' ? S.mgmt : '';
  let res;
  try {
    res = await fetch(base + path, {method, cache: 'no-store', headers: {
      ...(S.token ? {Authorization: 'Bearer ' + S.token} : {}),
      ...(body !== undefined ? {'Content-Type': 'application/json'} : {}), ...headers},
      body: body !== undefined ? JSON.stringify(body) : undefined});
  } catch (e) {
    const err = new HttpError(0, {code: 'UNREACHABLE', detail: String(e)});
    err.plane = plane;
    throw err;
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  if (!res.ok) throw new HttpError(res.status, data);
  return data;
}

// ---------------------------------------------------------------- dang nhap
function loginView(msg) {
  return `<div class="card" style="max-width:560px">
    <h2>Đăng nhập trạm</h2>
    ${msg ? `<div class="banner ng" role="alert">${esc(msg)}</div>` : ''}
    <form id="loginForm" class="row" style="flex-direction:column;align-items:stretch">
      <label class="field">Token truy cập
        <input type="password" id="tokenInput" autocomplete="off" required data-testid="token-input"></label>
      <button class="btn primary" type="submit" data-testid="login-btn">Đăng nhập</button>
    </form>
    <p class="muted">Bản lab: token nằm trong <span class="mono">run/auth/lab-tokens.secret.json</span> (mỗi vai trò một token).
    Token chỉ giữ trong tab này và mất khi đóng tab. Bản sản xuất cần định danh do PKI/IT nhà máy cấp.</p></div>`;
}

async function login(token) {
  S.token = token;
  try {
    S.me = await api('/v1/me');
  } catch (e) {
    S.token = null; S.me = null; store.set(null);
    renderLogin(e.status === 401 ? 'Token không đúng.' : `Không đăng nhập được: ${e.message}`);
    return;
  }
  store.set(token);
  try {
    const cfg = await api('/ui/config.json');
    S.mgmt = `${location.protocol}//${location.hostname}:${cfg.management_port}`;
  } catch (e) { S.mgmt = `${location.protocol}//${location.hostname}:9443`; }
  $('#app').classList.remove('anon');
  $('#logoutBtn').hidden = false;
  $('#stationName').textContent = S.me.station_id;
  $('#roleChip').innerHTML = `<span class="chip">${esc(S.me.principal_id)} · ${esc(S.me.role)}</span>`;
  S.timers.push(setInterval(pollReady, 5000));
  await pollReady();
  go('overview');
}

function logout() {
  S.timers.forEach(clearInterval); S.timers = [];
  S.token = null; S.me = null; S.active = null; store.set(null);
  renderLogin();
}

function renderLogin(msg) {
  $('#app').classList.add('anon');
  $('#logoutBtn').hidden = true;
  $('#roleChip').innerHTML = ''; $('#readyChip').innerHTML = ''; $('#stationName').textContent = '';
  $('#nav').innerHTML = '';
  $('#main').innerHTML = loginView(msg);
  $('#loginForm').addEventListener('submit', (ev) => { ev.preventDefault(); login($('#tokenInput').value.trim()); });
  $('#tokenInput').focus();
}

// ---------------------------------------------------------------- khung chung
function go(screen) {
  const allowed = SCREENS.filter(s => s.roles.includes(S.me.role));
  if (!allowed.some(s => s.id === screen)) screen = 'overview';
  S.screen = screen;
  $('#nav').innerHTML = allowed.map(s => `<button data-screen="${s.id}" data-testid="nav-${s.id}" ${s.id === screen ? 'aria-current="page"' : ''}>
    ${esc(s.title)}<small>${esc(s.hint)}</small></button>`).join('');
  $('#nav').querySelectorAll('button').forEach(b => b.addEventListener('click', () => go(b.dataset.screen)));
  ({overview: renderOverview, inspect: renderInspect, history: renderHistory, recipe: renderRecipe})[screen]();
}

async function pollReady() {
  let r;
  try {
    const res = await fetch('/readyz', {cache: 'no-store'});
    r = await res.json();
  } catch (e) { r = {ready: false, reasons: ['UNREACHABLE']}; }
  S.ready = r;
  $('#readyChip').innerHTML = r.ready ? '<span class="chip ok">● Sẵn sàng</span>'
    : `<span class="chip ng" title="${esc(r.reasons.join(', '))}">● Chưa sẵn sàng</span>`;
  const banner = $('#readyBanner');
  if (banner) banner.outerHTML = readyBanner();
}

function readyBanner() {
  const r = S.ready || {ready: false, reasons: ['UNREACHABLE']};
  if (r.ready) return '<div class="banner ok" id="readyBanner" data-testid="ready-banner" data-ready="true">Hệ thống SẴN SÀNG nhận ảnh</div>';
  return `<div class="banner ng" id="readyBanner" data-testid="ready-banner" data-ready="false" role="alert">Hệ thống CHƯA SẴN SÀNG — không nhận ảnh mới
    <p>Lý do: ${r.reasons.map(c => `<span class="mono">${esc(c)}</span> (${esc(REASONS[c] || 'xem runbook')})`).join('; ')}.
    Sản phẩm trong lúc này <strong>chưa được kiểm</strong>; giữ lại theo quy trình QC. Trang tự kiểm lại mỗi 5 giây.</p></div>`;
}

function errorBanner(e, what) {
  if (e.status === 0 && e.plane === 'management') {
    return `<div class="banner ng" role="alert">Không kết nối được cổng quản trị <span class="mono">${esc(S.mgmt)}</span>
      <p>Bản lab dùng chứng chỉ tự ký: mở <a href="${esc(S.mgmt)}/healthz" target="_blank" rel="noopener">${esc(S.mgmt)}/healthz</a>
      một lần để trình duyệt chấp nhận chứng chỉ, rồi bấm Thử lại.</p></div>`;
  }
  if (e.status === 401) { setTimeout(() => logout(), 0); return ''; }
  return `<div class="banner ng" role="alert">Không tải được ${esc(what)}
    <p><span class="mono">${esc(e.body?.code || e.status)}</span> ${esc(e.message)}. Kết quả đã lưu không bị mất.</p></div>`;
}

const loading = (what) => `<div class="center"><div class="spinner" role="status" aria-label="Đang tải"></div><div>Đang tải ${esc(what)}…</div></div>`;

function decisionChip(r) {
  if (r.state === 'CANCELLED') return '<span class="chip" data-kind="cancelled">⊘ Đã hủy</span>';
  if (r.state === 'RECEIVED' || r.state === 'PROCESSING') return `<span class="chip" data-kind="pending">… ${esc(r.state)}</span>`;
  if (r.state !== 'COMPLETED' || !['OK', 'NG', 'REVIEW'].includes(r.decision)) {
    return `<span class="chip tech" data-kind="technical">⚙ Chưa có kết luận · ${esc(r.state)}</span>`;
  }
  return {OK: '<span class="chip ok" data-kind="OK">✓ OK</span>', NG: '<span class="chip ng" data-kind="NG">✕ NG</span>',
    REVIEW: '<span class="chip rv" data-kind="REVIEW">? REVIEW</span>'}[r.decision];
}

function activeCard(a) {
  return `<div class="card" data-testid="active-card"><h3>Recipe và model đang dùng</h3>
    <div class="big" data-testid="active-recipe">${esc(a.recipe_version)}</div>
    <dl style="margin-top:10px"><dt>Model</dt><dd>${esc(a.model.name)} · ${esc(a.model.version)}</dd>
    <dt>Digest model</dt><dd class="mono" title="${esc(a.model.manifest_sha256)}">${short(a.model.manifest_sha256, 16)}</dd>
    <dt>Revision</dt><dd class="mono" title="${esc(a.active_revision)}">${short(a.active_revision, 16)}</dd>
    <dt>Kích hoạt</dt><dd>${fmtTime(a.activated_at)}</dd></dl></div>`;
}

// ---------------------------------------------------------------- Tong quan (B1, B6, B7)
async function renderOverview() {
  const main = $('#main');
  main.innerHTML = `<h2>Tổng quan</h2>${readyBanner()}${loading('trạng thái trạm')}`;
  const st = encodeURIComponent(S.me.station_id);
  const [act, sum, hist] = await Promise.allSettled([
    api(`/v1/stations/${st}/active-recipe`), api(`/v1/stations/${st}/summary?since=${encodeURIComponent(localMidnight())}`), api(`/v1/stations/${st}/activations?limit=5`)]);
  if (S.screen !== 'overview') return;
  if (act.status === 'fulfilled') S.active = act.value;
  const parts = [];
  parts.push(act.status === 'fulfilled' ? activeCard(act.value)
    : `<div class="card"><h3>Recipe và model đang dùng</h3>${act.reason.status === 503
      ? '<p class="banner ng">Chưa xác minh được recipe đang chọn. Không gửi ảnh cho tới khi kỹ sư vận hành xác nhận.</p>'
      : errorBanner(act.reason, 'recipe đang dùng')}</div>`);
  if (sum.status === 'fulfilled') {
    const c = sum.value;
    parts.push(`<div class="card" data-testid="summary-card"><h3>Từ 00:00 hôm nay · ${c.total} lần kiểm</h3><div class="counts">
      <div class="count ok"><b data-testid="count-ok">${c.ok}</b>OK</div><div class="count ng"><b data-testid="count-ng">${c.ng}</b>NG</div>
      <div class="count rv"><b data-testid="count-review">${c.review}</b>REVIEW</div>
      <div class="count tech"><b data-testid="count-tech">${c.technical_error}</b>Chưa có kết luận</div>
      <div class="count"><b data-testid="count-cancelled">${c.cancelled}</b>Đã hủy</div><div class="count"><b>${c.in_progress}</b>Đang xử lý</div></div>
      ${c.technical_error ? `<p class="muted">${c.technical_error} sản phẩm bị lỗi kỹ thuật <strong>chưa có kết luận</strong>, cần kiểm lại theo quy trình QC.</p>
        <button class="btn" id="seeTech">Xem sản phẩm chưa có kết luận</button>` : ''}</div>`);
  } else parts.push(`<div class="card">${errorBanner(sum.reason, 'số đếm')}</div>`);
  if (hist.status === 'fulfilled') {
    const items = hist.value.items;
    const auto = items[0] && items[0].kind === 'auto_rollback';
    parts.push(`<div class="card" data-testid="activation-card"><h3>Lần chuyển recipe gần đây</h3>
      ${auto ? `<div class="banner rv" data-testid="auto-rollback-warning" role="alert">Hệ thống đã TỰ ROLLBACK về ${esc(items[0].to_recipe_version)}
        <p>${esc(items[0].reason)} · ${fmtTime(items[0].at)}. Báo kỹ sư vận hành kiểm model ${esc(items[0].from_recipe_version)}.</p></div>` : ''}
      ${items.length ? `<ul style="margin:0;padding-left:20px">${items.map(i => `<li><span class="mono">${esc(i.from_recipe_version || '—')} → ${esc(i.to_recipe_version)}</span>
        <br><span class="muted">${esc(kindText(i.kind))} · ${esc(i.actor)} · ${fmtTime(i.at)} · ${esc(i.reason)}</span></li>`).join('')}</ul>` : '<p class="muted">Chưa có.</p>'}</div>`);
  } else parts.push(`<div class="card">${errorBanner(hist.reason, 'lịch sử chuyển recipe')}</div>`);
  main.innerHTML = `<h2>Tổng quan</h2>${readyBanner()}<div class="grid">${parts.join('')}</div>`;
  const b = $('#seeTech');
  if (b) b.addEventListener('click', () => { S.history.state = 'TECH'; S.history.product = ''; go('history'); });
}
const localMidnight = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d.toISOString(); };
const kindText = (k) => ({initial: 'Khởi tạo', activate: 'Chuyển', rollback: 'Rollback thủ công', auto_rollback: 'TỰ ROLLBACK'}[k] || k);

// ---------------------------------------------------------------- Kiem tra (B2) - chi operator
const SAMPLES = [['Mẫu sáng', 220], ['Mẫu trung bình', 128], ['Mẫu tối', 40]];
function sampleDataUrl(level) {
  const c = document.createElement('canvas'); c.width = c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = `rgb(${level},${level},${level})`; g.fillRect(0, 0, 64, 64);
  g.fillStyle = `rgb(${Math.min(255, level + 25)},${Math.min(255, level + 25)},${Math.min(255, level + 25)})`;
  g.fillRect(12, 12, 40, 40);  // de anh nhin giong mot bo mach; diem model mau van phu thuoc do sang trung binh
  return c.toDataURL('image/png');
}
const newId = (p) => `${p}-${new Date().toISOString().replace(/[-:.TZ]/g, '').slice(0, 14)}-${Math.random().toString(36).slice(2, 8)}`;

function renderInspect() {
  const I = S.inspect;
  if (I.run) return renderRun();
  $('#main').innerHTML = `<h2>Kiểm tra</h2>${readyBanner()}
    <form class="card" id="inspectForm"><h3>1. Chọn ảnh</h3><div class="thumbs">${SAMPLES.map((s, i) =>
      `<button type="button" class="thumb" aria-pressed="${!I.file && I.sample === i}" data-sample="${i}" data-testid="sample-${i}">
        <img alt="" src="${sampleDataUrl(s[1])}">${esc(s[0])}</button>`).join('')}
      <label class="thumb" aria-pressed="${!!I.file}"><span style="display:flex;height:84px;align-items:center;justify-content:center">📷</span>
        ${I.file ? esc(I.file.name).slice(0, 18) : 'Ảnh từ máy'}<input type="file" id="fileInput" accept="image/png,image/jpeg" hidden></label></div>
      <h3 style="margin-top:18px">2. Mã sản phẩm</h3>
      <input type="text" id="productInput" required pattern="[A-Za-z0-9._\\-]{1,64}" value="${esc(I.product || newId('PCB1-SN'))}" aria-label="Mã sản phẩm" data-testid="product-input">
      <p class="muted">Recipe gửi kèm lấy từ hệ thống lúc gửi, không nhập tay: <span class="mono" id="recipeNow">${esc(S.active?.recipe_version || '…')}</span></p>
      <button class="btn primary" type="submit" data-testid="submit-btn" ${S.ready?.ready ? '' : 'disabled'}>Gửi kiểm tra</button>
      ${S.ready?.ready ? '' : '<p class="muted">Nút gửi tắt vì hệ thống chưa sẵn sàng.</p>'}</form>`;
  document.querySelectorAll('[data-sample]').forEach(b => b.addEventListener('click', () => {
    I.sample = +b.dataset.sample; I.file = null; I.product = $('#productInput').value; renderInspect(); }));
  $('#fileInput').addEventListener('change', (ev) => { I.file = ev.target.files[0] || null; I.product = $('#productInput').value; renderInspect(); });
  $('#inspectForm').addEventListener('submit', (ev) => { ev.preventDefault(); startRun($('#productInput').value.trim(), null); });
  if (!S.active) api(`/v1/stations/${encodeURIComponent(S.me.station_id)}/active-recipe`).then(a => {
    S.active = a; const el = $('#recipeNow'); if (el) el.textContent = a.recipe_version; }).catch(() => {});
}

async function imagePayload() {
  const I = S.inspect;
  if (I.file) {
    if (!['image/png', 'image/jpeg'].includes(I.file.type)) throw new HttpError(400, {code: 'UNSUPPORTED_IMAGE', detail: 'Chỉ nhận PNG hoặc JPEG.'});
    const buf = new Uint8Array(await I.file.arrayBuffer());
    let bin = ''; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
    return {content_type: I.file.type, data_base64: btoa(bin)};
  }
  return {content_type: 'image/png', data_base64: sampleDataUrl(SAMPLES[I.sample][1]).split(',')[1]};
}

async function startRun(product, retryOf) {
  const I = S.inspect;
  I.product = product;
  I.run = {request_id: newId('ui'), product, retry_of: retryOf, phase: 'sending', status: null, result: null, error: null};
  renderRun();
  let image;
  try { image = await imagePayload(); } catch (e) { I.run.phase = 'error'; I.run.error = e; return renderRun(); }
  await submitRun(image, 0);
}

async function submitRun(image, attempt) {
  const run = S.inspect.run;
  try {
    if (!S.active || attempt > 0) S.active = await api(`/v1/stations/${encodeURIComponent(S.me.station_id)}/active-recipe`);
    const body = {request_id: run.request_id, product_id: run.product, product_type: S.me.product_types[0],
      recipe_version: S.active.recipe_version, captured_at: new Date().toISOString(), station_id: S.me.station_id, image};
    if (run.retry_of) body.retry_of = run.retry_of;
    run.status = await api('/v1/inspections', {method: 'POST', body});
    run.phase = 'processing';
  } catch (e) {
    // Recipe vua doi giua luc lay va luc gui: lay recipe moi, gui lai CUNG request_id (chua co ban ghi nao).
    if (e.status === 409 && e.body.code === 'RECIPE_VERSION_MISMATCH' && attempt < 2) return submitRun(image, attempt + 1);
    run.phase = 'error'; run.error = e; run.image = image;
    return renderRun();
  }
  renderRun();
  pollRun(run);
}

async function pollRun(run) {
  while (S.inspect.run === run && !TERMINAL.includes(run.status.state)) {
    await new Promise(r => setTimeout(r, 400));
    try { run.status = await api(`/v1/inspections/${encodeURIComponent(run.request_id)}`); } catch (e) { run.pollError = e; }
    if (S.screen === 'inspect' && S.inspect.run === run) renderRun();
  }
  if (S.inspect.run !== run) return;
  try { run.result = await api(`/v1/inspections/${encodeURIComponent(run.request_id)}/result`); } catch (e) { run.pollError = e; }
  run.phase = 'done';
  if (S.screen === 'inspect') renderRun();
}

function traceCard(r) {
  const l = r.lineage;
  return `<div class="card" data-testid="trace-card"><h3>Truy vết</h3><dl>
    <dt>Sản phẩm</dt><dd class="mono">${esc(l.product_id)}</dd><dt>Request</dt><dd class="mono" data-testid="request-id">${esc(r.request_id)}</dd>
    <dt>Trace</dt><dd class="mono">${esc(l.trace_id)}</dd><dt>Recipe</dt><dd class="mono">${esc(l.recipe.name)}@${esc(l.recipe.version)}</dd>
    <dt>Model</dt><dd class="mono" data-testid="lineage-model">${esc(l.model.name)}@${esc(l.model.version)} · ${short(l.model.manifest_sha256)}</dd>
    <dt>Ảnh (SHA-256)</dt><dd class="mono">${short(l.input_sha256, 16)}</dd><dt>Người gửi</dt><dd>${esc(l.submitted_by)}</dd>
    ${r.retry_of ? `<dt>Kiểm lại của</dt><dd class="mono">${esc(r.retry_of)}</dd>` : ''}
    <dt>Thời gian</dt><dd>chờ ${esc(r.timing_ms.queue ?? '—')} ms · suy luận ${esc(r.timing_ms.inference ?? '—')} ms · tổng ${esc(r.timing_ms.total ?? '—')} ms</dd>
    <dt>Nhận lúc</dt><dd>${fmtTime(r.received_at)}</dd></dl></div>`;
}

function verdictCard(r) {
  if (r.state === 'COMPLETED' && ['OK', 'NG', 'REVIEW'].includes(r.decision)) {
    const m = {OK: ['ok', 'OK', 'Đạt'], NG: ['ng', 'NG', 'Không đạt'], REVIEW: ['rv', 'REVIEW', 'Cần người kiểm lại (điểm sát ngưỡng)']}[r.decision];
    return `<div class="card ${m[0]}" style="border-width:2px" data-testid="verdict-card" data-verdict="${m[1]}"><div class="center">
      <div class="verdict">${m[1]}</div><div>${m[2]}</div><div>Điểm ${esc(r.score)} · ngưỡng ${esc(r.threshold)} (REVIEW ± ${esc(r.review_band)})</div></div></div>`;
  }
  const txt = r.state === 'CANCELLED' ? ['ĐÃ HỦY', 'Lần kiểm này đã bị hủy, không có kết luận.']
    : ['CHƯA CÓ KẾT LUẬN', `Lỗi kỹ thuật (${r.state}${r.reason ? ' · ' + r.reason : ''}). Sản phẩm này CHƯA được kiểm — không coi là OK hay NG.`];
  return `<div class="card tech" style="border-width:2px" data-testid="verdict-card" data-verdict="${r.state === 'CANCELLED' ? 'CANCELLED' : 'TECHNICAL'}"><div class="center">
    <div class="verdict" style="font-size:40px">${txt[0]}</div><div>${esc(txt[1])}</div>
    <button class="btn primary" id="retryBtn" data-testid="retry-btn">Kiểm lại sản phẩm này</button></div></div>`;
}

function renderRun() {
  const run = S.inspect.run;
  const main = $('#main');
  const next = '<button class="btn" id="nextBtn" data-testid="next-btn">Kiểm sản phẩm tiếp theo</button>';
  if (run.phase === 'sending') {
    main.innerHTML = `<h2>Kiểm tra</h2><div class="card center"><div class="spinner" role="status"></div><div>Đang gửi ảnh…</div></div>`;
  } else if (run.phase === 'error') {
    const e = run.error; const code = e.body?.code || 'UNREACHABLE';
    const retryable = e.status === 0 || e.status === 429 || e.status === 503;
    main.innerHTML = `<h2>Kiểm tra</h2><div class="banner ng" role="alert" data-testid="submit-error" data-code="${esc(code)}">Chưa gửi được — sản phẩm CHƯA được kiểm
      <p><span class="mono">${esc(e.status)} ${esc(code)}</span>: ${esc(e.message)}</p>
      <p>${retryable ? 'Có thể gửi lại (cùng mã request, hệ thống không tạo bản ghi trùng).' : 'Sửa đầu vào rồi gửi lần mới.'}</p></div>
      <div class="row">${retryable ? '<button class="btn primary" id="resendBtn">Gửi lại</button>' : ''}${next}</div>`;
    const rb = $('#resendBtn');
    if (rb) rb.addEventListener('click', () => { run.phase = 'sending'; renderRun(); submitRun(run.image, 0); });
  } else if (run.phase === 'processing') {
    main.innerHTML = `<h2>Kiểm tra</h2><div class="card"><div class="center"><div class="spinner" role="status"></div>
      <div class="big">Đã nhận, đang kiểm</div><div class="mono">${esc(run.request_id)}</div>
      <div class="muted">Trạng thái: <span data-testid="run-state">${esc(run.status.state)}</span></div>
      <button class="btn danger" id="cancelBtn" data-testid="cancel-btn">Hủy lần kiểm này</button></div></div>`;
    $('#cancelBtn').addEventListener('click', () => confirmDialog({title: 'Hủy lần kiểm này?', body: 'Sản phẩm sẽ không có kết luận và phải kiểm lại.',
      needReason: true, ok: 'Hủy lần kiểm', onOk: async (reason) => {
        try { run.status = await api(`/v1/inspections/${encodeURIComponent(run.request_id)}/cancel`, {method: 'POST', body: {reason}}); }
        catch (e) { if (!(e.status === 409 && e.body.code === 'ALREADY_TERMINAL')) throw e; }
      }}));
  } else {
    const r = run.result;
    main.innerHTML = `<h2>Kiểm tra</h2>${r ? `<div class="grid">${verdictCard(r)}${traceCard(r)}</div>`
      : errorBanner(run.pollError || new HttpError(0, {}), 'kết quả')}<div class="row" style="margin-top:16px">${next}</div>`;
    const rt = $('#retryBtn');
    if (rt) rt.addEventListener('click', () => startRun(run.product, run.request_id));
  }
  const nb = $('#nextBtn');
  if (nb) nb.addEventListener('click', () => { S.inspect.run = null; S.inspect.product = ''; renderInspect(); });
}

// ---------------------------------------------------------------- Lich su (B3)
async function renderHistory(append) {
  const H = S.history;
  if (H.detail) return renderDetail();
  const main = $('#main');
  const opts = [['', 'Tất cả'], ['TECH', 'Chưa có kết luận (lỗi kỹ thuật)'], ...STATES.map(s => [s, s])];
  if (!append) {
    main.innerHTML = `<h2>Lịch sử</h2><form class="row card" id="histForm" style="margin-bottom:16px">
      <label class="field">Trạng thái<select id="stateSel" data-testid="state-filter">${opts.map(([v, t]) =>
        `<option value="${v}" ${H.state === v ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></label>
      <label class="field">Mã sản phẩm<input type="text" id="prodInput" value="${esc(H.product)}" placeholder="vd PCB1-SN-0001" data-testid="product-filter"></label>
      <button class="btn primary" type="submit" style="align-self:flex-end">Lọc</button></form><div id="histBody">${loading('lịch sử')}</div>`;
    $('#histForm').addEventListener('submit', (ev) => { ev.preventDefault();
      H.state = $('#stateSel').value; H.product = $('#prodInput').value.trim(); H.items = []; H.next = null; renderHistory(); });
    H.items = []; H.next = null;
  }
  try {
    const states = H.state === 'TECH' ? ['FAILED', 'TIMEOUT', 'INDETERMINATE'] : [H.state];
    const pages = await Promise.all(states.map(s => {
      const q = new URLSearchParams({limit: '20'});
      if (s) q.set('state', s);
      if (H.product) q.set('product_id', H.product);
      if (append && H.next && states.length === 1) q.set('cursor', H.next);
      return api('/v1/inspections?' + q);
    }));
    const items = pages.flatMap(p => p.items).sort((a, b) => b.received_at.localeCompare(a.received_at));
    H.items = append ? H.items.concat(items) : items;
    H.next = states.length === 1 ? pages[0].next_cursor : null;
  } catch (e) {
    $('#histBody').innerHTML = errorBanner(e, 'lịch sử');
    return;
  }
  if (S.screen !== 'history') return;
  $('#histBody').innerHTML = H.items.length ? `<div class="card tablewrap"><table data-testid="history-table"><thead><tr>
      <th>Nhận lúc</th><th>Sản phẩm</th><th>Kết quả</th><th>Request</th></tr></thead><tbody>
      ${H.items.map((r, i) => `<tr class="click" tabindex="0" data-i="${i}" data-request-id="${esc(r.request_id)}"><td>${fmtTime(r.received_at)}</td>
        <td class="mono">${esc(r.product_id)}</td><td>${decisionChip(r)}</td><td class="mono">${esc(r.request_id)}</td></tr>`).join('')}
      </tbody></table>${H.next ? '<p><button class="btn" id="moreBtn">Tải thêm</button></p>' : ''}</div>`
    : '<div class="card"><p class="muted" data-testid="history-empty">Không có lần kiểm nào khớp bộ lọc.</p></div>';
  document.querySelectorAll('#histBody tr.click').forEach(tr => {
    const open = () => { H.detail = H.items[+tr.dataset.i]; renderDetail(); };
    tr.addEventListener('click', open);
    tr.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') open(); });
  });
  const mb = $('#moreBtn');
  if (mb) mb.addEventListener('click', () => renderHistory(true));
}

async function renderDetail() {
  const H = S.history; const d = H.detail;
  const main = $('#main');
  main.innerHTML = `<h2>Chi tiết lần kiểm</h2>${loading('chi tiết')}`;
  let body;
  try {
    if (TERMINAL.includes(d.state)) {
      const r = await api(`/v1/inspections/${encodeURIComponent(d.request_id)}/result`);
      body = `<div class="grid">${verdictCard(r)}${traceCard({...r, retry_of: d.retry_of})}</div>`;
    } else {
      const s = await api(`/v1/inspections/${encodeURIComponent(d.request_id)}`);
      body = `<div class="card"><p>${decisionChip(s)}</p><p class="mono">${esc(s.request_id)}</p><p class="muted">Chưa kết thúc; mở lại sau vài giây.</p></div>`;
    }
  } catch (e) { body = errorBanner(e, 'chi tiết'); }
  main.innerHTML = `<h2>Chi tiết lần kiểm</h2><p><button class="btn small" id="backBtn" data-testid="back-btn">← Về danh sách</button></p>${body}`;
  const rt = $('#retryBtn');
  if (rt) {
    if (S.me.role === 'operator') rt.addEventListener('click', () => { H.detail = null; go('inspect'); startRun(d.product_id, d.request_id); });
    else rt.remove();  // chi operator duoc gui anh
  }
  $('#backBtn').addEventListener('click', () => { H.detail = null; renderHistory(); });
}

// ---------------------------------------------------------------- Recipe va model (B4) - chi admin, qua cong quan tri
async function renderRecipe() {
  const main = $('#main');
  main.innerHTML = `<h2>Recipe và model</h2>${loading('recipe')}`;
  const st = encodeURIComponent(S.me.station_id);
  let station, recipes;
  try {
    [station, recipes] = await Promise.all([api(`/v1/admin/stations/${st}`, {plane: 'management'}),
      api('/v1/admin/recipes', {plane: 'management'})]);
  } catch (e) {
    main.innerHTML = `<h2>Recipe và model</h2>${errorBanner(e, 'recipe')}<button class="btn" id="againBtn">Thử lại</button>`;
    $('#againBtn').addEventListener('click', renderRecipe);
    return;
  }
  if (S.screen !== 'recipe') return;
  const a = station.active;
  main.innerHTML = `<h2>Recipe và model</h2>${readyBanner()}<div class="grid">${activeCard(a)}
    <div class="card"><h3>Recipe đã duyệt trong kho</h3><div class="tablewrap"><table data-testid="recipe-table"><thead><tr><th>Recipe</th><th>Model</th><th></th></tr></thead><tbody>
    ${recipes.items.map(r => { const ref = `${r.recipe.name}@${r.recipe.version}`; return `<tr><td class="mono">${esc(ref)}</td>
      <td class="mono">${esc(r.model.name)}@${esc(r.model.version)}</td><td>${r.active ? '<span class="chip ok">Đang dùng</span>'
      : `<button class="btn small" data-activate="${esc(ref)}" data-testid="activate-${esc(r.recipe.name)}">Chuyển sang</button>`}</td></tr>`; }).join('')}
    </tbody></table></div>
    <p><button class="btn danger" id="rollbackBtn" data-testid="rollback-btn">Rollback về recipe trước</button></p></div></div>
    <div class="card" style="margin-top:16px"><h3>Lịch sử chuyển (từ ledger)</h3><div class="tablewrap"><table><thead><tr><th>Lúc</th><th>Từ → tới</th><th>Ai</th><th>Lý do</th><th>Golden</th></tr></thead><tbody>
    ${station.history.map(h => `<tr><td>${fmtTime(h.at)}</td><td class="mono">${esc(h.from_recipe ? h.from_recipe.name + '@' + h.from_recipe.version : '—')} → ${esc(h.to_recipe.name)}@${esc(h.to_recipe.version)}</td>
      <td>${esc(h.actor)}</td><td>${esc(h.reason)}</td><td>${h.golden?.passed ? '✓' : '✕'}</td></tr>`).join('')}</tbody></table></div></div>`;
  document.querySelectorAll('[data-activate]').forEach(b => b.addEventListener('click', () => {
    const [name, version] = b.dataset.activate.split('@');
    confirmDialog({title: `Chuyển sang ${b.dataset.activate}?`, needReason: true, ok: 'Chuyển recipe',
      body: `Đang dùng ${a.recipe_version}. Hệ thống nạp model mới, kiểm golden, rồi mới chuyển; request đang chạy vẫn hoàn tất trên model cũ. Nếu golden không đạt thì giữ recipe cũ.`,
      onOk: async (reason) => {
        const r = await api(`/v1/admin/stations/${st}/activation`, {method: 'POST', plane: 'management',
          headers: {'If-Match': `"${a.active_revision}"`}, body: {recipe_name: name, recipe_version: version, reason}});
        S.active = null;
        return `Đã chuyển sang ${r.to_recipe.name}@${r.to_recipe.version}.`;
      }, after: renderRecipe});
  }));
  $('#rollbackBtn').addEventListener('click', () => confirmDialog({title: 'Rollback về recipe trước?', needReason: true, ok: 'Rollback',
    body: `Đang dùng ${a.recipe_version}. Hệ thống quay về recipe đã dùng trước đó, có kiểm golden.`,
    onOk: async (reason) => {
      const r = await api(`/v1/admin/stations/${st}/rollback`, {method: 'POST', plane: 'management', body: {reason}});
      S.active = null;
      return `Đã rollback về ${r.to_recipe.name}@${r.to_recipe.version}.`;
    }, after: renderRecipe}));
}

// ---------------------------------------------------------------- hop thoai xac nhan co ly do
function confirmDialog({title, body, needReason, ok, onOk, after}) {
  const d = document.createElement('div');
  d.className = 'dialog'; d.setAttribute('role', 'dialog'); d.setAttribute('aria-modal', 'true'); d.dataset.testid = 'confirm-dialog';
  d.innerHTML = `<form class="card"><h2>${esc(title)}</h2><p>${esc(body)}</p>
    ${needReason ? '<label class="field">Lý do (bắt buộc, ghi vào audit)<textarea id="reasonInput" required minlength="3" maxlength="200" data-testid="reason-input"></textarea></label>' : ''}
    <div id="dlgMsg"></div><div class="row" style="margin-top:12px"><button class="btn primary" type="submit" data-testid="confirm-btn">${esc(ok)}</button>
    <button class="btn" type="button" id="dlgCancel">Đóng</button></div></form>`;
  document.body.appendChild(d);
  const close = () => { d.remove(); if (after) after(); };
  d.querySelector('#dlgCancel').addEventListener('click', close);
  d.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') close(); });
  const f = d.querySelector('form');
  (d.querySelector('#reasonInput') || d.querySelector('[data-testid=confirm-btn]')).focus();
  f.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const btn = f.querySelector('[type=submit]'); btn.disabled = true;
    const msg = d.querySelector('#dlgMsg');
    msg.innerHTML = '<div class="row"><div class="spinner" role="status"></div><span>Đang thực hiện…</span></div>';
    try {
      const text = await onOk(needReason ? d.querySelector('#reasonInput').value.trim() : null);
      msg.innerHTML = `<div class="banner ok" data-testid="dialog-ok">${esc(text || 'Đã xong.')}</div>`;
      btn.remove();
    } catch (e) {
      msg.innerHTML = `<div class="banner ng" data-testid="dialog-error" data-code="${esc(e.body?.code || e.status)}">Không thực hiện được
        <p><span class="mono">${esc(e.status)} ${esc(e.body?.code || '')}</span>: ${esc(e.message)}</p></div>`;
      btn.disabled = false;
    }
  });
}

// ---------------------------------------------------------------- khoi dong
$('#logoutBtn').addEventListener('click', logout);
const saved = store.get();
if (saved) login(saved); else renderLogin();
