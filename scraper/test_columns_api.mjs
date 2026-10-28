// node --test scraper/test_columns_api.mjs
// Guest columns (functions/api/columns.js) with an in-memory KV and a fake Brevo.
import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequestGet, onRequestPost } from '../functions/api/columns.js';
import { onRequestGet as newsdeskGet, onRequestPost as newsdeskPost } from '../functions/api/newsdesk.js';

const store = new Map();
const sent = [];
let brevoUp = true;
globalThis.fetch = async (url, init) => {
  if (String(url).startsWith('https://api.brevo.com/')) {
    if (!brevoUp) return new Response('{"message":"sender not verified"}', { status: 400 });
    sent.push(JSON.parse(init.body));
    return new Response('{"messageId":"x"}', { status: 201 });
  }
  throw new Error('unexpected fetch ' + url);
};
const env = {
  EVENTS_ADMIN_TOKEN: 'desk-key-123',
  BREVO_API_KEY: 'brevo-test',
  EVENTS_KV: {
    get: async (key, opts) => (store.has(key) ? (opts && opts.type === 'json' ? JSON.parse(store.get(key)) : store.get(key)) : null),
    put: async (key, value) => { store.set(key, value); },
    delete: async (key) => { store.delete(key); },
  },
  ASSETS: { fetch: async () => new Response(JSON.stringify({ wards: { Bamford: { areas: ['bamford'] }, 'Central Rochdale': { areas: [] } } })) },
};
const req = (path, init = {}) => new Request('https://rochdaledaily.co.uk' + path, init);
const post = (body, admin = false) => onRequestPost({ env, request: req('/api/columns', {
  method: 'POST', headers: { 'content-type': 'application/json', ...(admin ? { 'x-admin-token': 'desk-key-123' } : {}) }, body: JSON.stringify(body) }) });

const words = (n) => Array.from({ length: n }, (_, i) => (i % 40 === 39 ? 'end.\n\nNew' : 'word')).join(' ');
const tinyJpeg = 'data:image/jpeg;base64,' + Buffer.from('fake-jpeg-bytes').toString('base64');
const good = {
  title: 'Littleborough needs its buses back before its shops close',
  body: words(400), author: 'Jane Smith', authorRole: 'chair of Littleborough Traders',
  interests: 'None', category: 'community', ward: 'Bamford', email: 'jane@example.com',
  ownWork: true, editing: true, reply: true,
  image: tinyJpeg, photoPermission: true, photoCaption: 'Jane Smith at the station', photoCredit: '',
};

test('form options come from the ward list', async () => {
  const d = await (await onRequestGet({ env, request: req('/api/columns?options=1') })).json();
  assert.deepEqual(d.wards, ['Borough-wide', 'Bamford', 'Central Rochdale']);
  assert.ok(!('crime' in d.categories));
});

test('rules: word limits, capitals, ward, confirmations, photo permission', async () => {
  assert.equal((await post({ ...good, body: words(701) })).status, 400);
  assert.equal((await post({ ...good, body: words(100) })).status, 400);
  assert.equal((await post({ ...good, title: 'COUNCIL FAILS RESIDENTS AGAIN TODAY' })).status, 400);
  assert.equal((await post({ ...good, ward: 'Nowhere' })).status, 400);
  assert.equal((await post({ ...good, reply: false })).status, 400);
  assert.equal((await post({ ...good, photoPermission: false })).status, 400);
  assert.equal((await post({ ...good, image: 'data:text/html;base64,PHNjcmlwdD4=' })).status, 400);
});

test('if the email cannot be sent nothing is saved and the reason is kept', async () => {
  brevoUp = false;
  const r = await post({ ...good, email: 'fail@example.com' });
  assert.equal(r.status, 502);
  assert.equal([...store.keys()].filter((k) => k.startsWith('columns:verify:')).length, 0);
  assert.equal([...store.keys()].filter((k) => k.startsWith('columns:image:')).length, 0);
  assert.ok(store.get('columns:last-email-error').includes('sender not verified'));
  brevoUp = true;
});

let columnId;
test('submit -> email link -> queue (email never public)', async () => {
  const r = await post(good);
  assert.equal(r.status, 201);
  const mail = sent.at(-1);
  assert.equal(mail.to[0].email, 'jane@example.com');
  const token = mail.textContent.match(/verify=([a-f0-9-]{36})/)[1];
  // Not in the editor's queue until the link is clicked.
  let q = await (await onRequestGet({ env, request: req('/api/columns?queue=pending', { headers: { 'x-admin-token': 'desk-key-123' } }) })).json();
  assert.equal(q.pending.length, 0);
  const v = await onRequestGet({ env, request: req('/api/columns?verify=' + token) });
  assert.equal(v.status, 303);
  assert.ok(v.headers.get('location').endsWith('verified=1'));
  q = await (await onRequestGet({ env, request: req('/api/columns?queue=pending', { headers: { 'x-admin-token': 'desk-key-123' } }) })).json();
  assert.equal(q.pending.length, 1);
  columnId = q.pending[0].id;
  assert.equal(q.pending[0].area, 'bamford');
  // Second click on the same link does nothing harmful.
  const again = await onRequestGet({ env, request: req('/api/columns?verify=' + token) });
  assert.ok(again.headers.get('location').endsWith('verified=expired'));
  // The queue and the photo are editor-only.
  assert.equal((await onRequestGet({ env, request: req('/api/columns?queue=pending') })).status, 401);
  assert.equal((await onRequestGet({ env, request: req('/api/columns?image=' + columnId) })).status, 401);
  assert.equal((await onRequestPost({ env, request: req('/api/columns', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ action: 'approve', id: columnId }) }) })).status, 401);
});

test('approval puts the column and its photo on the newsdesk queue', async () => {
  const d = await (await post({ action: 'approve', id: columnId, title: good.title, body: good.body, withPhoto: true }, true)).json();
  assert.equal(d.ok, true);
  const queue = JSON.parse(store.get('newsdesk:pending'));
  const entry = queue[0];
  assert.equal(entry.article.kicker, 'Opinion');
  assert.equal(entry.article.byline, 'Jane Smith, chair of Littleborough Traders');
  assert.ok(entry.article.body.endsWith("The views are the author's own and not those of Rochdale Daily."));
  assert.ok(!JSON.stringify(entry).includes('jane@example.com'), 'email must not reach the article');
  assert.equal(entry.image_key, 'newsdesk:image:' + entry.article.slug);
  assert.equal(entry.article.image_credit, 'Jane Smith');
  // The drain workflow reads the photo with the admin token...
  const img = await (await newsdeskGet({ env, request: req('/api/newsdesk?image=' + encodeURIComponent(entry.image_key), { headers: { 'x-admin-token': 'desk-key-123' } }) })).json();
  assert.equal(img.image, tinyJpeg);
  // ...and draining removes it.
  await newsdeskPost({ env, request: req('/api/newsdesk', { method: 'POST', headers: { 'content-type': 'application/json', 'x-admin-token': 'desk-key-123' }, body: JSON.stringify({ action: 'drain', ids: [entry.id] }) }) });
  assert.equal(store.has(entry.image_key), false);
  assert.equal(store.has('columns:image:' + columnId), false);
});

test('honeypot is silently accepted and stores nothing', async () => {
  const before = store.size;
  const r = await post({ ...good, website: 'http://spam' });
  assert.equal(r.status, 201);
  assert.equal(store.size, before);
});
