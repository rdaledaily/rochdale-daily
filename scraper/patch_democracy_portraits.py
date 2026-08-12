#!/usr/bin/env python3
"""Ensure the homepage Democracy councillor cards render local portraits.

The ward pages already use councillor_photos.json, but the homepage Democracy
panel historically rendered councillor names and votes only. This patch keeps
the inline homepage renderer wired to the same local-only portrait index.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "index.html"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Could not find {label} in index.html")
    return text.replace(old, new, 1)


def main() -> int:
    text = INDEX.read_text(encoding="utf-8")

    old_card = '''      function councillorCard(person) {
        var votes = (person.votes || []).map(voteLine).join("");
        return '<article class="dem-card">' +
          '<div class="dem-mp"><div>' +
            '<div class="who">' + esc(person.name) + "</div>" +
            '<div class="dem-sub">' + esc(person.party || "") +
              (person.ward ? " &middot; " + esc(person.ward) : "") + "</div>" +
          "</div></div>" +
          (votes
            ? '<p style="margin:0 0 6px"><b>Recorded votes</b></p><ul class="dem-list">' + votes + "</ul>"
            : "<p>No recorded vote has named this councillor yet.</p>") +
          "</article>";
      }
'''
    new_card = '''      function councillorCard(person) {
        var votes = (person.votes || []).map(voteLine).join("");
        var photo = (councillorPhotos && councillorPhotos[person.name]) || {};
        var image = String(photo.image_url || "");
        var portrait = image.indexOf("/assets/img/cards/") === 0
          ? '<img loading="lazy" alt="Portrait of ' + esc(person.name) + '" src="' + esc(image) + '">'
          : "";
        return '<article class="dem-card">' +
          '<div class="dem-mp">' + portrait + '<div>' +
            '<div class="who">' + esc(person.name) + "</div>" +
            '<div class="dem-sub">' + esc(person.party || "") +
              (person.ward ? " &middot; " + esc(person.ward) : "") + "</div>" +
          "</div></div>" +
          (votes
            ? '<p style="margin:0 0 6px"><b>Recorded votes</b></p><ul class="dem-list">' + votes + "</ul>"
            : "<p>No recorded vote has named this councillor yet.</p>") +
          "</article>";
      }
'''
    text = replace_once(text, old_card, new_card, "councillor card renderer")

    old_state = '''      var councilVotes = null;
      var activeWard = "";
'''
    new_state = '''      var councilVotes = null;
      var councillorPhotos = null;
      var activeWard = "";
'''
    text = replace_once(text, old_state, new_state, "councillor portrait state")

    old_load = '''        fetch("/council_votes.json", { cache: "no-store" })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (payload) { councilVotes = payload; if (view === "councillors") render(); })
          .catch(function () {});

        fetch("/api/democracy", { cache: "no-store" })
'''
    new_load = '''        fetch("/council_votes.json", { cache: "no-store" })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (payload) { councilVotes = payload; if (view === "councillors") render(); })
          .catch(function () {});

        fetch("/councillor_photos.json", { cache: "no-store" })
          .then(function (r) { return r.ok ? r.json() : null; })
          .then(function (payload) { councillorPhotos = payload; if (view === "councillors") render(); })
          .catch(function () {});

        fetch("/api/democracy", { cache: "no-store" })
'''
    text = replace_once(text, old_load, new_load, "councillor portrait loader")

    INDEX.write_text(text, encoding="utf-8")
    print("Homepage Democracy councillor portraits are wired to councillor_photos.json.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
