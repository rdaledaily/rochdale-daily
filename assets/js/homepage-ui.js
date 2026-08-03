/* Homepage-only progressive disclosure for Latest news.
 * Desktop shows 12 stories as a compact horizontal card grid and reveals the
 * next 12 from one simple Read more button beneath the grid. Mobile keeps its
 * existing category-section layout and is untouched.
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
      ".latest-news-more{" +
        "display:block;" +
        "min-width:180px;" +
        "margin:28px auto 0;" +
        "padding:12px 24px;" +
        "border:2px solid var(--accent,#0e7490);" +
        "background:var(--accent,#0e7490);" +
        "color:#fff;" +
        "font-family:\"Roboto Condensed\",Arial,sans-serif;" +
        "font-weight:900;" +
        "text-transform:uppercase;" +
        "cursor:pointer;" +
      "}" +
      ".latest-news-more:hover,.latest-news-more:focus-visible{" +
        "background:var(--yellow-dark,#0b5f75);" +
      "}" +
    "}" +
    "@media (min-width:821px) and (max-width:1080px){" +
      "#news-grid.rd-latest-horizontal{grid-template-columns:repeat(3,minmax(0,1fr))!important;}" +
    "}";
  document.head.appendChild(style);

  var button = document.createElement("button");
  button.type = "button";
  button.id = "latest-news-more";
  button.className = "latest-news-more";
  button.textContent = "Read more";
  button.hidden = true;
  grid.insertAdjacentElement("afterend", button);

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
      button.hidden = true;
      return;
    }

    grid.classList.add("rd-latest-horizontal");
    items.forEach(function (item, index) {
      item.hidden = index >= visible;
    });

    var remaining = Math.max(0, items.length - visible);
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
