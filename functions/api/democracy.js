/**
 * Rochdale Daily - democracy endpoint.
 *
 * Serves three independent sections at /api/democracy:
 *
 *   petitions  UK Parliament petitions, ranked by how many people in the
 *              borough signed them rather than by national totals.
 *   mp         The borough's MPs, their recent Commons votes and speeches.
 *   council    Rochdale Borough Council meeting agendas and minutes.
 *
 * Sources and licensing
 * ---------------------
 * petition.parliament.uk, members-api.parliament.uk,
 * commonsvotes-api.parliament.uk and hansard-api.parliament.uk are all free,
 * need no API key, and publish under the Open Parliament Licence v3.0, which
 * permits commercial reuse with attribution.
 *
 * TheyWorkForYou is deliberately NOT used. Its API costs GBP 20/month for
 * commercial use and is free only to registered charities or unpaid non-profit
 * projects. A site carrying advertising does not qualify. The underlying data
 * is Hansard either way, so the official APIs give the same facts for nothing.
 *
 * Failure isolation
 * -----------------
 * Each section is fetched independently and a failure in one never empties the
 * others. Every response reports which upstream calls succeeded, because the
 * traffic endpoint taught us that a filter you cannot observe is a filter you
 * cannot fix.
 */

const VERSION = "2026-07-23-democracy-2";

/* Cache windows. Petition signature counts move slowly; a council agenda is
   published once and then sits there. Nothing here needs to be live. */
const CACHE = { petitions: 1800, mp: 3600, council: 1800, error: 120 };

/**
 * The borough is split across three Westminster seats, which is the single
 * most important fact for this endpoint. Reporting "Rochdale constituency"
 * alone would silently omit Heywood, Middleton, Norden, Bamford, Castleton and
 * Spotland - roughly half the borough's population and a large share of the
 * readership.
 *
 * Rochdale and Heywood & Middleton North lie wholly inside the borough, so
 * their signature counts can be added together honestly. Blackley & Middleton
 * South contains the East and South Middleton wards but is otherwise a
 * Manchester seat, so it is tracked separately and never folded into the
 * borough total.
 */
const BOROUGH_SEATS = ["Rochdale", "Heywood and Middleton North"];
const PARTIAL_SEATS = ["Blackley and Middleton South"];

/* How many open petitions to inspect per refresh. Every petition needs its own
   detail fetch to reveal the constituency breakdown, and Cloudflare caps
   subrequests per invocation, so this cannot simply be "all of them". Petitions
   are examined in national-signature order, which means a small petition with
   strong local support may not surface yet. That limitation is real and is
   reported in the response rather than hidden. */
const PETITION_SAMPLE = 30;
const PETITION_MIN_LOCAL = 20;

const UA = "RochdaleDaily/1.0 (+https://rochdaledaily.co.uk)";

function json(body, status = 200, seconds = 300) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": `public, max-age=${seconds}`,
      "access-control-allow-origin": "*",
    },
  });
}

/** Fetch JSON, recording the outcome so ?debug=1 can explain an empty section. */
async function getJson(url, log, label, seconds) {
  try {
    const response = await fetch(url, {
      headers: { accept: "application/json", "user-agent": UA },
      cf: { cacheTtl: seconds, cacheEverything: true },
    });
    if (!response.ok) {
      log.push({ label, url, status: response.status, ok: false });
      return null;
    }
    const data = await response.json();
    log.push({ label, url, status: response.status, ok: true });
    return data;
  } catch (error) {
    log.push({ label, url, error: String(error), ok: false });
    return null;
  }
}

async function getText(url, log, label, seconds) {
  try {
    const response = await fetch(url, {
      headers: { accept: "application/rss+xml, application/xml, text/xml, text/html", "user-agent": UA },
      cf: { cacheTtl: seconds, cacheEverything: true },
    });
    if (!response.ok) {
      log.push({ label, url, status: response.status, ok: false });
      return null;
    }
    log.push({ label, url, status: response.status, ok: true });
    return await response.text();
  } catch (error) {
    log.push({ label, url, error: String(error), ok: false });
    return null;
  }
}

function clean(value) {
  return String(value == null ? "" : value)
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/<[^>]+>/g, " ")
    .replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"')
    .replace(/&#0?39;|&apos;/g, "'").replace(/&amp;/g, "&").replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/* ------------------------------------------------------------------ *
 * Petitions
 * ------------------------------------------------------------------ */

export function summariseConstituencies(detail) {
  const rows = (detail && detail.data && detail.data.attributes &&
    detail.data.attributes.signatures_by_constituency) || [];

  let borough = 0;
  let partial = 0;
  const breakdown = [];

  for (const row of rows) {
    const name = String(row.name || "");
    const count = Number(row.signature_count) || 0;
    if (BOROUGH_SEATS.includes(name)) {
      borough += count;
      breakdown.push({ seat: name, mp: row.mp || "", signatures: count, partial: false });
    } else if (PARTIAL_SEATS.includes(name)) {
      partial += count;
      breakdown.push({ seat: name, mp: row.mp || "", signatures: count, partial: true });
    }
  }
  return { borough, partial, breakdown };
}

/**
 * Salience: how over-represented the borough is compared with the country.
 *
 * A raw local count favours whatever is biggest nationally, which is exactly
 * the story every other outlet already has. The ratio finds the petition that
 * matters HERE more than it does elsewhere, which is the one worth writing
 * about. 1.0 means the borough signed at the national rate; 3.0 means three
 * times the national rate.
 *
 * The borough holds roughly 0.33% of the UK electorate (about 155,000 of
 * 47 million). Approximate by design - it is used for ranking, never printed
 * as a fact.
 */
const BOROUGH_ELECTORATE_SHARE = 0.0033;

function salience(localCount, nationalCount) {
  if (!nationalCount) return 0;
  const expected = nationalCount * BOROUGH_ELECTORATE_SHARE;
  if (expected <= 0) return 0;
  return localCount / expected;
}

export function shapePetition(detail, id) {
  const attributes = (detail && detail.data && detail.data.attributes) || {};
  const totals = summariseConstituencies(detail);
  const national = Number(attributes.signature_count) || 0;

  return {
    id,
    url: `https://petition.parliament.uk/petitions/${id}`,
    action: clean(attributes.action),
    background: clean(attributes.background).slice(0, 320),
    state: attributes.state || "open",
    national,
    borough: totals.borough,
    partial: totals.partial,
    breakdown: totals.breakdown,
    salience: Math.round(salience(totals.borough, national) * 100) / 100,
    deadline: attributes.closed_at || attributes.scheduled_debate_date || "",
    respondedAt: attributes.government_response_at || "",
    debatedAt: (attributes.debate && attributes.debate.debated_on) || "",
  };
}

async function loadPetitions(log) {
  const list = await getJson(
    "https://petition.parliament.uk/petitions.json?state=open",
    log, "petitions:list", CACHE.petitions
  );
  if (!list || !Array.isArray(list.data)) return { items: [], sampled: 0 };

  const ids = list.data.slice(0, PETITION_SAMPLE).map((item) => item.id).filter(Boolean);

  const details = await Promise.all(ids.map((id) =>
    getJson(`https://petition.parliament.uk/petitions/${id}.json`,
      log, `petitions:${id}`, CACHE.petitions)
      .then((detail) => (detail ? shapePetition(detail, id) : null))
  ));

  const items = details
    .filter(Boolean)
    .filter((item) => item.borough >= PETITION_MIN_LOCAL)
    // Rank by local salience, not national size. See salience() above.
    .sort((a, b) => b.salience - a.salience || b.borough - a.borough)
    .slice(0, 8);

  return { items, sampled: ids.length };
}

/* ------------------------------------------------------------------ *
 * MPs
 * ------------------------------------------------------------------ */

/**
 * Look the MP up rather than hard-coding a name or an ID.
 *
 * Rochdale has had four MPs since 2017 and two in 2024 alone. A hard-coded name
 * would sit there being wrong after the next by-election, on a news site, under
 * a masthead whose whole value is being right about local facts.
 */
async function findMember(seat, log) {
  const search = await getJson(
    "https://members-api.parliament.uk/api/Location/Constituency/Search?searchText=" +
      encodeURIComponent(seat) + "&skip=0&take=5",
    log, `mp:constituency:${seat}`, CACHE.mp
  );

  const results = (search && search.items) || [];
  const match = results
    .map((entry) => entry.value || entry)
    .find((value) => value && String(value.name || "").toLowerCase() === seat.toLowerCase());
  if (!match) return null;

  const representation = match.currentRepresentation || {};
  const member = (representation.member && (representation.member.value || representation.member)) || null;
  if (!member) return { seat, constituencyId: match.id || null, member: null };

  return {
    seat,
    constituencyId: match.id || null,
    memberId: member.id,
    name: member.nameDisplayAs || member.nameListAs || "",
    party: (member.latestParty && member.latestParty.name) || "",
    partyColour: (member.latestParty && member.latestParty.backgroundColour) || "",
    thumbnail: member.thumbnailUrl || "",
    since: (member.latestHouseMembership && member.latestHouseMembership.membershipStartDate) || "",
  };
}

const VOTE_ENDPOINTS = [
  (id) => `https://commonsvotes-api.parliament.uk/data/divisions.json/membervoting?queryParameters.memberId=${id}&queryParameters.take=6`,
  (id) => `https://commonsvotes-api.parliament.uk/data/divisions.json/search?queryParameters.memberId=${id}&queryParameters.take=6`,
];

async function loadVotes(memberId, log) {
  for (let index = 0; index < VOTE_ENDPOINTS.length; index += 1) {
    const data = await getJson(
      VOTE_ENDPOINTS[index](memberId),
      log, `mp:votes:${memberId}:v${index + 1}`, CACHE.mp
    );
    if (!Array.isArray(data) || !data.length) continue;

    const votes = data.map((entry) => {
      const division = entry.PublishedDivision || entry.publishedDivision || entry;
      return {
        title: clean(division.Title || division.title),
        date: division.Date || division.date || "",
        votedAye: entry.MemberVotedAye != null ? entry.MemberVotedAye : entry.memberVotedAye,
        ayes: division.AyeCount != null ? division.AyeCount : division.ayeCount,
        noes: division.NoCount != null ? division.NoCount : division.noCount,
        id: division.DivisionId || division.divisionId || null,
      };
    }).filter((vote) => vote.title);

    if (votes.length) return votes;
  }
  return [];
}

/**
 * Candidate Hansard endpoints, tried in order.
 *
 * The Hansard API is not documented publicly in a form I could verify, and
 * guessing a single path is how the traffic endpoint wasted three deploys.
 * Trying the plausible shapes and recording which one answered costs one extra
 * request on first load and then nothing, because the result is cached.
 */
const HANSARD_ENDPOINTS = [
  (id) => `https://hansard-api.parliament.uk/search/contributions/Spoken.json?queryParameters.memberId=${id}&queryParameters.take=5&queryParameters.orderBy=SittingDateDesc`,
  (id) => `https://hansard-api.parliament.uk/search/debates.json?queryParameters.memberId=${id}&queryParameters.take=5&queryParameters.orderBy=SittingDateDesc`,
  (id) => `https://hansard-api.parliament.uk/search.json?queryParameters.memberId=${id}&queryParameters.take=5`,
];

/** Field names vary in case and spelling between Parliament APIs. */
function pick(row, ...names) {
  for (const name of names) {
    if (row[name] != null && row[name] !== "") return row[name];
  }
  return "";
}

async function loadSpeeches(memberId, log) {
  for (let index = 0; index < HANSARD_ENDPOINTS.length; index += 1) {
    const data = await getJson(
      HANSARD_ENDPOINTS[index](memberId),
      log, `mp:speeches:${memberId}:v${index + 1}`, CACHE.mp
    );
    if (!data) continue;

    const results = data.Results || data.results || data.Contributions || data.items || [];
    if (!Array.isArray(results) || !results.length) continue;

    const speeches = results.map((row) => ({
      title: clean(pick(row, "DebateSection", "debateSection", "Title", "title", "House")),
      date: pick(row, "SittingDate", "sittingDate", "Date", "date"),
      house: pick(row, "House", "house"),
      text: clean(pick(row, "ContributionTextFull", "contributionTextFull", "ContributionText")).slice(0, 200),
      extId: pick(row, "DebateSectionExtId", "debateSectionExtId", "ContributionExtId"),
    })).filter((item) => item.title || item.text);

    if (speeches.length) return speeches;
  }
  return [];
}

async function loadMps(log) {
  const seats = await Promise.all(BOROUGH_SEATS.map((seat) => findMember(seat, log)));

  return await Promise.all(seats.filter(Boolean).map(async (entry) => {
    if (!entry.memberId) return entry;
    const [votes, speeches] = await Promise.all([
      loadVotes(entry.memberId, log),
      loadSpeeches(entry.memberId, log),
    ]);
    return { ...entry, votes, speeches };
  }));
}

/* ------------------------------------------------------------------ *
 * Council
 * ------------------------------------------------------------------ */

/**
 * Rochdale Borough Council runs ModernGov at democracy.rochdale.gov.uk, which
 * publishes RSS. ModernGov installations commonly sit behind bot protection,
 * and a direct fetch was refused during development, so this may return nothing
 * even when the URL is correct. The section fails quietly and reports the
 * status in the log rather than breaking the panel.
 *
 * Several feed paths are attempted because ModernGov exposes different ones
 * depending on version and configuration.
 */
const COUNCIL_FEEDS = [
  "https://democracy.rochdale.gov.uk/mgWhatsNew.aspx?bcr=1&RSS=1",
  "https://democracy.rochdale.gov.uk/mgRSSFeeds.aspx?bcr=1",
  "https://rochdale.moderngov.co.uk/mgWhatsNew.aspx?bcr=1&RSS=1",
];

export function parseRss(xml, limit = 8) {
  const items = [];
  const blocks = xml.match(/<item\b[\s\S]*?<\/item>/gi) || [];

  for (const block of blocks.slice(0, limit)) {
    const pick = (tag) => {
      const match = block.match(
        new RegExp(`<${tag}\\b[^>]*>([\\s\\S]*?)</${tag}>`, "i")
      );
      return match ? clean(match[1]) : "";
    };
    const title = pick("title");
    if (!title) continue;
    items.push({
      title,
      link: pick("link"),
      date: pick("pubDate") || pick("dc:date"),
      summary: pick("description").slice(0, 220),
    });
  }
  return items;
}

async function loadCouncil(log) {
  for (const url of COUNCIL_FEEDS) {
    const xml = await getText(url, log, "council:feed", CACHE.council);
    if (!xml) continue;
    const items = parseRss(xml);
    if (items.length) return { items, source: url };
  }
  return { items: [], source: "" };
}

/* ------------------------------------------------------------------ *
 * Handler
 * ------------------------------------------------------------------ */

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const debug = url.searchParams.get("debug") === "1";
  const only = url.searchParams.get("section");
  const log = [];

  const wanted = (name) => !only || only === name;

  const [petitions, mps, council] = await Promise.all([
    wanted("petitions") ? loadPetitions(log).catch(() => ({ items: [], sampled: 0 })) : null,
    wanted("mp") ? loadMps(log).catch(() => []) : null,
    wanted("council") ? loadCouncil(log).catch(() => ({ items: [], source: "" })) : null,
  ]);

  const body = {
    version: VERSION,
    updated: new Date().toISOString(),
    attribution:
      "Contains Parliamentary information licensed under the Open Parliament Licence v3.0, " +
      "and public sector information licensed under the Open Government Licence v3.0.",
    petitions: petitions
      ? {
          items: petitions.items,
          sampled: petitions.sampled,
          note:
            `The ${PETITION_SAMPLE} most-signed open petitions are checked each refresh. ` +
            "A smaller petition with strong local support may not appear yet.",
        }
      : undefined,
    mps: mps || undefined,
    council: council ? { items: council.items } : undefined,
  };

  if (debug) body.upstream = log;

  const failed = log.some((entry) => !entry.ok);
  return json(body, 200, failed ? CACHE.error : CACHE.petitions);
}
