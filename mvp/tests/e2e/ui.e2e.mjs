// E2E test cho UI VR-01 (W5-02, B1-B7) tren mot stack DANG CHAY (Compose, K8s hoac tests/local_stack.py).
// Chay:  VR01_RUN_DIR=../../run VR01_UI_URL=https://localhost:8443 node --test ui.e2e.mjs
// Tuy chon: VR01_CHROMIUM=<duong dan chromium>  (bo trong = trinh duyet do `npx playwright-core install chromium` tai)
//           VR01_STOP_BACKEND / VR01_START_BACKEND = lenh shell dung/bat inference server that (vd docker stop vr01-mvp-triton-1)
//           VR01_E2E_OUT=<thu muc> ghi ket qua JSON + anh chup man hinh lam evidence.
// Test lam thay doi trang thai stack (chuyen recipe, tu rollback) nhung luon tra ve recipe-a khi xong.
import {test, before, after} from 'node:test';
import assert from 'node:assert/strict';
import {execSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {chromium} from 'playwright-core';

const RUN = process.env.VR01_RUN_DIR || '../../run';
const BASE = (process.env.VR01_UI_URL || 'https://localhost:8443').replace(/\/$/, '');
const OUT = process.env.VR01_E2E_OUT || '';
const VIDEO = process.env.VR01_E2E_VIDEO || '';  // thu muc: quay video webm moi kich ban giao dien (demo evidence)
const toks = JSON.parse(fs.readFileSync(path.join(RUN, 'auth', 'lab-tokens.secret.json'), 'utf8'));
const TOKEN = Object.fromEntries(Object.values(toks).map(v => [v.role, v.token]));
const results = [];
let browser, mgmtPort, station, current = '';
const pages = [];

async function apiCall(p, {role = 'admin', method = 'GET', body, mgmt = false} = {}) {
  // Goi API truc tiep qua trinh duyet (bo qua chung chi lab) de chuan bi/kiem du lieu.
  const ctx = await browser.newContext({ignoreHTTPSErrors: true});
  const url = mgmt ? BASE.replace(/:\d+$/, ':' + mgmtPort) + p : BASE + p;
  const r = await ctx.request.fetch(url, {method, headers: {Authorization: 'Bearer ' + TOKEN[role]}, data: body});
  const out = {status: r.status(), body: await r.json().catch(() => null)};
  await ctx.close();
  return out;
}

async function ensureRecipe(name) {
  const a = await apiCall(`/v1/stations/${station}/active-recipe`);
  if (a.body?.recipe.name === name) return;
  const r = await apiCall(`/v1/admin/stations/${station}/activation`, {method: 'POST', mgmt: true,
    body: {recipe_name: name, recipe_version: '0.1.0', reason: 'e2e setup'}});
  assert.equal(r.status, 200, JSON.stringify(r.body));
}

async function open(role, {stub} = {}) {
  const ctx = await browser.newContext({ignoreHTTPSErrors: true, viewport: {width: 1280, height: 900},
    ...(VIDEO ? {recordVideo: {dir: VIDEO, size: {width: 1280, height: 900}}} : {})});
  const page = await ctx.newPage();
  pages.push([current, page]);
  const requests = [];
  page.on('request', r => requests.push(r.url()));
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  if (stub) await stub(page);
  await page.goto(BASE + '/ui/');
  if (role) {
    await page.getByTestId('token-input').fill(TOKEN[role]);
    await page.getByTestId('login-btn').click();
    await page.getByTestId('role-chip').getByText(role).waitFor();
  }
  return {ctx, page, requests, errors};
}

async function shot(page, name) {
  if (OUT) await page.screenshot({path: path.join(OUT, name + '.png'), fullPage: true});
}

function record(name, opts, fn) {
  if (typeof opts === 'function') [fn, opts] = [opts, {}];
  test(name, opts, async (t) => {
    const t0 = Date.now();
    current = name.split(' ')[0];
    try { if (await fn(t) === 'SKIP') { results.push({name, result: 'SKIP'}); return; } results.push({name, result: 'PASS', ms: Date.now() - t0}); }
    catch (e) { results.push({name, result: 'FAIL', ms: Date.now() - t0, error: String(e).slice(0, 500)}); throw e; }
  });
}

async function submitSample(page, sample, product) {
  await page.getByTestId('nav-inspect').click();
  await page.getByTestId(`sample-${sample}`).click();
  await page.getByTestId('product-input').fill(product);
  await page.getByTestId('submit-btn').click();
  const card = page.getByTestId('verdict-card');
  await card.waitFor({timeout: 30000});
  return {verdict: await card.getAttribute('data-verdict'), request_id: await page.getByTestId('request-id').textContent()};
}

before(async () => {
  browser = await chromium.launch({executablePath: process.env.VR01_CHROMIUM || undefined});
  const cfg = await apiCall('/ui/config.json');
  mgmtPort = cfg.body.management_port;
  station = (await apiCall('/v1/me', {role: 'viewer'})).body.station_id;
  if (OUT) fs.mkdirSync(OUT, {recursive: true});
  await ensureRecipe('recipe-a');
});

after(async () => {
  try { await ensureRecipe('recipe-a'); } finally { await browser?.close(); }
  if (VIDEO) {  // dat ten video theo kich ban: E04-1.webm ...
    const seen = {};
    for (const [name, page] of pages) {
      const v = page.video(); if (!v) continue;
      seen[name] = (seen[name] || 0) + 1;
      try { fs.renameSync(await v.path(), path.join(VIDEO, `${name}-${seen[name]}.webm`)); } catch (e) { /* video co the khong ton tai */ }
    }
  }
  if (OUT) fs.writeFileSync(path.join(OUT, 'e2e-results.json'), JSON.stringify(
    {base: BASE, at: new Date().toISOString(), passed: results.filter(r => r.result === 'PASS').length,
      failed: results.filter(r => r.result === 'FAIL').length, results}, null, 2));
});

record('E01 token sai bi tu choi, khong vao duoc man hinh nao', async () => {
  const {ctx, page} = await open(null);
  await page.getByTestId('token-input').fill('sai-token');
  await page.getByTestId('login-btn').click();
  await page.getByRole('alert').getByText('Token không đúng').waitFor();
  assert.equal(await page.getByTestId('nav-overview').count(), 0);
  await ctx.close();
});

record('E02 B1/B5 viewer: thay trang thai + recipe dang chon, chi co Tong quan/Lich su, khong goi cong quan tri', async () => {
  const {ctx, page, requests, errors} = await open('viewer');
  await page.getByTestId('active-recipe').getByText('recipe-a@0.1.0').waitFor();
  assert.equal(await page.getByTestId('ready-banner').getAttribute('data-ready'), 'true');
  for (const s of ['inspect', 'recipe']) assert.equal(await page.getByTestId(`nav-${s}`).count(), 0, s);
  await page.getByTestId('nav-history').click();
  await page.waitForLoadState('networkidle');
  await shot(page, 'E02-viewer');
  assert.deepEqual(requests.filter(u => u.includes(':' + mgmtPort)), []);
  assert.deepEqual(errors, []);
  await ctx.close();
});

record('E03 B1 khi /readyz bao chua san sang: banner do kem ly do, nut gui bi tat', async () => {
  const {ctx, page} = await open('operator', {stub: async (p) => p.route('**/readyz', r => r.fulfill(
    {status: 503, contentType: 'application/json', body: JSON.stringify({ready: false, reasons: ['BACKEND_UNAVAILABLE']})}))});
  const b = page.getByTestId('ready-banner');
  await b.getByText('BACKEND_UNAVAILABLE').waitFor();
  assert.equal(await b.getAttribute('data-ready'), 'false');
  await page.getByTestId('nav-inspect').click();
  assert.equal(await page.getByTestId('submit-btn').isDisabled(), true);
  await shot(page, 'E03-not-ready');
  await ctx.close();
});

record('E04 B2/B3 operator gui anh -> OK/NG/REVIEW kem truy vet; tim lai trong Lich su, chi tiet khop', async () => {
  const {ctx, page, requests} = await open('operator');
  const product = 'PCB1-SN-E2E-' + Date.now();
  const r = await submitSample(page, 0, product);
  assert.ok(['OK', 'NG', 'REVIEW'].includes(r.verdict), r.verdict);
  assert.match(await page.getByTestId('lineage-model').textContent(), /^model-a@0\.1\.0/);
  await shot(page, 'E04-result');
  await page.getByTestId('nav-history').click();
  await page.getByTestId('product-filter').fill(product);
  await page.getByRole('button', {name: 'Lọc'}).click();
  await page.locator(`tr[data-request-id="${r.request_id}"]`).click();
  await page.getByTestId('trace-card').getByText(r.request_id).waitFor();
  assert.equal(await page.getByTestId('verdict-card').getAttribute('data-verdict'), r.verdict);
  const res = await apiCall(`/v1/inspections/${r.request_id}/result`, {role: 'viewer'});
  assert.equal(res.body.decision, r.verdict);
  assert.equal(res.body.lineage.submitted_by, 'cam-sim-01');
  assert.deepEqual(requests.filter(u => u.includes(':' + mgmtPort)), []);
  await ctx.close();
});

record('E05 B4 admin chuyen recipe qua hop thoai co ly do, rollback; audit ghi nguoi + ly do', async () => {
  const {ctx, page, errors} = await open('admin');
  await page.getByTestId('nav-recipe').click();
  await page.getByTestId('activate-recipe-b').click();
  await page.getByTestId('reason-input').fill('e2e chuyen sang b');
  await page.getByTestId('confirm-btn').click();
  await page.getByTestId('dialog-ok').waitFor({timeout: 30000});
  await page.getByRole('button', {name: 'Đóng'}).click();
  await page.getByTestId('active-recipe').getByText('recipe-b@0.1.0').waitFor();
  await shot(page, 'E05-recipe-b');
  await page.getByTestId('rollback-btn').click();
  await page.getByTestId('reason-input').fill('e2e rollback ve a');
  await page.getByTestId('confirm-btn').click();
  await page.getByTestId('dialog-ok').waitFor({timeout: 30000});
  await page.getByRole('button', {name: 'Đóng'}).click();
  await page.getByTestId('active-recipe').getByText('recipe-a@0.1.0').waitFor();
  const audit = (await apiCall('/v1/admin/audit?limit=20', {mgmt: true})).body.items;
  assert.ok(audit.some(a => a.action === 'activate' && a.outcome === 'OK' && a.actor === 'ops-admin-01'));
  assert.ok(audit.some(a => a.action === 'rollback' && a.outcome === 'OK' && a.actor === 'ops-admin-01'));
  const hist = (await apiCall(`/v1/stations/${station}/activations?limit=2`, {role: 'viewer'})).body.items;
  assert.deepEqual(hist.map(h => [h.kind, h.reason]), [['rollback', 'e2e rollback ve a'], ['activate', 'e2e chuyen sang b']]);
  assert.deepEqual(errors, []);
  await ctx.close();
});

record('E06 B5 operator/viewer goi thang API quan tri -> 403; admin -> 200', async () => {
  for (const [role, want] of [['viewer', 403], ['operator', 403], ['admin', 200]]) {
    for (const p of ['/v1/admin/recipes', `/v1/admin/stations/${station}`, '/v1/admin/audit']) {
      assert.equal((await apiCall(p, {role, mgmt: true})).status, want, `${role} ${p}`);
    }
    const r = await apiCall(`/v1/admin/stations/${station}/rollback`, {role, mgmt: true, method: 'POST', body: {reason: 'e2e rbac'}});
    assert.equal(r.status === 403, want === 403, `${role} rollback ${r.status}`);
  }
  await ensureRecipe('recipe-a');
});

record('E07 B2/B7 loi ky thuat hien "chua co ket luan" (khong bao gio OK/NG); tu rollback hien canh bao', async (t) => {
  const recipes = (await apiCall('/v1/admin/recipes', {mgmt: true})).body.items.map(r => r.recipe.name);
  if (!recipes.includes('recipe-bad')) { t.skip('can make start SLOW=1'); return 'SKIP'; }
  await ensureRecipe('recipe-bad');  // model-bad: qua golden, loi khi anh sang (mean >= 0.5)
  const {ctx, page} = await open('operator');
  const verdicts = [];
  for (let i = 0; i < 3; i++) {
    verdicts.push((await submitSample(page, 0, `PCB1-SN-E2E-BAD-${Date.now()}-${i}`)).verdict);
    if (i === 0) await shot(page, 'E07-technical');
    await page.getByTestId('next-btn').click();
  }
  assert.deepEqual(verdicts, ['TECHNICAL', 'TECHNICAL', 'TECHNICAL']);
  // 3 loi lien tiep sau cutover -> API tu rollback ve recipe-a; Tong quan phai canh bao
  let warned = false;
  for (let i = 0; i < 20 && !warned; i++) {
    await page.getByTestId('nav-overview').click();
    await page.getByTestId('activation-card').waitFor();
    warned = await page.getByTestId('auto-rollback-warning').isVisible();
    if (!warned) await page.waitForTimeout(1000);
  }
  assert.ok(warned, 'khong thay canh bao tu rollback');
  await page.getByTestId('active-recipe').getByText('recipe-a@0.1.0').waitFor();
  assert.ok(+(await page.getByTestId('count-tech').textContent()) >= 3);
  await shot(page, 'E07-auto-rollback');
  await ctx.close();
});

record('E08 B2 huy lan kiem dang chay -> "Da huy", khong co ket luan', async (t) => {
  const recipes = (await apiCall('/v1/admin/recipes', {mgmt: true})).body.items.map(r => r.recipe.name);
  if (!recipes.includes('recipe-slow')) { t.skip('can make start SLOW=1'); return 'SKIP'; }
  await ensureRecipe('recipe-slow');
  const {ctx, page} = await open('operator');
  await page.getByTestId('nav-inspect').click();
  await page.getByTestId('sample-1').click();
  await page.getByTestId('product-input').fill('PCB1-SN-E2E-CANCEL-' + Date.now());
  await page.getByTestId('submit-btn').click();
  await page.getByTestId('cancel-btn').click();
  await page.getByTestId('reason-input').fill('e2e huy');
  await page.getByTestId('confirm-btn').click();
  await page.getByTestId('dialog-ok').waitFor();
  await page.getByRole('button', {name: 'Đóng'}).click();
  const card = page.getByTestId('verdict-card');
  await card.waitFor({timeout: 30000});
  assert.equal(await card.getAttribute('data-verdict'), 'CANCELLED');
  await ensureRecipe('recipe-a');
  await ctx.close();
});

const stop = process.env.VR01_STOP_BACKEND, start = process.env.VR01_START_BACKEND;
record('E09 B1 dung inference server that -> trong 10 s man hinh bao chua san sang; bat lai -> san sang', {skip: !(stop && start)}, async () => {
  const {ctx, page} = await open('viewer');
  await page.getByTestId('active-recipe').waitFor();
  execSync(stop, {stdio: 'inherit'});
  const t0 = Date.now();
  try {
    await page.locator('[data-testid=ready-banner][data-ready=false]').waitFor({timeout: 10000});
    results.push({name: 'E09 not-ready seconds', value: (Date.now() - t0) / 1000});
    await shot(page, 'E09-backend-stopped');
  } finally { execSync(start, {stdio: 'inherit'}); }
  await page.locator('[data-testid=ready-banner][data-ready=true]').waitFor({timeout: 120000});
  await ctx.close();
});

record('E10 man hep 390 px (dien thoai/tablet doc): khong tran ngang o moi man hinh cua operator', async () => {
  const {ctx, page} = await open('operator');
  await page.setViewportSize({width: 390, height: 844});
  for (const s of ['overview', 'inspect', 'history']) {
    await page.getByTestId(`nav-${s}`).click();
    await page.waitForLoadState('networkidle');
    const [sw, iw] = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
    assert.ok(sw <= iw, `${s}: scrollWidth ${sw} > ${iw}`);
  }
  await shot(page, 'E10-narrow-history');
  await ctx.close();
});
