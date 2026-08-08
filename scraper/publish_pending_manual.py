from __future__ import annotations

import glob
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "manual_articles.json"


def main() -> None:
    if not TARGET.exists():
        raise SystemExit("manual_articles.json not found")

    with TARGET.open(encoding="utf-8") as f:
        existing = json.load(f)

    pending_paths = sorted(ROOT.glob("pending_manual_*.json"))
    pending: list[dict] = []

    for path in pending_paths:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            pending.append(data)
        elif isinstance(data, list):
            pending.extend(x for x in data if isinstance(x, dict))
        else:
            raise ValueError(f"Unsupported JSON structure in {path.name}")

    if not pending:
        print("No pending manual articles to publish.")
        return

    ids = {a.get("id") for a in pending if a.get("id")}
    slugs = {a.get("slug") for a in pending if a.get("slug")}
    existing = [
        a for a in existing
        if a.get("id") not in ids and a.get("slug") not in slugs
    ]

    pending.sort(
        key=lambda a: a.get("published_at") or a.get("last_updated_at") or "",
        reverse=True,
    )

    with TARGET.open("w", encoding="utf-8") as f:
        json.dump(pending + existing, f, ensure_ascii=False, indent=2)
        f.write("\n")

    for path in pending_paths:
        path.unlink()

    for trigger in ROOT.glob("trigger_publish_*.txt"):
        trigger.unlink()
    trigger = ROOT / "manual_publish_trigger.txt"
    if trigger.exists():
        trigger.unlink()

    print(f"Published {len(pending)} pending manual article(s).")


if __name__ == "__main__":
    main()
