/** Residents' Corner submissions and moderation.
 * Bindings: EVENTS_KV and EVENTS_ADMIN_TOKEN (shared with event moderation).
 */
const PENDING_KEY = "residents:pending";
const APPROVED_KEY = "residents:approved";
const MAX_PENDING = 100;
const MAX_APPROVED = 80;
const TYPES = new Set(["story", "recipe", "birthday", "exam", "death", "missing_pet", "found_pet"]);

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
async function readList(kv, key) {
  const value = await kv.get(key, { type: "json" });
  return Array.isArray(value) ? value : [];
}
function clean(value, max = 5000) {
  return String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
}
function id() {
  return `resident-${Date.now().toString(36)}-${crypto.randomUUID().slice(0, 8)}`;
}

export async function onRequestGet({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  const url = new URL(request.url);
  if (url.searchParams.get("queue") === "pending") {
    if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
    const pending = await readList(env.EVENTS_KV, PENDING_KEY);
    return json({ ok: true, pending, count: pending.length });
  }
  const approved = await readList(env.EVENTS_KV, APPROVED_KEY);
  return json({ ok: true, items: approved.map(({ contact, ...item }) => item) });
}

export async function onRequestPost({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  let payload;
  try { payload = await request.json(); } catch { return json({ ok: false, error: "Invalid JSON" }, 400); }

  if (isAdmin(request, env) && payload.action) {
    const action = clean(payload.action, 20).toLowerCase();
    const targetId = clean(payload.id, 100);
    if (!["approve", "reject"].includes(action) || !targetId) return json({ ok: false, error: "Invalid moderation request" }, 400);
    const pending = await readList(env.EVENTS_KV, PENDING_KEY);
    const index = pending.findIndex(item => item.id === targetId);
    if (index < 0) return json({ ok: false, error: "Submission not found" }, 404);
    const [item] = pending.splice(index, 1);
    await env.EVENTS_KV.put(PENDING_KEY, JSON.stringify(pending));
    if (action === "approve") {
      const approved = await readList(env.EVENTS_KV, APPROVED_KEY);
      const { contact, ...publicItem } = item;
      approved.unshift({ ...publicItem, status: "approved", approvedAt: new Date().toISOString() });
      approved.splice(MAX_APPROVED);
      await env.EVENTS_KV.put(APPROVED_KEY, JSON.stringify(approved));
    }
    return json({ ok: true, action, id: targetId });
  }

  const type = clean(payload.type, 30).toLowerCase();
  const title = clean(payload.title, 160);
  const body = clean(payload.body, 7000);
  const name = clean(payload.name, 100);
  const area = clean(payload.area, 100);
  const contact = clean(payload.contact, 180);
  const eventDate = clean(payload.eventDate, 40);
  const location = clean(payload.location, 180);
  const animalDetails = clean(payload.animalDetails, 1000);
  const consent = payload.consent === true;
  const familyPermission = payload.familyPermission === true;

  if (!TYPES.has(type)) return json({ ok: false, error: "Choose a valid submission type" }, 400);
  if (!title || !body || !name || !area || !contact) return json({ ok: false, error: "Complete all required fields" }, 400);
  if (!consent) return json({ ok: false, error: "Permission to review and publish is required" }, 400);
  if (type === "death" && !familyPermission) return json({ ok: false, error: "Death notices must be submitted with the family's permission" }, 400);
  if ((type === "missing_pet" || type === "found_pet") && (!eventDate || !location || !animalDetails)) {
    return json({ ok: false, error: "Include when and where the animal was last seen or found, plus identifying details" }, 400);
  }

  const pending = await readList(env.EVENTS_KV, PENDING_KEY);
  if (pending.length >= MAX_PENDING) return json({ ok: false, error: "The submission queue is temporarily full" }, 429);
  pending.unshift({
    id: id(), type, title, body, name, area, contact,
    eventDate, location, animalDetails,
    familyPermission: type === "death" ? familyPermission : undefined,
    submittedAt: new Date().toISOString(), status: "pending"
  });
  await env.EVENTS_KV.put(PENDING_KEY, JSON.stringify(pending));
  return json({ ok: true, message: "Thank you. Your submission has been sent to the Rochdale Daily newsdesk for review." }, 201);
}