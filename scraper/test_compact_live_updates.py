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

    # A named location is material even where the rest of the transport update
    # is boilerplate. Do not compact it into a generic service-change line.
    exchange_square = (
        "Planned track renewal works on the Rochdale line will result in service changes "
        "and a bus replacement service until 28 August. No trams will operate via Exchange Square this weekend."
    )
    assert not compact.redundant_update(exchange_square, newest)

    rows = [
        {"timestamp": "2026-08-16T15:00:00Z", "text": newest},
        {"timestamp": "2026-08-16T14:30:00Z", "text": paraphrase},
        {"timestamp": "2026-08-16T14:00:00Z", "text": changed_date},
    ]
    result = compact.compact_updates(rows)
    assert len(result) == 2
    assert result[0]["timestamp"] == "2026-08-16T15:00:00Z"
    assert result[1]["timestamp"] == "2026-08-16T14:00:00Z"

    # Regression for the live Rochdale-line article: repeated scraper
    # paraphrases should collapse while genuinely different facts/locations
    # remain represented. This is intentionally a shortened form of the
    # production timeline rather than a synthetic two-line example.
    transport_rows = [
        {
            "timestamp": "2026-08-16T18:12:20Z",
            "text": "Track renewal works on the Rochdale line will affect services until 28 August, with bus replacements in place.",
        },
        {
            "timestamp": "2026-08-16T17:40:33Z",
            "text": "Planned track renewal works on the Rochdale line will result in service changes and a bus replacement service until 28 August. No trams will operate via Exchange Square this weekend.",
        },
        {
            "timestamp": "2026-08-16T17:23:50Z",
            "text": "Planned track renewal works on the Rochdale line will affect tram services from 15 to 28 August, with bus replacements in place.",
        },
        {
            "timestamp": "2026-08-16T17:23:49Z",
            "text": "Track renewal works on the Rochdale line will result in service changes from 15 to 28 August, with bus replacements in place.",
        },
        {
            "timestamp": "2026-08-16T16:56:30Z",
            "text": "Planned works on the Rochdale line and in Manchester city centre will affect tram services until 28 August, with bus replacements in place for affected stops.",
        },
        {
            "timestamp": "2026-08-16T16:11:32Z",
            "text": "Track renewal works on the Rochdale line will affect services until 28 August, with bus replacements in place. Tram services will also be altered this weekend due to city centre works.",
        },
        {
            "timestamp": "2026-08-16T15:11:01Z",
            "text": "Track renewal works on the Rochdale line will result in service changes and a bus replacement service until 28 August, following disruptions on 15 and 16 August.",
        },
        {
            "timestamp": "2026-08-16T13:29:46Z",
            "text": "Planned works on the Rochdale line and in Manchester city centre will result in service changes and a bus replacement service until 28 August. Passengers are advised to plan their journeys accordingly.",
        },
        {
            "timestamp": "2026-08-16T11:49:51Z",
            "text": "Planned works on the Rochdale line and in Manchester city centre will affect tram services from 15 to 28 August. A bus replacement service will operate during this period.",
        },
    ]
    compacted_transport = compact.compact_updates(transport_rows)
    assert len(compacted_transport) < len(transport_rows)
    assert len(compacted_transport) <= 6
    joined = " ".join(row["text"] for row in compacted_transport)
    assert "Exchange Square" in joined
    assert "15 and 16 August" in joined
    assert "Manchester city centre" in joined

    articles = [{"live_updates": rows, "update_count": 99}, {"title": "ordinary"}]
    payload, changed, removed = compact.compact_articles(articles)
    assert changed == 1
    assert removed == 1
    assert payload[0]["update_count"] == 2

    print("LIVE timeline compaction checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
