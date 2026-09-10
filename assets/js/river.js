/* Rochdale Daily — the river: endless local news, honestly labelled.
 *
 * The front page used to end after six stories while 1,250 sat in the archive
 * unreachable. This keeps the page going, but it does not pretend that
 * everything it serves is new.
 *
 * Two rules the feed apps break and this one does not:
 *
 *   1. When the reader has seen everything published recently, SAY SO. A
 *      "You're up to date" line marks the boundary; everything below it is
 *      openly labelled as older. The reader always knows whether they are
 *      reading news or browsing an archive.
 *
 *   2. The river ends. When the archive is exhausted the page says so and
 *      offers real destinations (wards, sections) rather than looping or
 *      padding with filler to keep the scroll alive.
 *
 * Pull-to-refresh is a real check against the live feed, not a lever. If
 * nothing has been published since the reader arrived it says exactly that,
 * with the time. A refresh that always "finds" something would be the one
 * dishonest thing on a page whose entire job is being believed.
 */
(function () {
  "use strict";

  var BATCH = 8;
  var FRESH_HOURS = 48;
  var ARCHIVE = "/archive-index.json";
  var FRONTPAGE = "/articles/frontpage.json";

  var host = document.getElementById("river");
  if (!host) return;

  var stream = host.querySelector(".river-stream");
  var status = host.querySelector(".river-status");
  var items = [];
  var cursor = 0;
  var markerPlaced = false;
  var loading = false;

  /* Slugs already on the page must not appear again in the river. */
  function seenSlugs() {
    var set = Object.create(null);
    document.querySelectorAll('a[href*="/articles/"], a[href^="articles/"]').forEach(function (a) {
      var m = (a.getAttribute("href") || "").match(/([^/]+)\.html$/);
      if (m) set[m[1]] = true;
    });
    return set;
  }

  function parseTime(value) {
    var t = Date.parse(value || "");
    return isNaN(t) ? 0 : t;
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function ago(ts) {
    if (!ts) return "";
    var mins = Math.round((Date.now() - ts) / 60000);
    if (mins < 60) return mins <= 1 ? "just now" : mins + " min ago";
    var hrs = Math.round(mins / 60);
    if (hrs < 24) return hrs + (hrs === 1 ? " hour ago" : " hours ago");
    var days = Math.round(hrs / 24);
    if (days < 31) return days + (days === 1 ? " day ago" : " days ago");
    return new Date(ts).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
  }

  function card(item) {
    var el = document.createElement("a");
    el.className = "river-item";
    el.href = item.url || ("/articles/" + item.slug + ".html");
    el.innerHTML =
      '<span class="river-meta">' + esc(item.category || "News") +
      " &middot; " + esc(ago(item._t)) + "</span>" +
      '<span class="river-title"></span>' +
      (item.description ? '<span class="river-standfirst"></span>' : "");
    el.querySelector(".river-title").textContent = item.title || "Local news";
    if (item.description) {
      el.querySelector(".river-standfirst").textContent = String(item.description).slice(0, 150);
    }
    return el;
  }

  /* The honest boundary. Placed once, at the point where recent news ends. */
  function marker() {
    var el = document.createElement("div");
    el.className = "river-marker";
    el.setAttribute("role", "separator");
    el.innerHTML =
      '<span class="river-marker-line" aria-hidden="true"></span>' +
      '<span class="river-marker-text">You&rsquo;re up to date</span>' +
      '<span class="river-marker-note">Everything below is older reporting from the archive</span>';
    return el;
  }

  function renderBatch() {
    if (loading || cursor >= items.length) return;
    loading = true;
    var frag = document.createDocumentFragment();
    var end = Math.min(cursor + BATCH, items.length);
    for (var i = cursor; i < end; i += 1) {
      if (!markerPlaced && !items[i]._fresh) {
        frag.appendChild(marker());
        markerPlaced = true;
      }
      frag.appendChild(card(items[i]));
    }
    stream.appendChild(frag);
    cursor = end;
    loading = false;

    if (cursor >= items.length) {
      status.innerHTML =
        '<p class="river-end-title">That is every story we have published &mdash; ' +
        items.length.toLocaleString("en-GB") + " of them.</p>" +
        '<p class="river-end-note">Nothing is hidden below this point. ' +
        'Try <a href="/archive.html">the archive</a> to search, ' +
        'or read by <a href="/wards/">ward</a> or <a href="/news/">section</a>.</p>';
      status.hidden = false;
    }
  }

  function start(data) {
    var seen = seenSlugs();
    var cutoff = Date.now() - FRESH_HOURS * 3600 * 1000;
    items = (Array.isArray(data) ? data : data.articles || data.items || [])
      .filter(function (item) {
        var slug = item.slug || "";
        return slug && !seen[slug] && item.title;
      })
      .map(function (item) {
        item._t = parseTime(item.published_at);
        item._fresh = item._t >= cutoff;
        return item;
      })
      .sort(function (a, b) { return b._t - a._t; });

    if (!items.length) return;
    host.hidden = false;
    renderBatch();

    var sentinel = host.querySelector(".river-sentinel");
    if ("IntersectionObserver" in window) {
      new IntersectionObserver(function (entries) {
        if (entries[0].isIntersecting) renderBatch();
      }, { rootMargin: "600px" }).observe(sentinel);
    } else {
      window.addEventListener("scroll", function () {
        if (sentinel.getBoundingClientRect().top < window.innerHeight + 600) renderBatch();
      }, { passive: true });
    }
  }

  fetch(ARCHIVE, { credentials: "omit" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (d) { if (d) start(d); })
    .catch(function () { /* the page is complete without the river */ });

  /* ------------------------------------------------------------- pull to refresh
     A genuine check. It reports what it found, including nothing. */
  (function pullToRefresh() {
    if (!window.matchMedia("(max-width: 820px)").matches) return;

    var THRESHOLD = 72;
    var startY = 0, pulling = false, dist = 0;
    var arrivedAt = Date.now();

    var ind = document.createElement("div");
    ind.className = "ptr";
    ind.innerHTML = '<span class="ptr-text">Pull to check for new stories</span>';
    document.body.appendChild(ind);
    var text = ind.querySelector(".ptr-text");

    function reset(delay) {
      setTimeout(function () {
        ind.classList.remove("is-active", "is-busy");
        ind.style.transform = "";
        dist = 0;
      }, delay || 0);
    }

    document.addEventListener("touchstart", function (e) {
      if (window.scrollY > 0 || e.touches.length !== 1) return;
      startY = e.touches[0].clientY;
      pulling = true;
    }, { passive: true });

    document.addEventListener("touchmove", function (e) {
      if (!pulling) return;
      dist = e.touches[0].clientY - startY;
      if (dist <= 0) { pulling = false; reset(); return; }
      var pull = Math.min(dist * 0.5, 96);       // resistance, like a real lever
      ind.classList.add("is-active");
      ind.style.transform = "translateY(" + pull + "px)";
      text.textContent = pull >= THRESHOLD ? "Release to check" : "Pull to check for new stories";
    }, { passive: true });

    document.addEventListener("touchend", function () {
      if (!pulling) return;
      pulling = false;
      if (dist * 0.5 < THRESHOLD) { reset(); return; }

      ind.classList.add("is-busy");
      text.textContent = "Checking…";
      if (navigator.vibrate) navigator.vibrate(8);

      fetch(FRONTPAGE + "?t=" + Date.now(), { credentials: "omit" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          var list = (data && data.articles) || [];
          var newest = 0;
          list.forEach(function (a) {
            var t = parseTime(a.published_at || a.first_published_at);
            if (t > newest) newest = t;
          });
          var seen = seenSlugs();
          var unseen = list.filter(function (a) { return a.slug && !seen[a.slug]; }).length;

          if (unseen > 0) {
            text.textContent = unseen === 1 ? "1 new story — loading…" : unseen + " new stories — loading…";
            setTimeout(function () { window.location.reload(); }, 550);
            return;
          }
          /* The honest empty state: no invented reward. */
          text.textContent = newest
            ? "Nothing new. Last published " + ago(newest) + "."
            : "Nothing new since you arrived.";
          reset(1900);
        })
        .catch(function () {
          text.textContent = "Could not check just now.";
          reset(1600);
        });
    }, { passive: true });

    void arrivedAt;
  })();
})();
