/** Newsletter signups.
 *
 * Bindings: EVENTS_KV (shared), EVENTS_ADMIN_TOKEN (shared), EVENTS_IP_SALT (shared).
 *
 * Storage layout in EVENTS_KV:
 *   newsletter:sub:<sha256(email)>   {"email","consented_at","source","ip_hash"}
 *   newsletter:index                 legacy index; exports use individual records
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
  const email = String(value || "").trim().toLowerCase();
  // Deliberately simple: one @, a dot in the domain, no whitespace. Provider
  // confirmation is the real validation.
  if (email.length>254 || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return "";
  return email;
}

async function readJson(kv, key, fallback) {
  const value = await kv.get(key, { type: "json" });
  return value == null ? fallback : value;
}


/* Optional Brevo contact sync. Subscriber consent remains in our KV ledger;
 * this only joins the configured newsletter list, never sends a campaign.
 * Do not subscribe someone whom the provider has already suppressed.
 */
async function syncBrevo(env,record){
  if(!env.BREVO_API_KEY||!env.BREVO_LIST_ID)return {configured:false,synced:false};
  const listId=Number(env.BREVO_LIST_ID);
  if(!Number.isSafeInteger(listId)||listId<=0)return {configured:false,synced:false};
  const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),6500);
  try{
    const r=await fetch('https://api.brevo.com/v3/contacts',{
      method:'POST',
      headers:{'api-key':env.BREVO_API_KEY,'Content-Type':'application/json','Accept':'application/json'},
      body:JSON.stringify({email:record.email,listIds:[listId],updateEnabled:false}),
      signal:ctrl.signal
    });
    // Provider duplicate/blacklisted contacts must not be reactivated just
    // because a local user retried the form.
    if(r.status===201||r.status===204)return {configured:true,synced:true};
    if(r.status===400||r.status===409)return {configured:true,synced:false,reason:'review_provider_existing_or_suppressed'};
    return {configured:true,synced:false,reason:'provider_error'};
  }catch{return {configured:true,synced:false,reason:'provider_unavailable'}}
  finally{clearTimeout(timer)}
}

export async function onRequestPost({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  let body;
  try {
    body = await request.json();
  } catch (err) {
    return json({ ok: false, error: "Invalid request" }, 400);
  }
  if (!body || typeof body!=="object" || Array.isArray(body)) return json({ok:false,error:"Invalid request"},400);
  if (body.action === "sync") return syncPending(request, env);
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
    // Count/export enumerate the consent ledger directly. A redundant shared
    // index can race, or fail after consent was saved and before provider sync.
    // Do not let that obsolete bookkeeping turn a saved signup into an error.
  }
  // Sync only a fresh, explicit consent record, and never reinstate
  // provider-suppressed contacts. If the provider is offline the secure CSV
  // export remains available for a compliant, reviewed retry.
  if (!existing && env.BREVO_API_KEY && env.BREVO_LIST_ID) {
    const record = await readJson(kv, subKey, null);
    if (record) {
      const outcome = await syncBrevo(env, record);
      record.brevo_sync_status = outcome.synced ? "synced" : (outcome.reason || "not_configured");
      record.brevo_sync_attempt = new Date().toISOString();
      await kv.put(subKey, JSON.stringify(record));
    }
  }
  // Same answer whether new or already subscribed: never reveal membership.
  const providerConfigured=Boolean(env.BREVO_API_KEY&&Number.isSafeInteger(Number(env.BREVO_LIST_ID))&&Number(env.BREVO_LIST_ID)>0);
  return json({ ok: true, providerConfigured, message: providerConfigured
    ? "Your signup has been saved. You can unsubscribe using the link in every newsletter."
    : "Your signup has been saved. Email delivery is being set up; newsletters are not being sent yet." });
}

// The per-subscriber ledger is authoritative: concurrent signups can overwrite
// a shared KV index. List ledger keys so exports never silently omit consent.
async function subscriberHashes(kv){
 const hashes=[];let cursor;
 do{
  const page=await kv.list({prefix:'newsletter:sub:',limit:1000,...(cursor?{cursor}:{})});
  for(const key of page.keys||[])if(/^newsletter:sub:[a-f0-9]{64}$/.test(key.name))hashes.push(key.name.slice(15));
  cursor=page.list_complete?null:page.cursor;
 }while(cursor);
 return hashes;
}
function csvCell(value){
 const raw=String(value||'');
 // Escape quotes, commas and newlines, and prevent spreadsheet formulas.
 const safe=/^[=+@\-\t\r]/.test(raw)?"'"+raw:raw;
 return '"'+safe.replace(/"/g,'""')+'"';
}

/* Sign-ups saved before Brevo was connected (or while it was down) never
 * reached the list. These states are retried; anything Brevo already holds
 * (existing, unsubscribed or blocked contacts) is left alone and counted.
 */
const RETRYABLE = new Set(["", "not_configured", "provider_error", "provider_unavailable"]);
const SYNC_BATCH = 40; // stays inside the per-request subrequest limit

function syncState(record) {
  if (record.brevo_sync_status === "synced") return "synced";
  if (record.brevo_sync_status === "review_provider_existing_or_suppressed") return "held";
  return "waiting";
}

async function ledger(kv) {
  const records = [];
  for (const hash of await subscriberHashes(kv)) {
    const record = await readJson(kv, `newsletter:sub:${hash}`, null);
    if (record && record.email) records.push({ hash, record });
  }
  return records;
}

function summary(records) {
  const counts = { total: records.length, synced: 0, waiting: 0, held: 0 };
  for (const { record } of records) counts[syncState(record)] += 1;
  return counts;
}

async function syncPending(request, env) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
  if (!env.BREVO_API_KEY || !env.BREVO_LIST_ID) return json({ ok: false, error: "Brevo is not connected (BREVO_API_KEY / BREVO_LIST_ID)." }, 503);
  const records = await ledger(env.EVENTS_KV);
  const waiting = records.filter(({ record }) => RETRYABLE.has(String(record.brevo_sync_status || "")) && record.brevo_sync_status !== "synced");
  const batch = waiting.slice(0, SYNC_BATCH);
  const result = { added: 0, held: 0, failed: 0 };
  for (const { hash, record } of batch) {
    const outcome = await syncBrevo(env, record);
    record.brevo_sync_status = outcome.synced ? "synced" : (outcome.reason || "not_configured");
    record.brevo_sync_attempt = new Date().toISOString();
    await env.EVENTS_KV.put(`newsletter:sub:${hash}`, JSON.stringify(record));
    if (outcome.synced) result.added += 1;
    else if (outcome.reason === "review_provider_existing_or_suppressed") result.held += 1;
    else result.failed += 1;
  }
  // A failure stops further batches from looping on a provider outage.
  const remaining = waiting.length - batch.length;
  return json({ ok: true, ...result, remaining, more: remaining > 0 && result.failed === 0, counts: summary(records) });
}

export async function onRequestGet({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
  const url = new URL(request.url);
  if (url.searchParams.get("status") === "1") {
    const counts = summary(await ledger(env.EVENTS_KV));
    const providerConfigured = Boolean(env.BREVO_API_KEY && Number(env.BREVO_LIST_ID) > 0);
    return json({ ok: true, providerConfigured, counts });
  }
  const index = await subscriberHashes(env.EVENTS_KV);
  if (url.searchParams.get("export") !== "csv") return json({ ok: true, count: index.length });

  const rows = ["email,consented_at,source"];
  for (const hash of index) {
    const record = await readJson(env.EVENTS_KV, `newsletter:sub:${hash}`, null);
    if (record && record.email) rows.push([record.email,record.consented_at,record.source].map(csvCell).join(","));
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
  const index = (await subscriberHashes(env.EVENTS_KV)).filter((h) => h !== hash);
  await env.EVENTS_KV.put(INDEX_KEY, JSON.stringify(index));
  return json({ ok: true });
}
