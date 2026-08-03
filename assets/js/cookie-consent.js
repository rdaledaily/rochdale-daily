/* Rochdale Daily cookie consent.
 *
 * One implementation for every page. The banner used to live inline in
 * index.html, so it appeared on the homepage only: a reader who arrived on an
 * article - which is how most people arrive - was never asked, and the
 * "Cookie settings" link the privacy policy points them at did not exist on
 * the 600+ article pages. This script injects the banner wherever it is
 * loaded and binds the settings link, so the promise the privacy page makes
 * is true on every page.
 *
 * The choice is stored in localStorage under rd-cookie-choice, the same key
 * the homepage already used, so anyone who has already chosen is not asked
 * again.
 *
 * Optional cookies stay off unless "rd-cookie-choice" is "optional-accepted".
 * Nothing here sets an analytics or advertising cookie itself; it records the
 * decision, and anything optional must check rdCookieConsent() before running.
 */
(function () {
  "use strict";

  var KEY = "rd-cookie-choice";
  var ACCEPTED = "optional-accepted";
  var DECLINED = "essential-only";

  function read() {
    try {
      return window.localStorage.getItem(KEY);
    } catch (error) {
      // Private browsing, or storage disabled. Treat as undecided rather than
      // assuming consent.
      return null;
    }
  }

  function save(choice) {
    try {
      window.localStorage.setItem(KEY, choice);
    } catch (error) {
      // Nothing we can do; the banner still closes for this page view.
    }
  }

  // Public: anything optional must gate itself on this.
  window.rdCookieConsent = function () {
    return read() === ACCEPTED;
  };

  function build() {
    var existing = document.getElementById("cookie-banner");
    if (existing) return existing;

    var banner = document.createElement("div");
    banner.className = "cookie";
    banner.id = "cookie-banner";
    banner.setAttribute("role", "region");
    banner.set.setAttribute;
    banner.setAttribute("aria-label", "Cookie choices");
    banner.innerHTML =
      '<div class="wrap cookie-row">' +
      '<p><strong>Cookie choices:</strong> We use strictly necessary cookies and ' +
      "local storage to operate this website, keep it secure and remember your " +
      "preferences. Optional analytics cookies help us understand how the site is " +
      "used, while optional advertising cookies may be used to support relevant " +
      "advertising. Optional cookies remain off unless you consent. You can change " +
      'your choice at any time using <a href="/privacy.html#cookies" style="color:#f5c400">Cookie settings</a>.</p>' +
      '<div class="cookie-actions">' +
      '<button class="cookie-decline" id="cookie-decline" type="button">Essential only</button>' +
      '<button class="cookie-accept" id="cookie-accept" type="button">Accept optional cookies</button>' +
      "</div></div>";
    document.body.appendChild(banner);
    return banner;
  }

  function loadCommunityPoll() {
    var ward = document.getElementById("news-by-ward");
    if (!ward || document.getElementById("community-poll")) return;

    var section = document.createElement("section");
    section.id = "community-poll";
    section.setAttribute("aria-label", "Rochdale Daily community poll");
    section.innerHTML = '<div class="rd-poll-shell"><p class="rd-poll-error">Loading live community poll…</p></div>';
    ward.insertAdjacentElement("afterend", section);

    if (!document.querySelector('link[href="/assets/css/community-poll.css"]')) {
      var style = document.createElement("link");
      style.rel = "stylesheet";
      style.href = "/assets/css/community-poll.css";
      document.head.appendChild(style);
    }

    if (!document.querySelector('script[src="/assets/js/community-poll.js"]')) {
      var script = document.createElement("script");
      script.src = "/assets/js/community-poll.js";
      script.defer = true;
      document.body.appendChild(script);
    }
  }

  function init() {
    var banner = build();
    var accept = document.getElementById("cookie-accept");
    var decline = document.getElementById("cookie-decline");

    function close(choice) {
      save(choice);
      banner.classList.remove("show");
      // Return focus somewhere sensible for keyboard and screen reader users
      // rather than dropping it on a removed element.
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

    // Any "Cookie settings" control on the page reopens the banner. Matched by
    // id (the homepage's existing link) or by attribute, so a page can add one
    // without touching this file.
    var links = [].slice.call(document.querySelectorAll("[data-cookie-settings]"));
    var byId = document.getElementById("cookie-settings-link");
    if (byId && links.indexOf(byId) === -1) links.push(byId);
    links.forEach(function (link) { link.addEventListener("click", open); });

    if (!read()) banner.classList.add("show");
    loadCommunityPoll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
