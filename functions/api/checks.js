/**
 * Newsdesk checks: when an editor read a published story against its sources.
 *
 *   GET    /api/checks                 -> {"checks": {"<slug>": "<ISO time>", ...}}   public
 *   GET    /api/checks?slug=<slug>     -> {"slug", "checked_at"|null}                  public
 *   POST   /api/checks  {"slug"}       -> records the check now           admin token only
 *   DELETE /api/checks?slug=<slug>     -> removes a mistaken check       admin token only
 *
 *   GET    /api/checks?approvals=1     -> {"approvals": {"<story id>": "<ISO time>"}}  public
 *   POST   /api/checks  {"approve": "<story id>"}  -> approves a held newsletter court
 *                                         story for writing             admin token only
 *   DELETE /api/checks?approval=<id>  -> withdraws an approval          admin token only
 *
 * The time is always the server's, never the browser's, so a check can't be
 * backdated. Only the editor's tap creates one: the pipeline never writes
 * here, so "Checked" on a page is always a true statement. Stored in
 * EVENTS_KV under check:<slug>. A check is accepted only for a story that is
 * published (its page exists).
 */

const PREFIX = "check:";
const APPROVE_PREFIX = "nlapprove:";
const ID_RE = /^[0-9a-f]{16}$/;
const SLUG_RE = /^[a-z0-9][a-z0-9-]{3,180}$/;

function json(body, status = 200, cache = "no-store") {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": cache },
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

async function storyIsPublished(env, request, slug) {
  if (!env.ASSETS) return true;
  const origin = new URL(request.url).origin;
  try {
    const response = await env.ASSETS.fetch(new Request(`${origin}/articles/${slug}.html`, { method: "GET" }));
    return response.status === 200;
  } catch (error) {
    return false;
  }
}

async function allChecks(env, prefix = PREFIX) {
  const checks = {};
  let cursor;
  do {
    const page = await env.EVENTS_KV.list({ prefix, cursor });
    for (const key of page.keys) {
      // The time rides in the key's metadata, so a listing is one KV read
      // however many stories have been checked.
      const value = (key.metadata && key.metadata.checked_at) || (await env.EVENTS_KV.get(key.name));
      if (value) checks[key.name.slice(prefix.length)] = value;
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return checks;
}

export async function onRequestGet({ request, env }) {
  if (!env.EVENTS_KV) return json({ error: "EVENTS_KV binding missing" }, 500);
  const params = new URL(request.url).searchParams;
  if (params.get("approvals") === "1") {
    return json({ approvals: await allChecks(env, APPROVE_PREFIX) }, 200, "no-store");
  }
  const slug = params.get("slug");
  if (slug !== null) {
    if (!SLUG_RE.test(slug)) return json({ error: "bad slug" }, 400);
    const checkedAt = await env.EVENTS_KV.get(PREFIX + slug);
    return json({ slug, checked_at: checkedAt || null }, 200, "public, max-age=30");
  }
  return json({ checks: await allChecks(env) }, 200, "public, max-age=30");
}

export async function onRequestPost({ request, env }) {
  if (!isAdmin(request, env)) return json({ error: "unauthorised" }, 401);
  if (!env.EVENTS_KV) return json({ error: "EVENTS_KV binding missing" }, 500);
  const body = await request.json().catch(() => ({}));
  if (body && body.approve !== undefined) {
    const id = String(body.approve || "");
    if (!ID_RE.test(id)) return json({ error: "bad story id" }, 400);
    const approvedAt = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
    await env.EVENTS_KV.put(APPROVE_PREFIX + id, approvedAt, { metadata: { checked_at: approvedAt } });
    return json({ id, approved_at: approvedAt });
  }
  const slug = String((body && body.slug) || "");
  if (!SLUG_RE.test(slug)) return json({ error: "bad slug" }, 400);
  if (!(await storyIsPublished(env, request, slug))) return json({ error: "no published story with that slug" }, 404);
  const checkedAt = new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  await env.EVENTS_KV.put(PREFIX + slug, checkedAt, { metadata: { checked_at: checkedAt } });
  return json({ slug, checked_at: checkedAt });
}

export async function onRequestDelete({ request, env }) {
  if (!isAdmin(request, env)) return json({ error: "unauthorised" }, 401);
  if (!env.EVENTS_KV) return json({ error: "EVENTS_KV binding missing" }, 500);
  const params = new URL(request.url).searchParams;
  if (params.has("approval")) {
    const id = params.get("approval") || "";
    if (!ID_RE.test(id)) return json({ error: "bad story id" }, 400);
    await env.EVENTS_KV.delete(APPROVE_PREFIX + id);
    return json({ id, approved_at: null });
  }
  const slug = params.get("slug") || "";
  if (!SLUG_RE.test(slug)) return json({ error: "bad slug" }, 400);
  await env.EVENTS_KV.delete(PREFIX + slug);
  return json({ slug, checked_at: null });
}
