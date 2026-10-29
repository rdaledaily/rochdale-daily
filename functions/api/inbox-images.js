/** news@ inbox hand-off for the email image saver.
 *
 * The rd-news-inbox Worker (workers/news-inbox/worker.js) forwards every email
 * to the editor and keeps a raw copy in EVENTS_KV under "inbox-raw:". This
 * endpoint lets the GitHub lane email-images.yml collect those copies, save
 * their images into assets/img/cards/, and then delete them.
 *
 * Every request needs the admin token; anyone else gets 401 and nothing else.
 *
 *   GET                       list waiting emails and capture errors
 *   GET  ?key=inbox-raw:...   the raw email bytes
 *   POST {action:"ack", keys} delete emails (and error notes) once handled
 *
 * Bindings: EVENTS_KV and EVENTS_ADMIN_TOKEN, shared with newsdesk/residents.
 */
const RAW_PREFIX = "inbox-raw:";
const ERROR_PREFIX = "inbox-err:";
const MAX_ACK = 200;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

function isAdmin(request, env) {
  const token = request.headers.get("x-admin-token") || "";
  const expected = env.EVENTS_ADMIN_TOKEN || "";
  if (!expected || token.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) diff |= token.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0; // constant-time compare, matching newsdesk.js
}

function ownKey(key) {
  return typeof key === "string" && (key.startsWith(RAW_PREFIX) || key.startsWith(ERROR_PREFIX)) && key.length <= 200;
}

async function listPrefix(kv, prefix) {
  const out = [];
  let cursor;
  for (let page = 0; page < 20; page += 1) {
    const res = await kv.list({ prefix, cursor, limit: 1000 });
    for (const k of res.keys) out.push({ key: k.name, meta: k.metadata || {} });
    if (res.list_complete) break;
    cursor = res.cursor;
  }
  return out;
}

export async function onRequestGet({ request, env }) {
  if (!isAdmin(request, env)) return json({ ok: false, error: "unauthorised" }, 401);
  if (!env.EVENTS_KV) return json({ ok: false, error: "EVENTS_KV binding missing" }, 500);
  const key = new URL(request.url).searchParams.get("key");
  if (key) {
    if (!key.startsWith(RAW_PREFIX)) return json({ ok: false, error: "unknown key" }, 400);
    const bytes = await env.EVENTS_KV.get(key, { type: "arrayBuffer" });
    if (!bytes) return json({ ok: false, error: "not found" }, 404);
    return new Response(bytes, {
      headers: { "Content-Type": "message/rfc822", "Cache-Control": "no-store" },
    });
  }
  const [emails, errors] = await Promise.all([
    listPrefix(env.EVENTS_KV, RAW_PREFIX),
    listPrefix(env.EVENTS_KV, ERROR_PREFIX),
  ]);
  return json({ ok: true, emails, errors });
}

export async function onRequestPost({ request, env }) {
  if (!isAdmin(request, env)) return json({ ok: false, error: "unauthorised" }, 401);
  if (!env.EVENTS_KV) return json({ ok: false, error: "EVENTS_KV binding missing" }, 500);
  let body;
  try {
    body = await request.json();
  } catch (_) {
    return json({ ok: false, error: "invalid JSON" }, 400);
  }
  if (!body || body.action !== "ack" || !Array.isArray(body.keys)) {
    return json({ ok: false, error: "expected {action:'ack', keys:[...]}" }, 400);
  }
  const keys = body.keys.filter(ownKey).slice(0, MAX_ACK);
  await Promise.all(keys.map((k) => env.EVENTS_KV.delete(k)));
  return json({ ok: true, deleted: keys.length });
}
