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
const BOROUGH = { minLat: 53.55, maxLat: 53.70, minLon: -2.30, maxLon: -2.03 };

/**
 * Place names that mean "this is in Rochdale borough". A SIRI-SX situation may
 * identify its location by AffectedPlace, by stop name, or only in the free
 * text, so all three are searched. Ordering matters for nothing here; this is a
 * membership test.
 */
const BOROUGH_PLACES = [
  "rochdale", "heywood", "middleton", "littleborough", "milnrow", "newhey",
  "wardle", "smallbridge", "castleton", "norden", "bamford", "healey",
  "spotland", "falinge", "kirkholt", "balderstone", "sudden", "newbold",
  "belfield", "firgrove", "shawclough", "syke", "cutgate", "bagslate",
  "marland", "hollingworth lake", "darnhill", "hopwood", "alkrington",
  "langley", "rhodes", "bowlee", "birch", "deeplish", "meanwood",
  "wardleworth", "lowerplace", "buersil", "kingsway", "queensway",
];

/** Roads worth flagging even when the place name is absent from the text. */
const BOROUGH_ROADS = [
  "a58", "a627", "a664", "a671", "a680", "m62", "m66",
  "oldham road", "manchester road", "bury road", "edenfield road",
  "milnrow road", "whitworth road", "rochdale road", "halifax road",
  "queensway", "kingsway", "drake street", "yorkshire street",
];

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

function inBorough(situation) {
  const haystack = [
    situation.summary,
    situation.description,
    ...situation.places,
    ...situation.stops,
  ].join(" ").toLowerCase();

  if (BOROUGH_PLACES.some((p) => haystack.includes(p))) return true;
  if (BOROUGH_ROADS.some((r) => new RegExp(`\\b${r}\\b`).test(haystack))) return true;

  // Fall back to coordinates when the publisher supplied them and the text
  // gave us nothing to match on.
  if (situation.lat !== null && situation.lon !== null) {
    return (
      situation.lat >= BOROUGH.minLat && situation.lat <= BOROUGH.maxLat &&
      situation.lon >= BOROUGH.minLon && situation.lon <= BOROUGH.maxLon
    );
  }
  return false;
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
    // Nor is one whose validity window has already ended.
    .filter((s) => !s.end || Date.parse(s.end) >= nowMs)
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
    });
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
