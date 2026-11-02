"""Tests for scraper/email_intake.py — run: python -m pytest -q scraper/test_email_intake.py"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import zipfile
from email.message import EmailMessage
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import email_intake  # noqa: E402

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def jpeg(size=(800, 600), gps=False) -> bytes:
    image = Image.new("RGB", size, (120, 80, 200))
    out = io.BytesIO()
    if gps:
        exif = Image.Exif()
        exif[0x0110] = "Test phone"
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N"
        gps_ifd[2] = (53.0, 37.0, 0.0)
        image.save(out, "JPEG", exif=exif.tobytes())
    else:
        image.save(out, "JPEG", quality=90)
    return out.getvalue()


def png(size=(120, 40)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (0, 0, 0)).save(out, "PNG")
    return out.getvalue()


def docx(text: str) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", f'<w:document><w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p><w:p><w:r><w:t>Second &amp; last</w:t></w:r></w:p></w:body></w:document>')
    return out.getvalue()


def press_release(photo: bytes, message_id: str = "<pr-1@example.org>") -> bytes:
    m = EmailMessage()
    m["From"] = "Media Team <press@example.org>"
    m["To"] = "news@rochdaledaily.co.uk"
    m["Subject"] = "Café milestone — 10,000 days ✓"
    m["Message-ID"] = message_id
    m["Date"] = "Mon, 02 Nov 2026 11:16:17 +0000"
    m.set_content("Plain body with £5 and “quotes”.\n\nSee attached.", cte="quoted-printable")
    m.add_alternative('<p>HTML body</p><img src="cid:logo1">', subtype="html")
    m.get_payload()[1].add_related(png(), "image", "png", cid="<logo1>", filename="image001.png", disposition="inline")
    m.add_attachment(photo, maintype="image", subtype="jpeg", filename="Story – 4.jpg")
    m.add_attachment(docx("Joined in May 1999"), maintype="application", subtype="vnd.openxmlformats-officedocument.wordprocessingml.document", filename="Release.docx")
    m.add_attachment(b"<script>alert(1)</script>", maintype="text", subtype="html", filename="evil.html")
    return bytes(m)


def test_press_release_lands_complete(tmp_path):
    photo = jpeg()
    result = email_intake.parse_message(press_release(photo), tmp_path)
    assert result["status"] == "written"
    folder = tmp_path / result["folder"]
    record = json.loads((folder / "message.json").read_text())

    assert record["subject"] == "Café milestone — 10,000 days ✓"
    assert "£5 and “quotes”" in record["text"]
    assert record["date"] == "2026-11-02T11:16:17Z"
    assert result["folder"].startswith("inbox/2026/11/20261102T111617Z-cafe-milestone-10-000-days-")

    cards = [a for a in record["attachments"] if a["role"] == "card-photo"]
    assert len(cards) == 1, "only the real photo goes to the card library, not the signature logo"
    assert cards[0]["saved_to"].startswith("assets/img/cards/email-20261102-cafe-milestone-10-000-days-")
    assert (tmp_path / cards[0]["saved_to"]).read_bytes() == photo, "photo without GPS is stored byte-identical"

    logo = next(a for a in record["attachments"] if a["filename"] == "image001.png")
    assert logo["role"] == "image-not-a-photo" and logo["saved_to"].startswith(result["folder"])

    doc = next(a for a in record["attachments"] if a["filename"] == "Release.docx")
    assert doc["text"] == "Joined in May 1999\nSecond & last"

    evil = next(a for a in record["attachments"] if a["filename"] == "evil.html")
    assert evil["saved_to"].endswith("evil.html.txt")
    assert not any(p.endswith((".html", ".htm", ".svg", ".js")) for p in result["files"])


def test_sender_address_never_written(tmp_path):
    result = email_intake.parse_message(press_release(jpeg()), tmp_path)
    blob = "".join((tmp_path / p).read_bytes().decode("utf-8", "ignore") for p in result["files"] if p.endswith(".json"))
    assert "press@example.org" not in blob
    record = result["record"]
    assert record["sender_domain"] == "example.org"
    assert record["sender_sha256"] == hashlib.sha256(b"press@example.org").hexdigest()


def test_gps_location_removed_from_reader_photo(tmp_path):
    result = email_intake.parse_message(press_release(jpeg(gps=True), "<gps@x>"), tmp_path)
    card = next(a for a in result["record"]["attachments"] if a["role"] == "card-photo")
    assert card["note"] == "GPS location removed"
    stored = Image.open(tmp_path / card["saved_to"])
    assert not stored.getexif().get_ifd(0x8825)
    assert stored.size == (800, 600)


def test_same_email_twice_is_a_duplicate(tmp_path):
    raw = press_release(jpeg())
    first = email_intake.parse_message(raw, tmp_path)
    second = email_intake.parse_message(raw, tmp_path)
    assert second == {"status": "duplicate", "folder": first["folder"], "files": []}
    assert len(list((tmp_path / "assets/img/cards").iterdir())) == 1


def test_html_only_email_gets_text(tmp_path):
    m = EmailMessage()
    m["From"] = "x@y.example"
    m["Subject"] = "HTML only"
    m.set_content("<p>Road closed on <b>Yorkshire Street</b>&nbsp;today.</p><p>Second</p>", subtype="html")
    result = email_intake.parse_message(bytes(m), tmp_path)
    assert result["record"]["text"] == "Road closed on Yorkshire Street today.\n\nSecond"


def test_failure_recorded_once_and_not_acknowledged(tmp_path, monkeypatch):
    raw = press_release(jpeg())
    monkeypatch.setattr(email_intake, "ROOT", tmp_path)
    calls = []

    def fake_api(method, key=None):
        calls.append((method, key))
        if key is None:
            return json.dumps({"keys": [{"name": "inbox:raw:20261102T111700Z-00000000-0000-0000-0000-000000000001"}]}).encode()
        return raw

    def boom(*args, **kwargs):
        raise ValueError("synthetic parse failure")

    monkeypatch.setenv("EVENTS_ADMIN_TOKEN", "t")
    monkeypatch.setattr(email_intake, "api", fake_api)
    monkeypatch.setattr(email_intake, "parse_message", boom)
    email_intake.collect(tmp_path)
    email_intake.collect(tmp_path)
    failed = list((tmp_path / "inbox/_failed").iterdir())
    assert len(failed) == 1
    rec = json.loads(failed[0].read_text())
    assert rec["status"] == "intake-failed" and "synthetic parse failure" in rec["error"]
    assert rec["subject"] == "Café milestone — 10,000 days ✓"
    assert json.loads((tmp_path / email_intake.ACK_FILE).read_text()) == []


def test_ack_deletes_only_collected_keys(tmp_path, monkeypatch):
    raw = press_release(jpeg())
    key = "inbox:raw:20261102T111700Z-00000000-0000-0000-0000-000000000002"
    deleted = []

    def fake_api(method, k=None):
        if method == "DELETE":
            deleted.append(k)
            return b"{}"
        if k is None:
            return json.dumps({"keys": [{"name": key}]}).encode()
        return raw

    monkeypatch.setenv("EVENTS_ADMIN_TOKEN", "t")
    monkeypatch.setattr(email_intake, "api", fake_api)
    email_intake.collect(tmp_path)
    assert deleted == [], "nothing deleted before the commit is pushed"
    email_intake.acknowledge(tmp_path)
    assert deleted == [key]
    assert not (tmp_path / email_intake.ACK_FILE).exists()


def test_missing_token_is_a_visible_warning_not_a_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("EVENTS_ADMIN_TOKEN", raising=False)
    assert email_intake.collect(tmp_path) == 0
    assert "::warning title=Email intake not connected::" in capsys.readouterr().out
    assert json.loads((tmp_path / email_intake.ACK_FILE).read_text()) == []
    assert email_intake.acknowledge(tmp_path) == 0
