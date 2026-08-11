#!/usr/bin/env python3
"""Build the Rochdale councillor portrait index from assets/img/cards only.

Rochdale Daily's image policy is deliberately local: councillor portraits are
never fetched from council sites, search engines, Wikimedia, social media or any
other remote source. A portrait is eligible only when the image file already
lives in ``assets/img/cards``.

Matching is name based and tolerant of the filename conventions used by the
editorial library:

* ``Ashley_Louise_Gilbert.jpg`` -> Ashley-Louise Gilbert
* ``Paul_ONeill.png`` -> Paul O'Neill
* ``Dylan_James_Williams.jpg`` -> Dylan Williams
* ``Patricia_Mary_Dale.jpg`` -> Patricia Dale
* ``phillip_barrett.jpg`` -> Philip Barrett (minor spelling variation)

Exact full-name matches win. First+last-name matches allow an extra middle name.
A conservative fuzzy fallback handles a one-character spelling variation while
still requiring both first and last names to agree.
"""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ROSTER = ROOT / "council_roster.json"
OUT = ROOT / "councillor_photos.json"
CARDS_DIR = ROOT / "assets" / "img" / "cards"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
GENERATED_MARKERS = ("generated-card", "area-category-card", "placeholder")


def load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def words(value: Any) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    return [part for part in re.sub(r"[^a-z0-9]+", " ", text).split() if part]


def generated(path: Path) -> bool:
    stem = path.stem.lower().replace("_", "-")
    return any(marker in stem for marker in GENERATED_MARKERS)


def image_candidates() -> list[Path]:
    if not CARDS_DIR.is_dir():
        return []
    rows = []
    for path in CARDS_DIR.iterdir():
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES or generated(path):
            continue
        try:
            if path.stat().st_size <= 4096:
                continue
        except OSError:
            continue
        rows.append(path)
    return sorted(rows, key=lambda p: p.name.lower())


def token_similarity(left: str, right: str) -> float:
    if left == right:
        return 1.0
    return SequenceMatcher(None, left, right).ratio()


def portrait_score(name: str, path: Path) -> int:
    """Return a conservative name-to-filename score, or -1 for no match."""
    person = words(name)
    file_words = words(path.stem)
    if len(person) < 2 or len(file_words) < 2:
        return -1

    person_joined = "".join(person)
    file_joined = "".join(file_words)
    if person_joined == file_joined:
        return 10000 + len(person_joined)

    # The uploaded portrait may include a middle name not used in the roster.
    # Requiring both the first and last name keeps this much safer than a broad
    # keyword match against the whole cards directory.
    first, last = person[0], person[-1]
    if first in file_words and last in file_words:
        extras = max(0, len(file_words) - len(person))
        return 8500 - extras * 20 + len(first) + len(last)

    # Minor spelling differences such as Philip/Phillip are allowed only when
    # BOTH the first and last filename tokens closely match the roster name.
    file_first, file_last = file_words[0], file_words[-1]
    first_ratio = token_similarity(first, file_first)
    last_ratio = token_similarity(last, file_last)
    if first_ratio >= 0.86 and last_ratio >= 0.90:
        return 6500 + int((first_ratio + last_ratio) * 100)

    return -1


def find_portrait(name: str, candidates: list[Path] | None = None) -> Path | None:
    candidates = candidates if candidates is not None else image_candidates()
    scored = [(portrait_score(name, path), path) for path in candidates]
    scored = [(score, path) for score, path in scored if score >= 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1].name.lower()))
    return scored[0][1]


def build_local_portrait_map(*, write: bool = True) -> dict[str, dict[str, Any]]:
    raw = load(ROSTER, {})
    people = raw.get("councillors", []) if isinstance(raw, dict) else raw
    if not isinstance(people, list):
        people = []

    candidates = image_candidates()
    out: dict[str, dict[str, Any]] = {}
    matched = 0

    for person in people:
        if not isinstance(person, dict):
            continue
        name = str(person.get("name") or "").strip()
        ward = str(person.get("ward") or "").strip()
        if not name:
            continue

        path = find_portrait(name, candidates)
        if path is None:
            out[name] = {
                "image_url": "",
                "profile_url": "",
                "image_source": "assets/img/cards",
                "verified_name_match": False,
                "ward": ward,
            }
            print(f"MISS  {name}")
            continue

        rel = path.relative_to(ROOT).as_posix()
        out[name] = {
            "image_url": "/" + rel,
            "profile_url": "",
            "image_source": "assets/img/cards",
            "verified_name_match": True,
            "matched_filename": path.name,
            "ward": ward,
        }
        matched += 1
        print(f"LOCAL {name} -> {path.name}")

    if write:
        OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"Local councillor portraits: {matched}/{len(people)}")
    return out


def main() -> int:
    build_local_portrait_map(write=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
