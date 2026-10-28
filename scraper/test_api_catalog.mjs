// node --test scraper/test_api_catalog.mjs
// RFC 9727 catalog (functions/.well-known/api-catalog.js) and /api/health.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import { onRequestGet, onRequestHead } from '../functions/.well-known/api-catalog.js';
import { onRequestGet as health } from '../functions/api/health.js';

test('catalog is a linkset with service-desc, service-doc and status for every API', async () => {
  const r = onRequestGet();
  assert.equal(r.status, 200);
  assert.match(r.headers.get('content-type'), /^application\/linkset\+json/);
  const body = await r.json();
  assert.ok(Array.isArray(body.linkset) && body.linkset.length >= 4);
  for (const e of body.linkset) {
    assert.match(e.anchor, /^https:\/\/rochdaledaily\.co\.uk\//);
    for (const rel of ['service-desc', 'service-doc', 'status']) assert.ok(e[rel][0].href.startsWith('https://'), rel);
  }
  assert.equal(onRequestHead().status, 200);
});

test('everything the catalog points at exists in the repo', async () => {
  const spec = JSON.parse(readFileSync('openapi.json', 'utf8'));
  assert.equal(spec.openapi, '3.1.0');
  assert.ok(existsSync('developers.html'));
  for (const p of ['/articles.json', '/weather.json', '/api/events', '/api/live-updates', '/api/health']) assert.ok(spec.paths[p], p);
  assert.ok(!JSON.stringify(spec).includes('x-admin-token'), 'private endpoints stay out of the public description');
});

const env = (stories, ok = true) => ({ EVENTS_KV: {}, ASSETS: { fetch: async () => new Response(ok ? JSON.stringify(stories) : 'x', { status: ok ? 200 : 500 }) } });
const req = new Request('https://rochdaledaily.co.uk/api/health');

test('health: ok, degraded and down', async () => {
  let d = await (await health({ request: req, env: env([{ published_at: new Date().toISOString() }]) })).json();
  assert.equal(d.status, 'ok');
  d = await (await health({ request: req, env: env([{ published_at: '2020-01-01T00:00:00Z' }]) })).json();
  assert.equal(d.status, 'degraded');
  const r = await health({ request: req, env: env(null, false) });
  assert.equal(r.status, 503);
});
