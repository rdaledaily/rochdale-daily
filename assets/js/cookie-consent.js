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
  var ASSET_VERSION = "20261028-reader-behaviour";

  function read() {
    try { return window.localStorage.getItem(KEY); } catch (error) { return null; }
  }

  function save(choice) {
    try { window.localStorage.setItem(KEY, choice); } catch (error) { /* no-op */ }
  }

  window.rdCookieConsent = function () { return read() === ACCEPTED; };

  /* Google Analytics 4. Loaded only after a reader chooses "Accept optional",
     never before: privacy.html promises that nothing optional is set until
     then, and UK rules (PECR) require consent for analytics cookies. A reader
     who has not chosen, or chose "Essential only", sends nothing to Google --
     the script is not even requested. */
  var GA_ID = "G-FGW8TMCXBD";
  var analyticsLoaded = false;

  function loadAnalytics() {
    if (analyticsLoaded) return;
    analyticsLoaded = true;
    window["ga-disable-" + GA_ID] = false;
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
    window.gtag("js", new Date());
    window.gtag("config", GA_ID);
    var script = document.createElement("script");
    script.async = true;
    script.src = "https://www.googletagmanager.com/gtag/js?id=" + GA_ID;
    script.setAttribute("data-rd-analytics", GA_ID);
    document.head.appendChild(script);
  }

  /* Reader actions that build return visits, recorded as GA4 events so they
     can be marked as key events (Admin > Events > "Mark as key event").
     GA had 0 key events on 28 Oct 2026, so none of what brings a reader back
     could be measured. Nothing is sent without analytics consent: gtag only
     exists after loadAnalytics(), and ga-disable stops it on withdrawal. */
  function track(name, params) {
    if (!analyticsLoaded || typeof window.gtag !== "function") return;
    try { window.gtag("event", name, params || {}); } catch (error) { /* no-op */ }
  }
  window.rdTrack = track;
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || !form.id) return;
    if (/newsletter/i.test(form.id)) track("newsletter_signup", { form_id: form.id, page_type: pageType() });
    else if (/comment/i.test(form.id + " " + form.className)) track("comment_submit", { page_type: pageType() });
  }, true);
  document.addEventListener("click", function (event) {
    var el = event.target && event.target.closest ? event.target.closest("a, button") : null;
    if (!el) return;
    if (el.matches("[data-share]")) {
      track("share", { method: el.getAttribute("data-share"), content_type: "article" });
    } else if (el.closest(".read-next, .next-bar")) {
      track("read_next_click", { link_url: el.getAttribute("href") || "" });
    } else if (/facebook\.com\/1240511409139789/.test(el.getAttribute("href") || "")) {
      track("facebook_follow_click", { page_type: pageType() });
    } else if (/\/news-alerts|\/my-rochdale/.test(el.getAttribute("href") || "")) {
      track("return_tool_click", { link_url: el.getAttribute("href") });
    }
  }, true);
  function pageType() {
    var path = window.location.pathname;
    if (path === "/" || /^\/index(?:\.html)?$/.test(path)) return "home";
    if (path.indexOf("/articles/") === 0) return "article";
    return "other";
  }

  /* Withdrawing consent must take effect at once, not on the next visit: stop
     any further hits on this page and remove the cookies Analytics set. */
  function stopAnalytics() {
    window["ga-disable-" + GA_ID] = true;
    var host = window.location.hostname;
    var domains = ["", host, "." + host, "." + host.replace(/^www\./, "")];
    document.cookie.split(";").forEach(function (pair) {
      var name = pair.split("=")[0].trim();
      if (name !== "_ga" && name.indexOf("_ga_") !== 0) return;
      domains.forEach(function (domain) {
        document.cookie = name + "=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/" +
          (domain ? "; domain=" + domain : "");
      });
    });
  }

  function build() {
    var existing = document.getElementById("cookie-banner");
    if (existing) return existing;
    var banner = document.createElement("div");
    banner.className = "cookie";
    banner.id = "cookie-banner";
    banner.setAttribute("role", "region");
    banner.setAttribute("aria-label", "Cookie choices");
    /* Two versions of the same notice. editorial-theme.css has carried the
       .cookie-long / .cookie-short rules since 10 Sep, but this function only
       ever emitted one <p>, so the shortening never had anything to act on:
       on a 390px phone the full paragraph ran to eight lines and took roughly
       half the first screen before a reader saw a headline. The short version
       says the same thing and links to the same page.

       The Cookie settings link was hardcoded #f5c400 — the gold that was
       retired two palettes ago, and the last literal of it in the shell. */
    banner.innerHTML =
      '<div class="wrap cookie-row">' +
      '<p class="cookie-long"><strong>Cookie choices:</strong> We use strictly necessary cookies and local storage to operate this website, keep it secure and remember your preferences. Optional analytics cookies help us understand how the site is used, while optional advertising cookies may be used to support relevant advertising. Optional cookies remain off unless you consent. You can change your choice at any time using <a href="/privacy#cookies">Cookie settings</a>.</p>' +
      '<p class="cookie-short"><strong>Cookies:</strong> optional ones stay off unless you allow them. <a href="/privacy#cookies">Read more</a>.</p>' +
      '<div class="cookie-actions"><button class="cookie-decline" id="cookie-decline" type="button">Essential only</button><button class="cookie-accept" id="cookie-accept" type="button">Accept all</button></div></div>';
    document.body.appendChild(banner);
    return banner;
  }

  function addStyle(href) {
    var existing = document.querySelector('link[data-rd-asset="' + href + '"]');
    if (existing) {
      existing.href = href + "?v=" + ASSET_VERSION;
      return;
    }
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
            '<a href="/about">About</a>' +
            '<a href="/editor">The editor</a>' +
            '<a href="/editorial-standards">Editorial standards</a>' +
            '<a href="/corrections-and-complaints">Corrections &amp; complaints</a>' +
            '<a href="/contact">Contact</a>' +
            '<a href="https://www.google.com/preferences/source?q=rochdaledaily.co.uk" target="_blank" rel="noopener">Prefer us on Google</a>' +
            '<a href="/privacy">Privacy</a>' +
            '<a href="#" data-cookie-settings>Cookie settings</a>' +
            '<a href="/terms">Terms</a>' +
            '<a href="/accessibility">Accessibility</a>' +
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

  function addNewsAlertsLink() {
    /* Article pages are generated separately. Add the public opt-in link to
       their existing navigation, without changing a single article file. */
    var list = document.querySelector(".primary-nav .nav-list");
    if (!list || list.querySelector('a[href="/news-alerts"]')) return;
    var item = document.createElement("li");
    var link = document.createElement("a");
    link.href = "/news-alerts";
    link.textContent = "News alerts";
    item.appendChild(link);
    list.appendChild(item);
  }

  function init() {
    loadEditorialTheme();
    upgradeTrustPage();
    var banner = build();
    var accept = document.getElementById("cookie-accept");
    var decline = document.getElementById("cookie-decline");

    function close(choice) {
      save(choice);
      if (choice === ACCEPTED) loadAnalytics();
      else stopAnalytics();
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
    if (read() === ACCEPTED) loadAnalytics();
    loadHomepageEnhancements();
    addNewsAlertsLink();
    addScript("/assets/js/reader-growth.js");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

