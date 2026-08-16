from __future__ import annotations

import compact_live_updates as compact


def main() -> int:
    newest = "Track renewal works on the Rochdale line will result in service changes and a bus replacement service until 28 August."
    paraphrase = "Planned works on the Rochdale line will result in service changes and a bus replacement service until 28 August."
    assert compact.redundant_update(paraphrase, newest)

    # A changed date/count is a material fact and must survive even where most
    # wording overlaps.
    changed_date = "Track renewal works on the Rochdale line will result in service changes and a bus replacement service until 29 August."
    assert not compact.redundant_update(changed_date, newest)

    # A genuinely different development must survive.
    arrest = "Police have arrested a 34-year-old man who remains in custody."
    appeal = "Police are appealing for witnesses after the incident."
    assert not compact.redundant_update(appeal, arrest)

    rows = [
        {"timestamp": "2026-08-16T15:00:00Z", "text": newest},
        {"timestamp": "2026-08-16T14:30:00Z", "text": paraphrase},
        {"timestamp": "2026-08-16T14:00:00Z", "text": changed_date},
    ]
    result = compact.compact_updates(rows)
    assert len(result) == 2
    assert result[0]["timestamp"] == "2026-08-16T15:00:00Z"
    assert result[1]["timestamp"] == "2026-08-16T14:00:00Z"

    articles = [{"live_updates": rows, "update_count": 99}, {"title": "ordinary"}]
    payload, changed, removed = compact.compact_articles(articles)
    assert changed == 1
    assert removed == 1
    assert payload[0]["update_count"] == 2

    print("LIVE timeline compaction checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
