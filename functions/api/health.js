/** GET /api/health: public status for the read-only APIs.
 *
 * "ok" when the story feed is readable and was refreshed in the last six
 * hours, "degraded" when it is older, "down" (HTTP 503) when it cannot be read.
 */
const STALE_MS = 6 * 60 * 60 * 1000;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*" },
  });
}

export async function onRequestGet({ request, env }) {
  const checkedAt = new Date().toISOString();
  let stories;
  try {
    const res = await env.ASSETS.fetch(new URL("/articles.json", request.url));
    if (!res.ok) throw new Error("HTTP " + res.status);
    stories = await res.json();
    if (!Array.isArray(stories)) throw new Error("not a list");
  } catch (error) {
    return json({ status: "down", checked_at: checkedAt, feed: "unreadable" }, 503);
  }
  let latest = 0;
  for (const s of stories) {
    const t = Date.parse(s.last_updated_at || s.published_at || "");
    if (Number.isFinite(t) && t > latest) latest = t;
  }
  const fresh = latest && Date.now() - latest < STALE_MS;
  return json({
    status: fresh ? "ok" : "degraded",
    checked_at: checkedAt,
    stories: stories.length,
    latest_story_at: latest ? new Date(latest).toISOString() : null,
    events_store: env.EVENTS_KV ? "available" : "unavailable",
  });
}
