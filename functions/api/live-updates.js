/* Live coverage for big incidents and matchdays.
 *
 * One story, one URL, timestamped updates newest first: the format MEN runs
 * on every crash, fire, cordon and match. Updates are written from the live
 * desk (/live-desk.html) on a phone and stored here in EVENTS_KV, so they
 * reach readers within a minute without waiting for a site rebuild. The
 * page generator also folds them into the static page (scraper/live_format.py)
 * so search engines read them as LiveBlogPosting updates.
 *
 *   GET  /api/live-updates?slug=<slug>   updates for one story (public)
 *   GET  /api/live-updates?index=1       stories live right now (public)
 *   POST /api/live-updates               editor only (x-admin-token)
 *        {action:"add", slug, text, title?, image_url?, image_credit?, source_url?}
 *        {action:"points", slug, points:[...]}      "What we know" box
 *        {action:"end", slug} / {action:"reopen", slug}
 *        {action:"delete", slug, id}                 remove a mistaken update
 *
 * Required env: EVENTS_KV, EVENTS_ADMIN_TOKEN (the same token the push
 * publisher uses). Only a story already published in archive-index.json can
 * go live, so the desk cannot create a page that does not exist.
 */
const LIVE_WINDOW_MS = 6 * 60 * 60 * 1000;
const MAX_UPDATES = 200;
const INDEX_KEY = 'live:index';
const json = (body, status = 200, cache = 'no-store') => new Response(JSON.stringify(body), {
  status,
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': cache,
    'X-Content-Type-Options': 'nosniff',
  },
});
const str = (value, max) => String(value == null ? '' : value).replace(/\s+/g, ' ').trim().slice(0, max);
const slugOk = (slug) => /^[a-z0-9][a-z0-9-]{3,180}$/.test(slug);

function isAdmin(request, env) {
  const key = String(request.headers.get('x-admin-token') || '');
  const expected = String(env.EVENTS_ADMIN_TOKEN || '');
  if (!expected || key.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < key.length; i += 1) diff |= key.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0;
}

function safeUrl(value) {
  const raw = str(value, 500);
  if (!raw) return '';
  if (raw.startsWith('/assets/')) return raw;
  try {
    const url = new URL(raw);
    return url.protocol === 'https:' ? url.toString() : '';
  } catch (error) {
    return '';
  }
}

async function publishedStory(env, request, slug) {
  if (!env.ASSETS || !env.ASSETS.fetch) throw new Error('The published archive cannot be read.');
  const response = await env.ASSETS.fetch(new Request(new URL('/archive-index.json', request.url)));
  if (!response.ok) throw new Error('The published archive cannot be read.');
  const items = await response.json();
  const rows = Array.isArray(items) ? items : (items.items || items.articles || []);
  const item = rows.find((row) => row && row.slug === slug);
  if (!item) throw new Error('That story is not published yet, so it cannot go live.');
  return { slug, title: str(item.title, 180), category: str(item.category, 40) };
}

async function readRecord(env, slug) {
  return (await env.EVENTS_KV.get('live:' + slug, { type: 'json' })) || null;
}

async function readIndex(env) {
  const index = await env.EVENTS_KV.get(INDEX_KEY, { type: 'json' });
  return Array.isArray(index) ? index : [];
}

function isLive(entry, now) {
  if (!entry || entry.ended_at) return false;
  const last = Date.parse(entry.updated_at || entry.started_at || '');
  return Number.isFinite(last) && now - last < LIVE_WINDOW_MS;
}

async function purge(request, slug) {
  try {
    const cache = caches.default;
    await cache.delete(new Request(new URL('/api/live-updates?slug=' + slug, request.url)));
    await cache.delete(new Request(new URL('/api/live-updates?index=1', request.url)));
  } catch (error) { /* cache is a convenience, never a dependency */ }
}

export async function onRequestGet({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: 'Live storage is unavailable.' }, 503);
  const url = new URL(request.url);
  const cache = caches.default;
  const cacheKey = new Request(url.origin + url.pathname + (url.searchParams.get('index') ? '?index=1' : '?slug=' + str(url.searchParams.get('slug'), 190)));
  try {
    const hit = await cache.match(cacheKey);
    if (hit) return hit;
  } catch (error) { /* fall through to KV */ }

  let response;
  if (url.searchParams.get('index')) {
    const now = Date.now();
    const live = (await readIndex(env)).filter((entry) => isLive(entry, now))
      .sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at));
    response = json({ ok: true, live }, 200, 'public, max-age=15');
  } else {
    const slug = str(url.searchParams.get('slug'), 190);
    if (!slugOk(slug)) return json({ ok: false, error: 'Invalid story.' }, 400);
    const record = await readRecord(env, slug);
    response = json({
      ok: true,
      slug,
      title: record ? record.title : '',
      started_at: record ? record.started_at : '',
      updated_at: record ? record.updated_at : '',
      ended_at: record ? record.ended_at || '' : '',
      key_points: record ? record.key_points || [] : [],
      updates: record ? record.updates || [] : [],
    }, 200, 'public, max-age=15');
  }
  try { await cache.put(cacheKey, response.clone()); } catch (error) { /* ignore */ }
  return response;
}

export async function onRequestPost({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: 'Live storage is unavailable.' }, 503);
  if (!isAdmin(request, env)) return json({ ok: false, error: 'Not authorised.' }, 401);
  let body;
  try { body = await request.json(); } catch (error) { return json({ ok: false, error: 'Send JSON.' }, 400); }
  const action = str(body.action, 20);
  const slug = str(body.slug, 190);
  if (!slugOk(slug)) return json({ ok: false, error: 'Invalid story.' }, 400);

  let story;
  try { story = await publishedStory(env, request, slug); } catch (error) { return json({ ok: false, error: error.message }, 404); }

  const nowIso = new Date().toISOString();
  const record = (await readRecord(env, slug)) || {
    slug, title: story.title, category: story.category, started_at: nowIso, updated_at: nowIso,
    ended_at: '', key_points: [], updates: [],
  };

  if (action === 'add') {
    const text = str(body.text, 1500);
    if (text.length < 5) return json({ ok: false, error: 'Write the update first.' }, 400);
    const update = {
      id: crypto.randomUUID(),
      timestamp: nowIso,
      text,
      title: str(body.title, 140),
      image_url: safeUrl(body.image_url),
      image_credit: str(body.image_credit, 120),
      source_url: safeUrl(body.source_url),
    };
    record.updates = [update, ...(record.updates || [])].slice(0, MAX_UPDATES);
    record.updated_at = nowIso;
    record.ended_at = '';
  } else if (action === 'points') {
    const points = Array.isArray(body.points) ? body.points : String(body.points || '').split('\n');
    record.key_points = points.map((point) => str(point, 220)).filter(Boolean).slice(0, 6);
    record.updated_at = nowIso;
  } else if (action === 'end') {
    record.ended_at = nowIso;
  } else if (action === 'reopen') {
    record.ended_at = '';
    record.updated_at = nowIso;
  } else if (action === 'delete') {
    const id = str(body.id, 60);
    const before = (record.updates || []).length;
    record.updates = (record.updates || []).filter((update) => update.id !== id);
    if (record.updates.length === before) return json({ ok: false, error: 'No update with that id.' }, 404);
  } else {
    return json({ ok: false, error: 'Unknown action.' }, 400);
  }

  await env.EVENTS_KV.put('live:' + slug, JSON.stringify(record));
  const index = (await readIndex(env)).filter((entry) => entry.slug !== slug);
  index.unshift({
    slug, title: record.title, category: record.category, started_at: record.started_at,
    updated_at: record.updated_at, ended_at: record.ended_at || '', count: (record.updates || []).length,
  });
  await env.EVENTS_KV.put(INDEX_KEY, JSON.stringify(index.slice(0, 60)));
  await purge(request, slug);
  return json({ ok: true, record });
}
