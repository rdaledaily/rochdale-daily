"""Additional Rochdale Daily sources.

These are appended to the original scraper source lists.
They do not replace any existing RSS, discovery, live, Google,
Facebook Events or social-media collectors.
"""

EXTRA_DISCOVERY_PAGES = [
    # Housing
    {
        "name": "Rochdale Boroughwide Housing",
        "url": "https://www.rbh.org.uk/",
        "default_area": "rochdale",
        "default_category": "community",
        "link_pattern": r"/news/|/latest-news/|/updates/|/our-news/",
    },

    # Town-centre and local news
    {
        "name": "Rochdale Riverside News",
        "url": "https://rochdaleriverside.com/news/",
        "default_area": "rochdale",
        "default_category": "business",
        "link_pattern": r"/news/",
    },
    {
        "name": "Rochdale Valiant",
        "url": "https://www.rochdalevaliant.uk/",
        "default_area": "rochdale",
        "default_category": "news",
        "link_pattern": r"/",
    },

    # National publications with Rochdale sections
    {
        "name": "The Independent — Rochdale",
        "url": "https://www.independent.co.uk/topic/rochdale",
        "default_area": "rochdale",
        "default_category": "news",
        "link_pattern": r"/news/|/topic/rochdale",
    },

    # Council and politics
    {
        "name": "Rochdale Council Webcasts",
        "url": (
            "https://rochdale.public-i.tv/core/data/21235/"
            "archived/1/future/1/agenda/1/enctag/Council"
        ),
        "default_area": "rochdale",
        "default_category": "politics",
        "link_pattern": r"/core/portal/|/core/data/",
    },

    # Health
    {
        "name": "Northern Care Alliance News",
        "url": "https://www.northerncarealliance.nhs.uk/nca-news",
        "default_area": "rochdale",
        "default_category": "health",
        "link_pattern": r"/nca-news/|/news/",
    },

    # Education
    {
        "name": "Falinge Park High School",
        "url": "https://www.falingepark.com/news-and-events/",
        "default_area": "falinge",
        "default_category": "education",
        "link_pattern": r"/news-and-events/|/news/",
    },
    {
        "name": "Oulder Hill Leadership Academy",
        "url": "https://www.oulderhillacademy.com/latest-news/",
        "default_area": "rochdale",
        "default_category": "education",
        "link_pattern": r"/latest-news/|/news/",
    },
    {
        "name": "Wardle Academy",
        "url": "https://www.wchs.co/topic/news-and-events",
        "default_area": "wardle",
        "default_category": "education",
        "link_pattern": r"/topic/news-and-events|/news/",
    },
    {
        "name": "St Cuthbert's RC High School",
        "url": "https://stcuthberts.com/news",
        "default_area": "rochdale",
        "default_category": "education",
        "link_pattern": r"/news/",
    },
    {
        "name": "Edgar Wood Academy",
        "url": "https://www.edgarwood.org/80/news-and-events",
        "default_area": "middleton",
        "default_category": "education",
        "link_pattern": r"/80/news-and-events|/news-and-events|/news/",
    },
]


EXTRA_LIVE_PAGE_SOURCES = [
    {
        "name": "Traffic Update — Rochdale",
        "url": "https://www.traffic-update.co.uk/traffic/rochdale.asp",
        "category": "traffic",
        "default_area": "rochdale",
    },
    {
        "name": "Met Office — Rochdale forecast",
        "url": "https://weather.metoffice.gov.uk/forecast/gcw3nb4ge",
        # Keeps compatibility with the existing category system.
        "category": "environment",
        "default_area": "rochdale",
    },
]


EXTRA_OFFICIAL_X_HANDLES = {
    "highwaysnwest": "National Highways North West",
}


EXTRA_X_SEARCH_QUERIES = [
    (
        "from:HighwaysNWEST "
        "(Rochdale OR Heywood OR Middleton OR Littleborough OR Milnrow "
        'OR "M62 J19" OR "M62 J20" OR "M62 J21" OR "A627(M)") '
        "lang:en -is:retweet"
    ),
]


EXTRA_FACEBOOK_PAGES = [
    {
        "name": "My Rochdale News Facebook",
        "handle": "MyRochdaleNews",
        "url": "https://www.facebook.com/MyRochdaleNews/",
        "default_area": "rochdale",
        "official": False,
    },
]


# NewsNow and Ground News are aggregators, not original publishers.
# They need to be used to discover outbound publisher links rather than
# having their summaries rewritten as if they were the primary source.
EXTRA_AGGREGATOR_PAGES = [
    {
        "name": "NewsNow — Rochdale",
        "url": (
            "https://www.newsnow.co.uk/h/UK/England/"
            "Greater+Manchester/Rochdale"
        ),
        "default_area": "rochdale",
    },
    {
        "name": "Ground News — Rochdale",
        "url": "https://ground.news/interest/rochdale",
        "default_area": "rochdale",
    },
]
