/** Newsdesk composer intake — the editor's own manual-article queue.
 *
 * This is NOT Residents' Corner. Residents' Corner takes public submissions and
 * holds them for moderation; this endpoint takes the EDITOR's finished articles
 * and queues them for automatic publication, so every request -- submitting,
 * listing, draining -- requires the admin token. Anyone without it gets 401 and
 * nothing else.
 *
 * Flow: newsdesk.html POSTs a composed article here with the admin token; it
 * lands in EVENTS_KV under "newsdesk:pending". A scheduled workflow
 * (newsdesk-drain.yml) reads the queue with the same token, writes each item as
 * a pending_manual_<id>.json in the repo, and calls back with {action:"drain"}
 * to clear them -- at which point the existing publish-pending-manual workflow
 * merges them into manual_articles.json and the full pipeline runs (image
 * matching, category page, SEO). The editor never touches GitHub.
 *
 * Bindings: EVENTS_KV and EVENTS_ADMIN_TOKEN, shared with events/residents.
 */
const PENDING_KEY = "newsdesk:pending";
const MAX_PENDING = 200;
const VALID_CATEGORIES = new Set([
  "news", "crime", "politics", "traffic", "transport", "sport", "business",
  "health", "education", "environment", "community", "events",
]);

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
  return diff === 0;  // constant-time compare, matching residents.js
}

async function readList(kv, key) {
  const value = await kv.get(key, { type: "json" });
  return Array.isArray(value) ? value : [];
}

function clean(value, max = 8000) {
  return String(value || "")
    // Strip the ChatGPT citation furniture the validator rejects, plus control
    // characters. The composer does this too; doing it here as well means a
    // direct API caller cannot smuggle it into the pipeline.
    .replace(/:{0,2}contentReference\[oaicite:\d+\]\{index=\d+\}/g, "")
    .replace(/【[^】]*】/g, "")
    .replace(/[
