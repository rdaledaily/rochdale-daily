/* Homepage-only progressive disclosure for Latest news.
 * Desktop shows 12 stories as a compact horizontal card grid, then a proper
 * advertising position, followed by a compact control to reveal more stories.
 * Mobile keeps its existing category-section layout and is untouched.
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
      ".latest-news-ad{" +
        "display:flex;" +
        "align-items:center;" +
        "justify-content:center;" +
        "width:100%;" +
        "min-height:250px;" +
        "margin:30px 0 0;" +
        "background:#f3f3f3;" +
        "border:1px solid #d6d6d6;" +
        "overflow:hidden;" +
        "position:relative;" +
      "}" +
      ".latest-news-ad:not(.ad-live)::before{" +
        "content:\"Advertisement\";" +
        "font:700 11px/1 Arial,sans-serif;" +
        "letter-spacing:.12em;" +
        "text-transform:uppercase;" +
        "color:#777;" +
      "}" +
      ".latest-news-more{" +
        "display:block!important;" +
        "width:auto!important;" +
        "height:auto!important;" +
        "min-width:180px!important;" +
        "min-height:0!important;" +
        "max-width:280px!important;" +
        "margin:18px auto 0!important;" +
        "padding:12px 24px!important;" +
        "position:static!important;" +
        "inset:auto!important;" +
        "border:2px solid var(--accent,#0e7490)!important;" +
        "background:transparent!important;" +
        "color:var(--accent,#0e7490)!important;" +
        "font-family:\"Roboto Condensed\",Arial,sans-serif!important;" +
        "font-size:16px!important;" +
        "line-height:1.2!important;" +
        "font-weight:900!important;" +
        "text-transform:uppercase!important;" +
        "cursor:pointer;" +
      "}" +
      ".latest-news-more:hover,.latest-news-more:focus-visible{" +
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
  grid.insertAdjacentElement("afterend", advert);

  var button = document.createElement("button");
  button.type = "button";
  button.id = "latest-news-more";
  button.className = "latest-news-more";
  button.textContent = "Read more";
  button.hidden = true;
  advert.insertAdjacentElement("afterend", button);

  if (typeof window.rdFillAds === "function") window.rdFillAds();

  function isDesktop() {
    return window.matchMedia("(min-width: 821px)").matches;
  }

  function cards() {
    return Array.prototype.slice.call(grid.children).filter(function (node) {
      return node.nodeType === 1;
    });
  }

  function apply() {
    var items = cards();
    if (!isDesktop()) {
      grid.classList.remove("rd-latest-horizontal");
      items.forEach(function (item) { item.hidden = false; });
      advert.hidden = true;
      button.hidden = true;
      return;
    }

    grid.classList.add("rd-latest-horizontal");
    items.forEach(function (item, index) {
      item.hidden = index >= visible;
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

  button.addEventListener("click", function () {
    visible += STEP;
    apply();
  });

  var observer = new MutationObserver(function (mutations) {
    var changed = mutations.some(function (mutation) {
      return mutation.type === "childList";
    });
    if (changed) {
      visible = INITIAL;
      apply();
    }
  });
  observer.observe(grid, { childList: true });

  window.addEventListener("resize", apply);
  apply();
})();
