/**
 * /api/events
 *
 * Public:
 *   GET  /api/events                  -> approved community events, in the same
 *                                        shape the front page already uses for
 *                                        articles.json entries.
 *   GET  /api/events?image=<id>       -> the JPEG for one approved event.
 *
 * Newsdesk (requires header  x-admin-token: <EVENTS_ADMIN_TOKEN>):
 *   GET  /api/events?queue=pending    -> the moderation queue, contact details included.
 *   POST /api/events                  -> { "action": "approve" | "reject", "id": "evt-..." }
 *
 * Bindings required: EVENTS_KV, EVENTS_ADMIN_TOKEN.
 */

const APPROVED_CAP = 50;

function json(body, status = 200, cache = "no-store") {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cache,
    },
  });
}

function isAdmin(request, env) {
  const token = request.headers.get("x-admin-token") || "";
  const expected = env.EVENTS_ADMIN_TOKEN || "";
  if (!expected || token.length !== expected.length) return false;
  // Constant-time-ish comparison.
  let diff = 0;
  for (let i = 0; i < expected.length; i += 1) {
    diff |= token.charCodeAt(i) ^ expected.charCodeAt(i);
  }
  return diff === 0;
}

async function readList(kv, key) {
  const value = await kv.get(key, { type: "json" });
  return Array.isArray(value) ? value : [];
}

/** Combine the date and the start half of "14:00-19:00" into an ISO timestamp. */
function eventStartAt(record) {
  const start = String(record.time || "").split(/[-\u2013]/)[0].trim();
  const time = /^\d{2}:\d{2}$/.test(start) ? start : "00:00";
  return `${record.date}T${time}:00`;
}

function eventEndAt(record) {
  const parts = String(record.time || "").split(/[-\u2013]/);
  const end = String(parts[1] || "").trim();
  return /^\d{2}:\d{2}$/.test(end) ? `${record.date}T${end}:00` : "";
}

/** Map a stored record onto the article shape the front page renders. */
function toArticleShape(record) {
  const costLabel = /^free$/i.test(String(record.cost || "").trim())
    ? "Free"
    : `£${String(record.cost).replace(/^£/, "")}`;

  const summaryParts = [];
  if (record.description) summaryParts.push(record.description);
  summaryParts.push(`${record.time}. ${costLabel} entry.`);

  return {
    id: record.id,
    slug: record.slug || record.id,
    title: record.title,
    kicker: "What's on",
    category: "events",
    section: "events",
    source_kind: "event",
    source_name: "Reader submission",
    area: "rochdale",
    status: "published",
    summary: summaryParts.join(" "),
    body: record.description ? [record.description] : [],
    image: record.imageKey ? `/api/events?image=${encodeURIComponent(record.id)}` : "",
    imageLabel: "Submitted by the organiser",
    byline: "Rochdale Daily Newsdesk",
    published_at: record.approvedAt || record.submittedAt,
    updated_at: record.approvedAt || record.submittedAt,
    event_start_at: eventStartAt(record),
    event_end_at: eventEndAt(record),
    event_location: `${record.location}, ${record.postcode}`,
    event_cost: costLabel,
    community_submitted: true,
  };
}

/* ------------------------------------------------------------------ *
 * GET
 * ------------------------------------------------------------------ */

export async function onRequestGet({ request, env }) {
  const kv = env.EVENTS_KV;
  if (!kv) return json({ events: [] }, 200);

  const url = new URL(request.url);

  // --- image passthrough -------------------------------------------------
  const imageId = url.searchParams.get("image");
  if (imageId) {
    // The moderation page needs to SEE a submitted photograph before deciding
    // on it. Approving an image sight-unseen is the obvious route for something
    // inappropriate to reach the front page, so an authenticated request may
    // also read images still sitting in the pending queue. Unauthenticated
    // requests continue to see approved images only.
    const wantsPending = url.searchParams.get("queue") === "pending";
    const list = wantsPending && isAdmin(request, env)
      ? await readList(kv, "events:pending")
      : await readList(kv, "events:approved");
    const record = list.find(item => item.id === imageId);
    if (!record || !record.imageKey) return new Response("Not found", { status: 404 });

    const base64 = await kv.get(record.imageKey);
    if (!base64) return new Response("Not found", { status: 404 });

    const binary = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
    return new Response(binary, {
      headers: {
        "Content-Type": "image/jpeg",
        "Cache-Control": wantsPending ? "no-store" : "public, max-age=86400",
      },
    });
  }

  // --- moderation queue --------------------------------------------------
  if (url.searchParams.get("queue") === "pending") {
    if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
    const pending = await readList(kv, "events:pending");
    return json({ ok: true, count: pending.length, capacity: 50, pending });
  }

  // --- public feed -------------------------------------------------------
  const approved = await readList(kv, "events:approved");
  const cutoff = Date.now() - 12 * 60 * 60 * 1000;   // keep today's events visible

  const events = approved
    .map(toArticleShape)
    .filter(event => {
      const start = new Date(event.event_start_at).getTime();
      return !Number.isFinite(start) || start >= cutoff;
    })
    .sort((a, b) => new Date(a.event_start_at) - new Date(b.event_start_at));

  return json({ ok: true, events }, 200, "public, max-age=120");
}

/* ------------------------------------------------------------------ *
 * POST — approve or reject
 * ------------------------------------------------------------------ */

export async function onRequestPost({ request, env }) {
  const kv = env.EVENTS_KV;
  if (!kv) return json({ ok: false, error: "Not configured" }, 503);
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);

  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, error: "Invalid JSON" }, 400);
  }

  const action = String(payload.action || "").toLowerCase();
  const id = String(payload.id || "");
  if (!id || (action !== "approve" && action !== "reject")) {
    return json({ ok: false, error: 'Send { action: "approve" | "reject", id }' }, 400);
  }

  const pending = await readList(kv, "events:pending");
  const index = pending.findIndex(item => item.id === id);
  if (index === -1) return json({ ok: false, error: "Not in the queue" }, 404);

  const [record] = pending.splice(index, 1);
  await kv.put("events:pending", JSON.stringify(pending));

  if (action === "reject") {
    if (record.imageKey) await kv.delete(record.imageKey).catch(() => {});
    return json({ ok: true, action: "reject", id });
  }

  // Approve: strip the contact details before anything reaches the public list.
  const approved = await readList(kv, "events:approved");
  const { contact, submitterHash, ...publicRecord } = record;
  approved.unshift({ ...publicRecord, status: "approved", approvedAt: new Date().toISOString() });

  const dropped = approved.splice(APPROVED_CAP);
  await kv.put("events:approved", JSON.stringify(approved));
  for (const item of dropped) {
    if (item && item.imageKey) await kv.delete(item.imageKey).catch(() => {});
  }

  return json({ ok: true, action: "approve", id, live: approved.length });
}
