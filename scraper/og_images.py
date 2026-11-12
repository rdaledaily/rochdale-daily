"""Social and Google image crops at exactly 1200px wide: 16:9, 4:3 and 1:1.

Editor's request (12 Nov 2026). Google asks for article images in all three
ratios, at least 1200px wide, in the NewsArticle schema; social platforms read
og:image with its stated width and height.

Measured before building: of the 326 images live stories use, 128 are at least
1200px wide and 197 are narrower. Only the wide ones get crops. Stretching a
narrower picture to 1200px would only blur it, so those keep a single image at
its true size, and every page states its real dimensions. Nothing claims a
size it does not have.

Crops are centred, written once to assets/img/og/ (named from the source file's
content hash, so an edited picture gets new crops) and reused on every run.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path("assets/img/og")
WIDTH = 1200
VARIANTS = (("1200x675", 1200, 675), ("1200x900", 1200, 900), ("1200x1200", 1200, 1200))
QUALITY = 82

_cache: dict[str, list[dict[str, Any]]] = {}


def _local(image_url: str, root: Path) -> Path | None:
    value = str(image_url or "").strip()
    if not value or value.startswith(("http://", "https://", "//")):
        return None
    path = root / value.lstrip("/")
    return path if path.is_file() else None


def image_size(image_url: str, root: Path | None = None) -> tuple[int, int] | None:
    path = _local(image_url, root or ROOT)
    if path is None:
        return None
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 - an unreadable file simply has no stated size
        return None


def _crop(img, width: int, height: int):
    from PIL import Image

    src_w, src_h = img.size
    target = width / height
    if src_w / src_h > target:
        new_w = round(src_h * target)
        left = (src_w - new_w) // 2
        box = (left, 0, left + new_w, src_h)
    else:
        new_h = round(src_w / target)
        top = (src_h - new_h) // 2
        box = (0, top, src_w, top + new_h)
    return img.crop(box).resize((width, height), Image.LANCZOS)


def variants(image_url: str, root: Path | None = None, create: bool = True) -> list[dict[str, Any]]:
    """[{url, width, height, ratio}] for a local image at least 1200px wide, else []."""
    root = root or ROOT
    key = f"{root}:{image_url}"
    if key in _cache:
        return _cache[key]
    path = _local(image_url, root)
    result: list[dict[str, Any]] = []
    if path is not None:
        try:
            from PIL import Image, ImageOps

            with Image.open(path) as opened:
                img = ImageOps.exif_transpose(opened)
                if img.size[0] >= WIDTH:
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:10]
                    stem = path.stem[:60]
                    rgb = None
                    for ratio, width, height in VARIANTS:
                        rel = OUT_DIR / f"{stem}-{digest}-{ratio}.jpg"
                        target = root / rel
                        if not target.is_file():
                            if not create:
                                result = []
                                break
                            if rgb is None:
                                rgb = img.convert("RGB")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            _crop(rgb, width, height).save(target, "JPEG", quality=QUALITY, optimize=True, progressive=True)
                        result.append({"url": rel.as_posix(), "width": width, "height": height, "ratio": ratio})
        except Exception:  # noqa: BLE001 - no crops is always a safe answer
            result = []
    _cache[key] = result
    return result
