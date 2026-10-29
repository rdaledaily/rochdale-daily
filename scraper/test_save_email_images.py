"""Tests for scraper/save_email_images.py.

The emails are built the way Gmail, Outlook and Apple Mail actually send them:
attachments named by Content-Disposition (including RFC 2231 encoded names),
names only in Content-Type, inline signature logos with a Content-ID, and a
press release forwarded as message/rfc822.
"""
from __future__ import annotations

import base64
import io
import json
import sys
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.message import MIMEMessage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import save_email_images as sei  # noqa: E402


def jpeg(size=(3000, 2000), colour=(30, 120, 60), exif_orientation=None, gps=False) -> bytes:
    img = Image.new("RGB", size, colour)
    exif = Image.Exif()
    if exif_orientation:
        exif[0x0112] = exif_orientation
    if gps:
        exif[0x8825] = {1: "N", 2: (53.0, 37.0, 0.0), 3: "W", 4: (2.0, 9.0, 0.0)}
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif.tobytes(), quality=90)
    return out.getvalue()


def png(size=(1200, 800), alpha=False) -> bytes:
    img = Image.new("RGBA" if alpha else "RGB", size, (200, 200, 200, 128) if alpha else (200, 200, 200))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def press_release(images, subject="Cricket Connect", sender="Helen <helen@friedeggmedia.co.uk>") -> bytes:
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = "news@rochdaledaily.co.uk"
    msg["Subject"] = subject
    body = MIMEMultipart("alternative")
    body.attach(MIMEText("Hello, pics are attached.", "plain"))
    body.attach(MIMEText("<p>Hello, pics are attached.</p>", "html"))
    msg.attach(body)
    for item in images:
        msg.attach(item)
    return msg.as_bytes()


def attachment(data: bytes, filename: str, subtype="jpeg", rfc2231=False, name_only=False):
    part = MIMEImage(data, _subtype=subtype)
    if name_only:
        part.set_param("name", filename)
    elif rfc2231:
        part.add_header("Content-Disposition", "attachment", filename=("utf-8", "", filename))
    else:
        part.add_header("Content-Disposition", "attachment", filename=filename)
    return part


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / "assets/img/cards").mkdir(parents=True)
    (tmp_path / "assets/img/cards/credits.json").write_text('{"existing": "Rochdale AFC / Used with permission"}')
    return tmp_path


def run_one(root: Path, raw: bytes, key="inbox-raw:1"):
    return sei.run(root, [(key, "2026-10-29T11:10:37Z", raw)], [])


def saved_files(root: Path) -> list[Path]:
    return sorted((root / "assets/img/cards").glob(f"*{sei.NAME_SUFFIX}.*"))


def test_saves_every_attached_picture_with_hash_names(root):
    raw = press_release([
        attachment(jpeg(), "Image (4).jpeg"),
        attachment(png(), "Screenshot 2025-10-16 091517.png", subtype="png"),
        attachment(jpeg(colour=(1, 2, 3)), "Burnage.jpg"),
    ])
    result = run_one(root, raw)
    assert result["totals"]["saved"] == 3
    files = saved_files(root)
    assert len(files) == 3
    for path in files:
        stem = path.stem
        assert stem.endswith("-email-photo")
        assert len(stem.split("-")[0]) == 16
        assert "burnage" not in path.name.lower()
    index = json.loads((root / "reports/email_images.json").read_text())
    assert [i["original_filename"] for i in index["images"]] == [
        "Image (4).jpeg", "Screenshot 2025-10-16 091517.png", "Burnage.jpg"]
    assert all(i["sender_domain"] == "friedeggmedia.co.uk" for i in index["images"])
    assert all("helen" not in json.dumps(i).lower() for i in index["images"])  # no personal address
    assert result["acked"] == ["inbox-raw:1"]


def test_saved_names_never_match_a_headline(root):
    """The library matches filenames against headlines; ours must never match."""
    import ensure_article_images as eai

    raw = press_release([attachment(jpeg(), "Burnage.jpg"), attachment(jpeg(colour=(9, 9, 9)), "email photo.jpg")])
    run_one(root, raw)
    for title in ("Burnage Academy cricket hub opens", "Email photo competition for Rochdale schools",
                  "Cricket Connect brings £300k to Greater Manchester"):
        article = {"title": title, "slug": title.lower().replace(" ", "-"), "category": "sport"}
        assert eai.choose_filename_match(article, root) is None
        for path in saved_files(root):
            assert eai.filename_match_score(article, path) < 0


def test_rfc2231_and_content_type_only_names(root):
    raw = press_release([
        attachment(jpeg(), "Café opening – Littleborough.jpg", rfc2231=True),
        attachment(jpeg(colour=(4, 5, 6)), "outlook-style.jpg", name_only=True),
    ])
    run_one(root, raw)
    names = [i["original_filename"] for i in json.loads((root / "reports/email_images.json").read_text())["images"]]
    assert names == ["Café opening – Littleborough.jpg", "outlook-style.jpg"]


def test_rotates_strips_gps_and_scales(root):
    raw = press_release([attachment(jpeg(size=(3000, 2000), exif_orientation=6, gps=True), "phone.jpg")])
    run_one(root, raw)
    (path,) = saved_files(root)
    img = Image.open(path)
    assert img.size == (1333, 2000)  # turned upright (portrait) and scaled to 2000px
    exif = img.getexif()
    assert 0x8825 not in exif and 0x0112 not in exif
    assert b"Exif" not in path.read_bytes()[:200]


def test_skips_logos_and_pixels_but_records_why(root):
    logo = MIMEImage(png(size=(120, 40)), _subtype="png")
    logo.add_header("Content-ID", "<sig-logo>")
    logo.add_header("Content-Disposition", "inline", filename="logo.png")
    raw = press_release([logo, attachment(jpeg(), "real.jpg")])
    result = run_one(root, raw)
    assert result["totals"] == {"emails": 1, "found": 2, "saved": 1, "duplicate": 0, "skipped": 1, "capture_errors": 0}
    index = json.loads((root / "reports/email_images.json").read_text())
    assert index["skipped"][0]["original_filename"] == "logo.png"
    assert "signature logo" in index["skipped"][0]["reason"]


def test_inline_photos_in_body_are_saved(root):
    related = MIMEMultipart("related")
    related.attach(MIMEText('<p>See <img src="cid:pic1"></p>', "html"))
    pic = MIMEImage(jpeg(), _subtype="jpeg")
    pic.add_header("Content-ID", "<pic1>")
    related.attach(pic)
    msg = MIMEMultipart("mixed")
    msg["From"] = "tips@example.org"
    msg["Subject"] = "Inline"
    msg.attach(related)
    result = run_one(root, msg.as_bytes())
    assert result["totals"]["saved"] == 1


def test_forwarded_press_release_keeps_its_pictures(root):
    inner = press_release([attachment(jpeg(), "forwarded.jpg")], sender="press@rochdale.gov.uk")
    outer = MIMEMultipart("mixed")
    outer["From"] = "Reader <reader@gmail.com>"
    outer["Subject"] = "Fwd: council release"
    outer.attach(MIMEText("FYI", "plain"))
    from email import message_from_bytes
    outer.attach(MIMEMessage(message_from_bytes(inner)))
    result = run_one(root, outer.as_bytes())
    assert result["totals"]["saved"] == 1


def test_octet_stream_with_image_name_is_saved(root):
    part = MIMEApplication(jpeg(), _subtype="octet-stream")
    part.add_header("Content-Disposition", "attachment", filename="DSC_0042.JPG")
    result = run_one(root, press_release([part]))
    assert result["totals"]["saved"] == 1


def test_non_images_and_text_emails_are_ignored(root):
    pdf = MIMEApplication(b"%PDF-1.4 fake", _subtype="pdf")
    pdf.add_header("Content-Disposition", "attachment", filename="release.pdf")
    plain = MIMEText("just text")
    plain["From"] = "a@b.co.uk"
    plain["Subject"] = "no pics"
    result = sei.run(root, [("k1", "", press_release([pdf])), ("k2", "", plain.as_bytes())], [])
    assert result["totals"]["found"] == 0
    assert result["acked"] == ["k1", "k2"]  # cleared so they are not re-read forever
    assert saved_files(root) == []


def test_unreadable_and_heic_are_recorded_not_saved(root, monkeypatch):
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 5000
    raw = press_release([attachment(b"\xff\xd8\xff" + b"junk" * 2000, "broken.jpg"),
                         attachment(heic, "IMG_1234.HEIC", subtype="heic")])
    result = run_one(root, raw)
    assert result["totals"]["saved"] == 0  # both are corrupt, with or without the HEIC reader
    assert result["totals"]["skipped"] == 2
    reasons = [s["reason"] for s in json.loads((root / "reports/email_images.json").read_text())["skipped"]]
    assert any("not a readable image" in r or "could not be decoded" in r for r in reasons)


def test_same_picture_twice_is_stored_once(root):
    pic = jpeg()
    sei.run(root, [("k1", "", press_release([attachment(pic, "a.jpg")]))], [])
    result = sei.run(root, [("k2", "", press_release([attachment(pic, "b.jpg")], subject="Again"))], [])
    assert result["totals"]["duplicate"] == 1
    assert len(saved_files(root)) == 1
    index = json.loads((root / "reports/email_images.json").read_text())
    assert len(index["images"]) == 2 and index["images"][1]["duplicate_of_earlier_email"] is True


def test_transparent_png_stays_png_and_credit_is_written(root):
    run_one(root, press_release([attachment(png(alpha=True), "badge.png", subtype="png")], sender="x@rightagency.co.uk"))
    (path,) = saved_files(root)
    assert path.suffix == ".png"
    credits = json.loads((root / "assets/img/cards/credits.json").read_text())
    assert credits[path.stem] == "Supplied by rightagency.co.uk"
    assert credits["existing"] == "Rochdale AFC / Used with permission"  # untouched


def test_capture_errors_are_reported_and_cleared(root):
    errors = [{"key": "inbox-err:1", "meta": {"e": "store failed: boom", "s": "Big email", "d": "x.org", "r": "t"}}]
    result = sei.run(root, [], errors)
    assert result["acked"] == ["inbox-err:1"]
    index = json.loads((root / "reports/email_images.json").read_text())
    assert index["capture_errors"][0]["reason"] == "store failed: boom"


def test_nothing_waiting_writes_nothing(root):
    result = sei.run(root, [], [])
    assert result["acked"] == []
    assert not (root / "reports/email_images.json").exists()


def test_saved_file_is_valid_for_the_pipeline(root):
    import ensure_article_images as eai

    run_one(root, press_release([attachment(jpeg(), "x.jpg")]))
    (path,) = saved_files(root)
    rel = path.relative_to(root).as_posix()
    assert eai.valid_cards_image(root, rel)
    assert not eai.is_generated_card(path)
