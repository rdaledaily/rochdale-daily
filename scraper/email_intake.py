#!/usr/bin/env python3
"""Bring every email sent to news@rochdaledaily.co.uk into the repo.

Route: Cloudflare Email Routing -> workers/email-intake/worker.js (forwards to
Gmail, keeps the raw message in private EVENTS_KV, pings this workflow) ->
/api/inbox-raw (admin token) -> this script -> commit -> ack.

    python scraper/email_intake.py collect   # fetch + parse + write files
    (workflow commits and pushes)
    python scraper/email_intake.py ack       # delete committed raw messages

For each message it writes, in the working tree:

    inbox/YYYY/MM/<stamp>-<subject>-<id>/message.json   text + metadata
    inbox/YYYY/MM/<stamp>-<subject>-<id>/<file>         documents, logos, odd formats
    assets/img/cards/email-<date>-<subject>-<id>-<n>.jpg  photos (editor's standing
                                                          choice: every emailed photo
                                                          goes into the card library)

Privacy, because the repo is public: the raw message and its headers are never
written; the sender address is stored only as a SHA-256 plus its domain; GPS
location is stripped from photos. inbox/ is blocked from the website by
functions/inbox/[[path]].js.

A raw message is deleted from KV only after its files are pushed to main
(ack reads the keys collect wrote). A message that cannot be parsed is
recorded once in inbox/_failed/ and its raw copy kept for retry until KV
expires it, so a shortfall is always visible in the repo.
"""

from __future__ import annotations

import hashlib
import html as htmllib
import io
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("RD_REPO_ROOT", "."))
INBOX = Path("inbox")
CARDS = Path("assets/img/cards")
ACK_FILE = Path(os.environ.get("RD_INBOX_ACK_FILE", ".email_intake_ack.json"))
API = os.environ.get("INBOX_API", "https://rochdaledaily.co.uk/api/inbox-raw")

CARD_EXT = {"jpg", "jpeg", "png", "webp"}
CONVERT_TO_JPEG = {"heic", "heif"}  # iPhone photos
MIN_PHOTO_SIDE = 300  # logos and signature banners are smaller than this
DANGEROUS_EXT = {"html", "htm", "xhtml", "svg", "js", "mjs", "php", "shtml"}
MIME_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/pjpeg": "jpg", "image/png": "png",
    "image/webp": "webp", "image/gif": "gif", "image/heic": "heic", "image/heif": "heif",
    "application/pdf": "pdf", "application/msword": "doc", "text/csv": "csv", "text/calendar": "ics",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


# ------------------------------------------------------------------ helpers --

def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    text = re.sub(r"['’]", "", text.lower())
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def sha256(data: bytes | str) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def html_to_text(markup: str) -> str:
    text = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", "", markup or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n\n", text)
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", text)).replace(" ", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def docx_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", "replace")
    xml = xml.replace("<w:tab/>", "\t")
    xml = re.sub(r"<w:br[^>]*/>", "\n", xml)
    xml = xml.replace("</w:p>", "\n")
    text = htmllib.unescape(re.sub(r"<[^>]+>", "", xml))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extension(filename: str | None, content_type: str) -> str:
    match = re.search(r"\.([A-Za-z0-9]{1,8})$", filename or "")
    ext = match.group(1).lower() if match else MIME_EXT.get(content_type, "bin")
    return f"{ext}.txt" if ext in DANGEROUS_EXT else ext


def message_identity(msg: EmailMessage, raw: bytes) -> tuple[str, str]:
    message_id = str(msg.get("message-id") or "").strip()
    full = sha256(message_id) if message_id else sha256(raw)
    return full, full[:12]


def existing_folder(root: Path, short_id: str) -> Path | None:
    for path in (root / INBOX).glob(f"*/*/*-{short_id}/message.json"):
        return path.parent
    return None


def photo_bytes(data: bytes, ext: str) -> tuple[bytes, str] | None:
    """Return (bytes, ext) to store as a card photo, or None if not a photo.

    Photos are images at least MIN_PHOTO_SIDE on the short side. HEIC is
    converted to JPEG (the site cannot show HEIC). Bytes are kept untouched
    unless the picture carries GPS location, which is stripped by re-saving.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    if ext in CONVERT_TO_JPEG:
        try:
            import pillow_heif  # type: ignore
            pillow_heif.register_heif_opener()
        except ImportError:
            return None
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except Exception:
        return None
    if min(image.size) < MIN_PHOTO_SIDE:
        return None
    has_gps = False
    try:
        has_gps = bool(image.getexif().get_ifd(0x8825))
    except Exception:
        pass
    if ext in CONVERT_TO_JPEG or has_gps:
        from PIL import ImageOps
        image = ImageOps.exif_transpose(image).convert("RGB")
        out = io.BytesIO()
        image.save(out, "JPEG", quality=92, optimize=True)  # no exif written
        return out.getvalue(), "jpg"
    return data, "jpg" if ext == "jpeg" else ext


# ------------------------------------------------------------------- parse --

def parse_message(raw: bytes, root: Path = ROOT, received_at: datetime | None = None) -> dict[str, Any]:
    """Write one message's files under root. Returns a summary dict."""
    msg: EmailMessage = BytesParser(policy=policy.default).parsebytes(raw)  # type: ignore[assignment]
    full_id, short_id = message_identity(msg, raw)

    found = existing_folder(root, short_id)
    if found:
        return {"status": "duplicate", "folder": found.relative_to(root).as_posix(), "files": []}

    try:
        date = parsedate_to_datetime(str(msg.get("date"))).astimezone(timezone.utc)
    except Exception:
        date = received_at or datetime.now(timezone.utc)
    stamp = date.strftime("%Y%m%dT%H%M%SZ")
    subject = str(msg.get("subject") or "").strip() or "(no subject)"
    subject_slug = slugify(subject)[:60].rstrip("-") or "no-subject"
    folder = INBOX / stamp[:4] / stamp[4:6] / f"{stamp}-{subject_slug}-{short_id}"

    sender = parseaddr(str(msg.get("from") or ""))[1].strip().lower()

    body_part = msg.get_body(preferencelist=("plain", "html"))
    text = ""
    if body_part is not None:
        content = body_part.get_content()
        text = html_to_text(content) if body_part.get_content_type() == "text/html" else content
    text = text.replace("\r\n", "\n").strip()

    files: list[tuple[Path, bytes]] = []
    attachments: list[dict[str, Any]] = []
    used = {"message.json"}
    card_n = 0
    for part in msg.walk():
        if part.is_multipart() or part is body_part:
            continue
        ctype = part.get_content_type()
        filename = part.get_filename()
        disposition = part.get_content_disposition()
        if ctype.startswith("text/") and not filename and disposition != "attachment":
            continue  # the other alternative of the body
        if ctype == "message/rfc822":
            continue
        data = part.get_payload(decode=True) or b""
        if not data:
            continue
        ext = extension(filename, ctype)
        entry: dict[str, Any] = {"filename": filename, "content_type": ctype, "bytes": len(data), "sha256": sha256(data)}

        photo = photo_bytes(data, ext) if ctype.startswith("image/") or ext in CARD_EXT | CONVERT_TO_JPEG else None
        if photo:
            card_n += 1
            stored, card_ext = photo
            path = CARDS / f"email-{stamp[:8]}-{subject_slug[:40].rstrip('-')}-{short_id}-{card_n}.{card_ext}"
            files.append((path, stored))
            entry.update({"saved_to": path.as_posix(), "role": "card-photo"})
            if stored != data:
                entry["note"] = "converted to JPEG" if ext in CONVERT_TO_JPEG else "GPS location removed"
            attachments.append(entry)
            continue

        base = slugify(re.sub(r"\.[^.]+$", "", filename or "")) or ctype.split("/")[0] or "file"
        name = f"{base}.{ext}"
        n = 2
        while name in used:
            name, n = f"{base}-{n}.{ext}", n + 1
        used.add(name)
        path = folder / name
        files.append((path, data))
        entry.update({"saved_to": path.as_posix(), "role": "image-not-a-photo" if ctype.startswith("image/") else "document"})
        if ext == "docx":
            try:
                entry["text"] = docx_text(data)
            except Exception as error:  # a broken document is named, not hidden
                entry["text_error"] = str(error)
        attachments.append(entry)

    in_reply_to = str(msg.get("in-reply-to") or "").strip()
    record = {
        "version": 1,
        "id": short_id,
        "message_sha256": full_id,
        "received_at": (received_at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": date.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "subject": subject,
        "sender_domain": sender.rsplit("@", 1)[-1] if "@" in sender else None,
        "sender_sha256": sha256(sender) if sender else None,
        "in_reply_to_sha256": sha256(in_reply_to) if in_reply_to else None,
        "text": text,
        "attachments": attachments,
        "status": "received",
    }
    files.insert(0, (folder / "message.json", (json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8")))
    for rel, data in files:
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return {"status": "written", "folder": folder.as_posix(), "files": [p.as_posix() for p, _ in files], "record": record}


def record_failure(root: Path, key: str, raw: bytes, error: Exception) -> Path:
    try:
        subject = str(BytesParser(policy=policy.default).parsebytes(raw, headersonly=True).get("subject") or "")
    except Exception:
        subject = ""
    name = re.sub(r"[^A-Za-z0-9TZ-]", "", key.rsplit(":", 1)[-1])
    path = root / INBOX / "_failed" / f"{name}.json"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "kv_key": key, "subject": subject, "bytes": len(raw), "sha256": sha256(raw),
            "error": f"{type(error).__name__}: {error}", "status": "intake-failed",
            "note": "Raw copy kept in EVENTS_KV for retry until it expires (30 days). The email itself reached Gmail.",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# --------------------------------------------------------------------- API --

def api(method: str, key: str | None = None) -> bytes:
    token = os.environ["EVENTS_ADMIN_TOKEN"]
    url = API + (f"?key={urllib.parse.quote(key, safe='')}" if key else "")
    request = urllib.request.Request(url, method=method, headers={"x-admin-token": token, "User-Agent": "rochdale-daily-email-intake"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


NOT_CONFIGURED = (
    "::warning title=Email intake not connected::EVENTS_ADMIN_TOKEN is not set as a repository secret, "
    "so emails waiting in Cloudflare cannot be collected. Add it under Settings -> Secrets and variables -> "
    "Actions, with the same value as the EVENTS_ADMIN_TOKEN on the Cloudflare Pages project."
)


def collect(root: Path = ROOT) -> int:
    if not os.environ.get("EVENTS_ADMIN_TOKEN"):
        print(NOT_CONFIGURED)
        (root / ACK_FILE).write_text("[]", encoding="utf-8")
        return 0
    keys = [k["name"] for k in json.loads(api("GET")).get("keys", [])]
    print(f"{len(keys)} message(s) waiting")
    ack: list[str] = []
    failures = 0
    for key in keys:
        raw = api("GET", key)
        try:
            stamp = re.match(r"inbox:raw:(\d{8}T\d{6}Z)", key)
            received = datetime.strptime(stamp.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) if stamp else None
            result = parse_message(raw, root, received)
        except Exception as error:
            failures += 1
            path = record_failure(root, key, raw, error)
            print(f"::warning title=Email intake shortfall::{key} could not be parsed ({error}); recorded in {path.relative_to(root)}")
            continue
        print(f"{result['status']}: {result['folder']} ({len(result['files'])} file(s))")
        ack.append(key)
    (root / ACK_FILE).write_text(json.dumps(ack), encoding="utf-8")
    print(f"ready to acknowledge {len(ack)}; shortfalls {failures}")
    return 0


def acknowledge(root: Path = ROOT) -> int:
    path = root / ACK_FILE
    keys = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    for key in keys:
        api("DELETE", key)
        print(f"acknowledged {key}")
    path.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "collect":
        raise SystemExit(collect())
    if command == "ack":
        raise SystemExit(acknowledge())
    if command == "parse":  # local use: parse one .eml file into the working tree
        print(json.dumps({k: v for k, v in parse_message(Path(sys.argv[2]).read_bytes()).items() if k != "record"}, indent=2))
        raise SystemExit(0)
    raise SystemExit("usage: email_intake.py collect|ack|parse <file.eml>")
