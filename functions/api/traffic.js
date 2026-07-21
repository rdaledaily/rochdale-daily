/**
 * Rochdale Daily - live travel disruption endpoint.
 *
 * Runs as a Cloudflare Pages Function at /api/traffic. It runs on request, not
 * on a schedule, which is the whole point: GitHub Actions drops scheduled runs
 * under load, so a cron-driven traffic feed goes stale exactly when traffic is
 * worst. This is live by construction.
 *
 * Source: Department for Transport Bus Open Data Service, Disruptions API
 * (SIRI-SX). Published under the Open Government Licence, which permits
 * commercial reuse with attribution - unlike Google, Waze or Apple traffic
 * data, none of which may lawfully be scraped or redistributed.
 *
 * The API key is read from the environment and never reaches the browser.
 * Set BODS_API_KEY in the Cloudflare Pages dashboard under Settings ->
 * Environment variables. Do not commit it.
 */

const DEFAULT_ENDPOINT = "https://data.bus-data.dft.gov.uk/api/v1/siri-sx";

// Cache at the edge. Long enough that a busy morning does not hammer the
// upstream API, short enough that a new closure surfaces quickly.
const CACHE_SECONDS = 120;

// Rochdale borough bounding box, used when a situation carries coordinates.
// Rochdale borough bounding box. Southern edge reaches 53.52 so Middleton and
// Alkrington are inside it; a tighter box silently dropped them.
const BOROUGH = { minLat: 53.52, maxLat: 53.72, minLon: -2.32, maxLon: -2.00 };

/**
 * Localities distinctive enough to identify the borough on their own.
 */
const UNIQUE_PLACES = [
  "rochdale", "heywood", "littleborough", "milnrow", "newhey", "smallbridge",
  "spotland", "falinge", "kirkholt", "balderstone", "belfield", "firgrove",
  "shawclough", "cutgate", "bagslate", "darnhill", "hopwood", "alkrington",
  "deeplish", "wardleworth", "lowerplace", "buersil", "slattocks", "thornham",
  "hollingworth lake", "chadderton fold", "milkstone", "kingsway business park",
];

/**
 * Borough place names that are also common words or exist elsewhere in the UK.
 * These only count alongside a borough anchor, because on their own they were
 * demonstrably wrong in live data:
 *
 *   "sudden"   - a Rochdale locality AND an ordinary English word. It matched
 *                "Sudden closure of Walkley Road" in Sheffield.
 *   "healey"   - matched "Healey Grove" on the Wirral.
 *   "meanwood" - far better known as a district of Leeds.
 *   "castleton"- far better known as the village in Derbyshire.
 *   "middleton"- there are Middletons in Leeds, Sussex and a dozen counties.
 */
const AMBIGUOUS_PLACES = [
  "middleton", "castleton", "meanwood", "norden", "bamford", "healey", "syke",
  "marland", "wardle", "sudden", "newbold", "birch", "langley", "rhodes",
];

/** Proof that an ambiguous name refers to this borough and not another. */
const BOROUGH_ANCHORS = [
  "rochdale", "greater manchester", "oldham", "bury", "heywood", "metrolink",
];
const POSTCODE_ANCHOR = /\b(?:ol\s?(?:1[0-6]|[1-9])|m24)\b/i;

/**
 * Roads worth naming once a situation has already qualified on a locality.
 * These never qualify a situation on their own: Bury Road, Manchester Road and
 * Oldham Road exist in dozens of towns, so matching on them alone is exactly
 * how the Scunthorpe closure got through.
 */
const BOROUGH_ROADS = [
  "a58", "a627", "a664", "a671", "a680", "m62", "m66",
  "oldham road", "manchester road", "bury road", "edenfield road",
  "milnrow road", "whitworth road", "rochdale road", "halifax road",
  "drake street", "yorkshire street", "entwistle road", "sandy lane",
];

/**
 * How far ahead counts as "now". A closure starting within a few hours is worth
 * warning about; one starting in October is a diary item, not traffic.
 */
const LOOKAHEAD_MS = 3 * 60 * 60 * 1000;

/** The ticker has to stay readable. Beyond this nobody reaches the end. */
const MAX_ITEMS = 8;

/** SIRI-SX carries the cause in one of several *Reason elements. */
const REASON_TAGS = [
  "MiscellaneousReason", "EnvironmentReason", "EquipmentReason",
  "PersonnelReason", "UndefinedReason",
];

/**
 * Pull the text of the first occurrence of a tag from an XML fragment.
 * Namespace prefixes are tolerated, because publishers vary in whether they
 * prefix SIRI elements and a strict match silently returns nothing.
 */
function tagText(xml, tag) {
  const re = new RegExp(
    `<(?:[A-Za-z0-9_.-]+:)?${tag}\\b[^>]*>([\\s\\S]*?)</(?:[A-Za-z0-9_.-]+:)?${tag}>`,
    "i"
  );
  const m = xml.match(re);
  return m ? decode(m[1].trim()) : "";
}

/** Every occurrence of a tag, not just the first. */
function tagTextAll(xml, tag) {
  const re = new RegExp(
    `<(?:[A-Za-z0-9_.-]+:)?${tag}\\b[^>]*>([\\s\\S]*?)</(?:[A-Za-z0-9_.-]+:)?${tag}>`,
    "gi"
  );
  const out = [];
  let m;
  while ((m = re.exec(xml)) !== null) {
    const value = decode(m[1].trim());
    if (value && !out.includes(value)) out.push(value);
  }
  return out;
}

/** Split the document into individual situation blocks. */
function situationBlocks(xml) {
  const re = /<(?:[A-Za-z0-9_.-]+:)?PtSituationElement\b[^>]*>([\s\S]*?)<\/(?:[A-Za-z0-9_.-]+:)?PtSituationElement>/gi;
  const out = [];
  let m;
  while ((m = re.exec(xml)) !== null) out.push(m[1]);
  return out;
}

function decode(value) {
  return value
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;|&apos;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function reasonOf(block) {
  for (const tag of REASON_TAGS) {
    const value = tagText(block, tag);
    if (value) return humanReason(value);
  }
  return "";
}

/**
 * SIRI reason codes are lowerCamelCase enumerations. Split them into words so
 * they read as English rather than as machine tokens on the page.
 */
function humanReason(code) {
  const spaced = String(code).replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function hasWord(haystack, needle) {
  return new RegExp("(^|[^a-z0-9])" + needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + "([^a-z0-9]|$)")
    .test(haystack);
}

function inBox(lat, lon) {
  return (
    lat >= BOROUGH.minLat && lat <= BOROUGH.maxLat &&
    lon >= BOROUGH.minLon && lon <= BOROUGH.maxLon
  );
}

function inBorough(situation) {
  // Coordinates decide whenever the publisher supplied them, and this check has
  // to come FIRST. Testing names first meant a Sheffield closure whose text
  // contained the word "sudden" was accepted and returned before the latitude
  // that would have rejected it was ever consulted. A point on the map is
  // stronger evidence than any string, so it wins outright.
  if (situation.lat !== null && situation.lon !== null) {
    return inBox(situation.lat, situation.lon);
  }

  const text = [
    situation.summary,
    situation.description,
    ...situation.places,
    ...situation.stops,
  ].join(" ").toLowerCase();

  if (UNIQUE_PLACES.some((place) => hasWord(text, place))) return true;

  // An ambiguous name needs corroboration from something that pins the text to
  // this part of the country.
  const anchored =
    BOROUGH_ANCHORS.some((anchor) => hasWord(text, anchor)) ||
    POSTCODE_ANCHOR.test(text);
  if (!anchored) return false;

  return AMBIGUOUS_PLACES.some((place) => hasWord(text, place));
}

/** True when the situation is happening now, or starts within LOOKAHEAD_MS. */
function isCurrent(situation, nowMs) {
  const start = Date.parse(situation.start || situation.created || "");
  const end = Date.parse(situation.end || "");
  if (Number.isFinite(end) && end < nowMs) return false;
  if (Number.isFinite(start) && start > nowMs + LOOKAHEAD_MS) return false;
  return true;
}

function parseSituation(block) {
  const lat = parseFloat(tagText(block, "Latitude"));
  const lon = parseFloat(tagText(block, "Longitude"));
  return {
    id: tagText(block, "SituationNumber"),
    progress: (tagText(block, "Progress") || "open").toLowerCase(),
    summary: tagText(block, "Summary"),
    description: tagText(block, "Description"),
    reason: reasonOf(block),
    severity: (tagText(block, "Severity") || "").toLowerCase(),
    start: tagText(block, "StartTime"),
    end: tagText(block, "EndTime"),
    created: tagText(block, "CreationTime"),
    places: tagTextAll(block, "PlaceName"),
    stops: tagTextAll(block, "StopPointName"),
    lines: tagTextAll(block, "PublishedLineName"),
    lat: Number.isFinite(lat) ? lat : null,
    lon: Number.isFinite(lon) ? lon : null,
  };
}

/** Rank so the worst and most recent disruption leads the panel. */
const SEVERITY_RANK = {
  verySevere: 5, severe: 4, undefined: 3, normal: 3, slight: 2, noImpact: 1,
};

function sortKey(s) {
  const sev = SEVERITY_RANK[s.severity] || SEVERITY_RANK[s.severity?.toLowerCase()] || 3;
  const started = Date.parse(s.start || s.created || "") || 0;
  return [-sev, -started];
}

export function extractDisruptions(xml, now = new Date()) {
  const nowMs = now.getTime();
  const seen = new Set();

  return situationBlocks(xml)
    .map(parseSituation)
    // A situation the publisher has closed is history, not traffic.
    .filter((s) => s.progress !== "closed" && s.progress !== "closing")
    // Planned works months out are a diary item, not a live warning.
    .filter((s) => isCurrent(s, nowMs))
    // Publishers mark cancelled works by editing the summary, not the status.
    .filter((s) => !/\*\*\s*(postponed|cancelled|canceled)\s*\*\*/i.test(s.summary || ""))
    .filter((s) => s.summary || s.description)
    .filter(inBorough)
    .filter((s) => {
      const key = s.id || s.summary;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    })
    .sort((a, b) => {
      const ka = sortKey(a), kb = sortKey(b);
      return ka[0] - kb[0] || ka[1] - kb[1];
    })
    .slice(0, MAX_ITEMS);
}

export async function onRequest(context) {
  const { env } = context;
  const key = env.BODS_API_KEY;

  const headers = {
    "content-type": "application/json; charset=utf-8",
    "cache-control": `public, max-age=${CACHE_SECONDS}`,
    "access-control-allow-origin": "*",
  };

  if (!key) {
    return new Response(
      JSON.stringify({ error: "BODS_API_KEY is not configured.", disruptions: [] }),
      { status: 500, headers }
    );
  }

  const endpoint = env.BODS_SIRI_SX_ENDPOINT || DEFAULT_ENDPOINT;
  const url = `${endpoint}${endpoint.includes("?") ? "&" : "?"}api_key=${encodeURIComponent(key)}`;

  try {
    const upstream = await fetch(url, {
      headers: { accept: "application/xml, text/xml" },
      cf: { cacheTtl: CACHE_SECONDS, cacheEverything: true },
    });

    if (!upstream.ok) {
      return new Response(
        JSON.stringify({
          error: `Upstream returned ${upstream.status}.`,
          disruptions: [],
        }),
        { status: 502, headers }
      );
    }

    const xml = await upstream.text();
    const disruptions = extractDisruptions(xml);

    return new Response(
      JSON.stringify({
        updated: new Date().toISOString(),
        count: disruptions.length,
        attribution:
          "Contains public sector information licensed under the Open Government Licence v3.0. Source: Department for Transport Bus Open Data Service.",
        disruptions,
      }),
      { headers }
    );
  } catch (error) {
    return new Response(
      JSON.stringify({ error: String(error), disruptions: [] }),
      { status: 502, headers }
    );
  }
}
