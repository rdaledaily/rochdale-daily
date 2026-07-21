/**
 * /api/comments
 *
 * Reader comments for Rochdale Daily.
 *
 * Model: comments publish IMMEDIATELY (no pre-moderation), except on
 * categories listed in CLOSED_CATEGORIES — crime — where commenting is
 * refused outright. That refusal is enforced here, server-side, against the
 * published feed. Hiding the box in the browser would not stop anyone posting
 * with curl, and crime is precisely where contempt-of-court and defamation
 * risk sits, so the check has to be somewhere a reader cannot reach.
 *
 * Accounts carry an email address. It is never displayed and never returned by
 * any public endpoint. It exists so a poster is identifiable: the Defamation
 * Act 2013 s.5 defence for a website operator depends on being able to
 * identify who posted, alongside a working notice-and-takedown route. The
 * Report action below is that route.
 *
 * Public:
 *   GET  /api/comments?slug=<slug>     -> comments for one article
 *   GET  /api/comments?counts=1        -> { slug: count } for every article
 *   POST { action: "register", username, email, password }
 *   POST { action: "login", username, password }        -> { token }
 *   POST { action: "comment", token, slug, body }
 *   POST { action: "like", token, slug, id }        -> toggles, returns count
 *   POST { action: "report", slug, id, reason }
 *
 * Newsdesk (header  x-admin-token: <EVENTS_ADMIN_TOKEN>):
 *   GET  /api/comments?queue=reported  -> reported comments, with emails
 *   POST { action: "delete", slug, id }
 *
 * Bindings required: EVENTS_KV, EVENTS_ADMIN_TOKEN, EVENTS_IP_SALT.
 * (Reuses the same namespace and secrets as the events form.)
 */

// Categories where commenting is refused. Crime carries the contempt and
// defamation exposure: comments naming suspects in live proceedings are the
// commonest way a local publisher ends up before a court.
const CLOSED_CATEGORIES = new Set(["crime"]);

const COMMENTS_PER_ARTICLE = 200;   // ring buffer per article
const MAX_BODY_CHARS = 1500;
const MIN_BODY_CHARS = 2;
const USERNAME_RE = /^[a-z0-9_]{3,20}$/i;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[a-z]{2,}$/i;

// Rate limits, per account, rolling.
const HOUR = 60 * 60 * 1000;
const DAY = 24 * HOUR;
const COMMENTS_PER_HOUR = 10;
const LIKES_PER_DAY = 300;
const COMMENTS_PER_DAY = 40;
const STRIKE_BLOCKS = [1 * HOUR, 24 * HOUR, 7 * DAY, 30 * DAY];

const FEED_CACHE_KEY = "comments:feedcache";
const FEED_CACHE_TTL_MS = 5 * 60 * 1000;

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

/**
 * Usernames need STRICTER screening than prose. findBannedTerm deliberately
 * ignores a banned term sitting inside a longer word, because that is what
 * keeps "assault course" and "Burnley" publishable. A username has no
 * surrounding sentence to make it innocent, so "sh1thead" and "bigpaki" sailed
 * through that guard in testing. Here a substring hit is enough.
 *
 * Only terms of four characters or more are matched as substrings: shorter
 * ones ("rat", "hoe", "fag") would reject "grateful_ratcliffe" or "shoefan".
 * A wrongly refused username costs someone one retry; a slur permanently
 * displayed beside every comment they write costs rather more.
 */
function usernameIsAcceptable(username) {
  const normalised = normaliseForScreening(username).replace(/\s/g, "");
  if (!normalised) return false;
  for (const term of BANNED_TERMS) {
    const t = normaliseForScreening(term).replace(/\s/g, "");
    if (!t) continue;
    if (t.length >= 4 && normalised.includes(t)) return false;
    if (t.length < 4 && normalised === t) return false;
  }
  return true;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/* ------------------------------------------------------------------ *
 * Helpers
 * ------------------------------------------------------------------ */

function json(payload, status = 200, cache = "no-store") {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": cache },
  });
}

function clean(value) {
  return String(value ?? "").trim();
}

function isAdmin(request, env) {
  const given = request.headers.get("x-admin-token") || "";
  const want = env.EVENTS_ADMIN_TOKEN || "";
  if (!want || given.length !== want.length) return false;
  let diff = 0;
  for (let i = 0; i < want.length; i += 1) diff |= given.charCodeAt(i) ^ want.charCodeAt(i);
  return diff === 0;
}

function toBase64(bytes) {
  let s = "";
  for (const b of new Uint8Array(bytes)) s += String.fromCharCode(b);
  return btoa(s);
}

async function sha256Hex(text, take = 12) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].slice(0, take)
    .map(b => b.toString(16).padStart(2, "0")).join("");
}

/** Salted, iterated password hash. Never store or compare a raw password. */
async function hashPassword(password, saltB64) {
  const salt = saltB64
    ? Uint8Array.from(atob(saltB64), c => c.charCodeAt(0))
    : crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: 100000, hash: "SHA-256" }, key, 256
  );
  return { hash: toBase64(bits), salt: toBase64(salt) };
}

async function newToken() {
  return toBase64(crypto.getRandomValues(new Uint8Array(24))).replace(/[^a-zA-Z0-9]/g, "");
}

async function readList(kv, key) {
  const value = await kv.get(key, { type: "json" });
  return Array.isArray(value) ? value : [];
}

/* ------------------------------------------------------------------ *
 * Which articles accept comments
 * ------------------------------------------------------------------ */

/**
 * Read the published feed to learn each article's category. Cached briefly:
 * a comment POST must not trigger a fresh feed download every time.
 */
async function articleCategories(kv, origin) {
  const cached = await kv.get(FEED_CACHE_KEY, { type: "json" });
  if (cached && Date.now() - Number(cached.at || 0) < FEED_CACHE_TTL_MS) return cached.map;

  const map = {};
  for (const path of ["/articles.json", "/articles/frontpage.json"]) {
    try {
      const res = await fetch(new URL(path, origin).toString(), { cf: { cacheTtl: 120 } });
      if (!res.ok) continue;
      const payload = await res.json();
      const items = Array.isArray(payload) ? payload : (payload.articles || []);
      for (const item of items) {
        const slug = clean(item.slug || item.id);
        if (slug) map[slug] = clean(item.category).toLowerCase() || "news";
      }
    } catch { /* fall through with whatever was gathered */ }
  }
  if (Object.keys(map).length) {
    await kv.put(FEED_CACHE_KEY, JSON.stringify({ at: Date.now(), map }), { expirationTtl: 900 });
  }
  return map;
}

/**
 * Fail CLOSED. If the feed cannot be read we refuse the comment rather than
 * risk letting one through onto a crime story.
 */
async function commentingAllowed(kv, origin, slug) {
  const map = await articleCategories(kv, origin);
  const category = map[slug];
  if (!category) return { ok: false, reason: "We could not find that article." };
  if (CLOSED_CATEGORIES.has(category)) {
    return { ok: false, reason: "Comments are closed on crime reports." };
  }
  return { ok: true, category };
}

/* ------------------------------------------------------------------ *
 * Rate limiting
 * ------------------------------------------------------------------ */

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
  const ttl = Math.max(DAY, record.blockedUntil ? record.blockedUntil - Date.now() : 0);
  await kv.put(key, JSON.stringify(record), { expirationTtl: Math.ceil(ttl / 1000) + 60 });
}

function describeWait(ms) {
  const minutes = Math.ceil(ms / 60000);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"}`;
  const hours = Math.ceil(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? "" : "s"}`;
  return `${Math.ceil(hours / 24)} days`;
}

/* ------------------------------------------------------------------ *
 * Sessions
 * ------------------------------------------------------------------ */

async function userFromToken(kv, token) {
  const t = clean(token);
  if (!t) return null;
  const username = await kv.get(`session:${t}`);
  if (!username) return null;
  const user = await kv.get(`user:${username}`, { type: "json" });
  return user || null;
}

/**
 * Public shape of a comment. Emails, IP hashes and the list of who liked what
 * never leave the worker - only the total, plus whether the person asking has
 * liked it themselves.
 */
function publicComment(c, viewer = "") {
  const likes = Array.isArray(c.likes) ? c.likes : [];
  return {
    id: c.id,
    username: c.username,
    body: c.body,
    postedAt: c.postedAt,
    edited: Boolean(c.edited),
    reported: Boolean(c.reportCount),
    likeCount: likes.length,
    likedByMe: Boolean(viewer) && likes.includes(viewer),
  };
}

/* ------------------------------------------------------------------ *
 * GET
 * ------------------------------------------------------------------ */

export async function onRequestGet({ request, env }) {
  const kv = env.EVENTS_KV;
  if (!kv) return json({ ok: false, error: "Comments are not configured yet." }, 503);

  const url = new URL(request.url);

  // --- reported queue (newsdesk) ---
  if (url.searchParams.get("queue") === "reported") {
    if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
    const index = await readList(kv, "comments:reportedindex");
    const out = [];
    for (const entry of index.slice(0, 200)) {
      const list = await readList(kv, `comments:${entry.slug}`);
      const found = list.find(c => c.id === entry.id);
      if (found) {
        const author = await kv.get(`user:${found.usernameLower}`, { type: "json" });
        out.push({
          ...found,
          slug: entry.slug,
          reason: entry.reason,
          // Identifiability: only ever exposed behind the admin token.
          authorEmail: author ? author.email : "(account deleted)",
        });
      }
    }
    return json({ ok: true, count: out.length, reported: out });
  }

  // --- counts for every article ---
  if (url.searchParams.get("counts")) {
    const counts = (await kv.get("comments:counts", { type: "json" })) || {};
    return json({ ok: true, counts }, 200, "public, max-age=60");
  }

  // --- one article's comments ---
  const slug = clean(url.searchParams.get("slug"));
  if (!slug) return json({ ok: false, error: "Give a slug." }, 400);

  const gate = await commentingAllowed(kv, url.origin, slug);
  const list = await readList(kv, `comments:${slug}`);

  // The session token arrives as a header, not a query parameter: tokens in
  // URLs end up in browser history, referrer headers and server logs.
  const viewer = await userFromToken(kv, request.headers.get("x-session-token"));
  const viewerName = viewer ? viewer.usernameLower : "";

  return json({
    ok: true,
    slug,
    closed: !gate.ok,
    closedReason: gate.ok ? "" : gate.reason,
    count: list.length,
    comments: list.map(c => publicComment(c, viewerName)),
  // Per-reader like state means this response must not be shared by a cache.
  }, 200, viewerName ? "no-store" : "public, max-age=30");
}

/* ------------------------------------------------------------------ *
 * POST
 * ------------------------------------------------------------------ */

export async function onRequestPost({ request, env }) {
  const kv = env.EVENTS_KV;
  if (!kv) return json({ ok: false, error: "Comments are not configured yet." }, 503);

  if (Number(request.headers.get("content-length") || 0) > 20000) {
    return json({ ok: false, error: "That request is too large." }, 413);
  }

  let payload;
  try { payload = await request.json(); }
  catch { return json({ ok: false, error: "We could not read that request." }, 400); }

  const action = clean(payload.action).toLowerCase();
  const url = new URL(request.url);
  const ip = request.headers.get("CF-Connecting-IP") || "0.0.0.0";
  const ipHash = await sha256Hex(`${env.EVENTS_IP_SALT || "rd"}:${ip}`);

  /* ---------------- register ---------------- */
  if (action === "register") {
    const username = clean(payload.username);
    const email = clean(payload.email).toLowerCase();
    const password = String(payload.password ?? "");

    const errors = [];
    if (!USERNAME_RE.test(username)) {
      errors.push("Pick a username of 3-20 letters, numbers or underscores.");
    }
    if (!EMAIL_RE.test(email)) errors.push("Enter a valid email address.");
    if (password.length < 8) errors.push("Use a password of at least 8 characters.");

    // A username is displayed beside every comment its owner ever writes, so
    // it gets the stricter substring screen rather than the prose one.
    if (!usernameIsAcceptable(username)) {
      errors.push("Please choose a different username.");
    }
    if (errors.length) return json({ ok: false, errors }, 400);

    const key = `user:${username.toLowerCase()}`;
    if (await kv.get(key)) return json({ ok: false, errors: ["That username is taken."] }, 409);

    const { hash, salt } = await hashPassword(password);
    const user = {
      username,
      usernameLower: username.toLowerCase(),
      email,
      hash,
      salt,
      createdAt: new Date().toISOString(),
      signupIpHash: ipHash,
      blocked: false,
    };
    await kv.put(key, JSON.stringify(user));

    const token = await newToken();
    await kv.put(`session:${token}`, user.usernameLower, { expirationTtl: 60 * 60 * 24 * 30 });
    return json({ ok: true, token, username: user.username });
  }

  /* ---------------- login ---------------- */
  if (action === "login") {
    const username = clean(payload.username).toLowerCase();
    const password = String(payload.password ?? "");
    const user = await kv.get(`user:${username}`, { type: "json" });
    // Same message either way: do not reveal which usernames exist.
    const fail = json({ ok: false, errors: ["Username or password not recognised."] }, 401);
    if (!user) return fail;
    const { hash } = await hashPassword(password, user.salt);
    if (hash !== user.hash) return fail;
    if (user.blocked) return json({ ok: false, errors: ["This account is suspended."] }, 403);

    const token = await newToken();
    await kv.put(`session:${token}`, user.usernameLower, { expirationTtl: 60 * 60 * 24 * 30 });
    return json({ ok: true, token, username: user.username });
  }

  /* ---------------- comment ---------------- */
  if (action === "comment") {
    const user = await userFromToken(kv, payload.token);
    if (!user) return json({ ok: false, errors: ["Please sign in to comment."] }, 401);
    if (user.blocked) return json({ ok: false, errors: ["This account is suspended."] }, 403);

    const slug = clean(payload.slug);
    const body = clean(payload.body);

    const gate = await commentingAllowed(kv, url.origin, slug);
    if (!gate.ok) return json({ ok: false, errors: [gate.reason] }, 403);

    if (body.length < MIN_BODY_CHARS) return json({ ok: false, errors: ["Write a comment first."] }, 400);
    if (body.length > MAX_BODY_CHARS) {
      return json({ ok: false, errors: [`Keep comments under ${MAX_BODY_CHARS} characters.`] }, 400);
    }

    const limiterKey = `rl:c:${user.usernameLower}`;
    const limiter = await readLimiter(kv, limiterKey);
    const now = Date.now();
    if (limiter.blockedUntil > now) {
      return json({ ok: false, errors: [
        `Commenting is paused for ${describeWait(limiter.blockedUntil - now)}.`
      ] }, 429);
    }
    limiter.hits = limiter.hits.filter(t => now - t < DAY);
    if (limiter.hits.filter(t => now - t < HOUR).length >= COMMENTS_PER_HOUR) {
      await writeLimiter(kv, limiterKey, limiter);
      return json({ ok: false, errors: ["You have posted a lot in the last hour. Try again later."] }, 429);
    }
    if (limiter.hits.length >= COMMENTS_PER_DAY) {
      await writeLimiter(kv, limiterKey, limiter);
      return json({ ok: false, errors: ["You have reached today's comment limit."] }, 429);
    }

    const banned = findBannedTerm(body);
    if (banned) {
      limiter.strikes += 1;
      limiter.hits.push(now);
      const block = STRIKE_BLOCKS[Math.min(limiter.strikes, STRIKE_BLOCKS.length) - 1];
      limiter.blockedUntil = now + block;
      await writeLimiter(kv, limiterKey, limiter);
      return json({ ok: false, errors: [
        `That comment contains language we cannot publish, so it was not posted. Commenting is paused for ${describeWait(block)}.`
      ] }, 422);
    }

    const comment = {
      id: `c-${now.toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      username: user.username,
      usernameLower: user.usernameLower,
      body,
      postedAt: new Date(now).toISOString(),
      ipHash,
      reportCount: 0,
      likes: [],
    };

    const listKey = `comments:${slug}`;
    const list = await readList(kv, listKey);
    list.unshift(comment);
    list.splice(COMMENTS_PER_ARTICLE);
    await kv.put(listKey, JSON.stringify(list));

    const counts = (await kv.get("comments:counts", { type: "json" })) || {};
    counts[slug] = list.length;
    await kv.put("comments:counts", JSON.stringify(counts));

    limiter.hits.push(now);
    await writeLimiter(kv, limiterKey, limiter);

    return json({ ok: true, comment: publicComment(comment), count: list.length });
  }

  /* ---------------- like / unlike ---------------- */
  if (action === "like") {
    // Signed-in only. An anonymous upvote button on a local news site is a
    // one-click ballot box: refreshing the page would let anyone run a comment
    // up to any number they fancied.
    const user = await userFromToken(kv, payload.token);
    if (!user) return json({ ok: false, errors: ["Please sign in to upvote a comment."] }, 401);
    if (user.blocked) return json({ ok: false, errors: ["This account is suspended."] }, 403);

    const slug = clean(payload.slug);
    const id = clean(payload.id);
    const listKey = `comments:${slug}`;
    const list = await readList(kv, listKey);
    const target = list.find(c => c.id === id);
    if (!target) return json({ ok: false, errors: ["Comment not found."] }, 404);

    // Upvoting your own comment is not a vote, it is applause for yourself.
    if (target.usernameLower === user.usernameLower) {
      return json({ ok: false, errors: ["You cannot upvote your own comment."] }, 400);
    }

    const limiterKey = `rl:l:${user.usernameLower}`;
    const limiter = await readLimiter(kv, limiterKey);
    const now = Date.now();
    limiter.hits = limiter.hits.filter(t => now - t < DAY);
    if (limiter.hits.length >= LIKES_PER_DAY) {
      await writeLimiter(kv, limiterKey, limiter);
      return json({ ok: false, errors: ["You have upvoted a lot today. Try again tomorrow."] }, 429);
    }

    target.likes = Array.isArray(target.likes) ? target.likes : [];
    const at = target.likes.indexOf(user.usernameLower);
    const liked = at === -1;
    if (liked) target.likes.push(user.usernameLower);
    else target.likes.splice(at, 1);

    await kv.put(listKey, JSON.stringify(list));

    // Only a new like counts against the allowance; taking one back does not,
    // so nobody is penalised for changing their mind.
    if (liked) {
      limiter.hits.push(now);
      await writeLimiter(kv, limiterKey, limiter);
    }

    return json({ ok: true, id, liked, likeCount: target.likes.length });
  }

  /* ---------------- report (notice-and-takedown) ---------------- */
  if (action === "report") {
    const slug = clean(payload.slug);
    const id = clean(payload.id);
    const reason = clean(payload.reason).slice(0, 300);
    const listKey = `comments:${slug}`;
    const list = await readList(kv, listKey);
    const target = list.find(c => c.id === id);
    if (!target) return json({ ok: false, error: "Comment not found." }, 404);

    target.reportCount = Number(target.reportCount || 0) + 1;
    await kv.put(listKey, JSON.stringify(list));

    const index = await readList(kv, "comments:reportedindex");
    if (!index.some(e => e.id === id)) {
      index.unshift({ id, slug, reason, at: new Date().toISOString(), byIpHash: ipHash });
      index.splice(500);
      await kv.put("comments:reportedindex", JSON.stringify(index));
    }
    return json({ ok: true, message: "Thank you. The newsdesk will review this comment." });
  }

  /* ---------------- delete (newsdesk) ---------------- */
  if (action === "delete") {
    if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
    const slug = clean(payload.slug);
    const id = clean(payload.id);
    const listKey = `comments:${slug}`;
    const list = await readList(kv, listKey);
    const next = list.filter(c => c.id !== id);
    if (next.length === list.length) return json({ ok: false, error: "Comment not found." }, 404);
    await kv.put(listKey, JSON.stringify(next));

    const counts = (await kv.get("comments:counts", { type: "json" })) || {};
    counts[slug] = next.length;
    await kv.put("comments:counts", JSON.stringify(counts));

    const index = (await readList(kv, "comments:reportedindex")).filter(e => e.id !== id);
    await kv.put("comments:reportedindex", JSON.stringify(index));

    return json({ ok: true, removed: id, count: next.length });
  }

  /* ---------------- suspend an account (newsdesk) ---------------- */
  if (action === "suspend") {
    if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
    const username = clean(payload.username).toLowerCase();
    const user = await kv.get(`user:${username}`, { type: "json" });
    if (!user) return json({ ok: false, error: "No such account." }, 404);
    user.blocked = payload.blocked !== false;
    await kv.put(`user:${username}`, JSON.stringify(user));
    return json({ ok: true, username: user.username, blocked: user.blocked });
  }

  return json({ ok: false, error: "Unknown action." }, 400);
}
