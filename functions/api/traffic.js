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

/* Bumped whenever the filter changes. Visible in every response, so you can
   tell at a glance which build an edge node is actually serving instead of
   guessing whether a deploy landed. */
const FILTER_VERSION = "2026-07-21-zones";

const DEFAULT_ENDPOINT = "https://data.bus-data.dft.gov.uk/api/v1/siri-sx";

// Cache at the edge. Long enough that a busy morning does not hammer the
// upstream API, short enough that a new closure surfaces quickly.
const CACHE_SECONDS = 60;

// Rochdale borough bounding box, used when a situation carries coordinates.
// Outer limit. Used only to discard things that are nowhere near - Sheffield,
// the Wirral. Being inside it proves nothing, because it also contains Oldham,
// Bury and Prestwich.
const BOROUGH = { minLat: 53.52, maxLat: 53.72, minLon: -2.32, maxLon: -2.00 };

/**
 * Areas that are unambiguously in the borough with no neighbouring town inside
 * them. A point here can be accepted on coordinates alone, which matters
 * because plenty of records name a street and nothing else.
 *
 * Two zones because the borough is in two pieces for this purpose: the northern
 * mass around Rochdale, Littleborough and Milnrow, and the Middleton salient,
 * which is hemmed in by Bury, Manchester and Oldham. Royton (53.57) and Shaw
 * (53.58) sit just below the northern zone, which is why it starts at 53.60.
 */
const CORE_ZONES = [
  { minLat: 53.600, maxLat: 53.700, minLon: -2.220, maxLon: -2.020 },
  { minLat: 53.535, maxLat: 53.578, minLon: -2.230, maxLon: -2.155 },
];

/**
 * Words that turn a town name into a street name. "Bury Road" runs through
 * Heywood and Rochdale; "Oldham Road" and "Manchester Road" are among the
 * busiest roads in the borough. Treating those as evidence of Bury, Oldham or
 * Manchester would discard exactly the roads readers care most about.
 */
const STREET_SUFFIX =
  "road|street|lane|avenue|way|close|drive|hill|brow|gate|bank|terrace|place|" +
  "crescent|grove|walk|row|square|bridge|fold|side|rise|view|park road";

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

/**
 * Places that mean "not here". Checked before any positive name match, because
 * an explicit statement of somewhere else is far stronger evidence than a fuzzy
 * match on a name that might be local.
 *
 * This exists because the positive tests kept failing in ways I could not
 * anticipate: a Sheffield closure, a Wirral one and a Scunthorpe one all found
 * some borough word buried in their diversion text. Enumerating "elsewhere" is
 * a much smaller and more stable problem than enumerating every way a name can
 * be ambiguous.
 */
/**
 * Neighbouring Greater Manchester and Lancashire places. These matter more than
 * the far-away list: a bounding box drawn around Rochdale borough necessarily
 * contains large parts of Oldham, Bury and Prestwich, because the borough is
 * not a rectangle - Royton sits at longitude -2.10 while Milnrow, which IS in
 * the borough, sits at -2.09. Coordinates therefore cannot make this
 * distinction at all, and only the name can.
 *
 * Note "Rochdale Road, Oldham" is correctly rejected by this: a road named
 * after the borough is not in it.
 */
const NEIGHBOURS = [
  "oldham", "royton", "shaw and crompton", "crompton", "chadderton",
  "failsworth", "hollinwood", "garden suburb", "lees", "springhead",
  "uppermill", "saddleworth", "delph", "dobcross", "diggle", "greenfield",
  "mossley", "bury", "radcliffe", "whitefield", "prestwich", "ramsbottom",
  "tottington", "walshaw", "unsworth", "besses", "todmorden", "bacup",
  "rawtenstall", "haslingden", "shawforth", "manchester city centre",
  "blackley", "crumpsall", "moston", "harpurhey", "newton heath", "ancoats",
  "central park", "victoria station", "shudehill", "market street",
];

const ELSEWHERE = [
  "sheffield", "upperthorpe", "leeds", "bradford", "huddersfield", "halifax",
  "wakefield", "barnsley", "doncaster", "rotherham", "scunthorpe", "grimsby",
  "hull", "lincoln", "york", "harrogate", "liverpool", "wirral", "birkenhead",
  "new brighton", "irby", "chester", "crewe", "warrington", "widnes", "runcorn",
  "st helens", "wigan", "bolton", "blackburn", "burnley", "accrington",
  "preston", "blackpool", "lancaster", "stockport", "macclesfield", "buxton",
  "glossop", "derby", "nottingham", "leicester", "birmingham", "coventry",
  "london", "bristol", "cardiff", "swansea", "newcastle", "sunderland",
  "middlesbrough", "carlisle", "kendal", "hope valley", "sandbach",
  "north lincolnshire", "west yorkshire", "south yorkshire", "merseyside",
  "cheshire", "derbyshire", "lancashire county",
];

/** Proof that an ambiguous name refers to this borough and not another. */
const BOROUGH_ANCHORS = [
  "rochdale", "heywood", "littleborough", "milnrow", "middleton",
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

/**
 * True when the text refers to the PLACE, not to a street named after it.
 * "Bury Road, Heywood" names Heywood; it does not name Bury.
 */
function namesPlace(haystack, needle) {
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(
    "(^|[^a-z0-9])" + escaped + "(?!\\s+(?:" + STREET_SUFFIX + ")\\b)([^a-z0-9]|$)"
  ).test(haystack);
}

function inBox(lat, lon) {
  return inZone(lat, lon, BOROUGH);
}

function inZone(lat, lon, zone) {
  return lat >= zone.minLat && lat <= zone.maxLat && lon >= zone.minLon && lon <= zone.maxLon;
}

function inBorough(situation) {
  const hasCoords = situation.lat !== null && situation.lon !== null;

  // Nowhere near: discard before any string work.
  if (hasCoords && !inBox(situation.lat, situation.lon)) return false;

  // Unambiguously inside the borough: accept on the point alone, since many
  // records name only a street.
  if (hasCoords && CORE_ZONES.some((zone) => inZone(situation.lat, situation.lon, zone))) {
    return true;
  }

  const text = [
    situation.summary,
    situation.description,
    ...situation.places,
    ...situation.stops,
  ].join(" ").toLowerCase();

  // Everything left is in the contested fringe, where coordinates cannot help
  // and the name has to decide. An explicit somewhere-else beats any positive
  // match - but only when the name is used as a place, not as a street.
  if (NEIGHBOURS.some((place) => namesPlace(text, place))) return false;
  if (ELSEWHERE.some((place) => namesPlace(text, place))) return false;

  if (UNIQUE_PLACES.some((place) => hasWord(text, place))) return true;

  const anchored =
    BOROUGH_ANCHORS.some((word) => hasWord(text, word)) ||
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

/**
 * Parse everything, then report what was kept and what was thrown away and why.
 * extractDisruptions() wraps this for normal use; ?debug=1 exposes the whole
 * thing so a wrong result can be diagnosed from the response itself.
 */
export function analyse(xml, now = new Date()) {
  const nowMs = now.getTime();
  const all = situationBlocks(xml).map(parseSituation);
  const kept = [];
  const rejected = [];

  for (const item of all) {
    let reason = "";
    if (item.progress === "closed" || item.progress === "closing") reason = "status closed";
    else if (!isCurrent(item, nowMs)) reason = "outside time window";
    else if (/\*\*\s*(postponed|cancelled|canceled)\s*\*\*/i.test(item.summary || "")) reason = "marked postponed";
    else if (!item.summary && !item.description) reason = "no text";
    else if (!inBorough(item)) {
      reason = item.lat !== null && item.lon !== null
        ? `coordinates outside borough (${item.lat}, ${item.lon})`
        : "no borough locality in text";
    }
    if (reason) rejected.push({ id: item.id, summary: item.summary, lat: item.lat, lon: item.lon, reason });
    else kept.push(item);
  }

  const seen = new Set();
  const unique = kept.filter((item) => {
    const key = item.id || item.summary;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).sort((a, b) => {
    const ka = sortKey(a), kb = sortKey(b);
    return ka[0] - kb[0] || ka[1] - kb[1];
  });

  return { considered: all.length, kept: unique.slice(0, MAX_ITEMS), rejected };
}

export function extractDisruptions(xml, now = new Date()) {
  return analyse(xml, now).kept;
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
    const report = analyse(xml);
    const disruptions = report.kept;
    const debug = new URL(context.request.url).searchParams.get("debug") === "1";

    return new Response(
      JSON.stringify({
        version: FILTER_VERSION,
        updated: new Date().toISOString(),
        considered: report.considered,
        count: disruptions.length,
        ...(debug ? { rejected: report.rejected.slice(0, 60) } : {}),
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
