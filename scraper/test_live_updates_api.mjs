// node --test scraper/test_live_updates_api.mjs
// The live desk API (functions/api/live-updates.js) against an in-memory KV.
import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequestGet, onRequestPost } from '../functions/api/live-updates.js';

const store = new Map();
globalThis.caches = { default: { match: async () => undefined, put: async () => {}, delete: async () => true } };
const env = {
  EVENTS_ADMIN_TOKEN: 'desk-key-123',
  EVENTS_KV: {
    get: async (key, opts) => (store.has(key) ? (opts && opts.type === 'json' ? JSON.parse(store.get(key)) : store.get(key)) : null),
    put: async (key, value) => { store.set(key, value); },
  },
  ASSETS: {
    fetch: async () => new Response(JSON.stringify([
      { slug: 'm62-closed-after-crash-near-milnrow', title: 'M62 closed after crash near Milnrow', category: 'traffic', url: '/articles/m62-closed-after-crash-near-milnrow.html' },
    ])),
  },
};
const post = (body, token = 'desk-key-123') => onRequestPost({ env, request: new Request('https://rochdaledaily.co.uk/api/live-updates', {
  method: 'POST', headers: { 'content-type': 'application/json', 'x-admin-token': token }, body: JSON.stringify(body) }) });
const get = (q) => onRequestGet({ env, request: new Request('https://rochdaledaily.co.uk/api/live-updates?' + q) });
const slug = 'm62-closed-after-crash-near-milnrow';

test('only the desk key can post', async () => {
  assert.equal((await post({ action: 'add', slug, text: 'Two lanes shut.' }, 'wrong')).status, 401);
});

test('a story that is not published cannot go live', async () => {
  const r = await post({ action: 'add', slug: 'not-a-real-story', text: 'Something happened here.' });
  assert.equal(r.status, 404);
});

test('updates are added newest first and listed as live', async () => {
  let r = await post({ action: 'add', slug, text: 'Police have closed the westbound carriageway.', title: 'Road closed' });
  assert.equal(r.status, 200);
  r = await post({ action: 'add', slug, text: 'One lane has reopened.', image_url: 'javascript:alert(1)', source_url: 'http://insecure.example' });
  const record = (await r.json()).record;
  assert.equal(record.updates.length, 2);
  assert.equal(record.updates[0].text, 'One lane has reopened.');
  assert.equal(record.updates[0].image_url, '', 'non-https image refused');
  assert.equal(record.updates[0].source_url, '', 'non-https source refused');
  const index = await (await get('index=1')).json();
  assert.equal(index.live[0].slug, slug);
  const one = await (await get('slug=' + slug)).json();
  assert.equal(one.updates.length, 2);
});

test('key points, delete, end and reopen', async () => {
  let record = (await (await post({ action: 'points', slug, points: 'Westbound closed\nAir ambulance attended\n\n' })).json()).record;
  assert.deepEqual(record.key_points, ['Westbound closed', 'Air ambulance attended']);
  const id = record.updates[1].id;
  record = (await (await post({ action: 'delete', slug, id })).json()).record;
  assert.equal(record.updates.length, 1);
  record = (await (await post({ action: 'end', slug })).json()).record;
  assert.ok(record.ended_at);
  assert.equal((await (await get('index=1')).json()).live.length, 0, 'ended coverage is not listed');
  record = (await (await post({ action: 'reopen', slug })).json()).record;
  assert.equal(record.ended_at, '');
});

test('bad slugs are refused on read', async () => {
  assert.equal((await get('slug=../../etc')).status, 400);
});
