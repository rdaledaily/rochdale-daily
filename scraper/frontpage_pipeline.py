from pathlib import Path
import re
import py_compile

source_path = Path("/mnt/data/Pasted code.py")
output_path = Path("/mnt/data/frontpage_pipeline_updated.py")

text = source_path.read_text(encoding="utf-8")

# Update module description and robust defaults.
text = text.replace(
    "* retain a 14-day article archive while selecting a balanced 30-36 story front page;",
    "* retain the article archive while selecting a balanced front page of up to 60 stories;",
)

text = text.replace(
    'FRONTPAGE_TARGET = int(os.getenv("FRONTPAGE_TARGET_ARTICLES", "36"))',
    'FRONTPAGE_TARGET = int(os.getenv("FRONTPAGE_TARGET_ARTICLES", "60"))',
)
text = text.replace(
    'PRIMARY_DAYS = int(os.getenv("FRONTPAGE_PRIMARY_DAYS", "7"))',
    'PRIMARY_DAYS = int(os.getenv("FRONTPAGE_PRIMARY_DAYS", "1"))',
)
text = text.replace(
    'FALLBACK_DAYS = int(os.getenv("FRONTPAGE_FALLBACK_DAYS", "14"))',
    'FALLBACK_DAYS = int(os.getenv("FRONTPAGE_FALLBACK_DAYS", "3"))',
)

old_selection = '''    primary_cutoff = reference - timedelta(days=PRIMARY_DAYS)
    fallback_cutoff = reference - timedelta(days=FALLBACK_DAYS)
    primary = [article for article in base if _age_eligible(article, primary_cutoff)]
    pool = primary if len(primary) >= FRONTPAGE_MIN else [article for article in base if _age_eligible(article, fallback_cutoff)]
    pool = sorted(pool, key=lambda item: _article_rank(item, reference), reverse=True)
    longform_pool = [
        item for item in pool
        if is_event(item) or editorial_word_count(item) >= 200
    ]
    if len(longform_pool) >= FRONTPAGE_MIN:
        pool = longform_pool
'''

new_selection = '''    primary_cutoff = reference - timedelta(days=PRIMARY_DAYS)
    fallback_cutoff = reference - timedelta(days=FALLBACK_DAYS)

    primary = [
        article
        for article in base
        if _age_eligible(article, primary_cutoff)
    ]
    fallback = [
        article
        for article in base
        if _age_eligible(article, fallback_cutoff)
    ]

    # Prefer the last 24 hours, but use the wider fallback window whenever
    # it is needed to fill the requested front-page capacity.
    pool = primary if len(primary) >= FRONTPAGE_TARGET else fallback
    pool = sorted(pool, key=lambda item: _article_rank(item, reference), reverse=True)

    longform_pool = [
        item for item in pool
        if is_event(item) or editorial_word_count(item) >= 200
    ]
    if len(longform_pool) >= min(FRONTPAGE_TARGET, len(pool)):
        pool = longform_pool
'''

if old_selection not in text:
    raise RuntimeError("Could not locate the existing select_frontpage age-window block.")
text = text.replace(old_selection, new_selection)

text = text.replace(
    '"selection_window_days": PRIMARY_DAYS if len(primary) >= FRONTPAGE_MIN else FALLBACK_DAYS,',
    '"selection_window_days": PRIMARY_DAYS if len(primary) >= FRONTPAGE_TARGET else FALLBACK_DAYS,',
)

old_dedupe = '''def _dedupe_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        key = str(item.get("story_key") or build_story_key(item) or item.get("source_url") or item.get("title")).lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output
'''

new_dedupe = '''FRONTPAGE_TITLE_STOPWORDS = {
    "a", "an", "the", "to", "for", "of", "in", "on", "at", "and", "or",
    "is", "are", "was", "were", "be", "been", "being", "will", "would",
    "could", "should", "set", "scheduled", "take", "takes", "taking",
    "place", "planned", "plans", "due", "latest", "update", "updates",
}


def _frontpage_title_tokens(article: dict[str, Any]) -> set[str]:
    """Return the meaningful words used to compare front-page headlines."""
    title = strip_publisher_suffix(
        plain_text(article.get("title") or "")
    ).lower()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", title)
        if len(token) > 1 and token not in FRONTPAGE_TITLE_STOPWORDS
    }


def _same_frontpage_story(
    left: dict[str, Any],
    right: dict[str, Any],
) -> bool:
    """Catch duplicate stories that were assigned different categories."""
    left_event = is_event(left)
    right_event = is_event(right)

    # Approved ticket events remain separate unless their canonical URLs match.
    if left_event or right_event:
        if not (left_event and right_event):
            return False
        left_url = normalise_url(str(left.get("source_url") or ""))
        right_url = normalise_url(str(right.get("source_url") or ""))
        return bool(left_url and left_url == right_url)

    left_key = str(
        left.get("story_key") or build_story_key(left)
    ).lower()
    right_key = str(
        right.get("story_key") or build_story_key(right)
    ).lower()
    if left_key and left_key == right_key:
        return True

    left_area = str(left.get("area") or "rochdale").lower()
    right_area = str(right.get("area") or "rochdale").lower()

    # A borough-wide Rochdale record may match a more specific township record.
    if (
        left_area != right_area
        and "rochdale" not in {left_area, right_area}
    ):
        return False

    if hours_apart(left, right) > 72:
        return False

    left_tokens = _frontpage_title_tokens(left)
    right_tokens = _frontpage_title_tokens(right)
    smaller_title = min(len(left_tokens), len(right_tokens))
    shared_tokens = left_tokens & right_tokens

    return (
        smaller_title >= 3
        and len(shared_tokens) >= 3
        and len(shared_tokens) / smaller_title >= 0.80
    )


def _dedupe_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Final cross-category duplicate protection for the published feeds."""
    clusters: list[list[dict[str, Any]]] = []

    for item in items:
        matching_cluster = next(
            (
                cluster
                for cluster in clusters
                if all(
                    _same_frontpage_story(item, existing)
                    for existing in cluster
                )
            ),
            None,
        )

        if matching_cluster is None:
            clusters.append([item])
        else:
            matching_cluster.append(item)

    return [merge_group(cluster) for cluster in clusters]
'''

if old_dedupe not in text:
    raise RuntimeError("Could not locate the existing _dedupe_by_url function.")
text = text.replace(old_dedupe, new_dedupe)

old_main = '''    merged = merge_duplicate_articles(cleaned)
    merged = [apply_category_rules(article) for article in merged]
    merged = _dedupe_by_url(merged)
    merged.sort(
'''

new_main = '''    merged = merge_duplicate_articles(cleaned)
    merged = [apply_category_rules(article) for article in merged]
    merged = _dedupe_by_url(merged)

    # Recalculate category after cross-category duplicates have been combined.
    merged = [apply_category_rules(article) for article in merged]
    merged.sort(
'''

if old_main not in text:
    raise RuntimeError("Could not locate the merge section in main().")
text = text.replace(old_main, new_main)

output_path.write_text(text, encoding="utf-8")

# Validate Python syntax.
py_compile.compile(str(output_path), doraise=True)

print(f"Created and syntax-checked: {output_path.name}")
print(f"Lines: {len(text.splitlines())}")
