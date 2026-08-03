/* Rochdale Daily cookie consent and homepage enhancements. */
(function () {
  "use strict";

  var KEY = "rd-cookie-choice";
  var ACCEPTED = "optional-accepted";
  var DECLINED = "essential-only";
  var ASSET_VERSION = "20260803-6";

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

  function pollLoadError() {
    var poll = document.getElementById("community-poll");
    if (!poll) return;
    poll.innerHTML = '<div class="rd-poll-shell"><p class="rd-poll-error">The community poll could not be loaded. Please refresh the page and try again.</p></div>';
  }

  function loadHomepageEnhancements() {
    if (!document.getElementById("news-grid")) return;
    addStyle("/assets/css/community-poll.css");
    addScript("/assets/js/homepage-ui.js");

    var ward = document.getElementById("news-by-ward");
    if (!ward || document.getElementById("community-poll")) return;
    var section = document.createElement("section");
    section.id = "community-poll";
    section.setAttribute("aria-label", "Rochdale Daily community poll");
    section.innerHTML = '<div class="rd-poll-shell"><p class="rd-poll-error">Loading live community poll…</p></div>';
    ward.insertAdjacentElement("afterend", section);
    addScript("/assets/js/community-poll-v2.js", pollLoadError);

    window.setTimeout(function () {
      var current = document.getElementById("community-poll");
      if (current && current.textContent.indexOf("Loading live community poll") !== -1) pollLoadError();
    }, 15000);
  }

  function init() {
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
