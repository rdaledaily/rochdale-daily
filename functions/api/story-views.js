/**
 * /api/story-views
 *
 * Counts how many times each article is opened per day (Europe/London), so the
 * live front page can lift the day's most-read stories (editor's rule, 9 Nov
 * 2026: crime keeps #1, warnings keep #2, today's most-read fill from #3 down;
 * the reordering itself lives in functions/articles/frontpage.json.js).
 *
 * What is stored: day, slug, count. Nothing else -- no IP address, no cookie,
 * no device identifier, nothing written to the reader's browser. The beacon
 * (appended to /assets/ads.js by functions/assets/_middleware.js) skips
 * reloads and back/forward visits, so one reader refreshing does not count.
 * Counts are approximate: they measure article opens by readers whose browser
 * runs the page script, which excludes most bots.
 *
 * Public:
 *   POST { slug }                  -> 204 (counted) or 204 (ignored)
 *   GET  /api/story-views          -> today's counts, highest first
 *   GET  /api/story-views?day=YYYY-MM-DD
 *
 * Binding required: STORY_VIEWS_DB (a Cloudflare D1 database). The table is
 * created on first use. If the binding is missing every call answers 503 with
 * a reason, and the front page keeps its normal order.
 */

const SLUG_RE = /^[a-z0-9][a-z0-9-]{1,198}$/;
const BOT_RE = /bot|crawl|spider|slurp|headless|preview|facebookexternalhit|embedly|monitor/i;
const KEEP_DAYS = 14;

function londonDay(date = new Date()) {
  // en-CA formats as YYYY-MM-DD; the timeZone makes the day roll at UK midnight
  // in both GMT and BST.
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' },
  });
}

async function ensureTable(db) {
  await db.prepare(
    'CREATE TABLE IF NOT EXISTS story_views (day TEXT NOT NULL, slug TEXT NOT NULL, views INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (day, slug))'
  ).run();
}

async function withTable(db, fn) {
  try {
    return await fn();
  } catch (error) {
    if (!/no such table/i.test(String(error && error.message))) throw error;
    await ensureTable(db);
    return fn();
  }
}

export async function onRequestPost({ request, env }) {
  const db = env.STORY_VIEWS_DB;
  if (!db) return json({ ok: false, reason: 'STORY_VIEWS_DB binding missing' }, 503);
  if (BOT_RE.test(request.headers.get('user-agent') || '')) return new Response(null, { status: 204 });

  let slug = '';
  try {
    const body = await request.json();
    slug = String(body && body.slug || '').trim().toLowerCase();
  } catch (_) {
    return json({ ok: false, reason: 'bad body' }, 400);
  }
  if (!SLUG_RE.test(slug)) return json({ ok: false, reason: 'bad slug' }, 400);

  const day = londonDay();
  await withTable(db, () => db.prepare(
    'INSERT INTO story_views (day, slug, views) VALUES (?1, ?2, 1) ON CONFLICT(day, slug) DO UPDATE SET views = views + 1'
  ).bind(day, slug).run());

  // Housekeeping: roughly one write in fifty also drops rows older than
  // KEEP_DAYS, so the table never grows without bound.
  if (Math.random() < 0.02) {
    const cutoff = londonDay(new Date(Date.now() - KEEP_DAYS * 86400000));
    await db.prepare('DELETE FROM story_views WHERE day < ?1').bind(cutoff).run();
  }
  return new Response(null, { status: 204 });
}

export async function onRequestGet({ request, env }) {
  const db = env.STORY_VIEWS_DB;
  if (!db) return json({ ok: false, reason: 'STORY_VIEWS_DB binding missing' }, 503);
  const url = new URL(request.url);
  const day = /^\d{4}-\d{2}-\d{2}$/.test(url.searchParams.get('day') || '') ? url.searchParams.get('day') : londonDay();
  const result = await withTable(db, () => db.prepare(
    'SELECT slug, views FROM story_views WHERE day = ?1 ORDER BY views DESC LIMIT 100'
  ).bind(day).all());
  return json({ ok: true, day, timezone: 'Europe/London', stories: result.results || [] });
}
