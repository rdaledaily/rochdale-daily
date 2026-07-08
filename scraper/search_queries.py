"""Deep Rochdale discovery query matrix.

The matrix covers wards, named neighbourhood assets, venues, sports clubs,
schools, civic activity, councillors and the Rochdale MP. Queries are used for
lawful RSS/search discovery only; publication still requires source, freshness,
locality, duplication and editorial checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

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
        '(council OR councillor OR committee OR consultation OR election OR '
        'vote OR motion)',
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

WATCH_QUERIES = (
    '"robbery" "Healey" Rochdale',
    '"charity event" "Kirkholt"',
    '"GMP issue appeal for" Rochdale',
    '"GMP issued an appeal" Rochdale',
    '"Falinge" ("parkrun" OR "park run")',
    '"Falinger" ("parkrun" OR "park run")',
    '"rapist deportation fight" Rochdale',
    '"deportation fight" Rochdale',
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
    (
        "civic:meeting-documents",
        'site:democracy.rochdale.gov.uk '
        '(minutes OR agenda OR motion OR vote OR decision) Rochdale',
    ),
    (
        "civic:council-actions",
        'site:rochdale.gov.uk/news councillor '
        '(opened OR visited OR announced OR supported OR opposed OR campaign)',
    ),
    (
        "civic:councillor-directory",
        'site:democracy.rochdale.gov.uk/mgMemberIndex.aspx '
        '"Rochdale Borough Council" councillors',
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
        "civic:paul-waugh-constituency",
        'site:paulwaugh.co.uk Rochdale',
    ),
)

SOURCE_QUERIES = (
    'site:manchestereveningnews.co.uk/all-about/rochdale Rochdale',
    'site:manchestereveningnews.co.uk/news/greater-manchester-news/ Rochdale',
    '"Manchester Evening News" Rochdale',
    '"Rochdale Borough Council" news',
    '"Roch Valley Radio" Rochdale',
    '"Action Together" Rochdale',
    '"Your Trust Rochdale"',
    '"Rochdale AFC" news',
    '"Rochdale Hornets" news',
    '"Northern Care Alliance" Rochdale',
    '"Rochdale Sixth Form College" news',
)

COUNCILLOR_SHARD_SIZE = 15


@dataclass(frozen=True)
class SearchQuery:
    label: str
    query: str
    category: str = "news"
    ward: str = ""
    person: str = ""


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
            'OR supported OR opposed OR questioned)'
        ),
        category="politics",
        ward=ward,
        person=name,
    )


def build_search_query_specs(
    max_queries: int = 128,
    now: datetime | None = None,
) -> list[SearchQuery]:
    specs: list[SearchQuery] = []

    for index, query in enumerate(OFFICIAL_GMP_QUERIES, start=1):
        specs.append(
            SearchQuery(
                label=f"official-gmp:{index}",
                query=query,
                category="crime",
            )
        )

    for index, query in enumerate(WATCH_QUERIES, start=1):
        specs.append(
            SearchQuery(
                label=f"watch:{index}",
                query=query,
            )
        )

    for label, category, query in DISCOVERY_TOPICS:
        specs.append(
            SearchQuery(
                label=f"topic:{label}",
                query=query,
                category=category,
            )
        )

    for label, query in CIVIC_QUERIES:
        specs.append(
            SearchQuery(
                label=label,
                query=query,
                category="politics",
                person=ROCHDALE_MP_NAME if "paul-waugh" in label else "",
            )
        )

    # One quarter of the current councillor list is checked on each scrape.
    # At the four normal scheduled minutes, all 60 are covered every hour.
    specs.extend(
        councillor_query(name, ward)
        for name, ward in councillors_for_run(now)
    )

    for category, query in CATEGORY_QUERIES:
        specs.append(
            SearchQuery(
                label=f"category:{category}",
                query=query,
                category=category,
            )
        )

    specs.extend(ward_query(ward) for ward in ROCHDALE_WARDS)

    for index, query in enumerate(SOURCE_QUERIES, start=1):
        specs.append(
            SearchQuery(
                label=f"source:{index}",
                query=query,
            )
        )

    unique: list[SearchQuery] = []
    seen: set[str] = set()
    for spec in specs:
        key = spec.query.casefold().strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)

    return unique[: max(1, int(max_queries))]


def build_search_queries(
    max_queries: int = 128,
    now: datetime | None = None,
) -> list[str]:
    return [
        spec.query
        for spec in build_search_query_specs(max_queries=max_queries, now=now)
    ]
