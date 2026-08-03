/** Public community poll API backed by EVENTS_KV. */
const MAX_VOTES_PER_IP_HOUR = 8;
const HOUR = 60 * 60 * 1000;

function json(payload, status = 200, cache = "no-store") {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": cache,
    },
  });
}

function clean(value) {
  return String(value ?? "").trim();
}

async function sha256Hex(text, take = 16) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].slice(0, take)
    .map(byte => byte.toString(16).padStart(2, "0")).join("");
}

async function loadPoll(request) {
  const url = new URL("/polls.json", request.url);
  const response = await fetch(url.toString(), { cf: { cacheTtl: 60 } });
  if (!response.ok) throw new Error("Poll configuration unavailable");
  const payload = await response.json();
  if (!payload?.current) throw new Error("No current poll configured");
  return payload.current;
}

function optionMap(poll) {
  return new Map((poll.options || []).map(option => [clean(option.id), clean(option.label)]));
}

async function listAll(kv, prefix) {
  const keys = [];
  let cursor;
  do {
    const page = await kv.list({ prefix, cursor, limit: 1000 });
    keys.push(...page.keys);
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return keys;
}

async function publicResults(kv, poll) {
  const options = optionMap(poll);
  const counts = Object.fromEntries([...options.keys()].map(id => [id, 0]));
  const prefix = `pollvote:${poll.id}:`;
  const keys = await listAll(kv, prefix);

  for (const key of keys) {
    const rest = key.name.slice(prefix.length);
    const split = rest.indexOf(":");
    if (split < 1) continue;
    const optionId = rest.slice(0, split);
    if (optionId in counts) counts[optionId] += 1;
  }

  const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const ranked = [...options.entries()].map(([id, label]) => ({
    id,
    label,
    votes: counts[id],
    percentage: total ? Math.round((counts[id] / total) * 1000) / 10 : 0,
  })).sort((a, b) => b.votes - a.votes || a.label.localeCompare(b.label));

  return { total, options: ranked, recent: [] };
}

function pollState(poll) {
  const now = Date.now();
  const starts = Date.parse(poll.starts_at);
  const ends = Date.parse(poll.ends_at);
  return {
    open: Number.isFinite(starts) && Number.isFinite(ends) && now >= starts && now < ends,
    starts_at: poll.starts_at,
    ends_at: poll.ends_at,
    server_time: new Date(now).toISOString(),
  };
}

async function confirmedVote(request, env, poll) {
  const voterId = clean(new URL(request.url).searchParams.get("voter_id"));
  if (!/^[a-zA-Z0-9_-]{20,120}$/.test(voterId)) return "";
  const salt = clean(env.EVENTS_IP_SALT) || "rochdale-daily-poll";
  const voterHash = await sha256Hex(`${salt}:${poll.id}:${voterId}`);
  const previous = await env.EVENTS_KV.get(`pollvoter:${poll.id}:${voterHash}`, { type: "json" });
  return clean(previous?.option_id);
}

async function handleGet(request, env) {
  const poll = await loadPoll(request);
  const [results, votedFor] = await Promise.all([
    publicResults(env.EVENTS_KV, poll),
    confirmedVote(request, env, poll),
  ]);
  return json({ poll, state: pollState(poll), results, voted_for: votedFor || null }, 200, "no-store");
}

async function handlePost(request, env) {
  const poll = await loadPoll(request);
  const state = pollState(poll);
  if (!state.open) return json({ error: "This poll is closed.", state }, 409);

  let body;
  try { body = await request.json(); }
  catch { return json({ error: "Invalid request." }, 400); }

  const pollId = clean(body.poll_id);
  const optionId = clean(body.option_id);
  const voterId = clean(body.voter_id);
  const options = optionMap(poll);

  if (pollId !== clean(poll.id)) return json({ error: "That poll is not active." }, 400);
  if (!options.has(optionId)) return json({ error: "Choose one of the listed options." }, 400);
  if (!/^[a-zA-Z0-9_-]{20,120}$/.test(voterId)) return json({ error: "Your browser vote token is invalid. Refresh the page and try again." }, 400);

  const salt = clean(env.EVENTS_IP_SALT) || "rochdale-daily-poll";
  const voterHash = await sha256Hex(`${salt}:${poll.id}:${voterId}`);
  const voterKey = `pollvoter:${poll.id}:${voterHash}`;
  const previous = await env.EVENTS_KV.get(voterKey, { type: "json" });

  if (previous) {
    const results = await publicResults(env.EVENTS_KV, poll);
    return json({ error: "This browser has already voted.", voted_for: previous.option_id, poll, state, results }, 409);
  }

  const ip = clean(request.headers.get("CF-Connecting-IP")) || "unknown";
  const userAgent = clean(request.headers.get("User-Agent")).slice(0, 180);
  const ipHash = await sha256Hex(`${salt}:${ip}:${userAgent}`);
  const limiterKey = `pollrate:${poll.id}:${ipHash}`;
  const limiter = await env.EVENTS_KV.get(limiterKey, { type: "json" });
  const now = Date.now();
  const hits = Array.isArray(limiter?.hits)
    ? limiter.hits.filter(value => now - Number(value) < HOUR)
    : [];

  if (hits.length >= MAX_VOTES_PER_IP_HOUR) {
    return json({ error: "Too many votes have been submitted from this connection. Try again later." }, 429);
  }

  const voteKey = `pollvote:${poll.id}:${optionId}:${voterHash}`;
  const ttl = Math.max(86400, Math.ceil((Date.parse(poll.ends_at) - now) / 1000) + 90 * 86400);

  await Promise.all([
    env.EVENTS_KV.put(voteKey, "1", { expirationTtl: ttl, metadata: { at: now } }),
    env.EVENTS_KV.put(voterKey, JSON.stringify({ option_id: optionId, at: now }), { expirationTtl: ttl }),
    env.EVENTS_KV.put(limiterKey, JSON.stringify({ hits: [...hits, now] }), { expirationTtl: 3600 }),
  ]);

  const results = await publicResults(env.EVENTS_KV, poll);
  return json({ ok: true, voted_for: optionId, poll, state, results });
}

export async function onRequest({ request, env }) {
  if (!env.EVENTS_KV) return json({ error: "Poll storage is not configured." }, 503);
  try {
    if (request.method === "GET") return await handleGet(request, env);
    if (request.method === "POST") return await handlePost(request, env);
    return json({ error: "Method not allowed." }, 405);
  } catch (error) {
    console.error("poll API error", error);
    return json({ error: "The poll is temporarily unavailable." }, 503);
  }
}
