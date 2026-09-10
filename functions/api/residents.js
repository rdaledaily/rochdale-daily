/** Residents' Corner submissions and moderation.
 * Bindings: EVENTS_KV and EVENTS_ADMIN_TOKEN (shared with event moderation).
 *
 * Photographs (added 10 Sep 2026)
 * -------------------------------
 * Readers can now attach one photo. Three things made that safe to add without
 * standing up new infrastructure:
 *
 *   - The browser resizes and re-encodes the picture before it is sent, so what
 *     arrives is a few hundred KB of JPEG rather than a 12MB phone original.
 *     Re-encoding to a canvas also strips EXIF, which means a reader's home
 *     GPS coordinates never reach the newsdesk in the first place.
 *   - The image is stored under its OWN key, never inside the pending list.
 *     The queue is a single JSON value; embedding base64 photographs in it
 *     would bloat every read and eventually break the moderation page.
 *   - Only the editor can see an unapproved photo. A pending image requires the
 *     admin token; approved ones are public because they have been reviewed.
 *
 * Nothing is published by submitting. Everything waits for moderation.
 */
const PENDING_KEY = "residents:pending";
const APPROVED_KEY = "residents:approved";
const IMAGE_PREFIX = "residents:image:";
const MAX_PENDING = 100;
const MAX_APPROVED = 80;

/* Obituaries, weddings, births and Pride announcements join the original set:
   the same queue and the same moderation serve all of them. */
const TYPES = new Set([
  "story", "recipe", "birthday", "exam", "death",
  "missing_pet", "found_pet", "wedding", "birth", "pride",
]);

/* Types where a photograph is the point of the submission. */
const PHOTO_TYPES = new Set(["wedding", "birth", "pride", "death", "missing_pet", "found_pet", "story", "recipe"]);

/* ~1.4MB of base64. The browser aims far below this; the cap is here to stop a
   hand-crafted request filling KV, not to constrain honest submissions. */
const MAX_IMAGE_CHARS = 1900000;
const IMAGE_PATTERN = /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=\s]+$/;

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

/** Validate a submitted data URL. Returns the string, or "" if unusable. */
function cleanImage(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  if (text.length > MAX_IMAGE_CHARS) return "";
  if (!IMAGE_PATTERN.test(text)) return "";
  return text;
}

export async function onRequestGet({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  const url = new URL(request.url);

  /* One photo, by submission id. Unapproved photos are editor-only: a reader's
     picture must not be reachable before anyone has looked at it. */
  const wantedImage = clean(url.searchParams.get("image"), 100);
  if (wantedImage) {
    const approved = await readList(env.EVENTS_KV, APPROVED_KEY);
    const isApproved = approved.some(item => item.id === wantedImage);
    if (!isApproved && !isAdmin(request, env)) {
      return json({ ok: false, error: "Unauthorised" }, 401);
    }
    const stored = await env.EVENTS_KV.get(IMAGE_PREFIX + wantedImage);
    if (!stored) return json({ ok: false, error: "No photo for that submission" }, 404);
    return json({ ok: true, id: wantedImage, image: stored });
  }

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
      const dropped = approved.splice(MAX_APPROVED);
      await env.EVENTS_KV.put(APPROVED_KEY, JSON.stringify(approved));
      /* Photos belonging to items that have aged out are deleted with them;
         nothing should linger in storage that no page can reach. */
      for (const old of dropped) {
        if (old && old.hasImage) await env.EVENTS_KV.delete(IMAGE_PREFIX + old.id);
      }
    } else if (item.hasImage) {
      await env.EVENTS_KV.delete(IMAGE_PREFIX + item.id);
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
  const photoCredit = clean(payload.photoCredit, 120);
  const consent = payload.consent === true;
  const familyPermission = payload.familyPermission === true;
  const photoConsent = payload.photoConsent === true;
  const image = cleanImage(payload.image);

  if (!TYPES.has(type)) return json({ ok: false, error: "Choose a valid submission type" }, 400);
  if (!title || !body || !name || !area || !contact) return json({ ok: false, error: "Complete all required fields" }, 400);
  if (!consent) return json({ ok: false, error: "Permission to review and publish is required" }, 400);
  if (type === "death" && !familyPermission) return json({ ok: false, error: "Death notices must be submitted with the family's permission" }, 400);
  if ((type === "missing_pet" || type === "found_pet") && (!eventDate || !location || !animalDetails)) {
    return json({ ok: false, error: "Include when and where the animal was last seen or found, plus identifying details" }, 400);
  }
  if (payload.image && !image) {
    return json({ ok: false, error: "That photo could not be read. Use a JPEG, PNG or WebP under about 1MB." }, 400);
  }
  /* A photograph of identifiable people needs the photographer's permission to
     publish it. Asking once, here, is the difference between a picture desk and
     a copyright problem. */
  if (image && !photoConsent) {
    return json({ ok: false, error: "Confirm the photo is yours to share before submitting it." }, 400);
  }
  if (image && !PHOTO_TYPES.has(type)) {
    return json({ ok: false, error: "Photos are not accepted for that submission type." }, 400);
  }

  const pending = await readList(env.EVENTS_KV, PENDING_KEY);
  if (pending.length >= MAX_PENDING) return json({ ok: false, error: "The submission queue is temporarily full" }, 429);

  const submissionId = id();
  if (image) {
    /* Stored apart from the queue so the moderation list stays small. */
    await env.EVENTS_KV.put(IMAGE_PREFIX + submissionId, image);
  }
  pending.unshift({
    id: submissionId, type, title, body, name, area, contact,
    eventDate, location, animalDetails,
    familyPermission: type === "death" ? familyPermission : undefined,
    hasImage: Boolean(image),
    photoCredit: image ? (photoCredit || name) : undefined,
    submittedAt: new Date().toISOString(), status: "pending"
  });
  await env.EVENTS_KV.put(PENDING_KEY, JSON.stringify(pending));
  return json({
    ok: true,
    message: "Thank you. Your submission has been sent to the Rochdale Daily newsdesk for review."
  }, 201);
}
