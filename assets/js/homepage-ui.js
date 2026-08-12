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
        "font:700 11px/1 Arial,sans-serif;" +
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
        "font-family:\"Roboto Condensed\",Arial,sans-serif!important;" +
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

/* Collapse Community support into a simple arrow tab. */
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
