from datetime import datetime, timezone

from search_queries import (
    COUNCILLOR_SHARD_SIZE,
    CURRENT_COUNCILLORS,
    DISCOVERY_TOPICS,
    ROCHDALE_MP_NAME,
    ROCHDALE_WARDS,
    build_search_query_specs,
    councillors_for_run,
)

fixed_runs = (
    datetime(2026, 7, 8, 16, 7, tzinfo=timezone.utc),
    datetime(2026, 7, 8, 16, 22, tzinfo=timezone.utc),
    datetime(2026, 7, 8, 16, 37, tzinfo=timezone.utc),
    datetime(2026, 7, 8, 16, 52, tzinfo=timezone.utc),
)

all_watched = []
for run_time in fixed_runs:
    shard = councillors_for_run(run_time)
    assert len(shard) == COUNCILLOR_SHARD_SIZE
    all_watched.extend(shard)

assert len(CURRENT_COUNCILLORS) == 60
assert len({name for name, _ in CURRENT_COUNCILLORS}) == 60
assert all_watched == list(CURRENT_COUNCILLORS)

# Bulk queries (watch/topics/categories/wards/sources) are now sharded
# across the four scheduled runs per hour, to keep Google News request
# volume per run low enough to avoid rate-limiting/bot-detection (a burst
# of 130+ requests in one run was observed to get every single query
# blocked, returning zero results across the board). Any single run only
# covers roughly a quarter of the bulk set; the full set is covered across
# all four runs combined. So topic/ward/source coverage is checked
# cumulatively here, the same way councillor coverage already is.
per_run_specs = [build_search_query_specs(200, now=run_time) for run_time in fixed_runs]
cumulative_queries = [spec.query for specs in per_run_specs for spec in specs]
cumulative_joined = "\n".join(cumulative_queries).lower()

required_fragments = (
    '"healey dell" viaduct',
    '"healey dell" robbery',
    '"healey dell" fishing',
    '"milkstone road" takeaway',
    '"milkstone road" speeding',
    '"bamford" rochdale "house prices"',
    '"norden" rochdale "school results"',
    '"bamford" rochdale restaurant',
    '"norden golf club"',
    '"kirkholt" charity',
    '"kirkholt" ("sure start" or surestart or "family sessions")',
    '"whitworth stronger together"',
    'whitworth ("swimming baths" or pool or leisure centre)',
    '("oulder hill" or "oulder hill leisure complex")',
    '("cowm reservoir" or "cowm resevoir")',
    '"college bank" ("padel court" or padel)',
    '("spotland mill" or "spotland mills") businesses',
    '"milnrow" football',
    '"firgrove playing fields"',
    '("rochdale mayfield" or "mayfield rugby club")',
    '"middleton arena"',
    '"spotland reform club"',
    '"crown oil arena"',
    '("rochdale afc" or "rochdale football club")',
    '"manchester road" rochdale traffic',
    '("hamer amateur boxing club" or "hamer abc")',
    '"newhey" potholes',
    'rochdale (sheep or lambs or flock or livestock)',
    'heywood (hmo or "house in multiple occupation")',
    'rochdale (church or chapel)',
    'rochdale ("charity event" or fundraiser or fundraising)',
    'rochdale (sats or "sat results" or "key stage 2 results")',
    'rochdale ("a level results" or "a-level results")',
    '("rochdale sixth form college" or "rochdale sfc")',
    'rochdale ("mma fighter" or "mixed martial arts fighter")',
    'rochdale ("thai boxer" or "muay thai" or "thai boxing")',
    'rochdale footballer',
    'rochdale netball',
    'rochdale rugby',
    'rochdale (award or awards or winner or honoured or recognition)',
    'rochdale headteacher',
    'rochdale murder',
    '("rochdale canal" or "rochdale canal")',
    '"rochdale town hall"',
    '"paul waugh" rochdale',
    "site:manchestereveningnews.co.uk/all-about/rochdale rochdale",
    "site:manchestereveningnews.co.uk/news/greater-manchester-news/ rochdale",
    '"manchester evening news" rochdale',
)

for fragment in required_fragments:
    assert fragment in cumulative_joined, fragment

assert set(ROCHDALE_WARDS) <= {
    spec.ward for specs in per_run_specs for spec in specs if spec.ward
}
assert len(DISCOVERY_TOPICS) >= 44

# Search locations and current councillors, not invented police branches.
assert "gmp bamford" not in cumulative_joined
assert "gmp healey" not in cumulative_joined

# Per-run invariants: the small always-on sets (GMP, civic/Parliament,
# this run's councillor shard) must appear on EVERY run, not just
# cumulatively, and each run's total request volume must stay well below
# the burst size that was observed to trigger Google's rate-limiting.
for specs in per_run_specs:
    labels = {spec.label for spec in specs}
    assert any(label.startswith("official-gmp:") for label in labels)
    assert any(spec.person == ROCHDALE_MP_NAME for spec in specs)
    assert len([spec for spec in specs if spec.label.startswith("councillor:")]) == 15
    assert len(specs) < 70, (
        f"single-run query volume too high ({len(specs)}); "
        "this is what caused Google to block every query in a run"
    )

print(
    f"Deep-local query tests passed: {len(cumulative_queries)} cumulative queries "
    f"across 4 runs ({[len(s) for s in per_run_specs]} per run), "
    f"{len(DISCOVERY_TOPICS)} named topics, 15 councillors per run."
)
