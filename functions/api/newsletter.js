/** Newsletter signups.
 *
 * Bindings: EVENTS_KV (shared), EVENTS_ADMIN_TOKEN (shared), EVENTS_IP_SALT (shared).
 *
 * Storage layout in EVENTS_KV:
 *   newsletter:sub:<sha256(email)>   {"email","consented_at","source","ip_hash"}
 *   newsletter:index                 JSON array of hashes, newest first (for export)
 *   newsletter:rl:<ipHash>           rolling per-address rate limit
 *
 * Why this exists before an email provider is chosen: the audience is the
 * asset, and a signup box that works today is worth more than a perfect
 * provider next month. When one is chosen, GET /api/newsletter?export=csv with
 * the admin token returns every consented address for import. The provider
 * then handles confirmation and unsubscribe. Until then nothing is sent.
 *
 * Consent record per UK GDPR / PECR: we store what was consented to, when,
 * and a salted hash of the requesting IP (not the IP). No other data.
 */
const INDEX_KEY = "newsletter:index";
const MAX_INDEX = 20000;
const RL_WINDOW_MS = 10 * 60 * 1000;
const RL_MAX = 5;
const CONSENT_TEXT = "Send me the Rochdale Daily newsletter. I can unsubscribe at any time.";

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

async function sha256(text) {
  const data = new TextEncoder().encode(text);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function normaliseEmail(value) {
  const email = String(value || "").trim().toLowerCase().slice(0, 254);
  // Deliberately simple: one @, a dot in the domain, no whitespace. Provider
  // confirmation is the real validation.
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return "";
  return email;
}

async function readJson(kv, key, fallback) {
  const value = await kv.get(key, { type: "json" });
  return value == null ? fallback : value;
}

export async function onRequestPost({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return json({ ok: false, error: "Invalid request" }, 400);
  }
  // Honeypot: real forms leave this empty; bots fill every field.
  if (String(body.website || "").trim()) return json({ ok: true });

  const email = normaliseEmail(body.email);
  if (!email) return json({ ok: false, error: "Please enter a valid email address." }, 400);
  if (body.consent !== true) return json({ ok: false, error: "Please tick the box to consent." }, 400);

  const kv = env.EVENTS_KV;
  const ip = request.headers.get("CF-Connecting-IP") || "0.0.0.0";
  const ipHash = (await sha256(`${env.EVENTS_IP_SALT || "salt"}:${ip}`)).slice(0, 32);
  const rlKey = `newsletter:rl:${ipHash}`;
  const now = Date.now();
  const limiter = await readJson(kv, rlKey, { start: now, count: 0 });
  if (now - limiter.start > RL_WINDOW_MS) {
    limiter.start = now;
    limiter.count = 0;
  }
  if (limiter.count >= RL_MAX) return json({ ok: false, error: "Too many attempts. Please try again later." }, 429);
  limiter.count += 1;
  await kv.put(rlKey, JSON.stringify(limiter), { expirationTtl: Math.ceil(RL_WINDOW_MS / 1000) });

  const hash = await sha256(email);
  const subKey = `newsletter:sub:${hash}`;
  const existing = await kv.get(subKey);
  if (!existing) {
    await kv.put(
      subKey,
      JSON.stringify({
        email,
        consented_at: new Date(now).toISOString(),
        consent_text: CONSENT_TEXT,
        source: String(body.source || "homepage").slice(0, 40),
        ip_hash: ipHash,
      }),
    );
    const index = await readJson(kv, INDEX_KEY, []);
    index.unshift(hash);
    await kv.put(INDEX_KEY, JSON.stringify(index.slice(0, MAX_INDEX)));
  }
  // Same answer whether new or already subscribed: never reveal membership.
  return json({ ok: true, message: "Thanks. You're on the list." });
}

export async function onRequestGet({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
  const url = new URL(request.url);
  const index = await readJson(env.EVENTS_KV, INDEX_KEY, []);
  if (url.searchParams.get("export") !== "csv") return json({ ok: true, count: index.length });

  const rows = ["email,consented_at,source"];
  for (const hash of index) {
    const record = await readJson(env.EVENTS_KV, `newsletter:sub:${hash}`, null);
    if (record && record.email) rows.push(`${record.email},${record.consented_at},${record.source}`);
  }
  return new Response(rows.join("\n") + "\n", {
    headers: {
      "Content-Type": "text/csv; charset=utf-8",
      "Content-Disposition": "attachment; filename=rochdale-daily-newsletter.csv",
      "Cache-Control": "no-store",
    },
  });
}

export async function onRequestDelete({ request, env }) {
  // Admin removal of one address (a reader asks to be forgotten before a provider exists).
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
  const url = new URL(request.url);
  const email = normaliseEmail(url.searchParams.get("email"));
  if (!email) return json({ ok: false, error: "email required" }, 400);
  const hash = await sha256(email);
  await env.EVENTS_KV.delete(`newsletter:sub:${hash}`);
  const index = (await readJson(env.EVENTS_KV, INDEX_KEY, [])).filter((h) => h !== hash);
  await env.EVENTS_KV.put(INDEX_KEY, JSON.stringify(index));
  return json({ ok: true });
}
