/**
 * POST /api/submit-event
 *
 * Receives community event submissions from the "Add an event" panel on the
 * Rochdale Daily front page and puts them into a moderation queue.
 *
 * Everything the browser checks is checked again here. A form can be bypassed
 * with curl, so the browser rules are convenience only — these are the real
 * ones.
 *
 * Cloudflare bindings required (Pages > Settings > Functions):
 *   KV namespace binding : EVENTS_KV
 *   Environment secret   : EVENTS_ADMIN_TOKEN   (used by /api/events for moderation)
 *   Environment secret   : EVENTS_IP_SALT       (any long random string)
 *
 * Storage layout in EVENTS_KV:
 *   events:pending    JSON array, newest first, hard-capped at PENDING_CAP
 *   events:approved   JSON array, newest first, hard-capped at APPROVED_CAP
 *   img:<id>          raw base64 JPEG for one submission
 *   rl:<ipHash>       rate-limit record for one submitter
 */

const PENDING_CAP = 50;    // "keep a stock of 50 events"
const APPROVED_CAP = 50;

const MAX_BODY_BYTES = 1_500_000;   // whole JSON payload
const MAX_IMAGE_BYTES = 400_000;    // decoded JPEG

// Rate limiting. Windows are rolling, not calendar-based.
const LIMIT_PER_HOUR = 3;
const LIMIT_PER_DAY = 8;
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;

// Escalating blocks for abusive language. Index = strike count - 1.
const STRIKE_BLOCKS = [1 * HOUR, 24 * HOUR, 7 * DAY, 30 * DAY];

// Rochdale borough and immediate fringe. Rejecting out-of-area postcodes is
// also a cheap spam filter — bots almost never get this right.
const POSTCODE_RE = /^(OL1[0-6]|OL[1-9]|M24|M26|BL9)\s?\d[A-Z]{2}$/i;
const TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)\s*[-\u2013]\s*([01]\d|2[0-3]):([0-5]\d)$/;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i;
const UK_PHONE_RE = /^(\+?44|0)\d[\d\s-]{8,13}$/;

/* ------------------------------------------------------------------ *
 * Language screening
 * ------------------------------------------------------------------ */

/**
 * Terms that cause outright rejection. Matched on word boundaries against a
 * normalised copy of the text, so "Burnley" does not trip "burn" and
 * "grateful" does not trip "rat", while "f.u.c.k" and "sh1t" do trip.
 *
 * Grouped only for readability — all groups are treated identically.
 */
const BANNED_TERMS = [
  // Profanity
  "fuck", "fucking", "fucker", "fuckoff", "motherfucker", "cunt", "bitch",
  "twat", "shit", "shite", "bullshit", "bastard", "wanker", "prick",
  "dickhead", "bellend", "arsehole", "asshole", "knobhead", "piss", "slag",

  // Sexual / explicit
  "shag", "shagging", "blowjob", "blow job", "dogging", "porn", "porno",
  "slut", "whore", "hooker", "milf", "gangbang", "cum", "wank", "handjob",
  "escort service", "sex work", "onlyfans",

  // Child safety
  "nonce", "pedo", "paedo", "pedophile", "paedophile", "kiddie fiddler",
  "grooming gang",

  // Violence and threats
  "murder", "murderer", "killer", "kill", "stab", "stabbing", "shoot",
  "shooting", "riot", "rioting", "attack", "assault", "lynch", "drown",
  "burn", "arson", "firebomb", "bomb", "bombing", "petrol bomb", "torch",
  "beat up", "batter", "smash up", "butcher", "behead", "massacre",
  "terrorist", "jihad",

  // Racist / xenophobic
  "paki", "pakis", "wog", "nigger", "nigga", "coon", "chink", "gook",
  "spic", "raghead", "towelhead", "gyppo", "gypo", "pikey", "half caste",
  "white power", "sieg heil", "go home", "send them back", "rapefugee",
  "illegals", "invader", "invaders", "vermin", "scum", "subhuman",
  "great replacement",

  // Homophobic / transphobic
  "faggot", "fag", "fags", "queer", "dyke", "poof", "poofter", "batty boy",
  "tranny", "shemale", "he she", "sodomite",

  // Sexist / misogynist
  "slapper", "bimbo", "gold digger", "hoe", "hoes", "thot", "harpy",
  "get back in the kitchen", "make me a sandwich", "females are",

  // Ableist
  "retard", "retarded", "spaz", "spastic", "mong", "mongoloid", "cripple",
  "window licker",

  // Defamatory labels
  "cheater", "fraudster", "thief", "crook", "liar", "rat", "grass",
  "snitch", "scammer", "conman", "paedo ring",

  // Extremist / hate movement markers
  "combat 18", "blood and honour", "white genocide", "kill all",
  "death to", "gas the",
];

/**
 * Ordinary event names that happen to contain a screened word. These are
 * removed before screening, so a murder-mystery night at the village hall is
 * not treated as a threat. Add to this list rather than removing a banned
 * term whenever a genuine listing is wrongly rejected.
 */
const ALLOWED_PHRASES = [
  "murder mystery", "murder mystery night", "assault course", "burn off",
  "burn out", "burns night", "burnley", "bonfire", "killer queen",
  "beat the", "beat box", "beatbox", "smash hits", "rat run",
  "attack on titan", "kill the noise", "shooting range", "clay pigeon shooting",
  "archery", "bomber command", "bomb disposal", "the killers",
];

/**
 * Leetspeak and obfuscation are folded away before matching, then the text is
 * split into tokens so matching is genuinely word-boundary based.
 */
function normaliseForScreening(text) {
  return String(text || "")
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")     // strip accents
    .replace(/[4@]/g, "a")
    .replace(/[3\u20AC]/g, "e")
    .replace(/[1!|]/g, "i")
    .replace(/0/g, "o")
    .replace(/[5$]/g, "s")
    .replace(/7/g, "t")
    .replace(/8/g, "b")
    .replace(/[^a-z\s]/g, " ")            // drop separators used to hide words
    .replace(/(.)\1{2,}/g, "$1$1")        // fuuuuck -> fuuck
    .replace(/\s+/g, " ")
    .trim();
}

/** Returns the first banned term found, or null. */
function findBannedTerm(text) {
  let normalised = normaliseForScreening(text);
  if (!normalised) return null;

  for (const phrase of ALLOWED_PHRASES) {
    const safe = normaliseForScreening(phrase);
    if (!safe) continue;
    normalised = normalised.split(safe).join(" ");
  }
  normalised = normalised.replace(/\s+/g, " ").trim();
  if (!normalised) return null;

  // Also test a de-spaced copy so "f u c k" and "c-u-n-t" are caught.
  const squashed = normalised.replace(/\s/g, "");
  const tokens = normalised.split(" ");
  const tokenSet = new Set(tokens);

  for (const term of BANNED_TERMS) {
    const normalisedTerm = normaliseForScreening(term);
    if (!normalisedTerm) continue;

    if (normalisedTerm.includes(" ")) {
      // Multi-word phrase: match on the spaced text with word boundaries.
      const pattern = new RegExp(`(^| )${escapeRegExp(normalisedTerm)}( |$)`);
      if (pattern.test(normalised)) return term;
      continue;
    }

    if (tokenSet.has(normalisedTerm)) return term;

    // Catch spaced-out obfuscation, but only for terms long enough that a
    // substring hit is unlikely to be a false positive.
    if (normalisedTerm.length >= 4 && squashed.includes(normalisedTerm)) {
      // Guard against the term appearing legitimately inside a longer word
      // that survived de-spacing (e.g. "assault course" vs "assault").
      const insideWord = tokens.some(
        token => token.includes(normalisedTerm) && token !== normalisedTerm
      );
      if (!insideWord) return term;
    }
  }
  return null;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/* ------------------------------------------------------------------ *
 * Rate limiting
 * ------------------------------------------------------------------ */

async function hashIp(ip, salt) {
  const data = new TextEncoder().encode(`${salt || "rochdale-daily"}:${ip}`);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)]
    .slice(0, 12)
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");
}

async function readLimiter(kv, key) {
  const raw = await kv.get(key, { type: "json" });
  if (!raw || typeof raw !== "object") return { hits: [], strikes: 0, blockedUntil: 0 };
  return {
    hits: Array.isArray(raw.hits) ? raw.hits : [],
    strikes: Number(raw.strikes) || 0,
    blockedUntil: Number(raw.blockedUntil) || 0,
  };
}

async function writeLimiter(kv, key, record) {
  // Expire the record once the longest relevant window has passed.
  const ttl = Math.max(
    DAY,
    record.blockedUntil ? record.blockedUntil - Date.now() : 0
  );
  await kv.put(key, JSON.stringify(record), {
    expirationTtl: Math.ceil(ttl / 1000) + 60,
  });
}

function describeWait(ms) {
  const minutes = Math.ceil(ms / 60000);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.ceil(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"}`;
  return `${Math.ceil(hours / 24)} days`;
}

/* ------------------------------------------------------------------ *
 * Validation
 * ------------------------------------------------------------------ */

function validate(values) {
  const errors = [];

  const title = String(values.title || "").trim();
  if (title.length < 4) errors.push("Give the event a title.");
  if (title.length > 80) errors.push("The title must be 80 characters or fewer.");

  const date = String(values.date || "").trim();
  if (!DATE_RE.test(date)) {
    errors.push("Choose a date.");
  } else {
    const start = new Date(`${date}T00:00:00Z`).getTime();
    if (!Number.isFinite(start)) {
      errors.push("Choose a valid date.");
    } else if (start < Date.now() - DAY) {
      errors.push("That date has already passed.");
    } else if (start > Date.now() + 365 * DAY) {
      errors.push("Events can only be listed up to a year ahead.");
    }
  }

  const time = String(values.time || "").trim();
  if (!TIME_RE.test(time)) {
    errors.push("Enter the time as 14:00-19:00.");
  } else {
    const [, sh, sm, eh, em] = time.match(TIME_RE);
    const startMinutes = Number(sh) * 60 + Number(sm);
    const endMinutes = Number(eh) * 60 + Number(em);
    // Allow an end before the start only as an overnight run.
    if (endMinutes === startMinutes) errors.push("The end time must differ from the start time.");
  }

  const location = String(values.location || "").trim();
  if (location.length < 6) errors.push("Enter the venue and street.");
  if (location.length > 120) errors.push("The venue and street must be 120 characters or fewer.");

  const postcode = String(values.postcode || "").trim().toUpperCase();
  if (!POSTCODE_RE.test(postcode)) {
    errors.push("Enter a valid Rochdale-borough postcode (OL1-OL16, M24, M26 or BL9).");
  }

  const cost = String(values.cost || "").trim();
  if (cost && !/^free$/i.test(cost)) {
    const amount = Number(cost.replace(/[£,\s]/g, ""));
    if (!Number.isFinite(amount) || amount < 0) {
      errors.push('Cost must be "Free" or an amount in pounds.');
    } else if (amount > 5000) {
      errors.push("That cost looks wrong. Contact the newsdesk for high-value listings.");
    }
  }

  const contact = String(values.contact || "").trim();
  if (!contact) {
    errors.push("Give us a contact so we can query the listing.");
  } else if (!EMAIL_RE.test(contact) && !UK_PHONE_RE.test(contact)) {
    errors.push("Enter a valid email address or UK phone number as your contact.");
  }

  const description = String(values.description || "").trim();
  if (description.length > 400) errors.push("The description must be 400 characters or fewer.");

  // Link spam. One organiser link is reasonable; a wall of them is not.
  const linkCount = (`${title} ${description} ${location}`.match(/https?:\/\/|www\.|\.co\.uk|\.com/gi) || []).length;
  if (linkCount > 2) errors.push("Please remove the links — we add the organiser link ourselves.");

  return { errors, clean: { title, date, time, location, postcode, cost, contact, description } };
}

function validateImage(raw) {
  const value = String(raw || "").trim();
  if (!value) return { ok: true, base64: "" };

  const match = value.match(/^data:image\/jpe?g;base64,([A-Za-z0-9+/=]+)$/);
  if (!match) return { ok: false, error: "The photo must be a JPEG." };

  const base64 = match[1];
  const bytes = Math.floor((base64.length * 3) / 4);
  if (bytes > MAX_IMAGE_BYTES) {
    return { ok: false, error: "That photo is too large. Please use a smaller JPEG." };
  }
  // JPEG files begin FF D8 FF, which is "/9j/" in base64.
  if (!base64.startsWith("/9j/")) {
    return { ok: false, error: "That file is not a valid JPEG." };
  }
  return { ok: true, base64 };
}

/* ------------------------------------------------------------------ *
 * Helpers
 * ------------------------------------------------------------------ */

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

function slugify(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 90);
}

/** Trim a capped JSON array in KV, deleting any images that fall off the end. */
async function pushCapped(kv, key, record, cap) {
  const current = (await kv.get(key, { type: "json" })) || [];
  const list = Array.isArray(current) ? current : [];
  list.unshift(record);
  const dropped = list.splice(cap);
  await kv.put(key, JSON.stringify(list));
  for (const item of dropped) {
    if (item && item.imageKey) await kv.delete(item.imageKey).catch(() => {});
  }
  return { stored: list.length, dropped: dropped.length };
}

/* ------------------------------------------------------------------ *
 * Handler
 * ------------------------------------------------------------------ */

export async function onRequestPost({ request, env }) {
  const kv = env.EVENTS_KV;
  if (!kv) {
    return json(
      { ok: false, errors: ["Event submissions are not configured yet. Please email events@rochdaledaily.co.uk."] },
      503
    );
  }

  const declaredLength = Number(request.headers.get("content-length") || 0);
  if (declaredLength > MAX_BODY_BYTES) {
    return json({ ok: false, errors: ["That submission is too large."] }, 413);
  }

  let payload;
  try {
    payload = await request.json();
  } catch {
    return json({ ok: false, errors: ["We could not read that submission."] }, 400);
  }
  if (!payload || typeof payload !== "object") {
    return json({ ok: false, errors: ["We could not read that submission."] }, 400);
  }

  const ip = request.headers.get("CF-Connecting-IP") || "0.0.0.0";
  const ipHash = await hashIp(ip, env.EVENTS_IP_SALT);
  const limiterKey = `rl:${ipHash}`;
  const limiter = await readLimiter(kv, limiterKey);
  const now = Date.now();

  // Blocked submitters are turned away before anything else is done.
  if (limiter.blockedUntil > now) {
    return json(
      {
        ok: false,
        errors: [
          `Submissions from this connection are paused for ${describeWait(limiter.blockedUntil - now)}. ` +
          `If you think that is wrong, email events@rochdaledaily.co.uk.`,
        ],
      },
      429
    );
  }

  // Volume limits.
  limiter.hits = limiter.hits.filter(t => now - t < DAY);
  const lastHour = limiter.hits.filter(t => now - t < HOUR).length;
  if (lastHour >= LIMIT_PER_HOUR) {
    await writeLimiter(kv, limiterKey, limiter);
    return json({ ok: false, errors: ["You have sent several events in the last hour. Please try again later."] }, 429);
  }
  if (limiter.hits.length >= LIMIT_PER_DAY) {
    await writeLimiter(kv, limiterKey, limiter);
    return json({ ok: false, errors: ["You have reached today's limit for event submissions."] }, 429);
  }

  // Field validation.
  const { errors, clean } = validate(payload);
  const image = validateImage(payload.image);
  if (!image.ok) errors.push(image.error);
  if (errors.length) {
    limiter.hits.push(now);
    await writeLimiter(kv, limiterKey, limiter);
    return json({ ok: false, errors }, 400);
  }

  // Language screening across every free-text field the public would see,
  // plus the contact field so abusive addresses are caught too.
  const screened = [clean.title, clean.description, clean.location, clean.contact].join(" \n ");
  const banned = findBannedTerm(screened);
  if (banned) {
    limiter.strikes += 1;
    limiter.hits.push(now);
    const block = STRIKE_BLOCKS[Math.min(limiter.strikes, STRIKE_BLOCKS.length) - 1];
    limiter.blockedUntil = now + block;
    await writeLimiter(kv, limiterKey, limiter);

    return json(
      {
        ok: false,
        errors: [
          "That listing contains language we cannot publish, so it has been rejected. " +
          `Further submissions from this connection are paused for ${describeWait(block)}.`,
        ],
      },
      422
    );
  }

  // Store the image separately so the queue itself stays small and fast to read.
  const id = `evt-${now.toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  let imageKey = "";
  if (image.base64) {
    imageKey = `img:${id}`;
    await kv.put(imageKey, image.base64);
  }

  const record = {
    id,
    slug: slugify(clean.title) || id,
    status: "pending",
    submittedAt: new Date(now).toISOString(),
    submitterHash: ipHash,          // hash only — the raw IP is never stored
    title: clean.title,
    date: clean.date,
    time: clean.time,
    location: clean.location,
    postcode: clean.postcode,
    cost: clean.cost || "Free",
    contact: clean.contact,         // never served publicly
    description: clean.description,
    imageKey,
  };

  const { dropped } = await pushCapped(kv, "events:pending", record, PENDING_CAP);

  limiter.hits.push(now);
  await writeLimiter(kv, limiterKey, limiter);

  return json({
    ok: true,
    id,
    queued: true,
    trimmed: dropped > 0,
    message: "Thank you — your event has been sent to the newsdesk for review.",
  });
}

// Anything other than POST gets a clear answer rather than a Pages 404.
export async function onRequestGet() {
  return json({ ok: false, errors: ["Use POST to submit an event."] }, 405);
}

export async function onRequestOptions() {
  return new Response(null, { status: 204, headers: { Allow: "POST, OPTIONS" } });
}
