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
import html
import json
import re
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
    for own in ("https://rochdaledaily.co.uk/", "http://rochdaledaily.co.uk/", "https://www.rochdaledaily.co.uk/"):
        if value.startswith(own):
            value = value[len(own):]  # our own file, addressed absolutely
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


# --------------------------------------------------------------------------
# One writer for a page's image metadata
# --------------------------------------------------------------------------
#
# Three post-processors (apply_incident_rule, archive_quality,
# legacy_archive_integrity) replace a page's picture after it is rendered.
# Each assumed a single og:image: on 12 Nov 2026 they swapped every crop URL
# back to the original card but left the 1200x675 / 1200x900 / 1200x1200
# sizes in place, so pages claimed dimensions the image did not have. They
# now all call rewrite_page_image(), which replaces the whole set.

SITE = "https://rochdaledaily.co.uk"

_OG_IMAGE_META = re.compile(
    r'[ \t]*<meta\b[^>]*(?:property|name)=["\'](?:og:image(?::(?:width|height|alt|secure_url|type))?|twitter:image(?::src|:alt)?)["\'][^>]*>\n?',
    re.I,
)
_ALT = re.compile(r'<meta\b[^>]*property=["\']og:image:alt["\'][^>]*content=["\']([^"\']*)["\']', re.I)
_LD = re.compile(r'(<script type="application/ld\+json">)(.*?)(</script>)', re.S)


def absolute(url: str) -> str:
    value = str(url or "").strip()
    if not value or value.startswith(("http://", "https://")):
        return value
    return f"{SITE}/{value.lstrip('/')}"


def image_set(image_url: str, root: Path | None = None) -> list[tuple[str, int | None, int | None]]:
    """[(absolute url, width, height)]: the three crops, or the original at its true size."""
    crops = variants(image_url, root)
    if crops:
        return [(absolute(c["url"]), c["width"], c["height"]) for c in crops]
    if not str(image_url or "").strip():
        return []
    size = image_size(image_url, root)
    return [(absolute(image_url), size[0] if size else None, size[1] if size else None)]


def meta_tags(image_url: str, alt: str, root: Path | None = None) -> str:
    alt_attr = html.escape(alt or "", quote=True)
    lines = []
    images = image_set(image_url, root)
    for url, width, height in images:
        lines.append(f'  <meta property="og:image" content="{html.escape(url, quote=True)}">')
        if width and height:
            lines.append(f'  <meta property="og:image:width" content="{width}">')
            lines.append(f'  <meta property="og:image:height" content="{height}">')
        lines.append(f'  <meta property="og:image:alt" content="{alt_attr}">')
    if images:
        lines.append(f'  <meta name="twitter:image" content="{html.escape(images[0][0], quote=True)}">')
        lines.append(f'  <meta name="twitter:image:alt" content="{alt_attr}">')
    return "\n".join(lines) + ("\n" if lines else "")


def schema_image_objects(image_url: str, caption: str = "", credit: str = "", root: Path | None = None) -> list[dict[str, Any]]:
    out = []
    for url, width, height in image_set(image_url, root):
        item: dict[str, Any] = {"@type": "ImageObject", "url": url}
        if width and height:
            item.update({"width": width, "height": height})
        if caption:
            item["caption"] = caption
        if credit:
            item["creditText"] = credit
        out.append(item)
    return out


def rewrite_page_image(page: str, image_url: str, alt: str | None = None, root: Path | None = None) -> str:
    """Replace every og:image, twitter:image and schema image on a rendered page."""
    if alt is None:
        found = _ALT.search(page)
        alt = html.unescape(found.group(1)) if found else ""
    page = _OG_IMAGE_META.sub("", page)
    block = meta_tags(image_url, alt, root)
    for anchor in ('  <meta property="og:url"', "</head>"):
        if anchor in page:
            page = page.replace(anchor, block + anchor, 1)
            break

    def fix_ld(match: re.Match) -> str:
        try:
            data = json.loads(match.group(2))
        except ValueError:
            return match.group(0)
        nodes = data.get("@graph", [data]) if isinstance(data, dict) else data if isinstance(data, list) else []
        changed = False
        for node in nodes:
            if isinstance(node, dict) and "image" in node and node.get("@type") in ("NewsArticle", "Article", "ReportageNewsArticle", "BlogPosting"):
                first = node["image"][0] if isinstance(node["image"], list) and node["image"] else node["image"]
                caption = first.get("caption", "") if isinstance(first, dict) else alt or ""
                credit = first.get("creditText", "") if isinstance(first, dict) else ""
                node["image"] = schema_image_objects(image_url, caption, credit, root)
                changed = True
        if not changed:
            return match.group(0)
        return match.group(1) + json.dumps(data, ensure_ascii=False) + match.group(3)

    return _LD.sub(fix_ld, page)
