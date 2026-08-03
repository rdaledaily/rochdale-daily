/**
 * /api/planning
 * Authenticated planning-news monitor for Rochdale Daily.
 * Reuses EVENTS_KV and EVENTS_ADMIN_TOKEN already configured for event moderation.
 */

const STORE_KEY = "planning:intelligence:v1";
const SOURCE_URL = "https://planatom.uk/rochdale";
const MAX_ITEMS = 300;

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

function decode(value) {
  return String(value || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ").replace(/\s+/g, " ").trim();
}

function absoluteUrl(href) {
  try { return new URL(href, SOURCE_URL).toString(); } catch { return SOURCE_URL; }
}

function scoreItem(text) {
  const value = text.toLowerCase();
  let score = 20;
  const reasons = [];
  const add = (points, reason) => { score += points; reasons.push(reason); };

  const homes = value.match(/\b(\d{2,4})\s+(?:new\s+)?(?:homes|houses|dwellings|apartments|flats)\b/);
  if (homes) {
    const count = Number(homes[1]);
    add(Math.min(35, 12 + Math.floor(count / 10)), `${count} homes`);
  }
  if (/demolish|demolition/.test(value)) add(18, "demolition");
  if (/green belt|greenbelt/.test(value)) add(24, "Green Belt");
  if (/listed building|conservation area/.test(value)) add(14, "heritage impact");
  if (/hmo|house in multiple occupation|supported accommodation|children'?s home|care home/.test(value)) add(18, "sensitive residential use");
  if (/school|nursery|college/.test(value)) add(14, "education");
  if (/pub|public house|supermarket|retail park|mosque|church|synagogue|temple/.test(value)) add(13, "community landmark");
  if (/mast|telecom|5g|antenna/.test(value)) add(10, "telecoms");
  if (/takeaway|hot food|late[- ]night|licen[cs]ed premises/.test(value)) add(9, "licensing interest");
  if (/refused|withdrawn|appeal|committee|recommended for approval|recommended for refusal/.test(value)) add(16, "decision-stage development");

  return { score: Math.min(100, score), reasons };
}

function parseApplications(html) {
  const items = [];
  const anchorRe = /<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let match;
  while ((match = anchorRe.exec(html))) {
    const href = match[1];
    const text = decode(match[2]);
    if (!/\b(?:2\d\/\d{4,6}\/[A-Z]{2,}|[A-Z]{1,4}\/\d{2}\/\d{3,6})\b/i.test(text) &&
        !/\bProposal:\s/i.test(text)) continue;

    const refMatch = text.match(/Reference\s+([A-Z0-9/-]+)/i) || text.match(/\b(2\d\/\d{4,6}\/[A-Z]{2,})\b/i);
    const proposalMatch = text.match(/Proposal:\s*(.*?)(?=\s+Location:|\s+Reference\s|$)/i);
    const locationMatch = text.match(/Location:\s*(.*?)(?=\s+\d{2}\/\d{2}\/\d{4}|\s+Reference\s|\s+Tags\s|$)/i);
    const dateMatch = text.match(/\b(\d{2}\/\d{2}\/\d{4})\b/);
    const reference = refMatch ? refMatch[1] : absoluteUrl(href).split("/").filter(Boolean).pop();
    const proposal = proposalMatch ? proposalMatch[1].trim() : text;
    const location = locationMatch ? locationMatch[1].trim() : "Rochdale borough";
    const scored = scoreItem(`${proposal} ${location} ${text}`);

    items.push({
      id: `planning-${String(reference).replace(/[^a-z0-9]+/gi, "-").toLowerCase()}`,
      reference,
      proposal,
      location,
      date: dateMatch ? dateMatch[1] : "",
      status: /refused/i.test(text) ? "refused" : /approved/i.test(text) ? "approved" : /withdrawn/i.test(text) ? "withdrawn" : "validated",
      score: scored.score,
      reasons: scored.reasons,
      source: "Planatom / Rochdale public planning data",
      sourceUrl: absoluteUrl(href),
    });
  }
  return Array.from(new Map(items.map(item => [item.id, item])).values());
}

async function readState(kv) {
  const stored = await kv.get(STORE_KEY, { type: "json" });
  return stored && Array.isArray(stored.items) ? stored : { items: [], lastCheckedAt: null };
}

async function refresh(kv) {
  const response = await fetch(SOURCE_URL, {
    headers: { "User-Agent": "Rochdale Daily planning monitor (+https://rochdaledaily.co.uk)" },
  });
  if (!response.ok) throw new Error(`Source returned ${response.status}`);
  const html = await response.text();
  const discovered = parseApplications(html);
  const previous = await readState(kv);
  const oldIds = new Set(previous.items.map(item => item.id));
  const checkedAt = new Date().toISOString();
  const merged = [...discovered.map(item => ({ ...item, firstSeenAt: oldIds.has(item.id)
    ? (previous.items.find(old => old.id === item.id)?.firstSeenAt || checkedAt)
    : checkedAt, new: !oldIds.has(item.id) })), ...previous.items.filter(item => !discovered.some(now => now.id === item.id)).map(item => ({ ...item, new: false }))]
    .sort((a, b) => b.score - a.score || String(b.firstSeenAt).localeCompare(String(a.firstSeenAt)))
    .slice(0, MAX_ITEMS);

  const state = { items: merged, lastCheckedAt: checkedAt, sourceUrl: SOURCE_URL, discovered: discovered.length };
  await kv.put(STORE_KEY, JSON.stringify(state));
  return state;
}

export async function onRequestGet({ request, env }) {
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
  if (!env.EVENTS_KV) return json({ ok: false, error: "EVENTS_KV is not configured" }, 503);
  const url = new URL(request.url);
  try {
    const state = url.searchParams.get("refresh") === "1" ? await refresh(env.EVENTS_KV) : await readState(env.EVENTS_KV);
    return json({ ok: true, ...state });
  } catch (error) {
    return json({ ok: false, error: error.message || "Refresh failed", ...(await readState(env.EVENTS_KV)) }, 502);
  }
}

export async function onRequestPost({ request, env }) {
  if (!isAdmin(request, env)) return json({ ok: false, error: "Unauthorised" }, 401);
  if (!env.EVENTS_KV) return json({ ok: false, error: "EVENTS_KV is not configured" }, 503);
  try {
    const state = await refresh(env.EVENTS_KV);
    return json({ ok: true, ...state });
  } catch (error) {
    return json({ ok: false, error: error.message || "Refresh failed" }, 502);
  }
}
