/* Homepage-only progressive disclosure for Latest news.
 * Desktop shows 12 stories as a compact card grid. A full-width advertising
 * position and a compact Read more control sit inside that same grid, so they
 * cannot be pushed into the weather/sidebar layout. Mobile is untouched.
 */
(function () {
  "use strict";

  var INITIAL = 12;
  var STEP = 12;
  var visible = INITIAL;
  var grid = document.getElementById("news-grid");
  if (!grid) return;

  var style = document.createElement("style");
  style.id = "latest-news-desktop-layout";
  style.textContent =
    "@media (min-width:821px){" +
      "#news-grid.rd-latest-horizontal{" +
        "display:grid!important;" +
        "grid-template-columns:repeat(4,minmax(0,1fr))!important;" +
        "gap:22px!important;" +
        "align-items:stretch!important;" +
      "}" +
      "#news-grid.rd-latest-horizontal>article," +
      "#news-grid.rd-latest-horizontal>.card," +
      "#news-grid.rd-latest-horizontal>a{" +
        "width:auto!important;" +
        "max-width:none!important;" +
        "margin:0!important;" +
      "}" +
      "#news-grid.rd-latest-horizontal>.rd-latest-hidden{" +
        "display:none!important;" +
      "}" +
      "#news-grid .latest-news-ad{" +
        "grid-column:1/-1!important;" +
        "display:flex;" +
        "align-items:center;" +
        "justify-content:center;" +
        "width:100%!important;" +
        "min-width:0!important;" +
        "min-height:180px;" +
        "max-height:280px;" +
        "margin:8px 0 0!important;" +
        "background:#f3f3f3;" +
        "border:1px solid #d6d6d6;" +
        "overflow:hidden;" +
        "position:relative;" +
      "}" +
      "#news-grid .latest-news-ad:not(.ad-live)::before{" +
        "content:\"Advertisement\";" +
        "font:700 11px/1 var(--font-body);" +
        "letter-spacing:.12em;" +
        "text-transform:uppercase;" +
        "color:#777;" +
      "}" +
      "#news-grid .latest-news-more{" +
        "grid-column:1/-1!important;" +
        "justify-self:center!important;" +
        "align-self:start!important;" +
        "display:block!important;" +
        "width:auto!important;" +
        "height:auto!important;" +
        "min-width:180px!important;" +
        "min-height:0!important;" +
        "max-width:280px!important;" +
        "margin:0 auto!important;" +
        "padding:12px 24px!important;" +
        "position:static!important;" +
        "inset:auto!important;" +
        "border:2px solid var(--accent,#0e7490)!important;" +
        "background:#fff!important;" +
        "color:var(--accent,#0e7490)!important;" +
        "font-family:var(--font-display)!important;" +
        "font-size:16px!important;" +
        "line-height:1.2!important;" +
        "font-weight:900!important;" +
        "text-transform:uppercase!important;" +
        "cursor:pointer;" +
      "}" +
      "#news-grid .latest-news-more:hover,#news-grid .latest-news-more:focus-visible{" +
        "background:var(--accent,#0e7490)!important;" +
        "color:#fff!important;" +
      "}" +
    "}" +
    "@media (min-width:821px) and (max-width:1080px){" +
      "#news-grid.rd-latest-horizontal{grid-template-columns:repeat(3,minmax(0,1fr))!important;}" +
    "}";
  document.head.appendChild(style);

  var advert = document.createElement("div");
  advert.id = "latest-news-ad";
  advert.className = "ad-slot ad-slot-billboard latest-news-ad";
  advert.setAttribute("data-ad-slot", "home-billboard");
  advert.setAttribute("role", "complementary");
  advert.setAttribute("aria-label", "Advertisement");

  var button = document.createElement("button");
  button.type = "button";
  button.id = "latest-news-more";
  button.className = "latest-news-more";
  button.textContent = "Read more";
  button.hidden = true;

  grid.appendChild(advert);
  grid.appendChild(button);

  if (typeof window.rdFillAds === "function") window.rdFillAds();

  function isDesktop() {
    return window.matchMedia("(min-width: 821px)").matches;
  }

  function cards() {
    return Array.prototype.slice.call(grid.children).filter(function (node) {
      return node.nodeType === 1 && node !== advert && node !== button;
    });
  }

  function setCardVisible(item, shouldShow) {
    item.classList.toggle("rd-latest-hidden", !shouldShow);
    if (shouldShow) {
      item.removeAttribute("hidden");
    } else {
      item.setAttribute("hidden", "");
    }
  }

  function apply() {
    var items = cards();
    if (!isDesktop()) {
      grid.classList.remove("rd-latest-horizontal");
      items.forEach(function (item) { setCardVisible(item, true); });
      advert.hidden = true;
      button.hidden = true;
      return;
    }

    grid.classList.add("rd-latest-horizontal");
    items.forEach(function (item, index) {
      setCardVisible(item, index < visible);
    });

    var remaining = Math.max(0, items.length - visible);
    advert.hidden = false;
    button.hidden = remaining === 0;
    button.textContent = "Read more";
    button.setAttribute(
      "aria-label",
      "Read more Latest news stories" + (remaining ? " (" + remaining + " remaining)" : "")
    );
  }

  button.addEventListener("click", function (event) {
    event.preventDefault();
    event.stopPropagation();

    var items = cards();
    if (!items.length) return;

    var nextVisible = Math.min(items.length, visible + STEP);
    for (var i = visible; i < nextVisible; i += 1) {
      setCardVisible(items[i], true);
    }
    visible = nextVisible;
    apply();
  });

  var observer = new MutationObserver(function (mutations) {
    var changed = mutations.some(function (mutation) {
      return Array.prototype.some.call(mutation.addedNodes, function (node) {
        return node.nodeType === 1 && node !== advert && node !== button;
      }) || Array.prototype.some.call(mutation.removedNodes, function (node) {
        return node.nodeType === 1 && node !== advert && node !== button;
      });
    });
    if (changed) {
      visible = INITIAL;
      if (!grid.contains(advert)) grid.appendChild(advert);
      if (!grid.contains(button)) grid.appendChild(button);
      apply();
      if (typeof window.rdFillAds === "function") window.rdFillAds();
    }
  });
  observer.observe(grid, { childList: true });

  window.addEventListener("resize", apply);
  apply();
})();

/* Collapse Community support while preserving its h2 -> h3 heading hierarchy. */
(function () {
  "use strict";

  /* Disclosure sections. Democracy and Community support are reference
     material rather than news, so they sit folded with a plain instruction on
     the tab -- "Open to explore", "Open for resources" -- and unfold on a
     click. The same code drives both so they look and behave identically.

     Two things the old Community-support-only version got wrong, both fixed:
       - it hid the content with the `hidden` attribute, which any stylesheet
         rule with display:grid overrides, so the "closed" tab sat above fully
         visible content;
       - Democracy had no tab at all, just four buttons over an empty panel. */
  var DISCLOSURES = [
    { id: "support",   heading: "support-title",   label: "Community support", hint: "Open for resources" },
    { id: "democracy", heading: "democracy-title", label: "Democracy",         hint: "Open to explore" }
  ];

  function installDisclosureStyle() {
    if (document.getElementById("rd-disclosure-style")) return;
    var style = document.createElement("style");
    style.id = "rd-disclosure-style";
    style.textContent =
      ".rd-disclosure{padding:0!important;background:transparent!important;}" +
      ".rd-disclosure .rd-disclosure-heading{width:100%;margin:0!important;font:inherit;}" +
      ".rd-disclosure .section-head{margin:0!important;}" +
      ".rd-disclosure .section-head>.section-link{display:none;}" +
      ".rd-disclosure.rd-open .section-head>.section-link{display:inline-flex;}" +
      ".rd-disclosure-tab{width:100%;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:14px 18px;" +
        "border:1px solid var(--line,#dcdcdc);border-left:5px solid var(--accent,#0e7490);background:var(--card,#fff);color:var(--ink,#141414);" +
        "font-family:var(--font-display,inherit);font-size:20px;font-weight:800;letter-spacing:.01em;text-transform:uppercase;cursor:pointer;text-align:left;}" +
      ".rd-disclosure-tab:hover,.rd-disclosure-tab:focus-visible{background:#f5f7f8;}" +
      ".rd-disclosure-hint{margin-left:auto;display:inline-flex;align-items:center;gap:10px;font-family:var(--font-ui,inherit);font-size:12px;font-weight:700;letter-spacing:.08em;color:var(--accent,#0e7490);white-space:nowrap;}" +
      ".rd-disclosure-arrow{font-size:22px;line-height:1;transition:transform .18s ease;}" +
      ".rd-disclosure-tab[aria-expanded=\"true\"] .rd-disclosure-arrow{transform:rotate(180deg);}" +
      /* The important bit: `hidden` must beat display:grid/flex from any sheet. */
      ".rd-disclosure .rd-disclosure-body[hidden]{display:none!important;}" +
      ".rd-disclosure.rd-open .rd-disclosure-body{padding-top:22px;}" +
      "@media(max-width:820px){.rd-disclosure-tab{padding:12px 15px;font-size:16px}.rd-disclosure-hint{font-size:11px}}" +
      "@media(prefers-reduced-motion:reduce){.rd-disclosure-arrow{transition:none}}";
    document.head.appendChild(style);
  }

  function initDisclosure(spec) {
    var section = document.getElementById(spec.id);
    if (!section || section.dataset.rdDisclosure === "1") return;
    var wrap = section.querySelector(":scope > .wrap");
    var heading = document.getElementById(spec.heading);
    if (!wrap || !heading) return;
    var sectionHead = heading.closest(".section-head");
    if (!sectionHead) return;

    section.dataset.rdDisclosure = "1";
    section.classList.add("rd-disclosure");
    installDisclosureStyle();

    /* Everything in the wrap except the head becomes the body. */
    var body = document.createElement("div");
    body.className = "rd-disclosure-body";
    body.id = spec.id + "-disclosure-body";
    Array.prototype.slice.call(wrap.children).forEach(function (child) {
      if (child !== sectionHead) body.appendChild(child);
    });
    wrap.appendChild(body);
    body.hidden = true;

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "rd-disclosure-tab";
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-controls", body.id);
    toggle.innerHTML =
      "<span>" + spec.label + "</span>" +
      '<span class="rd-disclosure-hint"><span class="rd-disclosure-hint-text">' + spec.hint + "</span>" +
      '<span class="rd-disclosure-arrow" aria-hidden="true">&#9662;</span></span>';

    /* Keep the real h2 in the accessibility tree; the heading owns the control. */
    heading.textContent = "";
    heading.classList.add("rd-disclosure-heading");
    heading.appendChild(toggle);

    function setOpen(open) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      section.classList.toggle("rd-open", open);
      body.hidden = !open;
      toggle.querySelector(".rd-disclosure-hint-text").textContent = open ? "Close" : spec.hint;
      if (open) section.dispatchEvent(new CustomEvent("rd:disclosure-open", { bubbles: true }));
    }
    toggle.addEventListener("click", function () {
      setOpen(toggle.getAttribute("aria-expanded") !== "true");
    });
    /* A hash link straight to the section (the nav's "Democracy" and
       "Community") should land on it open, not on a closed tab. */
    function openIfTargeted() {
      if (window.location.hash === "#" + spec.id) setOpen(true);
    }
    openIfTargeted();
    window.addEventListener("hashchange", openIfTargeted);
  }

  function initDisclosures() {
    DISCLOSURES.forEach(initDisclosure);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initDisclosures, { once: true });
  } else {
    initDisclosures();
  }
})();

/* 56 sellable small-ad positions. Empty inventory is invisible; when an
 * active adverts.json placement targets small-ad-01 ... small-ad-56, that
 * position appears automatically in a responsive Local advertisers grid. */
(function () {
  "use strict";

  var COUNT = 56;

  function initSmallAdInventory() {
    if (document.getElementById("rd-small-ad-inventory")) return;

    var footer = document.querySelector("footer");
    if (!footer || !footer.parentNode) return;

    if (!document.getElementById("rd-small-ad-inventory-style")) {
      var style = document.createElement("style");
      style.id = "rd-small-ad-inventory-style";
      style.textContent =
        "#rd-small-ad-inventory{padding:28px 0;background:#fff;border-top:1px solid var(--line,#dcdcdc);}" +
        "#rd-small-ad-inventory[hidden]{display:none!important;}" +
        "#rd-small-ad-inventory .rd-small-ad-wrap{width:min(var(--max,1220px),calc(100% - 30px));margin:0 auto;}" +
        "#rd-small-ad-inventory h2{margin:0 0 14px;font-family:var(--font-display);font-size:18px;line-height:1.2;font-weight:900;text-transform:uppercase;}" +
        "#rd-small-ad-grid{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px;align-items:stretch;}" +
        ".rd-small-ad-slot:not(.ad-live){display:none!important;}" +
        ".rd-small-ad-slot.ad-live{display:flex;align-items:center;justify-content:center;min-width:0;min-height:92px;padding:5px;background:#f7f7f7;border:1px solid #ddd;overflow:hidden;}" +
        ".rd-small-ad-slot.ad-live>a{width:100%;}" +
        ".rd-small-ad-slot.ad-live img{width:100%!important;height:auto!important;max-height:120px!important;object-fit:contain!important;}" +
        "@media(max-width:1050px){#rd-small-ad-grid{grid-template-columns:repeat(4,minmax(0,1fr));}}" +
        "@media(max-width:640px){#rd-small-ad-inventory{padding:20px 0;}#rd-small-ad-grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}.rd-small-ad-slot.ad-live{min-height:82px;}}";
      document.head.appendChild(style);
    }

    var section = document.createElement("section");
    section.id = "rd-small-ad-inventory";
    section.hidden = true;
    section.setAttribute("aria-labelledby", "rd-small-ad-title");

    var wrap = document.createElement("div");
    wrap.className = "rd-small-ad-wrap";

    var heading = document.createElement("h2");
    heading.id = "rd-small-ad-title";
    heading.textContent = "Local advertisers";

    var grid = document.createElement("div");
    grid.id = "rd-small-ad-grid";

    for (var i = 1; i <= COUNT; i += 1) {
      var slot = document.createElement("div");
      var number = String(i).padStart(2, "0");
      slot.className = "ad-slot rd-small-ad-slot";
      slot.setAttribute("data-ad-slot", "small-ad-" + number);
      slot.setAttribute("aria-hidden", "true");
      grid.appendChild(slot);
    }

    wrap.appendChild(heading);
    wrap.appendChild(grid);
    section.appendChild(wrap);
    footer.parentNode.insertBefore(section, footer);

    function refreshVisibility() {
      section.hidden = !grid.querySelector(".rd-small-ad-slot.ad-live");
    }

    if (typeof MutationObserver === "function") {
      new MutationObserver(refreshVisibility).observe(grid, {
        subtree: true,
        attributes: true,
        attributeFilter: ["class"]
      });
    }

    if (typeof window.rdFillAds === "function") window.rdFillAds();
    window.setTimeout(refreshVisibility, 0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initSmallAdInventory, { once: true });
  } else {
    initSmallAdInventory();
  }
})();
