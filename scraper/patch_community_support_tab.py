#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "assets/js/homepage-ui.js"

OLD_START = '/* Collapse the large Community support block into a compact tab. */'

def main() -> int:
    text = JS.read_text(encoding="utf-8")
    if OLD_START in text:
        text = text.split(OLD_START, 1)[0].rstrip() + "\n\n"
    text += r'''/* Collapse Community support into a simple arrow tab. */
(function () {
  "use strict";

  function initSupportTab() {
    var section = document.getElementById("support");
    if (!section || section.dataset.rdSupportTab === "1") return;

    var content = section.querySelector(":scope > .wrap");
    if (!content) return;

    section.dataset.rdSupportTab = "1";
    section.classList.add("rd-support-collapsible");

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "rd-support-tab";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", "community-support-content");
    toggle.innerHTML = '<span>Community support</span><span class="rd-support-arrow" aria-hidden="true">&#9662;</span>';

    content.id = "community-support-content";
    content.hidden = true;
    section.insertBefore(toggle, content);

    if (!document.getElementById("community-support-tab-style")) {
      var style = document.createElement("style");
      style.id = "community-support-tab-style";
      style.textContent =
        "#support.rd-support-collapsible{padding:0!important;background:transparent!important;}" +
        "#support .rd-support-tab{width:min(var(--max,1220px),calc(100% - 30px));margin:0 auto;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 18px;border:1px solid var(--line,#dcdcdc);border-left:5px solid var(--accent,#0e7490);background:#fff;color:var(--ink,#1a1a1a);font-family:\"Roboto Condensed\",Arial,sans-serif;font-size:18px;font-weight:900;text-align:left;text-transform:uppercase;box-shadow:0 2px 10px rgba(0,0,0,.06);}" +
        "#support .rd-support-tab:hover,#support .rd-support-tab:focus-visible{background:#f5f7f8;}" +
        "#support .rd-support-arrow{font-size:24px;line-height:1;transition:transform .18s ease;color:var(--accent,#0e7490);}" +
        "#support .rd-support-tab[aria-expanded=\"true\"] .rd-support-arrow{transform:rotate(180deg);}" +
        "#community-support-content{padding-top:22px;padding-bottom:22px;}" +
        "#community-support-content[hidden]{display:none!important;}" +
        "@media(max-width:820px){#support .rd-support-tab{padding:12px 15px;font-size:16px}}";
      document.head.appendChild(style);
    }

    toggle.addEventListener("click", function () {
      var willOpen = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", willOpen ? "true" : "false");
      content.hidden = !willOpen;
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSupportTab, { once: true });
  } else {
    initSupportTab();
  }
})();
'''
    JS.write_text(text, encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
