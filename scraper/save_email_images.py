"""Save every image emailed to news@rochdaledaily.co.uk into assets/img/cards/.

The rd-news-inbox Worker forwards each email to the editor and keeps a raw copy
in Cloudflare KV. This script, run by .github/workflows/email-images.yml:

  1. lists the waiting emails through /api/inbox-images (admin token),
  2. pulls each one and finds every image in it with Python's own email parser
     (attachments, inline pictures, and pictures inside forwarded emails),
  3. writes each picture to assets/img/cards/<hash>-email-photo.<ext>,
  4. records it in reports/email_images.json and credits it in credits.json,
  5. writes the KV keys it has finished with to email_images_ack.json, which
     the workflow deletes from KV only after the commit has been pushed.

Why the file is named by content hash and not by the sender's filename:
assets/img/cards/ is a search library. A file's name IS the term it matches in
headlines (story_image.py, ensure_article_images.py), so "Burnage.jpg" would be
put on every story that mentions Burnage. "<hash>-email-photo.jpg" can never
match a headline, so a saved picture is only ever used where it is put on
purpose: by its exact path in an article's image_url, or by the editor renaming
it to a story's slug. The original filename, sender domain and subject are kept
in reports/email_images.json so the right picture is easy to find.

Pictures are re-encoded on the way in: rotated upright, metadata (including GPS
location) removed, and scaled to at most 2000px on the long edge. Pictures
smaller than 200px either way are skipped as icons, tracking pixels and email
signature logos; each skip is recorded with its reason, nothing vanishes.

Usage:
  python scraper/save_email_images.py                # live, from SITE_BASE
  python scraper/save_email_images.py --eml a.eml    # local test on saved emails
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageOps, UnidentifiedImageError

try:  # iPhone photos arrive as HEIC; Pillow cannot read them without this.
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    HEIF_READABLE = True
except Exception:  # pragma: no cover - depends on the runner
    HEIF_READABLE = False

CARDS_DIR = Path("assets/img/cards")
CREDITS_PATH = CARDS_DIR / "credits.json"
INDEX_PATH = Path("reports/email_images.json")
ACK_PATH = Path("email_images_ack.json")
SUMMARY_PATH = Path("email_images_summary.txt")

NAME_SUFFIX = "-email-photo"
MAX_EDGE = 2000
MIN_EDGE = 200
JPEG_QUALITY = 88
KEEP_SKIPS = 300
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff")

Image.MAX_IMAGE_PIXELS = 120_000_000  # well above any camera; stops decompression bombs


# ---------------------------------------------------------------- parsing --

def _filename(part: EmailMessage) -> str:
    name = part.get_filename() or part.get_param("name", header="content-type") or ""
    if isinstance(name, tuple):  # RFC 2231 tuple form from older policies
        name = name[2]
    return str(name).strip()


def extract_images(raw: bytes) -> list[dict[str, Any]]:
    """Every picture in an email, in the order the sender attached them.

    walk() descends into forwarded emails (message/rfc822), so a reader
    forwarding a press release does not lose its pictures.
    """
    message = BytesParser(policy=policy.default).parsebytes(raw)
    found: list[dict[str, Any]] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        ctype = part.get_content_type().lower()
        filename = _filename(part)
        if not (ctype.startswith("image/") or filename.lower().endswith(IMAGE_EXTENSIONS)):
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception:
            data = None
        if not data:
            continue
        found.append({
            "bytes": data,
            "filename": filename,
            "declared_type": ctype,
            "inline": (part.get_content_disposition() == "inline") or bool(part.get("Content-ID")),
        })
    return found


def email_details(raw: bytes) -> dict[str, str]:
    message = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
    address = parseaddr(str(message.get("From", "")))[1]
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    return {"subject": str(message.get("Subject", "")).strip(), "sender_domain": domain}


# ------------------------------------------------------------ re-encoding --

class Skip(Exception):
    """A picture that is deliberately not saved; the message is the reason."""


def prepare(data: bytes) -> tuple[str, bytes, int, int]:
    """Decode, rotate upright, strip metadata, scale. Returns (ext, bytes, w, h)."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except UnidentifiedImageError:
        head = data[4:12]
        if b"ftypheic" in head or b"ftypmif1" in head or b"ftypheix" in head:
            raise Skip("HEIC photo, but the HEIC reader is not installed") from None
        raise Skip("not a readable image") from None
    except Image.DecompressionBombError:
        raise Skip("image dimensions are implausibly large") from None
    except Exception as error:
        raise Skip(f"image could not be decoded ({type(error).__name__})") from None

    if getattr(img, "is_animated", False):
        img.seek(0)
    img = ImageOps.exif_transpose(img)
    width, height = img.size
    if width < MIN_EDGE or height < MIN_EDGE:
        raise Skip(f"{width}x{height}: icon, tracking pixel or signature logo")

    has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
    if max(width, height) > MAX_EDGE:
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)

    out = io.BytesIO()
    if has_alpha:
        img = img.convert("RGBA")
        img.save(out, "PNG", optimize=True)  # no exif/info passed: metadata stripped
        ext = "png"
    else:
        img = img.convert("RGB")
        img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
        ext = "jpg"
    return ext, out.getvalue(), img.size[0], img.size[1]


# ----------------------------------------------------------------- saving --

def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def existing_file_for(root: Path, digest: str) -> Path | None:
    for ext in ("jpg", "png"):
        candidate = root / CARDS_DIR / f"{digest[:16]}{NAME_SUFFIX}.{ext}"
        if candidate.exists():
            return candidate
    return None


def save_email(root: Path, raw: bytes, *, email_key: str, received_at: str,
               index: dict[str, Any], credits: dict[str, str], now: str) -> dict[str, int]:
    """Save every picture in one email. Mutates index and credits."""
    details = email_details(raw)
    counts = {"found": 0, "saved": 0, "duplicate": 0, "skipped": 0}
    for position, image in enumerate(extract_images(raw), start=1):
        counts["found"] += 1
        digest = hashlib.sha256(image["bytes"]).hexdigest()
        record = {
            "sha256": digest,
            "original_filename": image["filename"],
            "position": position,
            "inline": image["inline"],
            "sender_domain": details["sender_domain"],
            "subject": details["subject"][:300],
            "received_at": received_at,
            "email_key": email_key,
            "saved_at": now,
        }
        try:
            existing = existing_file_for(root, digest)
            if existing is not None:
                counts["duplicate"] += 1
                record["file"] = existing.relative_to(root).as_posix()
                record["duplicate_of_earlier_email"] = True
                index["images"].append(record)
                continue
            ext, data, width, height = prepare(image["bytes"])
        except Skip as reason:
            counts["skipped"] += 1
            record["reason"] = str(reason)
            index["skipped"].append(record)
            continue
        path = root / CARDS_DIR / f"{digest[:16]}{NAME_SUFFIX}.{ext}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        record.update({"file": path.relative_to(root).as_posix(), "width": width, "height": height})
        index["images"].append(record)
        if details["sender_domain"]:
            credits.setdefault(path.stem, f"Supplied by {details['sender_domain']}")
        counts["saved"] += 1
    return counts


def run(root: Path, emails: Iterable[tuple[str, str, bytes]], errors: list[dict[str, Any]]) -> dict[str, Any]:
    """emails: (kv_key, received_at, raw bytes). Returns the run summary."""
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    index = _load_json(root / INDEX_PATH, {})
    if not isinstance(index, dict):
        index = {}
    index.setdefault("version", 1)
    index.setdefault("images", [])
    index.setdefault("skipped", [])
    index.setdefault("capture_errors", [])
    credits = _load_json(root / CREDITS_PATH, {})
    if not isinstance(credits, dict):
        credits = {}
    credits_before = dict(credits)

    totals = {"emails": 0, "found": 0, "saved": 0, "duplicate": 0, "skipped": 0, "capture_errors": 0}
    acked: list[str] = []
    for key, received_at, raw in emails:
        counts = save_email(root, raw, email_key=key, received_at=received_at,
                            index=index, credits=credits, now=now)
        totals["emails"] += 1
        for name, value in counts.items():
            totals[name] += value
        acked.append(key)
    for error in errors:
        meta = error.get("meta") or {}
        index["capture_errors"].append({
            "reason": meta.get("e", ""), "subject": meta.get("s", ""),
            "sender_domain": meta.get("d", ""), "at": meta.get("r", ""), "reported_at": now,
        })
        totals["capture_errors"] += 1
        acked.append(error["key"])

    index["skipped"] = index["skipped"][-KEEP_SKIPS:]
    index["capture_errors"] = index["capture_errors"][-KEEP_SKIPS:]
    if acked:
        index["last_run"] = {"at": now, **totals}
        _write_json(root / INDEX_PATH, index)
    if credits != credits_before:
        _write_json(root / CREDITS_PATH, dict(sorted(credits.items())))
    return {"totals": totals, "acked": acked}


# --------------------------------------------------------------- network --

def _call(base: str, token: str, query: str = "", payload: Any = None, raw: bool = False) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"{base}/api/inbox-images{query}", data=data,
        method="POST" if payload is not None else "GET",
        headers={"x-admin-token": token, "Content-Type": "application/json",
                 "User-Agent": "RochdaleDaily-email-images/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = response.read()
    return body if raw else json.loads(body.decode("utf-8"))


def live(root: Path) -> int:
    base = os.environ.get("SITE_BASE", "https://rochdaledaily.co.uk").rstrip("/")
    token = os.environ.get("INBOX_ADMIN_TOKEN", "")
    if not token:
        # A visible warning on every run, not a red one: the lane is waiting on
        # setup, not broken. The annotation names exactly what is missing.
        print("::warning::EVENTS_ADMIN_TOKEN is not set as a repository secret, so no email images can be collected.")
        return 0
    listing = _call(base, token)
    waiting = listing.get("emails") or []
    errors = listing.get("errors") or []
    print(f"waiting emails: {len(waiting)}, capture errors: {len(errors)}")

    def pulled() -> Iterable[tuple[str, str, bytes]]:
        for item in waiting:
            key = item["key"]
            try:
                raw = _call(base, token, "?key=" + urllib.parse.quote(key, safe=""), raw=True)
            except Exception as error:  # left in KV for the next run
                print(f"::warning::could not fetch {key}: {error}")
                continue
            yield key, (item.get("meta") or {}).get("r", ""), raw

    result = run(root, pulled(), errors)
    _write_json(root / ACK_PATH, result["acked"])
    summary = ", ".join(f"{k} {v}" for k, v in result["totals"].items())
    (root / SUMMARY_PATH).write_text(summary + "\n", encoding="utf-8")
    print(summary)
    for error in errors:
        meta = error.get("meta") or {}
        print(f"::warning::inbox capture error for \"{meta.get('s', '')}\": {meta.get('e', '')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", default=".")
    parser.add_argument("--eml", nargs="*", help="process local .eml files instead of the live inbox")
    args = parser.parse_args(argv)
    root = Path(args.root)
    if args.eml:
        emails = [(f"local:{p}", "", Path(p).read_bytes()) for p in args.eml]
        result = run(root, emails, [])
        print(json.dumps(result["totals"]))
        return 0
    return live(root)


if __name__ == "__main__":
    sys.exit(main())
