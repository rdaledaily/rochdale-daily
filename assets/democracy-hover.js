/* Visual affordance for expandable Democracy controls. */
(function () {
  "use strict";

  function install() {
    if (document.getElementById("rd-democracy-hover-style")) return;

    var style = document.createElement("style");
    style.id = "rd-democracy-hover-style";
    style.textContent = [
      "#democracy .dem-tab {",
      "  transition: background-color .16s ease, color .16s ease, border-color .16s ease, transform .16s ease, box-shadow .16s ease;",
      "}",
      "#democracy .dem-tab:hover,",
      "#democracy .dem-tab:focus-visible {",
      "  background: #e8f5f8 !important;",
      "  border-color: #0e7490 !important;",
      "  color: #0b1f3a !important;",
      "  transform: translateY(-1px);",
      "  box-shadow: 0 3px 0 rgba(14, 116, 144, .16);",
      "}",
      "#democracy .dem-tab.active,",
      "#democracy .dem-tab[aria-expanded=\"true\"] {",
      "  background: #0e7490 !important;",
      "  border-color: #0e7490 !important;",
      "  color: #fff !important;",
      "}",
      "#democracy .dem-tab.active:hover,",
      "#democracy .dem-tab[aria-expanded=\"true\"]:hover {",
      "  background: #0b5f75 !important;",
      "  border-color: #0b5f75 !important;",
      "  color: #fff !important;",
      "}",
      "@media (prefers-reduced-motion: reduce) {",
      "  #democracy .dem-tab { transition: none; }",
      "}"
    ].join("\n");
    document.head.appendChild(style);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", install, { once: true });
  } else {
    install();
  }
})();
