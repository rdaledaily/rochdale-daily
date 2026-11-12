'use strict';
// Sign-up preferences (functions/api/newsletter.js) and the in-article
// sign-up box (assets/js/article-signup.js).
// Run: node tests/test_newsletter_signup.cjs
// The box tests need jsdom (JSDOM_PATH or an installed "jsdom"); without it
// they are reported as skipped rather than passed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

const ROOT = path.join(__dirname, '..');

async function api() {
  const copy = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'rd-nl-')), 'newsletter.mjs');
  fs.copyFileSync(path.join(ROOT, 'functions/api/newsletter.js'), copy);
  return import(pathToFileURL(copy).href);
}
function kv() {
  const data = new Map();
  return { data,
    async get(key, options) { const v = data.has(key) ? data.get(key) : null; return v != null && options && options.type === 'json' ? JSON.parse(v) : v; },
    async put(key, value) { data.set(key, value); },
    async delete(key) { data.delete(key); },
    async list({ prefix }) { return { keys: [...data.keys()].filter(k => k.startsWith(prefix)).map(name => ({ name })), list_complete: true }; } };
}
function post(body) {
  return new Request('https://rochdaledaily.co.uk/api/newsletter', { method: 'POST', headers: { 'Content-Type': 'application/json', 'CF-Connecting-IP': '203.0.113.9' }, body: JSON.stringify(body) });
}
function subscriber(store) {
  const key = [...store.data.keys()].find(k => k.startsWith('newsletter:sub:'));
  return key ? JSON.parse(store.data.get(key)) : null;
}
async function withBrevo(handler, run) {
  const calls = [], real = globalThis.fetch;
  globalThis.fetch = async (url, init) => { const call = { url: String(url), body: init && init.body ? JSON.parse(init.body) : null }; calls.push(call); return handler(call); };
  try { await run(calls); } finally { globalThis.fetch = real; }
}
const created = () => new Response('{"id":1}', { status: 201 });

test('area and topics are stored with a new sign-up and sent to Brevo', async () => {
  const { onRequestPost } = await api(); const store = kv();
  await withBrevo(created, async calls => {
    const res = await onRequestPost({ request: post({ email: 'Reader@Example.com', consent: true, source: 'article-inline', area: 'Heywood', topics: ['crime', 'whats-on', 'crime'] }), env: { EVENTS_KV: store, BREVO_API_KEY: 'k', BREVO_LIST_ID: '2' } });
    assert.equal((await res.json()).ok, true);
    const record = subscriber(store);
    assert.equal(record.area, 'heywood'); assert.deepEqual(record.topics, ['crime', 'whats-on']);
    assert.equal(record.source, 'article-inline'); assert.equal(record.brevo_sync_status, 'synced'); assert.equal(record.brevo_prefs_status, 'sent');
    const contact = calls.find(c => c.url.endsWith('/v3/contacts'));
    assert.deepEqual(contact.body.attributes, { RD_AREA: 'heywood', RD_TOPICS: 'crime,whats-on' });
    assert.deepEqual(contact.body.listIds, [2]); assert.equal(contact.body.updateEnabled, false);
    assert.equal(calls.filter(c => c.url.includes('/contacts/attributes/normal/')).length, 2);
    // The attributes are created once, not on every sign-up.
    await onRequestPost({ request: post({ email: 'second@example.com', consent: true, area: 'middleton' }), env: { EVENTS_KV: store, BREVO_API_KEY: 'k', BREVO_LIST_ID: '2' } });
    assert.equal(calls.filter(c => c.url.includes('/contacts/attributes/normal/')).length, 2);
  });
});

test('values outside the lists are dropped, never stored or sent', async () => {
  const { onRequestPost } = await api(); const store = kv();
  await withBrevo(created, async calls => {
    await onRequestPost({ request: post({ email: 'a@example.com', consent: true, area: '<script>', topics: ['politics', { x: 1 }, 'SPORT'] }), env: { EVENTS_KV: store, BREVO_API_KEY: 'k', BREVO_LIST_ID: '2' } });
    const record = subscriber(store);
    assert.equal('area' in record, false); assert.deepEqual(record.topics, ['sport']);
    assert.deepEqual(calls.find(c => c.url.endsWith('/v3/contacts')).body.attributes, { RD_TOPICS: 'sport' });
  });
});

test('a sign-up with no preferences is sent exactly as before', async () => {
  const { onRequestPost } = await api(); const store = kv();
  await withBrevo(created, async calls => {
    await onRequestPost({ request: post({ email: 'plain@example.com', consent: true }), env: { EVENTS_KV: store, BREVO_API_KEY: 'k', BREVO_LIST_ID: '2' } });
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].body, { email: 'plain@example.com', listIds: [2], updateEnabled: false });
    const record = subscriber(store); assert.equal('area' in record, false); assert.equal('topics' in record, false);
  });
});

test('if Brevo cannot take the attributes the reader still joins the list', async () => {
  const { onRequestPost } = await api(); const store = kv();
  await withBrevo(call => call.url.includes('/attributes/') ? new Response('{}', { status: 403 }) : created(), async calls => {
    await onRequestPost({ request: post({ email: 'b@example.com', consent: true, area: 'pennines' }), env: { EVENTS_KV: store, BREVO_API_KEY: 'k', BREVO_LIST_ID: '2' } });
    const record = subscriber(store);
    assert.equal(record.brevo_sync_status, 'synced'); assert.equal(record.brevo_prefs_status, 'ledger_only'); assert.equal(record.area, 'pennines');
    assert.equal('attributes' in calls.find(c => c.url.endsWith('/v3/contacts')).body, false);
    assert.equal(store.data.has('newsletter:brevo_attrs_ready'), false);
  });
});

test('an address already on the list cannot have its preferences changed by a later post', async () => {
  const { onRequestPost } = await api(); const store = kv();
  await withBrevo(created, async () => {
    const env = { EVENTS_KV: store, BREVO_API_KEY: 'k', BREVO_LIST_ID: '2' };
    await onRequestPost({ request: post({ email: 'c@example.com', consent: true, area: 'rochdale' }), env });
    await onRequestPost({ request: post({ email: 'c@example.com', consent: true, area: 'heywood', topics: ['crime'] }), env });
    const record = subscriber(store); assert.equal(record.area, 'rochdale'); assert.equal('topics' in record, false);
  });
});

test('the export carries the preferences', async () => {
  const { onRequestPost, onRequestGet } = await api(); const store = kv();
  await onRequestPost({ request: post({ email: 'd@example.com', consent: true, area: 'middleton', topics: ['council', 'sport'] }), env: { EVENTS_KV: store } });
  const res = await onRequestGet({ request: new Request('https://rochdaledaily.co.uk/api/newsletter?export=csv', { headers: { 'x-admin-token': 'secret' } }), env: { EVENTS_KV: store, EVENTS_ADMIN_TOKEN: 'secret' } });
  const lines = (await res.text()).trim().split('\n');
  assert.equal(lines[0], 'email,consented_at,source,area,topics');
  assert.match(lines[1], /"d@example\.com",.*"middleton","council sport"$/);
});

// ---------------------------------------------------------------- the box
let JSDOM = null;
try { ({ JSDOM } = require(process.env.JSDOM_PATH || 'jsdom')); } catch (error) { JSDOM = null; }
const boxTest = (name, fn) => test(name, { skip: JSDOM ? false : 'jsdom is not installed' }, fn);
const SCRIPT = fs.readFileSync(path.join(ROOT, 'assets/js/article-signup.js'), 'utf8');
const PAGE = legal => `<!doctype html><html><head></head><body><div class="article-main"><h1>Story</h1>
  <div class="article-copy"><p>One.</p><p>Two.</p></div>
  <section class="editorial-legal-note"><p>${legal || 'This article was compiled from identified public sources and may be updated.'}</p></section></div></body></html>`;

function open({ referrer = '', storage = {}, legal = '', html, fetcher } = {}) {
  const dom = new JSDOM(html || PAGE(legal), Object.assign({ url: 'https://rochdaledaily.co.uk/articles/a-story', runScripts: 'outside-only' }, referrer ? { referrer } : {}));
  for (const [key, value] of Object.entries(storage)) dom.window.localStorage.setItem(key, value);
  const posts = [];
  dom.window.fetch = fetcher || (async (url, init) => { posts.push({ url, body: JSON.parse(init.body) }); return { ok: true, json: async () => ({ ok: true, message: 'Your signup has been saved.' }) }; });
  dom.window.eval(SCRIPT);
  return { dom, posts, box: dom.window.document.getElementById('inline-newsletter') };
}
const settle = () => new Promise(resolve => setTimeout(resolve, 20));

boxTest('a first page view from outside the site is left alone', () => {
  assert.equal(open({ referrer: 'https://www.facebook.com/' }).box, null);
  assert.equal(open({}).box, null);
});
boxTest('a second page view gets one box directly under the story', () => {
  const { dom, box } = open({ referrer: 'https://rochdaledaily.co.uk/' });
  assert.ok(box); assert.equal(dom.window.document.querySelector('.article-copy').nextElementSibling, box);
  dom.window.eval(SCRIPT);
  assert.equal(dom.window.document.querySelectorAll('#inline-newsletter').length, 1);
});
boxTest('a returning reader gets it on the first page', () => {
  assert.ok(open({ storage: { rd_last_visit: String(Date.now() - 86400000) } }).box);
  assert.equal(open({ storage: { rd_last_visit: String(Date.now() - 60000) } }).box, null);
});
boxTest('never shown to a subscriber, after "Not now", or under a sensitive story', () => {
  const ref = 'https://rochdaledaily.co.uk/';
  assert.equal(open({ referrer: ref, storage: { rd_newsletter_done: '1' } }).box, null);
  assert.equal(open({ referrer: ref, storage: { rd_signup_snooze: String(Date.now() - 5 * 86400000) } }).box, null);
  assert.ok(open({ referrer: ref, storage: { rd_signup_snooze: String(Date.now() - 31 * 86400000) } }).box);
  assert.equal(open({ referrer: ref, legal: 'No finding of guilt should be inferred from an arrest, allegation or charge.' }).box, null);
  const { dom, box } = open({ referrer: ref });
  box.querySelector('.rd-is-later').click();
  assert.equal(dom.window.document.getElementById('inline-newsletter'), null);
  assert.ok(Number(dom.window.localStorage.getItem('rd_signup_snooze')) > 0);
});
boxTest('nothing is sent without a valid address and a ticked box', async () => {
  const { dom, posts, box } = open({ referrer: 'https://rochdaledaily.co.uk/' });
  const form = box.querySelector('form'), submit = () => form.dispatchEvent(new dom.window.Event('submit', { cancelable: true, bubbles: true }));
  box.querySelector('input[type=email]').value = 'not-an-address'; submit(); await settle();
  box.querySelector('input[type=email]').value = 'reader@example.com'; submit(); await settle();
  assert.equal(posts.length, 0);
  assert.match(box.querySelector('.rd-is-status').textContent, /tick the box/);
});
boxTest('a sign-up posts the address and choices, then is remembered', async () => {
  const { dom, posts, box } = open({ referrer: 'https://rochdaledaily.co.uk/' });
  let saved = 0; dom.window.document.addEventListener('rd:newsletter-saved', () => { saved += 1; });
  box.querySelector('input[type=email]').value = ' reader@example.com ';
  box.querySelector('input[name=consent]').checked = true;
  box.querySelector('select').value = 'heywood';
  box.querySelector('input[value="crime"]').checked = true;
  box.querySelector('form').dispatchEvent(new dom.window.Event('submit', { cancelable: true, bubbles: true }));
  await settle();
  assert.equal(posts.length, 1);
  assert.deepEqual(posts[0].body, { email: 'reader@example.com', consent: true, website: '', source: 'article-inline', area: 'heywood', topics: ['crime'] });
  assert.equal(dom.window.localStorage.getItem('rd_newsletter_done'), '1');
  assert.equal(saved, 1); assert.equal(box.querySelector('form'), null);
  assert.match(box.textContent, /Your signup has been saved/);
});
boxTest('a failed save says so and keeps the form', async () => {
  const { dom, box } = open({ referrer: 'https://rochdaledaily.co.uk/', fetcher: async () => ({ ok: false, json: async () => ({ ok: false, error: 'Too many attempts. Please try again later.' }) }) });
  box.querySelector('input[type=email]').value = 'reader@example.com'; box.querySelector('input[name=consent]').checked = true;
  box.querySelector('form').dispatchEvent(new dom.window.Event('submit', { cancelable: true, bubbles: true }));
  await settle();
  assert.match(box.querySelector('.rd-is-status').textContent, /Too many attempts/);
  assert.equal(dom.window.localStorage.getItem('rd_newsletter_done'), null);
  assert.equal(box.querySelector('button[type=submit]').disabled, false);
});
boxTest('it works on a real published article page, old markup included', () => {
  const dir = path.join(ROOT, 'articles');
  const pages = fs.readdirSync(dir).filter(name => name.endsWith('.html'));
  let shown = 0, checked = 0;
  for (const name of [pages[0], pages[Math.floor(pages.length / 2)], pages[pages.length - 1]]) {
    const html = fs.readFileSync(path.join(dir, name), 'utf8').replace(/<script[\s\S]*?<\/script>/g, '');
    if (!/class="article-copy"/.test(html)) continue;
    checked += 1;
    const { box } = open({ referrer: 'https://rochdaledaily.co.uk/', html });
    if (box) shown += 1; else assert.match(html, /No finding of guilt should be inferred/);
  }
  assert.ok(checked > 0); assert.ok(shown > 0);
});
