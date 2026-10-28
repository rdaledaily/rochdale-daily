/* Live coverage on the page (see scraper/live_format.py and
 * functions/api/live-updates.js).
 *
 * Article pages: merge the live desk's updates into the timeline, newest
 * first, and check again every minute while the story is live and the tab is
 * visible. A reader who has scrolled down gets a "New updates" button rather
 * than the page jumping under their thumb.
 *
 * Homepage: fill #live-now with the stories that are live right now.
 *
 * Everything from the API is written with textContent, never as HTML.
 */
(function () {
  "use strict";
  var API = "/api/live-updates";
  var POLL_MS = 60 * 1000;
  var LIVE_WINDOW_MS = 6 * 60 * 60 * 1000;

  function fmtTime(iso, withDate) {
    var d = new Date(iso);
    if (!isFinite(d.getTime())) return "";
    var opts = { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Europe/London", timeZoneName: "short" };
    if (withDate) { opts.day = "numeric"; opts.month = "long"; }
    return new Intl.DateTimeFormat("en-GB", opts).format(d);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function safeUrl(value) {
    var raw = String(value || "");
    return raw.indexOf("/assets/") === 0 || raw.indexOf("https://") === 0 ? raw : "";
  }

  function getJson(url) {
    return fetch(url, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  /* ------------------------------------------------------------ homepage */
  var liveNow = document.getElementById("live-now");
  if (liveNow) {
    getJson(API + "?index=1").then(function (data) {
      var live = data && data.live;
      if (!live || !live.length) return;
      var list = liveNow.querySelector(".live-now-list");
      live.slice(0, 3).forEach(function (item) {
        if (!/^[a-z0-9][a-z0-9-]{3,180}$/.test(item.slug || "")) return;
        var li = el("li");
        var a = el("a");
        a.href = "/articles/" + item.slug;
        a.appendChild(el("span", "live-pill", "LIVE"));
        a.appendChild(el("span", "live-now-title", item.title || "Live coverage"));
        a.appendChild(el("span", "live-now-time", "Updated " + fmtTime(item.updated_at)));
        li.appendChild(a);
        list.appendChild(li);
      });
      if (list.children.length) liveNow.hidden = false;
    });
  }

  /* -------------------------------------------------------- article pages */
  var main = document.querySelector(".article-main[data-live-slug]");
  if (!main) return;
  var slug = main.getAttribute("data-live-slug");
  if (!/^[a-z0-9][a-z0-9-]{3,180}$/.test(slug || "")) return;

  var block = main.querySelector(".live-blog");
  var pending = [];

  function ensureBlock() {
    if (block) return block;
    block = el("section", "live-blog");
    block.id = "live";
    block.setAttribute("aria-label", "Live updates");
    var head = el("div", "live-head");
    head.appendChild(el("span", "live-pill", "LIVE"));
    var updated = el("span", "live-updated");
    head.appendChild(updated);
    head.appendChild(el("span", "live-count"));
    block.appendChild(head);
    var fresh = el("div", "live-new");
    fresh.hidden = true;
    fresh.appendChild(el("button", null, "New updates"));
    block.appendChild(fresh);
    block.appendChild(el("div", "live-timeline"));
    var anchor = main.querySelector(".article-hero-image") || main.querySelector(".article-copy");
    main.insertBefore(block, anchor);
    var dev = main.querySelector(".developing-note");
    if (dev) dev.remove();
    return block;
  }

  function entryNode(u) {
    var art = el("article", "live-entry");
    art.id = "update-" + u.id;
    art.setAttribute("data-id", u.id);
    var t = el("a", "live-time");
    t.href = "#update-" + u.id;
    var time = el("time", null, fmtTime(u.timestamp));
    time.setAttribute("datetime", u.timestamp);
    t.appendChild(time);
    art.appendChild(t);
    var body = el("div", "live-body");
    if (u.title) body.appendChild(el("h3", null, u.title));
    var p = el("p", null, u.text);
    var src = safeUrl(u.source_url);
    if (src) {
      var a = el("a", "live-source", "Source");
      a.href = src; a.target = "_blank"; a.rel = "noopener";
      p.appendChild(document.createTextNode(" "));
      p.appendChild(a);
    }
    body.appendChild(p);
    var img = safeUrl(u.image_url);
    if (img) {
      var fig = el("figure", "live-figure");
      var im = el("img");
      im.src = img; im.alt = ""; im.loading = "lazy"; im.referrerPolicy = "no-referrer";
      fig.appendChild(im);
      if (u.image_credit) fig.appendChild(el("figcaption", null, "Image: " + u.image_credit));
      body.appendChild(fig);
    }
    art.appendChild(body);
    return art;
  }

  function refreshHead(data) {
    var b = ensureBlock();
    var entries = b.querySelectorAll(".live-entry");
    var newest = entries.length ? entries[0].querySelector("time").getAttribute("datetime") : "";
    var ended = Boolean(data && data.ended_at);
    var isLive = !ended && newest && (Date.now() - Date.parse(newest) < LIVE_WINDOW_MS);
    var pill = b.querySelector(".live-pill");
    pill.textContent = isLive ? "LIVE" : "As it happened";
    pill.classList.toggle("live-pill--ended", !isLive);
    b.setAttribute("data-live", isLive ? "1" : "0");
    var updated = b.querySelector(".live-updated");
    updated.textContent = newest ? "Last updated " + fmtTime(newest, true) : "";
    var count = b.querySelector(".live-count");
    if (count) count.textContent = entries.length + (entries.length === 1 ? " update" : " updates");
    if (data && data.key_points && data.key_points.length) {
      var box = b.querySelector(".live-points");
      if (!box) {
        box = el("div", "live-points");
        box.appendChild(el("h2", null, "What we know so far"));
        box.appendChild(el("ul"));
        b.insertBefore(box, b.querySelector(".live-new"));
      }
      var ul = box.querySelector("ul");
      ul.textContent = "";
      data.key_points.slice(0, 6).forEach(function (point) { ul.appendChild(el("li", null, point)); });
    }
    return isLive;
  }

  function merge(data, firstLoad) {
    var updates = (data && data.updates) || [];
    if (!updates.length && !block) return false;
    var b = ensureBlock();
    var timeline = b.querySelector(".live-timeline");
    var have = {};
    timeline.querySelectorAll(".live-entry").forEach(function (node) { have[node.getAttribute("data-id")] = true; });
    var fresh = updates.filter(function (u) { return u && u.id && !have[u.id] && u.text; })
      .sort(function (a, c) { return Date.parse(c.timestamp) - Date.parse(a.timestamp); });
    var readerIsDown = window.scrollY > b.offsetTop + 400;
    if (fresh.length && !firstLoad && readerIsDown) {
      pending = fresh.concat(pending);
      var bar = b.querySelector(".live-new");
      bar.hidden = false;
      bar.querySelector("button").textContent = pending.length === 1 ? "1 new update" : pending.length + " new updates";
    } else {
      insert(fresh);
    }
    return refreshHead(data);
  }

  function insert(list) {
    var timeline = ensureBlock().querySelector(".live-timeline");
    // Oldest first into the top, so the newest ends up first.
    list.slice().reverse().forEach(function (u) { timeline.insertBefore(entryNode(u), timeline.firstChild); });
    // Keep the static entries in time order as well.
    var nodes = Array.prototype.slice.call(timeline.querySelectorAll(".live-entry"));
    nodes.sort(function (a, c) {
      return Date.parse(c.querySelector("time").getAttribute("datetime")) - Date.parse(a.querySelector("time").getAttribute("datetime"));
    }).forEach(function (node) { timeline.appendChild(node); });
  }

  document.addEventListener("click", function (event) {
    var btn = event.target.closest && event.target.closest(".live-new button");
    if (!btn) return;
    insert(pending);
    pending = [];
    btn.parentNode.hidden = true;
    refreshHead(null);
    block.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  var timer = null;
  function poll(firstLoad) {
    if (document.hidden && !firstLoad) return;
    getJson(API + "?slug=" + encodeURIComponent(slug)).then(function (data) {
      if (!data || !data.ok) return;
      var live = merge(data, firstLoad);
      if (live && !timer) timer = setInterval(function () { poll(false); }, POLL_MS);
      if (!live && timer) { clearInterval(timer); timer = null; }
    });
  }

  var staticLive = block && block.getAttribute("data-live") === "1";
  // Ask the desk only when this page is live already, or the desk lists it.
  if (staticLive) {
    poll(true);
  } else {
    getJson(API + "?index=1").then(function (data) {
      var listed = data && data.live && data.live.some(function (item) { return item.slug === slug; });
      if (listed) poll(true);
    });
  }
  document.addEventListener("visibilitychange", function () { if (!document.hidden && timer) poll(false); });
})();
