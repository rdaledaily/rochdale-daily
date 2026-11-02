/**
 * Private hand-off between the email-intake Worker and the email-intake
 * GitHub workflow. Admin token only (x-admin-token = EVENTS_ADMIN_TOKEN).
 *
 *   GET    /api/inbox-raw              -> {"keys": [{"name","bytes"}...]} waiting messages
 *   GET    /api/inbox-raw?key=...      -> the raw message bytes (message/rfc822)
 *   DELETE /api/inbox-raw?key=...      -> remove after the workflow has committed it
 *
 * Raw messages live in EVENTS_KV under inbox:raw:* (written by
 * workers/email-intake/worker.js, expire after 30 days). They contain sender
 * addresses and full headers, so they are never served publicly and never
 * committed to the repo.
 */

const PREFIX = "inbox:raw:";

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
  return diff === 0;
}

function validKey(key) {
  return typeof key === "string" && key.startsWith(PREFIX) && /^inbox:raw:[0-9TZ]+-[0-9a-f-]{36}$/.test(key);
}

export async function onRequest({ request, env }) {
  if (!isAdmin(request, env)) return json({ error: "not found" }, 404);
  if (!env.EVENTS_KV) return json({ error: "EVENTS_KV binding missing" }, 500);
  const url = new URL(request.url);
  const key = url.searchParams.get("key");

  if (request.method === "GET" && !key) {
    const keys = [];
    let cursor;
    do {
      const page = await env.EVENTS_KV.list({ prefix: PREFIX, cursor });
      for (const k of page.keys) keys.push({ name: k.name, bytes: (k.metadata && k.metadata.bytes) || null });
      cursor = page.list_complete ? undefined : page.cursor;
    } while (cursor);
    keys.sort((a, b) => a.name.localeCompare(b.name));
    return json({ keys });
  }

  if (!validKey(key)) return json({ error: "bad key" }, 400);

  if (request.method === "GET") {
    const value = await env.EVENTS_KV.get(key, "arrayBuffer");
    if (value === null) return json({ error: "gone" }, 404);
    return new Response(value, { headers: { "Content-Type": "message/rfc822", "Cache-Control": "no-store" } });
  }

  if (request.method === "DELETE") {
    await env.EVENTS_KV.delete(key);
    return json({ deleted: key });
  }

  return json({ error: "method not allowed" }, 405);
}
