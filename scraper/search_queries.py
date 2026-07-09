"""Deep Rochdale discovery query matrix.

The matrix covers wards, named neighbourhood assets, venues, sports clubs,
schools, civic activity, councillors and the Rochdale MP. Queries are used for
lawful RSS/search discovery only; publication still requires source, freshness,
locality, duplication and editorial checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

GOOGLE_SEARCH_SAFE_LIMIT = 68
LOCATION_QUERIES_PER_HOUR = 40

try:
    from .location_discovery import build_location_queries
except ImportError:
    from location_discovery import build_location_queries

COUNCILLOR_DIRECTORY_URL = (
    "https://democracy.rochdale.gov.uk/mgMemberIndex.aspx?bcr=1"
)
COUNCILLOR_LIST_VERIFIED_DATE = "2026-07-08"
ROCHDALE_MP_NAME = "Paul Waugh"
ROCHDALE_MP_MEMBER_ID = "5071"

ROCHDALE_WARDS = (
    "Balderstone and Kirkholt",
    "Bamford",
    "Castleton",
    "Central Rochdale",
    "East Middleton",
    "Healey",
    "Hopwood Hall",
    "Kingsway",
    "Littleborough Lakeside",
    "Milkstone and Deeplish",
    "Milnrow and Newhey",
    "Norden",
    "North Heywood",
    "North Middleton",
    "Smallbridge and Firgrove",
    "South Middleton",
    "Spotland and Falinge",
    "Wardle, Shore and West Littleborough",
    "West Heywood",
    "West Middleton",
)

# Current official council directory, verified 8 July 2026.
CURRENT_COUNCILLORS = (
    ("Farooq Ahmed", "Central Rochdale"),
    ("Shakil Ahmed", "Kingsway"),
    ("Daalat Ali", "Kingsway"),
    ("Stephen Anstee", "Bamford"),
    ("Elizabeth Atewologun", "North Middleton"),
    ("Tricia Ayrton", "Healey"),
    ("David Bamford", "Milnrow and Newhey"),
    ("Philip Barrett", "Wardle, Shore and West Littleborough"),
    ("Philip Beal", "Bamford"),
    ("Tom Besford", "Littleborough Lakeside"),
    ("John Blundell", "Smallbridge and Firgrove"),
    ("Adam Branton", "Wardle, Shore and West Littleborough"),
    ("Kathryn Bromfield", "North Middleton"),
    ("Stuart Crawford", "West Heywood"),
    ("Patricia Mary Dale", "South Middleton"),
    ("Minaam Ellahi", "Milkstone and Deeplish"),
    ("Paul Ellison", "Norden"),
    ("Neil Emmott", "West Middleton"),
    ("Carl Faulkner", "Spotland and Falinge"),
    ("Aisling-Blaise Gallagher", "Castleton"),
    ("Ashley-Louise Gilbert", "Balderstone and Kirkholt"),
    ("Anthony Gilbert", "Milnrow and Newhey"),
    ("Peter Hodgkinson", "Hopwood Hall"),
    ("Michael Holly", "Norden"),
    ("Michael Howard", "North Heywood"),
    ("Victoria Howard", "Littleborough Lakeside"),
    ("Richard Jackson", "Littleborough Lakeside"),
    ("Georgina Jacques", "East Middleton"),
    ("Peter Joinson", "West Heywood"),
    ("Dave Jones", "Castleton"),
    ("Andy Kelly", "Milnrow and Newhey"),
    ("Waqar Khan", "Central Rochdale"),
    ("Mohammed Khizer", "Smallbridge and Firgrove"),
    ("Rachel Massey", "Kingsway"),
    ("Daniel Meredith", "Balderstone and Kirkholt"),
    ("Amna Mir", "Smallbridge and Firgrove"),
    ("Amber Nisa", "Spotland and Falinge"),
    ("Paul O'Neill", "North Heywood"),
    ("Matthew Pilkington", "South Middleton"),
    ("Bev Place", "North Heywood"),
    ("Steve Potter", "Hopwood Hall"),
    ("Faisal Rana", "Spotland and Falinge"),
    ("Aasim Rashid", "Castleton"),
    ("Aiza Rashid", "Milkstone and Deeplish"),
    ("Linda Robinson", "West Heywood"),
    ("Mohammed Shafiq", "Milkstone and Deeplish"),
    ("Angela Smith", "Bamford"),
    ("Susan Smith", "West Middleton"),
    ("Terry Smith", "East Middleton"),
    ("Mark Stephens", "Healey"),
    ("Jordan Tarrant-Short", "Balderstone and Kirkholt"),
    ("John Taylor", "Wardle, Shore and West Littleborough"),
    ("Trevor Taylor", "West Middleton"),
    ("Carol Wardle", "Hopwood Hall"),
    ("Shah Wazir", "Healey"),
    ("June West", "South Middleton"),
    ("Dylan James Williams", "East Middleton"),
    ("Peter Winkler", "Norden"),
    ("Lee Wolf", "North Middleton"),
    ("Sameena Zaheer", "Central Rochdale"),
)

CATEGORY_QUERIES = (
    (
        "crime",
        '(Rochdale OR Heywood OR Middleton OR Littleborough) '
        '(robbery OR burglary OR assault OR appeal OR wanted OR missing OR '
        'arrest OR murder)',
    ),
    (
        "traffic",
        '(Rochdale OR Heywood OR Middleton OR Littleborough) '
        '(traffic OR collision OR road closure OR roadworks OR potholes OR '
        'speeding OR M62)',
    ),
    (
        "transport",
        '(Rochdale OR Heywood OR Middleton OR Littleborough) '
        '("Bee Network" OR bus OR tram OR train OR Northern OR disruption)',
    ),
    (
        "politics",
        '(Rochdale OR Heywood OR Middleton) '
        '(councillor OR election OR vote OR voted OR motion)',
    ),
    (
        "education",
        '(Rochdale OR Heywood OR Middleton) '
        '(school OR college OR academy OR pupils OR students OR SATs OR '
        '"A level results")',
    ),
    (
        "sport",
        '(Rochdale OR Heywood OR Middleton OR Littleborough) '
        '(football OR rugby OR cricket OR athletics OR parkrun OR boxing OR '
        'MMA OR netball OR sport)',
    ),
    (
        "events",
        '(Rochdale OR Heywood OR Middleton OR Littleborough) '
        '(event OR festival OR fair OR exhibition OR concert OR workshop OR '
        '"coffee morning")',
    ),
    (
        "business",
        '(Rochdale OR Heywood OR Middleton) '
        '(business OR investment OR shop opening OR restaurant OR takeaway OR '
        'development OR regeneration OR "house prices")',
    ),
    (
        "community",
        '(Rochdale OR Heywood OR Middleton OR Littleborough) '
        '(charity OR fundraiser OR community group OR volunteer OR donation OR '
        'protest)',
    ),
    (
        "health",
        '(Rochdale OR Heywood OR Middleton) '
        '(NHS OR hospital OR clinic OR health service OR GP OR Sure Start)',
    ),
    (
        "environment",
        '(Rochdale OR Heywood OR Middleton OR Littleborough OR Whitworth) '
        '(flood OR weather warning OR pollution OR canal OR reservoir OR '
        'fishing OR park OR environment)',
    ),
    (
        "planning",
        '(Rochdale OR Heywood OR Middleton) '
        '(planning application OR housing development OR HMO OR licensing OR '
        'demolition)',
    ),
)

TRAFFIC_ALWAYS_ON_QUERIES = (
    '(Rochdale OR Heywood OR Middleton OR Littleborough) ("road closure" OR collision OR crash)',
    '(Rochdale OR Milnrow OR Newhey OR Littleborough) (M62 OR A627M OR "A627(M)") traffic',
    '(Rochdale OR Heywood OR Middleton) (roadworks OR diversion OR congestion)',
    'site:rochdale.gov.uk (Rochdale OR Heywood OR Middleton) ("road closure" OR "traffic order")',
    'site:tfgm.com (Rochdale OR Heywood OR Middleton) (traffic OR disruption)',
)

WATCH_QUERIES = (
    '"robbery" "Healey" Rochdale',
    '"charity event" "Kirkholt"',
    '"GMP issue appeal for" Rochdale',
    '"GMP issued an appeal" Rochdale',
    '"Falinge" ("parkrun" OR "park run")',
    '"Falinger" ("parkrun" OR "park run")',
    # Previously exact-phrase queries here almost never matched real
    # headlines. Also: long compound queries mixing many OR terms and
    # several quoted phrases together (as tried in an earlier revision)
    # appeared to silently return nothing from Google News, so these are
    # kept short and single-focus rather than combined into one string.
    # He is a convicted, publicly named individual already the subject of
    # extensive Parliamentary and national press coverage, so searching
    # his name is standard aggregation practice, not different in kind
    # from any other named public figure in the news.
    '"Shabir Ahmed"',
    'Rochdale deportation',
    'Rochdale parole',
    'Rochdale "grooming gang"',
    'Rochdale "released from prison"',
    'Rochdale sentencing',
    'Rochdale convicted',
)

# Each requested subject has its own label, category and query. Alternative
# spellings are included where they improve recall.
DISCOVERY_TOPICS = (
    ("healey-dell-viaduct", "environment", '"Healey Dell" viaduct'),
    ("healey-dell-robbery", "crime", '"Healey Dell" robbery'),
    ("healey-dell-fishing", "environment", '"Healey Dell" fishing'),
    ("milkstone-road-takeaway", "business", '"Milkstone Road" takeaway'),
    ("milkstone-road-speeding", "traffic", '"Milkstone Road" speeding'),
    ("bamford-house-prices", "business", '"Bamford" Rochdale "house prices"'),
    ("norden-school-results", "education", '"Norden" Rochdale "school results"'),
    ("bamford-restaurant", "business", '"Bamford" Rochdale restaurant'),
    ("norden-golf-club", "sport", '"Norden Golf Club"'),
    ("kirkholt-charity", "community", '"Kirkholt" charity'),
    (
        "kirkholt-surestart",
        "community",
        '"Kirkholt" ("Sure Start" OR SureStart OR "family sessions")',
    ),
    (
        "whitworth-stronger-together",
        "events",
        '"Whitworth Stronger Together" ("coffee morning" OR "coffee mornings")',
    ),
    (
        "whitworth-swimming-baths",
        "sport",
        'Whitworth ("swimming baths" OR pool OR leisure centre)',
    ),
    (
        "oulder-hill-swimming-baths",
        "sport",
        '("Oulder Hill" OR "Oulder Hill Leisure Complex") '
        '("swimming baths" OR pool)',
    ),
    (
        "cowm-reservoir",
        "environment",
        '("Cowm Reservoir" OR "Cowm resevoir") Whitworth',
    ),
    (
        "college-bank-padel",
        "sport",
        '"College Bank" ("padel court" OR padel)',
    ),
    (
        "spotland-mill-businesses",
        "business",
        '("Spotland Mill" OR "Spotland mills") businesses',
    ),
    ("milnrow-football", "sport", '"Milnrow" football'),
    (
        "firgrove-playing-fields",
        "sport",
        '"Firgrove Playing Fields"',
    ),
    (
        "mayfield-rugby-club",
        "sport",
        '("Rochdale Mayfield" OR "Mayfield Rugby Club") rugby',
    ),
    (
        "middleton-arena",
        "events",
        '"Middleton Arena" (event OR show OR sport OR closure OR update)',
    ),
    (
        "spotland-reform-club",
        "events",
        '"Spotland Reform Club" (event OR events)',
    ),
    (
        "crown-oil-arena",
        "sport",
        '"Crown Oil Arena" (match OR event OR development OR tickets)',
    ),
    (
        "rochdale-football-club",
        "sport",
        '("Rochdale AFC" OR "Rochdale Football Club")',
    ),
    (
        "manchester-road-traffic",
        "traffic",
        '"Manchester Road" Rochdale traffic',
    ),
    (
        "hamer-boxing-club",
        "sport",
        '("Hamer Amateur Boxing Club" OR "Hamer ABC")',
    ),
    ("newhey-potholes", "traffic", '"Newhey" potholes'),
    (
        "rochdale-sheep",
        "environment",
        'Rochdale (sheep OR lambs OR flock OR livestock)',
    ),
    (
        "heywood-hmo-protests",
        "community",
        'Heywood (HMO OR "house in multiple occupation") '
        '(protest OR opposition OR residents)',
    ),
    (
        "rochdale-church-events",
        "events",
        'Rochdale (church OR chapel) (event OR service OR festival OR concert)',
    ),
    (
        "rochdale-charity-events",
        "events",
        'Rochdale ("charity event" OR fundraiser OR fundraising)',
    ),
    (
        "rochdale-sat-results",
        "education",
        'Rochdale (SATs OR "SAT results" OR "key stage 2 results")',
    ),
    (
        "rochdale-a-level-results",
        "education",
        'Rochdale ("A level results" OR "A-level results")',
    ),
    (
        "rochdale-sixth-form",
        "education",
        '("Rochdale Sixth Form College" OR "Rochdale SFC")',
    ),
    (
        "rochdale-mma-fighter",
        "sport",
        'Rochdale ("MMA fighter" OR "mixed martial arts fighter")',
    ),
    (
        "rochdale-thai-boxer",
        "sport",
        'Rochdale ("Thai boxer" OR "Muay Thai" OR "Thai boxing")',
    ),
    (
        "rochdale-footballer",
        "sport",
        'Rochdale footballer',
    ),
    (
        "rochdale-netball",
        "sport",
        'Rochdale netball',
    ),
    (
        "rochdale-rugby",
        "sport",
        'Rochdale rugby',
    ),
    (
        "rochdale-awards",
        "community",
        'Rochdale (award OR awards OR winner OR honoured OR recognition)',
    ),
    (
        "rochdale-headteacher",
        "education",
        'Rochdale headteacher',
    ),
    (
        "rochdale-murder",
        "crime",
        'Rochdale murder',
    ),
    (
        "rochdale-canal",
        "environment",
        '("Rochdale Canal" OR "Rochdale canal")',
    ),
    (
        "rochdale-town-hall",
        "events",
        '"Rochdale Town Hall" (event OR restoration OR wedding OR exhibition)',
    ),
    (
        "rochdale-council-budget",
        "politics",
        'Rochdale ("council budget" OR "council tax" OR "budget cuts" OR '
        '"budget proposals" OR "budget vote")',
    ),
    (
        "rochdale-councillor-resigns",
        "politics",
        'Rochdale councillor (resigns OR resignation OR "steps down" OR '
        '"stands down" OR quits OR quitting)',
    ),
)

OFFICIAL_GMP_QUERIES = (
    'site:gmp.police.uk/news/greater-manchester/news/news/ '
    '(Rochdale OR Heywood OR Middleton OR Littleborough)',
    'site:gmp.police.uk "GMP issue appeal for" '
    '(Rochdale OR Heywood OR Middleton OR Littleborough)',
    'site:gmp.police.uk '
    '(robbery OR burglary OR assault OR appeal OR wanted OR missing) Rochdale',
    'site:gmp.police.uk '
    '("Milkstone and Deeplish" OR Kirkholt OR Healey OR Bamford OR Falinge)',
)

CIVIC_QUERIES = (
    # Bare meeting minutes/agendas and the councillor directory listing are
    # deliberately not queried here — they're institutional council process,
    # not news. Individual councillor votes, resignations and budget
    # decisions are covered by councillor_query() and the politics topics
    # in DISCOVERY_TOPICS instead.
    (
        "civic:council-actions",
        'site:rochdale.gov.uk/news councillor '
        '(opened OR visited OR resigns OR resignation OR "steps down" OR '
        '"stands down" OR quits OR supported OR opposed OR campaign)',
    ),
    (
        "civic:paul-waugh",
        '"Paul Waugh" Rochdale '
        '(statement OR campaign OR visit OR question OR debate OR vote)',
    ),
    (
        "civic:paul-waugh-parliament",
        'site:members.parliament.uk/member/5071 "Paul Waugh"',
    ),
    (
        "civic:paul-waugh-hansard",
        'site:hansard.parliament.uk "Paul Waugh"',
    ),
    (
        "civic:hansard-rochdale",
        'site:hansard.parliament.uk Rochdale',
    ),
    (
        "civic:paul-waugh-constituency",
        'site:paulwaugh.co.uk Rochdale',
    ),
)

SOURCE_QUERIES = (
    'site:manchestereveningnews.co.uk/all-about/rochdale Rochdale',
    'site:manchestereveningnews.co.uk/news/greater-manchester-news/ Rochdale',
    '"Manchester Evening News" Rochdale',
    '"Roch Valley Radio" Rochdale',
    '"Action Together" Rochdale',
    '"Your Trust Rochdale"',
    '"Rochdale AFC" news',
    '"Rochdale Hornets" news',
    '"Northern Care Alliance" Rochdale',
    '"Rochdale Sixth Form College" news',
    # National outlets, not just the regional/Manchester verticals: a story
    # can start locally and be covered nationally without ever appearing on
    # a Manchester-specific page (e.g. a case with national political or
    # legal significance).
    'site:bbc.co.uk/news Rochdale',
    'site:news.sky.com Rochdale',
    'site:itv.com/news Rochdale',
    'site:theguardian.com Rochdale',
    'site:telegraph.co.uk Rochdale',
    'site:independent.co.uk Rochdale',
)

COUNCILLOR_SHARD_SIZE = 15


@dataclass(frozen=True)
class SearchQuery:
    label: str
    query: str
    category: str = "news"
    ward: str = ""
    person: str = ""
    location_slug: str = ""
    location_name: str = ""


def ward_query(ward: str) -> SearchQuery:
    return SearchQuery(
        label=f"ward:{ward}",
        query=(
            f'"{ward}" '
            '(news OR police OR appeal OR traffic OR council OR charity OR '
            'event OR sport)'
        ),
        category="news",
        ward=ward,
    )


def councillor_shard_index(now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    # Scheduled runs at :07, :22, :37 and :52 map to shards 0, 1, 2 and 3.
    return min(3, max(0, current.minute // 15))


def councillors_for_run(
    now: datetime | None = None,
) -> tuple[tuple[str, str], ...]:
    shard = councillor_shard_index(now)
    start = shard * COUNCILLOR_SHARD_SIZE
    end = start + COUNCILLOR_SHARD_SIZE
    return CURRENT_COUNCILLORS[start:end]


def councillor_query(name: str, ward: str) -> SearchQuery:
    return SearchQuery(
        label=f"councillor:{name}",
        query=(
            f'"Councillor {name}" Rochdale '
            '("voted" OR vote OR motion OR committee OR decision OR attended '
            'OR participated OR "called for" OR campaign OR opened OR visited '
            'OR supported OR opposed OR questioned OR resigns OR resignation '
            'OR "steps down" OR "stands down" OR quits OR quitting)'
        ),
        category="politics",
        ward=ward,
        person=name,
    )



def rotating_location_queries(
    now: datetime | None = None,
    limit: int = LOCATION_QUERIES_PER_HOUR,
):
    # Return a safe hourly slice of the generated location matrix.
    # Named topics, wards, categories and source searches remain on
    # their normal four-way hourly shard. The larger generated matrix
    # rotates by UTC hour, avoiding a rate-limiting burst.
    items = list(build_location_queries())
    if not items or limit <= 0:
        return []

    count = min(int(limit), len(items))
    current = now or datetime.now(timezone.utc)
    hour_index = int(current.timestamp() // 3600)
    start = (hour_index * count) % len(items)
    return [items[(start + offset) % len(items)] for offset in range(count)]


def build_search_query_specs(
    max_queries: int = GOOGLE_SEARCH_SAFE_LIMIT,
    now: datetime | None = None,
) -> list[SearchQuery]:
    """Build this run's Google News query list.

    Google News' RSS search appears to rate-limit or bot-block bursts of
    requests from a single IP range: past a certain volume, it returns a
    non-RSS (likely CAPTCHA/consent) page that feedparser then reports as
    "not well-formed (invalid token)" for every single query in the run,
    with zero raw entries recovered from any of them. Firing 130+ Google
    News requests back-to-back every 15 minutes from a shared GitHub
    Actions IP range is well within the range known to trigger this.

    To stay under that threshold, only the small always-on sets (official
    GMP queries, civic/Parliament queries, and this run's councillor
    shard) run every time. Everything else -- watch queries, discovery
    topics, category queries, ward queries and source queries -- is
    treated as one combined pool and sharded across the four scheduled
    runs per hour, the same way councillor coverage already shards. Any
    single run therefore covers roughly a quarter of the full topic list,
    but the full set is still covered every hour, and each individual
    Google request is far less likely to be blocked.
    """
    always_on: list[SearchQuery] = []

    for index, query in enumerate(OFFICIAL_GMP_QUERIES, start=1):
        always_on.append(
            SearchQuery(
                label=f"official-gmp:{index}",
                query=query,
                category="crime",
            )
        )

    for index, query in enumerate(TRAFFIC_ALWAYS_ON_QUERIES, start=1):
        always_on.append(
            SearchQuery(
                label=f"always-traffic:{index}",
                query=query,
                category="traffic",
            )
        )

    for label, query in CIVIC_QUERIES:
        always_on.append(
            SearchQuery(
                label=label,
                query=query,
                category="politics",
                person=ROCHDALE_MP_NAME if "paul-waugh" in label else "",
            )
        )

    # One quarter of the current councillor list is checked on each scrape.
    # At the four normal scheduled minutes, all 60 are covered every hour.
    always_on.extend(
        councillor_query(name, ward)
        for name, ward in councillors_for_run(now)
    )

    bulk: list[SearchQuery] = []

    for index, query in enumerate(WATCH_QUERIES, start=1):
        bulk.append(
            SearchQuery(
                label=f"watch:{index}",
                query=query,
            )
        )

    for label, category, query in DISCOVERY_TOPICS:
        bulk.append(
            SearchQuery(
                label=f"topic:{label}",
                query=query,
                category=category,
            )
        )

    for category, query in CATEGORY_QUERIES:
        bulk.append(
            SearchQuery(
                label=f"category:{category}",
                query=query,
                category=category,
            )
        )

    # Location/category discovery is generated centrally from locations.py.
    # These searches are part of the same four-way shard as the other bulk
    # searches, so the complete location matrix is covered each hour without
    # sending hundreds of Google News requests in a single run.
    for item in rotating_location_queries(now):
        bulk.append(
            SearchQuery(
                label=item.label,
                query=item.query,
                category=item.category,
                location_slug=item.location_slug,
                location_name=item.location_name,
            )
        )

    bulk.extend(ward_query(ward) for ward in ROCHDALE_WARDS)

    for index, query in enumerate(SOURCE_QUERIES, start=1):
        bulk.append(
            SearchQuery(
                label=f"source:{index}",
                query=query,
            )
        )

    shard = councillor_shard_index(now)
    shard_size = math.ceil(len(bulk) / 4) if bulk else 0
    start = shard * shard_size
    bulk_shard = bulk[start:start + shard_size] if shard_size else []

    specs = always_on + bulk_shard

    unique: list[SearchQuery] = []
    seen: set[str] = set()
    for spec in specs:
        key = spec.query.casefold().strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)

    requested_limit = max(1, int(max_queries))
    safe_limit = min(requested_limit, GOOGLE_SEARCH_SAFE_LIMIT)
    return unique[:safe_limit]


def build_search_queries(
    max_queries: int = GOOGLE_SEARCH_SAFE_LIMIT,
    now: datetime | None = None,
) -> list[str]:
    return [
        spec.query
        for spec in build_search_query_specs(max_queries=max_queries, now=now)
    ]
