/** Guest columns from readers, councillors and community voices.
 *
 * Flow
 *   1. /write-a-column posts a column here: headline, up to 700 words, the
 *      author's name and one-line description, declared interests, a section
 *      and a ward, plus an email address that is NEVER published.
 *   2. Nothing reaches the editor until the author proves the address is
 *      theirs: we email a link, and only a click moves the column into the
 *      review queue. Unclicked submissions expire after 48 hours.
 *   3. The editor reviews it on /column-moderate (admin token), can edit the
 *      headline and text, then approves or rejects. Approval puts the column
 *      on the newsdesk queue (functions/api/newsdesk.js), which the
 *      newsdesk-drain workflow publishes through the full pipeline within
 *      about 15 minutes. Nothing is ever published by submitting.
 *
 * Email is sent through Brevo (BREVO_API_KEY, already used for the
 * newsletter) from COLUMN_SENDER_EMAIL, default news@rochdaledaily.co.uk,
 * which must be a verified sender in Brevo. If the email cannot be sent the
 * writer is told so plainly and the reason is kept for the moderation page;
 * there is no unverified route into the queue.
 *
 * Photos: one optional picture (a headshot or an image for the column),
 * stored under its own key, visible only to the editor until approved. On
 * approval it is handed to the newsdesk queue, and newsdesk-drain.yml saves
 * it to assets/img/cards/ beside the article so the pipeline treats it as the
 * editor's own photo.
 *
 * Bindings: EVENTS_KV, EVENTS_ADMIN_TOKEN, BREVO_API_KEY.
 */
const PENDING_KEY = "columns:pending";
const VERIFY_PREFIX = "columns:verify:";
const RATE_PREFIX = "columns:rate:";
const LAST_EMAIL_ERROR = "columns:last-email-error";
const NEWSDESK_KEY = "newsdesk:pending";
const IMAGE_PREFIX = "columns:image:";          // editor-only until approved
const NEWSDESK_IMAGE_PREFIX = "newsdesk:image:"; // read by newsdesk-drain.yml
// Same rules as Residents' Corner: resized and re-encoded in the browser
// (which strips EXIF, so no home GPS ever arrives), at most ~1.4 MB.
const MAX_IMAGE_CHARS = 1900000;
const IMAGE_PATTERN = /^data:image\/(jpeg|png|webp);base64,[A-Za-z0-9+/=\s]+$/;
const VERIFY_TTL = 48 * 60 * 60;
const MAX_PENDING = 60;
const MAX_WORDS = 700;
const MIN_WORDS = 150;
const SITE = "https://rochdaledaily.co.uk";

// Crime and traffic are left out on purpose: a column about a live criminal
// case risks contempt of court, and traffic is service news, not opinion.
const CATEGORIES = {
  politics: "Politics", community: "Community", business: "Business", sport: "Sport",
  health: "Health", education: "Education", environment: "Environment and planning",
  transport: "Transport", events: "Arts and events", news: "Something else",
};

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

// One-line fields: control characters out, spaces collapsed.
function line(value, max) {
  return String(value || "").replace(/[\u0000-\u001f\u007f]/g, " ").replace(/\s+/g, " ").trim().slice(0, max);
}

// The column itself: paragraphs kept (blank line between), everything else tidied.
function prose(value, max = 9000) {
  return String(value || "")
    .replace(/\r\n?/g, "\n")
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g, "")
    .split(/\n\s*\n/)
    .map((p) => p.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .join("\n\n")
    .slice(0, max);
}

function wordCount(text) {
  return (String(text || "").match(/\S+/g) || []).length;
}

function slugify(value) {
  return String(value || "").toLowerCase().replace(/['‘’]/g, "").replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "").slice(0, 80);
}

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function cleanImage(value) {
  const text = String(value || "").trim();
  if (!text || text.length > MAX_IMAGE_CHARS || !IMAGE_PATTERN.test(text)) return "";
  return text;
}

const EMAIL_RE = /^[^\s@]{1,64}@[^\s@]{1,190}\.[a-z]{2,24}$/i;

async function readList(kv, key) {
  const value = await kv.get(key, { type: "json" });
  return Array.isArray(value) ? value : [];
}

async function sha(text) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

/** Ward name -> the area tag ward pages and read-next use. */
async function wardOptions(env, request) {
  try {
    const response = await env.ASSETS.fetch(new Request(new URL("/ward_areas.json", request.url)));
    const data = await response.json();
    const wards = (data && data.wards) || {};
    const out = { "Borough-wide": "rochdale" };
    for (const [name, info] of Object.entries(wards)) {
      const areas = (info && Array.isArray(info.areas)) ? info.areas : [];
      out[name] = areas[0] || slugify(name) || "rochdale";
    }
    return out;
  } catch (error) {
    return null;
  }
}

async function sendEmail(env, to, subject, text, html) {
  if (!env.BREVO_API_KEY) return { ok: false, reason: "BREVO_API_KEY is not set" };
  try {
    const response = await fetch("https://api.brevo.com/v3/smtp/email", {
      method: "POST",
      headers: { "api-key": env.BREVO_API_KEY, "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        sender: { name: "Rochdale Daily", email: env.COLUMN_SENDER_EMAIL || "news@rochdaledaily.co.uk" },
        to: [{ email: to }],
        subject,
        textContent: text,
        htmlContent: html,
      }),
    });
    if (response.ok) return { ok: true };
    const detail = await response.text();
    return { ok: false, reason: `Brevo HTTP ${response.status}: ${detail.slice(0, 200)}` };
  } catch (error) {
    return { ok: false, reason: `Brevo unreachable: ${String(error && error.message || error).slice(0, 160)}` };
  }
}

/** Five submissions an hour per address and per connection. */
async function rateLimited(env, keyText) {
  const key = RATE_PREFIX + (await sha(keyText));
  const count = Number(await env.EVENTS_KV.get(key)) || 0;
  if (count >= 5) return true;
  await env.EVENTS_KV.put(key, String(count + 1), { expirationTtl: 3600 });
  return false;
}

export async function onRequestGet({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  const url = new URL(request.url);

  // The link in the verification email.
  const verify = line(url.searchParams.get("verify"), 80);
  if (verify) {
    const back = (state) => Response.redirect(`${SITE}/write-a-column?verified=${state}`, 303);
    if (!/^[a-f0-9-]{36}$/.test(verify)) return back("invalid");
    const item = await env.EVENTS_KV.get(VERIFY_PREFIX + verify, { type: "json" });
    if (!item) return back("expired");
    const pending = await readList(env.EVENTS_KV, PENDING_KEY);
    if (!pending.some((p) => p.id === item.id)) {
      if (pending.length >= MAX_PENDING) return back("full");
      pending.unshift({ ...item, status: "verified", verifiedAt: new Date().toISOString() });
      if (item.hasImage) {
        // Unconfirmed photos expire with their link; a confirmed one stays.
        const photo = await env.EVENTS_KV.get(IMAGE_PREFIX + item.id);
        if (photo) await env.EVENTS_KV.put(IMAGE_PREFIX + item.id, photo);
      }
      await env.EVENTS_KV.put(PENDING_KEY, JSON.stringify(pending));
      // Tell the newsdesk. Best effort: the queue is the record either way.
      await sendEmail(env, env.COLUMN_NOTIFY_EMAIL || "news@rochdaledaily.co.uk",
        `Guest column awaiting review: ${item.title}`,
        `${item.author} (${item.authorRole || "no description"}) sent "${item.title}" (${item.words} words). Review it at ${SITE}/column-moderate`,
        `<p>${esc(item.author)} (${esc(item.authorRole || "no description")}) sent <strong>${esc(item.title)}</strong> (${item.words} words).</p><p><a href="${SITE}/column-moderate">Review it</a></p>`);
    }
    await env.EVENTS_KV.delete(VERIFY_PREFIX + verify);
    return back("1");
  }

  // Form options, so the page and the API cannot disagree.
  if (url.searchParams.get("options")) {
    const wards = await wardOptions(env, request);
    return json({ ok: true, categories: CATEGORIES, wards: wards ? Object.keys(wards) : ["Borough-wide"], maxWords: MAX_WORDS, minWords: MIN_WORDS });
  }

  const wantedImage = line(url.searchParams.get("image"), 100);
  if (wantedImage) {
    if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
    const stored = await env.EVENTS_KV.get(IMAGE_PREFIX + wantedImage);
    if (!stored) return json({ ok: false, error: "No photo for that column" }, 404);
    return json({ ok: true, id: wantedImage, image: stored });
  }

  if (url.searchParams.get("queue") === "pending") {
    if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
    const pending = await readList(env.EVENTS_KV, PENDING_KEY);
    const lastEmailError = await env.EVENTS_KV.get(LAST_EMAIL_ERROR, { type: "json" });
    return json({ ok: true, pending, count: pending.length, lastEmailError: lastEmailError || null });
  }
  return json({ ok: false, error: "Unknown request" }, 400);
}

export async function onRequestPost({ request, env }) {
  if (!env.EVENTS_KV) return json({ ok: false, error: "Not configured" }, 503);
  let payload;
  try { payload = await request.json(); } catch (error) { return json({ ok: false, error: "Invalid request" }, 400); }
  if (!payload || typeof payload !== "object") return json({ ok: false, error: "Invalid request" }, 400);

  /* ---------------------------------------------------- editor actions */
  if (payload.action) {
    if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
    const action = line(payload.action, 20);
    const id = line(payload.id, 100);
    const pending = await readList(env.EVENTS_KV, PENDING_KEY);
    const index = pending.findIndex((p) => p.id === id);
    if (index < 0) return json({ ok: false, error: "Column not found" }, 404);
    const item = pending[index];

    if (action === "reject") {
      pending.splice(index, 1);
      if (item.hasImage) await env.EVENTS_KV.delete(IMAGE_PREFIX + item.id);
      await env.EVENTS_KV.put(PENDING_KEY, JSON.stringify(pending));
      return json({ ok: true, action, id });
    }
    if (action !== "approve") return json({ ok: false, error: "Unknown action" }, 400);

    // The editor may cut or correct before publishing.
    const title = line(payload.title || item.title, 140);
    const body = prose(payload.body || item.body);
    const words = wordCount(body);
    if (title.length < 10) return json({ ok: false, error: "The headline is too short" }, 400);
    if (words > MAX_WORDS) return json({ ok: false, error: `The column is ${words} words; cut it to ${MAX_WORDS}` }, 400);
    const slug = slugify(title);
    if (!slug) return json({ ok: false, error: "The headline does not make a valid link" }, 400);

    const queue = await readList(env.EVENTS_KV, NEWSDESK_KEY);
    if (queue.some((q) => q.id === slug)) return json({ ok: false, error: "An article with this headline is already queued" }, 409);

    const now = new Date().toISOString();
    const byline = item.authorRole ? `${item.author}, ${item.authorRole}` : item.author;
    const interests = item.interests && !/^(none|no|n\/a|nil)\.?$/i.test(item.interests)
      ? `Declared interests: ${item.interests}`
      : "Declared interests: none.";
    const first = body.split("\n\n")[0] || "";
    const article = {
      id: slug,
      slug,
      title,
      excerpt: first.length > 300 ? first.slice(0, 297).replace(/\s+\S*$/, "") + "…" : first,
      body: `${body}\n\n${interests}\n\nThis is a guest column. The views are the author's own and not those of Rochdale Daily.`,
      category: item.category,
      area: item.area,
      types: [item.category],
      kicker: "Opinion",
      image_url: "",
      published_at: now,
      first_published_at: now,
      last_updated_at: now,
      scraped_at: now,
      source_name: "Rochdale Daily",
      source_names: ["Rochdale Daily"],
      byline: byline.slice(0, 120),
      status: "published",
      manual_article: true,
      editorial_lock: true,
      rewrite_quality_checked: true,
      publication_route: "guest-column",
      legal_disclaimer: "Guest column: the views expressed are the author's own and not those of Rochdale Daily.",
      right_to_reply: "Anyone named in this column can reply by emailing news@rochdaledaily.co.uk; replies of up to 300 words are published.",
    };
    let imageKey = "";
    if (item.hasImage && payload.withPhoto !== false) {
      const photo = await env.EVENTS_KV.get(IMAGE_PREFIX + item.id);
      if (photo) {
        imageKey = NEWSDESK_IMAGE_PREFIX + slug;
        await env.EVENTS_KV.put(imageKey, photo);
        article.image_credit = item.photoCredit || item.author;
        article.image_alt = (item.photoCaption || `${item.author}`).slice(0, 200);
      }
    }
    if (item.hasImage) await env.EVENTS_KV.delete(IMAGE_PREFIX + item.id);
    queue.unshift({ id: slug, article, submittedAt: now, source: "guest-column", columnId: item.id, image_key: imageKey });
    await env.EVENTS_KV.put(NEWSDESK_KEY, JSON.stringify(queue));
    pending.splice(index, 1);
    await env.EVENTS_KV.put(PENDING_KEY, JSON.stringify(pending));

    await sendEmail(env, item.email, `Your column will be published: ${title}`,
      `Thank you. "${title}" has been approved and will appear on Rochdale Daily within about half an hour at ${SITE}/articles/${slug}`,
      `<p>Thank you. <strong>${esc(title)}</strong> has been approved and will appear on Rochdale Daily within about half an hour.</p><p><a href="${SITE}/articles/${slug}">${SITE}/articles/${slug}</a></p>`);
    return json({ ok: true, action, id, slug, url: `${SITE}/articles/${slug}` });
  }

  /* --------------------------------------------------- new submission */
  if (line(payload.website, 100)) return json({ ok: true, message: "Thank you." }, 201); // honeypot

  const title = line(payload.title, 140);
  const body = prose(payload.body);
  const author = line(payload.author, 80);
  const authorRole = line(payload.authorRole, 80);
  const interests = line(payload.interests, 300);
  const category = line(payload.category, 30).toLowerCase();
  const ward = line(payload.ward, 80);
  const email = line(payload.email, 254).toLowerCase();
  const words = wordCount(body);
  const image = cleanImage(payload.image);
  const photoCredit = line(payload.photoCredit, 120);
  const photoCaption = line(payload.photoCaption, 200);

  if (payload.image && !image) return json({ ok: false, error: "That photo could not be read. Use a JPEG, PNG or WebP under about 1MB." }, 400);
  if (image && payload.photoPermission !== true) return json({ ok: false, error: "Confirm the photo is yours to share, or that you have permission." }, 400);
  if (image && !photoCaption) return json({ ok: false, error: "Say what or who the photo shows." }, 400);
  if (title.length < 10) return json({ ok: false, error: "Write a headline of at least 10 characters." }, 400);
  if (/[A-Z]{4,}(?:\s+[A-Z]{4,}){2,}/.test(title)) return json({ ok: false, error: "Please write the headline in ordinary sentence case, not capitals." }, 400);
  if (words < MIN_WORDS) return json({ ok: false, error: `Your column is ${words} words. Columns need at least ${MIN_WORDS}.` }, 400);
  if (words > MAX_WORDS) return json({ ok: false, error: `Your column is ${words} words. The limit is ${MAX_WORDS}.` }, 400);
  if (author.length < 3) return json({ ok: false, error: "Add the name the column will be published under." }, 400);
  if (!interests) return json({ ok: false, error: "Declare any interests, or write \"None\"." }, 400);
  if (!CATEGORIES[category]) return json({ ok: false, error: "Choose a section." }, 400);
  if (!EMAIL_RE.test(email)) return json({ ok: false, error: "Enter a working email address so we can confirm it is you." }, 400);
  if (!(payload.ownWork === true && payload.editing === true && payload.reply === true)) {
    return json({ ok: false, error: "Tick the three confirmations before sending." }, 400);
  }
  const wards = await wardOptions(env, request);
  if (!wards) return json({ ok: false, error: "The ward list could not be loaded. Please try again shortly." }, 503);
  if (!Object.prototype.hasOwnProperty.call(wards, ward)) return json({ ok: false, error: "Choose a ward." }, 400);

  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  if (await rateLimited(env, "email:" + email) || await rateLimited(env, "ip:" + ip)) {
    return json({ ok: false, error: "Too many submissions in the last hour. Please try again later." }, 429);
  }

  const token = crypto.randomUUID();
  const item = {
    id: `column-${Date.now().toString(36)}-${token.slice(0, 8)}`,
    title, body, words, author, authorRole, interests, category, ward,
    area: wards[ward], email, submittedAt: new Date().toISOString(),
    hasImage: Boolean(image),
    photoCredit: image ? (photoCredit || author) : "",
    photoCaption: image ? photoCaption : "",
  };
  if (image) await env.EVENTS_KV.put(IMAGE_PREFIX + item.id, image, { expirationTtl: VERIFY_TTL });
  await env.EVENTS_KV.put(VERIFY_PREFIX + token, JSON.stringify(item), { expirationTtl: VERIFY_TTL });

  const link = `${SITE}/api/columns?verify=${token}`;
  const sent = await sendEmail(env, email, "Confirm your Rochdale Daily column",
    `Thank you for writing "${title}". Please confirm this is your email address by opening this link within 48 hours:\n\n${link}\n\nIf you did not send a column to Rochdale Daily, ignore this email and nothing will happen.`,
    `<p>Thank you for writing <strong>${esc(title)}</strong>.</p><p>Please confirm this is your email address within 48 hours:</p><p><a href="${link}">Confirm my column</a></p><p>If you did not send a column to Rochdale Daily, ignore this email and nothing will happen.</p>`);
  if (!sent.ok) {
    await env.EVENTS_KV.delete(VERIFY_PREFIX + token);
    if (image) await env.EVENTS_KV.delete(IMAGE_PREFIX + item.id);
    await env.EVENTS_KV.put(LAST_EMAIL_ERROR, JSON.stringify({ at: new Date().toISOString(), reason: sent.reason }));
    return json({ ok: false, error: "We could not send the confirmation email just now, so your column has not been saved. Please copy your text and try again later, or email it to news@rochdaledaily.co.uk." }, 502);
  }
  return json({ ok: true, message: "Nearly done: we have emailed you a link. Your column reaches the editor once you click it (within 48 hours)." }, 201);
}

