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

specs = build_search_query_specs(128, now=fixed_runs[0])
queries = [spec.query for spec in specs]
joined = "\n".join(queries).lower()
labels = {spec.label for spec in specs}

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
)

for fragment in required_fragments:
    assert fragment in joined, fragment

assert any(spec.person == ROCHDALE_MP_NAME for spec in specs)
assert len([spec for spec in specs if spec.label.startswith("councillor:")]) == 15
assert set(ROCHDALE_WARDS) <= {spec.ward for spec in specs if spec.ward}
assert len(DISCOVERY_TOPICS) >= 44

# Search locations and current councillors, not invented police branches.
assert "gmp bamford" not in joined
assert "gmp healey" not in joined

assert "site:manchestereveningnews.co.uk/all-about/rochdale rochdale" in joined
assert "site:manchestereveningnews.co.uk/news/greater-manchester-news/ rochdale" in joined
assert '"manchester evening news" rochdale' in joined

print(
    f"Deep-local query tests passed: {len(specs)} queries, "
    f"{len(DISCOVERY_TOPICS)} named topics, 15 councillors this run."
)
