"""Blanket incident rule (editor, 9 Nov 2026).

Any story whose headline contains the word "emergency" (or "emergencies") in
the sense of something happening is filed under Community and illustrated with the red Incident card, never a
place photo, stock photo or source picture. The editor asked for this as a
blanket rule with no exceptions, so it runs before every other category and
image rule, including editor locks, manual photos and the police stock photo.

Trigger: "Emergency services respond to incident in Middleton town centre"
(22 Jul 2026) had been filed as Business and shown a Geograph photo of a
church interior captioned "File photo: Middleton".

This module is the single source of the rule. Every lane imports it:
  - frontpage_pipeline.headline_category_rule / _normalise (live feed)
  - story_integrity_audit.headline_category (archive via category_for)
  - image_hierarchy.choose_image and ensure_article_images.enforce_article
  - source_presentation.enforce_police_image (so the police photo cannot win)
  - generate_pages.render_article_page (page breadcrumb and section)
"""
from __future__ import annotations

import html
import re
from typing import Any

INCIDENT_HEADLINE_RE = re.compile(r"\bemergenc(?:y|ies)\b", re.IGNORECASE)
# "Emergency" that is not an incident (editor, 9 Nov 2026: the National
# Emergency Briefing screenings, "climate emergency" and "emergency law" must
# NOT get the Incident card). Policy, campaigns, money, trades and council
# planning pages use the word without anything having happened.
NOT_INCIDENT_RE = re.compile(
    r"\bemergency (?:briefings?|laws?|legislation|powers?|bills?|acts?|motions?|debates?|"
    r"budgets?|fund(?:s|ing)?|grants?|payments?|loans?|appeal fund|"
    r"plumb\w*|electrician\w*|locksmith\w*|repairs?|call[- ]?outs?|"
    r"planning|plans?|preparedness|resilience|update information)\b|"
    r"\b(?:climate|ecological|nature|biodiversity|housing|cost[- ]of[- ]living|planetary) emergenc(?:y|ies)\b|"
    r"^\s*emergencies\s*[\u2013\u2014-]",
    re.IGNORECASE,
)
# Defined before CRIME_WORDS_RE below because is_incident_title uses it.
_CRIME_HEADLINE_RE = re.compile(
    r"\b(?:arrest\w*|charged|charges?|convicted|sentenced|jailed|murder\w*|manslaughter|"
    r"court|guilty|assault\w*|attack\w* (?:on|an?) emergency worker)\b", re.IGNORECASE)

INCIDENT_CATEGORY = "community"
INCIDENT_CARD = "assets/img/cards/incident-card.jpg"
INCIDENT_STATUS = "incident-card"
INCIDENT_ALT = "Incident"


def _plain(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def is_incident_title(title: Any) -> bool:
    text = _plain(title)
    # A charge, arrest, conviction or court headline is crime reporting, even
    # when it says "emergency" ("Middleton man charged with assaulting
    # emergency worker", 12 Nov 2026, was filed as Community, lost the crime
    # lead and showed in ordinary related boxes). Crashes already had this
    # exclusion; the "emergency" rule did not.
    if _CRIME_HEADLINE_RE.search(text):
        return False
    return bool(INCIDENT_HEADLINE_RE.search(text)) and not NOT_INCIDENT_RE.search(text)


# Incidents without the word "emergency" (editor, 9 Nov 2026): health
# emergencies like the woman who died at Tesco, car crashes, collisions. These
# get the Incident card but KEEP their own section (crashes stay in Traffic so
# road-closure warnings still rank), and crime/court crashes keep Crime and
# the police photo. Measured 9 Nov 2026: 22 non-crime and 15 crime matches.
CRASH_HEALTH_RE = re.compile(
    r"\b(?:crash(?:es|ed)?|collisions?|collided|overturned|"
    r"hit by (?:a )?(?:car|van|lorry|bus|vehicle|train|tram)|"
    r"medical (?:emergency|episode|incident)|collaps(?:ed|es)|cardiac arrest|air ambulance|"
    r"paramedics?|ambulances?|rushed to hospital|taken to hospital|"
    r"died after|dies after|found dead|sudden death)\b",
    re.IGNORECASE,
)
# A business named "Caliber Collision" is not a collision.
CRASH_NOT_RE = re.compile(r"\bcaliber collision\b", re.IGNORECASE)
CRIME_WORDS_RE = re.compile(
    r"\b(?:arrest\w*|charged|convicted|sentenced|jailed|murder\w*|manslaughter|court)\b", re.IGNORECASE)
CRIME_CATEGORIES = {"crime", "courts"}


def is_crash_or_health_incident(article: Any) -> bool:
    if not isinstance(article, dict):
        return False
    title = _plain(article.get("title"))
    if not CRASH_HEALTH_RE.search(title) or CRASH_NOT_RE.search(title):
        return False
    category = str(article.get("category") or "").casefold()
    # The section decides. police_matter is only consulted when there is no
    # section: archived records carry stale flags from before a recategorise.
    if category in CRIME_CATEGORIES or (not category and article.get("police_matter")):
        return False
    return not CRIME_WORDS_RE.search(title)


def wants_incident_card(article: Any) -> bool:
    """The red card: every "emergency" incident headline, plus non-crime
    crashes, collisions and health emergencies."""
    return is_incident(article) or is_crash_or_health_incident(article)


def is_incident(article: Any) -> bool:
    if not isinstance(article, dict):
        return False
    return is_incident_title(article.get("title"))


def apply_incident_card(article: dict[str, Any]) -> dict[str, Any]:
    """Point the story at the red Incident card. Idempotent."""
    article["image_url"] = INCIDENT_CARD
    article["img"] = INCIDENT_CARD
    article["image_alt"] = INCIDENT_ALT
    article["image_credit"] = "Rochdale Daily"
    article["image_credit_url"] = "https://rochdaledaily.co.uk/"
    article["image_status"] = INCIDENT_STATUS
    article["image_backfill_method"] = INCIDENT_STATUS
    article["source_image_reuse_status"] = "cards-only"
    article["image_placeholder_reason"] = "Headline contains 'emergency': blanket Incident card rule"
    for key in ("image_match_title", "image_match_score", "commons_validated_for",
                "source_image_candidate_url", "image_source_url", "image_width", "image_height"):
        article.pop(key, None)
    return article


def apply_incident_category(article: dict[str, Any]) -> dict[str, Any]:
    article["category"] = INCIDENT_CATEGORY
    article["types"] = [INCIDENT_CATEGORY]
    return article


def enforce(article: dict[str, Any]) -> bool:
    """The "emergency" rule: Community and the card. Returns True when applied."""
    if not is_incident(article):
        return False
    apply_incident_category(article)
    apply_incident_card(article)
    return True


def apply_card_if_wanted(article: dict[str, Any]) -> dict[str, Any]:
    """Card only, section untouched. Call after the category is final."""
    if wants_incident_card(article):
        apply_incident_card(article)
    return article
