#!/usr/bin/env python3
"""Keep every public photo small enough to load quickly.

The Ahrefs site audit of 26 Nov 2026 flagged 19 card images between 1 MB and
5.9 MB: camera originals uploaded at full resolution (White_Ribbon.jpg was
3307x2205, 5.9 MB) and photographs saved as PNG (weather.png, 2.8 MB). A card
is shown at most ~1,200px wide, so these cost readers seconds on a phone and
count against the site in search.

Each image over LIMIT_BYTES is rewritten IN PLACE, same filename and same
format, so no page, feed or JSON record that names it needs to change:

  * longest side reduced to MAX_EDGE (never enlarged)
  * EXIF orientation applied, metadata dropped
  * JPEG: quality 82, progressive
  * PNG: lossless re-encode; if still over PNG_PALETTE_ABOVE, reduced to a
    256-colour palette (photographs saved as PNG - visually the same at card
    size, measured 2.8 MB -> 523 KB on weather.png)
  * WebP: quality 82

A file is only replaced when the result is at least 10% smaller. Images under
the limit are never touched, and an image this script already produced does
not shrink 10% again, so a second run changes nothing.

Usage:
  python scraper/optimise_images.py            # optimise, print a summary
  python scraper/optimise_images.py --check    # report only, exit 1 if any over
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
IMAGE_DIRS = ("assets/img", "assets/article-images")
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
LIMIT_BYTES = 600 * 1024
MAX_EDGE = 1600
# A detailed photograph can still be over the limit at 1600px; it is then
# encoded once at SMALL_EDGE (cards display at most ~1,200px wide).
SMALL_EDGE = 1200
JPEG_QUALITY = 82
PNG_PALETTE_ABOVE = 600 * 1024
MIN_SAVING = 0.9


def candidates(root: Path = ROOT) -> list[Path]:
    found: list[Path] = []
    for rel in IMAGE_DIRS:
        folder = root / rel
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.lower() in SUFFIXES and path.stat().st_size > LIMIT_BYTES:
                found.append(path)
    return sorted(found)


def _encode(image: Image.Image, suffix: str, edge: int) -> bytes:
    image = image.copy()
    image.thumbnail((edge, edge), Image.LANCZOS)
    out = io.BytesIO()
    if suffix in {".jpg", ".jpeg"}:
        image.convert("RGB").save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
    elif suffix == ".webp":
        image.save(out, "WEBP", quality=JPEG_QUALITY, method=6)
    else:
        if image.mode not in {"RGB", "RGBA", "L", "LA", "P"}:
            image = image.convert("RGBA")
        image.save(out, "PNG", optimize=True)
        if out.tell() > PNG_PALETTE_ABOVE:
            palette = image.convert("RGBA").quantize(
                256, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.FLOYDSTEINBERG
            )
            out = io.BytesIO()
            palette.save(out, "PNG", optimize=True)
    return out.getvalue()


def optimised_bytes(path: Path) -> bytes:
    suffix = path.suffix.lower()
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source)
        image.load()
    data = _encode(image, suffix, MAX_EDGE)
    if len(data) > LIMIT_BYTES:
        data = _encode(image, suffix, SMALL_EDGE)
    return data


def optimise(root: Path = ROOT, *, check: bool = False) -> list[tuple[str, int, int]]:
    """Return (path, bytes_before, bytes_after) for every image over the limit."""
    results: list[tuple[str, int, int]] = []
    for path in candidates(root):
        before = path.stat().st_size
        rel = path.relative_to(root).as_posix()
        if check:
            results.append((rel, before, before))
            continue
        try:
            data = optimised_bytes(path)
        except Exception as exc:  # noqa: BLE001 - one unreadable file must not stop the rest
            print(f"::error title=Image optimise::{rel}: {type(exc).__name__}: {exc}")
            results.append((rel, before, before))
            continue
        # Only a real saving is written. Re-encoding a file this script
        # already produced saves a few percent at most, so a second run
        # leaves it alone instead of degrading it a generation at a time.
        if len(data) <= before * MIN_SAVING:
            path.write_bytes(data)
            results.append((rel, before, len(data)))
        else:
            results.append((rel, before, before))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.root)
    results = optimise(root, check=args.check)
    over = [r for r in results if r[2] > LIMIT_BYTES]
    for rel, before, after in results:
        print(f"{before // 1024:>6} KB -> {after // 1024:>6} KB  {rel}")
    total_before = sum(r[1] for r in results)
    total_after = sum(r[2] for r in results)
    print(f"{len(results)} image(s) over {LIMIT_BYTES // 1024} KB: "
          f"{total_before // 1024} KB -> {total_after // 1024} KB; {len(over)} still over the limit.")
    if args.check and results:
        return 1
    if over:
        # Reported, not hidden: a file that cannot get under the limit with
        # these settings needs an editor's look, not a silent pass.
        for rel, _, after in over:
            print(f"::warning title=Image still large::{rel} is {after // 1024} KB after optimising")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
