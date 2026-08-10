"""First-party beat registry for Rochdale Daily.

Search engines are radar, not the newsroom. This registry documents the
organisations and public data beats that should be polled directly wherever a
stable public endpoint exists. It is intentionally data-only so collectors can
be migrated onto it incrementally without changing editorial rules.
"""
from __future__ import annotations

FIRST_PARTY_BEATS = (
    {"beat": "council-news", "name": "Rochdale Borough Council News", "url": "https://www.rochdale.gov.uk/news", "category": "politics", "area": "rochdale", "priority": "critical"},
    {"beat": "council-planning", "name": "Rochdale planning applications", "url": "https://www.rochdale.gov.uk/planning-permission", "category": "planning", "area": "rochdale", "priority": "critical"},
    {"beat": "council-democracy", "name": "Rochdale Council democracy", "url": "https://democracy.rochdale.gov.uk/", "category": "politics", "area": "rochdale", "priority": "critical"},
    {"beat": "police", "name": "Greater Manchester Police", "url": "https://www.gmp.police.uk/news/", "category": "crime", "area": "rochdale", "priority": "critical"},
    {"beat": "fire", "name": "Greater Manchester Fire and Rescue Service", "url": "https://www.manchesterfire.gov.uk/news-events/news/", "category": "crime", "area": "rochdale", "priority": "high"},
    {"beat": "health-nca-rochdale", "name": "Northern Care Alliance Rochdale", "url": "https://www.northerncarealliance.nhs.uk/news/rochdale-news", "category": "health", "area": "rochdale", "priority": "high"},
    {"beat": "mental-health", "name": "Pennine Care NHS", "url": "https://www.penninecare.nhs.uk/about-us/latest-news", "category": "health", "area": "rochdale", "priority": "high"},
    {"beat": "football", "name": "Rochdale AFC", "url": "https://rochdaleafc.co.uk/news/", "category": "sport", "area": "rochdale", "priority": "high"},
    {"beat": "rugby-league", "name": "Rochdale Hornets", "url": "https://www.hornetsrugbyleague.co.uk/news", "category": "sport", "area": "rochdale", "priority": "high"},
    {"beat": "mayfield", "name": "Rochdale Mayfield", "url": "https://www.rochdalemayfield.com/", "category": "sport", "area": "rochdale", "priority": "normal"},
    {"beat": "transport", "name": "Bee Network", "url": "https://tfgm.com/travel-updates/travel-alerts", "category": "transport", "area": "rochdale", "priority": "high"},
    {"beat": "rail", "name": "Northern", "url": "https://www.northernrailway.co.uk/service-updates", "category": "transport", "area": "rochdale", "priority": "high"},
    {"beat": "motorways", "name": "National Highways North West", "url": "https://nationalhighways.co.uk/our-roads/north-west/", "category": "traffic", "area": "rochdale", "priority": "high"},
    {"beat": "water", "name": "United Utilities", "url": "https://www.unitedutilities.com/emergencies/up-my-street/", "category": "community", "area": "rochdale", "priority": "high"},
    {"beat": "environment", "name": "Environment Agency", "url": "https://check-for-flooding.service.gov.uk/", "category": "environment", "area": "rochdale", "priority": "high"},
    {"beat": "housing", "name": "Rochdale Boroughwide Housing", "url": "https://www.rbh.org.uk/", "category": "community", "area": "rochdale", "priority": "normal"},
    {"beat": "regeneration", "name": "Rochdale Development Agency", "url": "https://investinrochdale.co.uk/news", "category": "business", "area": "rochdale", "priority": "high"},
    {"beat": "college", "name": "Hopwood Hall College", "url": "https://www.hopwood.ac.uk/news-and-events/latest-news/", "category": "education", "area": "rochdale", "priority": "normal"},
    {"beat": "sixth-form", "name": "Rochdale Sixth Form College", "url": "https://www.rochdalesfc.ac.uk/128/news", "category": "education", "area": "rochdale", "priority": "normal"},
    {"beat": "food-hygiene", "name": "Food Standards Agency", "url": "https://ratings.food.gov.uk/open-data", "category": "business", "area": "rochdale", "priority": "normal"},
)


def beat_names() -> set[str]:
    return {str(item["name"]) for item in FIRST_PARTY_BEATS}


def critical_beats() -> tuple[dict[str, str], ...]:
    return tuple(item for item in FIRST_PARTY_BEATS if item.get("priority") == "critical")
