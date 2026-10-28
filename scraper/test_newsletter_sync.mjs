// node --test scraper/test_newsletter_sync.mjs
// Admin status and "send waiting sign-ups to Brevo" (functions/api/newsletter.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import { onRequestGet, onRequestPost } from '../functions/api/newsletter.js';

const store = new Map();
const calls = [];
let brevo = (email) => (email.startsWith('gone') ? 400 : 201);
globalThis.fetch = async (url, init) => {
  assert.ok(String(url).startsWith('https://api.brevo.com/'));
  const body = JSON.parse(init.body);
  calls.push(body);
  assert.equal(body.updateEnabled, false, 'never reactivates existing contacts');
  return new Response('{}', { status: brevo(body.email) });
};
const kv = {
  get: async (k, o) => (store.has(k) ? (o && o.type === 'json' ? JSON.parse(store.get(k)) : store.get(k)) : null),
  put: async (k, v) => { store.set(k, v); },
  delete: async (k) => { store.delete(k); },
  list: async ({ prefix }) => ({ keys: [...store.keys()].filter((k) => k.startsWith(prefix)).map((name) => ({ name })), list_complete: true }),
};
const env = { EVENTS_KV: kv, EVENTS_ADMIN_TOKEN: 'desk-key-123', BREVO_API_KEY: 'k', BREVO_LIST_ID: '2' };
const hex = (n) => n.toString(16).padStart(64, '0');
const add = (n, email, status) => store.set('newsletter:sub:' + hex(n), JSON.stringify({ email, consented_at: '2026-10-01T00:00:00Z', ...(status ? { brevo_sync_status: status } : {}) }));
const admin = { 'x-admin-token': 'desk-key-123' };
const status = async () => (await (await onRequestGet({ env, request: new Request('https://rochdaledaily.co.uk/api/newsletter?status=1', { headers: admin }) })).json());
const sync = (headers = admin) => onRequestPost({ env, request: new Request('https://rochdaledaily.co.uk/api/newsletter', { method: 'POST', headers: { 'content-type': 'application/json', ...headers }, body: JSON.stringify({ action: 'sync' }) }) });

add(1, 'old@example.com');                       // signed up before Brevo existed
add(2, 'done@example.com', 'synced');
add(3, 'gone@example.com');                      // Brevo already holds (unsubscribed)
add(4, 'blip@example.com', 'provider_unavailable');
add(5, 'held@example.com', 'review_provider_existing_or_suppressed');

test('status counts without exposing emails; admin only', async () => {
  const d = await status();
  assert.deepEqual(d.counts, { total: 5, synced: 1, waiting: 3, held: 1 });
  assert.ok(!JSON.stringify(d).includes('@'));
  assert.equal((await onRequestGet({ env, request: new Request('https://rochdaledaily.co.uk/api/newsletter?status=1') })).status, 401);
  assert.equal((await sync({})).status, 401);
});

test('sync sends only waiting sign-ups and never retries held ones', async () => {
  const d = await (await sync()).json();
  assert.equal(d.added, 2);
  assert.equal(d.held, 1);
  assert.deepEqual(calls.map((c) => c.email).sort(), ['blip@example.com', 'gone@example.com', 'old@example.com']);
  assert.deepEqual((await status()).counts, { total: 5, synced: 3, waiting: 0, held: 2 });
  calls.length = 0;
  await sync();
  assert.equal(calls.length, 0, 'nothing left to send');
});

test('a Brevo outage stops the batch loop', async () => {
  add(6, 'later@example.com');
  brevo = () => 503;
  const d = await (await sync()).json();
  assert.equal(d.failed, 1);
  assert.equal(d.more, false);
});
