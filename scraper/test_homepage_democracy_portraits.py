#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


def main() -> int:
    text = INDEX.read_text(encoding="utf-8")
    required = [
        'var councillorPhotos = null;',
        'fetch("/councillor_photos.json", { cache: "no-store" })',
        'var portrait = image.indexOf("/assets/img/cards/") === 0',
    ]
    missing = [item for item in required if item not in text]
    if missing:
        raise SystemExit("Homepage Democracy portrait wiring missing: " + ", ".join(missing))
    print("Homepage Democracy portrait wiring passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
