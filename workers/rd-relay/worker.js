/**
 * rd-relay: fetches public pages for Rochdale Daily from Cloudflare's network.
 *
 * Why: these sites answer GitHub Actions' datacentre IPs with HTTP 403 for
 * every page, robots.txt included (measured 4 Nov 2026), although their own
 * robots.txt permits the pages we read. This Worker requests the same public
 * pages, identified honestly as Rochdale Daily.
 *
 * Rules it enforces itself:
 *   - Only the hosts in ALLOWED_HOSTS. Not the MEN: that publisher runs a
 *     bot challenge on purpose, and the editor decided not to route around it.
 *   - Each host's robots.txt, read through this Worker. A disallowed path is
 *     refused with 451. If robots.txt cannot be read, the request is refused
 *     too (fails closed).
 *   - Honest User-Agent; no browser impersonation; GET only; 10-minute cache.
 *
 * Routes:
 *   GET /fetch?url=<encoded url>          the page, upstream status and type
 *   GET /fetch?url=<encoded url>&debug=1  JSON measurement, no body
 *   GET /check                            measures every feed in CHECK_URLS
 *
 * Paste this whole file into Workers & Pages -> rd-relay -> Edit code.
 */

const USER_AGENT = "RochdaleDaily/3.2 (+https://rochdaledaily.co.uk; contact: news@rochdaledaily.co.uk)";
const ALLOWED_HOSTS = new Set([
  "www.gmp.police.uk", "gmp.police.uk",
  "rochdaleafc.co.uk", "www.rochdaleafc.co.uk",
  "www.rochdaleafccommunity.org", "rochdaleafccommunity.org",
  "www.falingepark.com", "falingepark.com",
]);
const CHECK_URLS = [
  "https://www.gmp.police.uk/news/greater-manchester/news/GetNewsRss/",
  "https://rochdaleafc.co.uk/feed/",
  "https://www.rochdaleafccommunity.org/feed/",
  "https://www.falingepark.com/feed/",
];
const CACHE_SECONDS = 600;

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
}

function allowedUrl(raw) {
  let url;
  try { url = new URL(raw); } catch (e) { return null; }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  if (!ALLOWED_HOSTS.has(url.hostname.toLowerCase())) return null;
  url.hash = "";
  return url;
}

// --- robots.txt (wildcard-aware: * and $) ---------------------------------
export function parseRobots(text) {
  const groups = [];
  let current = null;
  let lastWasAgent = false;
  for (const rawLine of String(text || "").split(/\r?\n/)) {
    const line = rawLine.replace(/#.*$/, "").trim();
    const match = line.match(/^([A-Za-z-]+)\s*:\s*(.*)$/);
    if (!match) continue;
    const field = match[1].toLowerCase();
    const value = match[2].trim();
    if (field === "user-agent") {
      if (!current || !lastWasAgent) { current = { agents: [], rules: [] }; groups.push(current); }
      current.agents.push(value.toLowerCase());
      lastWasAgent = true;
    } else if (field === "allow" || field === "disallow") {
      lastWasAgent = false;
      if (current) current.rules.push({ allow: field === "allow", path: value });
    } else {
      lastWasAgent = false;
    }
  }
  return groups;
}

function ruleMatches(rulePath, path) {
  if (!rulePath) return false;
  const anchored = rulePath.endsWith("$");
  const body = anchored ? rulePath.slice(0, -1) : rulePath;
  const pattern = "^" + body.split("*").map((part) => part.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*") + (anchored ? "$" : "");
  return new RegExp(pattern).test(path);
}

export function robotsAllows(groups, agentToken, pathAndQuery) {
  const token = agentToken.toLowerCase();
  let group = groups.find((g) => g.agents.some((a) => a !== "*" && token.includes(a)));
  if (!group) group = groups.find((g) => g.agents.includes("*"));
  if (!group) return true;
  let best = null;
  for (const rule of group.rules) {
    if (rule.path === "" && !rule.allow) continue; // "Disallow:" allows all
    if (!ruleMatches(rule.path, pathAndQuery)) continue;
    const length = rule.path.replace(/\$$/, "").length;
    if (!best || length > best.length || (length === best.length && rule.allow)) best = { allow: rule.allow, length };
  }
  return best ? best.allow : true;
}

async function upstream(url) {
  return fetch(url.toString(), {
    headers: { "user-agent": USER_AGENT, "accept": "application/rss+xml, application/xml, text/xml, text/html;q=0.9, */*;q=0.5", "accept-language": "en-GB,en;q=0.9" },
    redirect: "follow",
    cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
  });
}

async function robotsVerdict(url) {
  const robotsUrl = new URL("/robots.txt", url.origin);
  let response;
  try { response = await upstream(robotsUrl); } catch (e) { return { state: "unreachable", allowed: false }; }
  if (response.status === 404 || response.status === 410) return { state: "none published", allowed: true };
  if (response.status !== 200) return { state: `HTTP ${response.status}`, allowed: false };
  const groups = parseRobots(await response.text());
  const allowed = robotsAllows(groups, "RochdaleDaily", url.pathname + url.search);
  return { state: allowed ? "allows" : "disallows", allowed };
}

async function measure(url) {
  const robots = await robotsVerdict(url);
  const result = { url: url.toString(), robots: robots.state };
  if (!robots.allowed) return { ...result, refused: "robots.txt does not permit this page, or could not be read" };
  try {
    const response = await upstream(url);
    const text = await response.text();
    const final = new URL(response.url || url.toString());
    return {
      ...result,
      upstreamStatus: response.status,
      contentType: response.headers.get("content-type") || "",
      finalUrl: final.toString(),
      bytes: text.length,
      looksLikeFeed: /<(rss|feed|rdf:RDF)[\s>]/i.test(text.slice(0, 2000)),
      items: (text.match(/<item[\s>]/gi) || text.match(/<entry[\s>]/gi) || []).length,
    };
  } catch (error) {
    return { ...result, error: String(error && error.message || error) };
  }
}

export default {
  async fetch(request) {
    if (request.method !== "GET") return json({ error: "GET only" }, 405);
    const here = new URL(request.url);

    if (here.pathname === "/check") {
      const results = [];
      for (const raw of CHECK_URLS) results.push(await measure(new URL(raw)));
      return json({ relay: "rd-relay", checked_at: new Date().toISOString(), results });
    }

    if (here.pathname !== "/fetch") return json({ error: "not found", routes: ["/fetch?url=", "/check"] }, 404);
    const target = allowedUrl(here.searchParams.get("url") || "");
    if (!target) return json({ error: "host not served by this relay" }, 403);

    if (here.searchParams.get("debug") === "1") return json(await measure(target));

    // robots.txt itself is always readable: the scraper reads it to apply
    // the same policy on its side.
    const robots = target.pathname === "/robots.txt" ? { allowed: true, state: "robots.txt" } : await robotsVerdict(target);
    if (!robots.allowed) {
      return json({ error: "refused by robots.txt policy", robots: robots.state, url: target.toString() }, 451);
    }
    let response;
    try { response = await upstream(target); } catch (error) {
      return json({ error: "upstream unreachable", detail: String(error && error.message || error) }, 502);
    }
    const final = allowedUrl(response.url || target.toString());
    if (!final) return json({ error: "upstream redirected off the allowed hosts", to: response.url }, 403);
    const headers = new Headers();
    headers.set("content-type", response.headers.get("content-type") || "application/octet-stream");
    headers.set("cache-control", `public, max-age=${CACHE_SECONDS}`);
    headers.set("x-relay-upstream-status", String(response.status));
    headers.set("x-relay-final-url", final.toString());
    return new Response(response.body, { status: response.status, headers });
  },
};
