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
    // direct API caller cannot smuggle it into the pipeline. The control-class
    // is written with \u escapes and kept on one line so the regex literal can
    // never be split across a newline (that truncation once failed the build).
    .replace(/:{0,2}contentReference\[oaicite:\d+\]\{index=\d+\}/g, "")
    .replace(/【[^】]*】/g, "")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]+/g, "")
    .trim()
    .slice(0, max);
}

// Headline -> URL slug. Matches the pipeline's own slugging closely enough that
// publish-pending-manual can merge the record with no special-casing.
function slugify(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/['‘’]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80);
}

export async function onRequestGet({ request, env }) {
  // No token, no access -- to submit, to list, or to drain.
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  const pending = await readList(env.EVENTS_KV, PENDING_KEY);
  return json({ ok: true, pending, count: pending.length });
}

export async function onRequestPost({ request, env }) {
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);

  let payload;
  try {
    payload = await request.json();
  } catch (_) {
    return json({ ok: false, error: "Invalid JSON" }, 400);
  }
  if (!payload || typeof payload !== "object") {
    return json({ ok: false, error: "Invalid request" }, 400);
  }

  // Drain branch: the workflow clears only the items it has already committed
  // to the repo, by id. An empty id list is refused so a mistaken call can
  // never wipe the whole queue.
  if (payload.action) {
    const action = clean(payload.action, 20).toLowerCase();
    if (action !== "drain") return json({ ok: false, error: "Unknown action" }, 400);
    const ids = Array.isArray(payload.ids)
      ? payload.ids.map(value => clean(value, 100)).filter(Boolean)
      : [];
    if (!ids.length) return json({ ok: false, error: "Provide the ids to drain" }, 400);
    const pending = await readList(env.EVENTS_KV, PENDING_KEY);
    const remove = new Set(ids);
    const kept = pending.filter(item => !remove.has(item.id));
    const drained = pending.length - kept.length;
    await env.EVENTS_KV.put(PENDING_KEY, JSON.stringify(kept));
    return json({ ok: true, drained, remaining: kept.length });
  }

  // Submit branch: the editor's finished article.
  const title = clean(payload.title, 160);
  const body = clean(payload.body, 7000);
  const excerpt = clean(payload.excerpt, 400);
  const category = clean(payload.category, 40).toLowerCase();
  const area = clean(payload.area, 100).toLowerCase();
  const imageUrl = clean(payload.image_url, 400);
  const imageCredit = clean(payload.image_credit, 200) || "Rochdale Daily";
  const publishedAt = clean(payload.published_at, 40);
  const providedSlug = slugify(clean(payload.slug, 160));
  const slug = providedSlug || slugify(title);

  if (!title) return json({ ok: false, error: "A headline is required" }, 400);
  if (!body) return json({ ok: false, error: "The article body is required" }, 400);
  if (!imageUrl) return json({ ok: false, error: "An image is required" }, 400);
  if (!VALID_CATEGORIES.has(category)) return json({ ok: false, error: "Choose a valid category" }, 400);
  if (!slug) return json({ ok: false, error: "The headline does not make a valid link" }, 400);

  const pending = await readList(env.EVENTS_KV, PENDING_KEY);
  if (pending.some(item => item.id === slug)) {
    return json({ ok: false, error: "An article with this headline is already queued" }, 409);
  }
  if (pending.length >= MAX_PENDING) {
    return json({ ok: false, error: "The newsdesk queue is temporarily full" }, 429);
  }

  const nowIso = new Date().toISOString();
  // Shape the record the way the pipeline's manual articles look, so
  // publish-pending-manual merges it straight into manual_articles.json.
  const article = {
    id: slug,
    slug,
    title,
    excerpt: excerpt || body.slice(0, 220),
    body,
    category,
    area,
    types: ["news"],
    image_url: imageUrl,
    img: imageUrl,
    image_credit: imageCredit,
    image_status: "editorial-photo",
    published_at: publishedAt || nowIso,
    first_published_at: publishedAt || nowIso,
    last_updated_at: nowIso,
    scraped_at: nowIso,
    source_name: "Rochdale Daily",
    source_names: ["Rochdale Daily"],
    byline: "Rochdale Daily",
    status: "published",
    manual_article: true,
    editorial_lock: true,
    rewrite_quality_checked: true,
    publication_route: "newsdesk-composer",
    right_to_reply: "Anyone named in this article can reply by emailing news@rochdaledaily.co.uk and we will publish or append their response.",
  };

  pending.unshift({ id: slug, article, submittedAt: nowIso });
  await env.EVENTS_KV.put(PENDING_KEY, JSON.stringify(pending));
  return json({ ok: true, id: slug, message: "Queued for publication." }, 201);
}
