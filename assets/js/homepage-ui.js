/* Homepage-only progressive disclosure for the Latest news grid.
 * Desktop shows 12 cards initially, then reveals 12 more per click. Mobile
 * keeps its existing category-section layout and is untouched.
 */
(function () {
  "use strict";

  var INITIAL = 12;
  var STEP = 12;
  var visible = INITIAL;
  var grid = document.getElementById("news-grid");
  if (!grid) return;

  var button = document.createElement("button");
  button.type = "button";
  button.id = "latest-news-more";
  button.className = "latest-news-more";
  button.textContent = "Read more stories";
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
      items.forEach(function (item) { item.hidden = false; });
      button.hidden = true;
      return;
    }

    items.forEach(function (item, index) {
      item.hidden = index >= visible;
    });

    var remaining = Math.max(0, items.length - visible);
    button.hidden = remaining === 0;
    button.textContent = remaining > STEP
      ? "Read 12 more stories"
      : "Read " + remaining + " more stor" + (remaining === 1 ? "y" : "ies");
    button.setAttribute("aria-label", button.textContent + " in Latest news");
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
