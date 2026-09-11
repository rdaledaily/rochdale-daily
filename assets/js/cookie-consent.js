/* Rochdale Daily cookie consent and homepage enhancements. */
(function () {
  "use strict";

  var KEY = "rd-cookie-choice";
  var ACCEPTED = "optional-accepted";
  var DECLINED = "essential-only";
  /* Bump this EVERY time editorial-theme.css or any script loaded through
     addStyle/addScript changes. The version rides on the URL as ?v=, so a
     browser that cached the previous copy is forced to fetch the new one.
     It was left at -1 through several stylesheet uploads on 10 Sep, so a
     browser that visited in the morning could keep serving that morning's
     stylesheet -- without the river or filter-bar rules -- all day. */
  var ASSET_VERSION = "20260910-editorial-cohesion-2";

  function read() {
    try { return window.localStorage.getItem(KEY); } catch (error) { return null; }
  }

  function save(choice) {
    try { window.localStorage.setItem(KEY, choice); } catch (error) { /* no-op */ }
  }

  window.rdCookieConsent = function () { return read() === ACCEPTED; };

  function build() {
    var existing = document.getElementById("cookie-banner");
    if (existing) return existing;
    var banner = document.createElement("div");
    banner.className = "cookie";
    banner.id = "cookie-banner";
    banner.setAttribute("role", "region");
    banner.setAttribute("aria-label", "Cookie choices");
    banner.innerHTML =
      '<div class="wrap cookie-row">' +
      '<p><strong>Cookie choices:</strong> We use strictly necessary cookies and local storage to operate this website, keep it secure and remember your preferences. Optional analytics cookies help us understand how the site is used, while optional advertising cookies may be used to support relevant advertising. Optional cookies remain off unless you consent. You can change your choice at any time using <a href="/privacy.html#cookies" style="color:#f5c400">Cookie settings</a>.</p>' +
      '<div class="cookie-actions"><button class="cookie-decline" id="cookie-decline" type="button">Essential only</button><button class="cookie-accept" id="cookie-accept" type="button">Accept optional cookies</button></div></div>';
    document.body.appendChild(banner);
    return banner;
  }

  function addStyle(href) {
    if (document.querySelector('link[data-rd-asset="' + href + '"]')) return;
    var style = document.createElement("link");
    style.rel = "stylesheet";
    style.href = href + "?v=" + ASSET_VERSION;
    style.setAttribute("data-rd-asset", href);
    document.head.appendChild(style);
  }

  function addScript(src, onError) {
    if (document.querySelector('script[data-rd-asset="' + src + '"]')) return;
    var script = document.createElement("script");
    script.src = src + "?v=" + ASSET_VERSION;
    script.defer = true;
    script.setAttribute("data-rd-asset", src);
    if (typeof onError === "function") script.addEventListener("error", onError);
    document.body.appendChild(script);
  }

  function loadEditorialTheme() {
    /* Homepage and generated article pages currently carry different generations
       of inline CSS. This shared final layer gives both the same publication
       system without touching the breaking/traffic ticker implementation. */
    if (document.getElementById("news-grid") || document.querySelector(".article-main")) {
      addStyle("/assets/css/editorial-theme.css");
    }
  }

  function upgradeTrustPage() {
    var main = document.querySelector("main.trust-wrap");
    if (!main) return;

    addStyle("/assets/css/trust-pages.css");
    document.body.classList.add("trust-newspaper-body");

    /* The header used to be rebuilt here into a gold wordmark bar with a black
       nav -- a second masthead that made the trust pages look like a different
       site. The standard masthead in the page is kept. The footer is still
       normalised, because these pages carry an inline black footer. */
    var footer = document.querySelector("body > footer");
    if (footer) {
      footer.className = "trust-newspaper-footer";
      footer.removeAttribute("style");
      footer.innerHTML =
        '<div class="trust-newspaper-footer__inner">' +
          '<strong>Rochdale Daily</strong> — independent local news for the Rochdale borough.' +
          '<div class="trust-newspaper-footer__links">' +
            '<a href="/about.html">About</a>' +
            '<a href="/editor.html">The editor</a>' +
            '<a href="/editorial-standards.html">Editorial standards</a>' +
            '<a href="/corrections-and-complaints.html">Corrections &amp; complaints</a>' +
            '<a href="/contact.html">Contact</a>' +
            '<a href="/privacy.html">Privacy</a>' +
            '<a href="#" data-cookie-settings>Cookie settings</a>' +
            '<a href="/terms.html">Terms</a>' +
            '<a href="/accessibility.html">Accessibility</a>' +
          '</div>' +
        '</div>';
    }
  }

  function pollLoadError() {
    /* Same rule as the poll script itself: if there is nothing to show, show
       nothing. Readers do not need to know a poll module failed to load. */
    var poll = document.getElementById("community-poll");
    if (poll && poll.parentNode) poll.parentNode.removeChild(poll);
  }

  function loadHomepageEnhancements() {
    if (!document.getElementById("news-grid")) return;
    addStyle("/assets/css/community-poll.css");
    addScript("/assets/js/homepage-ui.js");

    var anchor = document.getElementById("news-by-ward")
      || (document.getElementById("latest-news-title") && document.getElementById("latest-news-title").closest("section"));
    if (!anchor || document.getElementById("community-poll")) return;
    var section = document.createElement("section");
    section.id = "community-poll";
    section.setAttribute("aria-label", "Rochdale Daily community poll");
    section.hidden = true;  /* revealed by the poll script only when a poll is live */
    anchor.insertAdjacentElement("afterend", section);
    addScript("/assets/js/community-poll-v2.js", pollLoadError);

    window.setTimeout(function () {
      var current = document.getElementById("community-poll");
      if (current && current.hidden) pollLoadError();
    }, 15000);
  }

  function init() {
    loadEditorialTheme();
    upgradeTrustPage();
    var banner = build();
    var accept = document.getElementById("cookie-accept");
    var decline = document.getElementById("cookie-decline");

    function close(choice) {
      save(choice);
      banner.classList.remove("show");
      var link = document.getElementById("cookie-settings-link");
      if (link) link.focus();
    }

    function open(event) {
      if (event) event.preventDefault();
      banner.classList.add("show");
      if (decline) decline.focus();
    }

    if (accept) accept.addEventListener("click", function () { close(ACCEPTED); });
    if (decline) decline.addEventListener("click", function () { close(DECLINED); });
    var links = [].slice.call(document.querySelectorAll("[data-cookie-settings]"));
    var byId = document.getElementById("cookie-settings-link");
    if (byId && links.indexOf(byId) === -1) links.push(byId);
    links.forEach(function (link) { link.addEventListener("click", open); });

    if (!read()) banner.classList.add("show");
    loadHomepageEnhancements();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
