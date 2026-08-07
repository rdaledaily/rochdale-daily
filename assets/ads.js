/* Rochdale Daily advertising loader.
   Reads /adverts.json, fills every [data-ad-slot] container with a live,
   in-date placement (weighted rotation per page view), fills sold
   [data-ad-directory] cards, and — when config.tracker_base is set —
   routes clicks through the tracking Worker and fires sampled impression
   beacons. On any failure it does nothing, leaving the built-in
   placeholders untouched. No frameworks, no cookies, no personal data. */
(function () {
  "use strict";

  function todayKey() {
    // Europe/London calendar day, matching start/end in adverts.json.
    var parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit"
    }).formatToParts(new Date());
    var v = {};
    parts.forEach(function (p) { v[p.type] = p.value; });
    return v.year + "-" + v.month + "-" + v.day;
  }

  function isActive(item, today) {
    return item && item.start && item.end && item.start <= today && today <= item.end;
  }

  function pickWeighted(items) {
    var total = 0;
    items.forEach(function (i) { total += Math.max(1, Number(i.weight) || 1); });
    var roll = Math.random() * total;
    for (var k = 0; k < items.length; k++) {
      roll -= Math.max(1, Number(items[k].weight) || 1);
      if (roll <= 0) return items[k];
    }
    return items[items.length - 1];
  }

  function esc(value) {
    var div = document.createElement("div");
    div.textContent = String(value == null ? "" : value);
    return div.innerHTML;
  }

  function clickUrl(base, ad) {
    return base ? base.replace(/\/$/, "") + "/go/" + encodeURIComponent(ad.id) : ad.url;
  }

  function beacon(base, ad, slot, sample) {
    if (!base) return;
    var factor = Math.max(1, Number(sample) || 1);
    if (Math.random() >= 1 / factor) return;
    var img = new Image(1, 1);
    img.src = base.replace(/\/$/, "") + "/px/" + encodeURIComponent(ad.id) +
      ".gif?s=" + encodeURIComponent(slot) + "&t=" + Date.now();
  }

  // Maximum rendered height per slot. Creatives are contained within these
  // bounds (letterboxed, never cropped or stretched), so a portrait image
  // accidentally assigned to a horizontal slot degrades gracefully instead
  // of dominating the page. The sidebar accepts tall 300x600 creatives.
  var SLOT_MAX_HEIGHT = {
    "home-leaderboard": 120,
    "article-leaderboard": 120,
    "home-billboard": 280,
    "article-incontent": 280,
    "article-mrec": 620
  };

  // Horizontal slots run the full width of the page column. A 970px creative
  // in a 1220px column previously sat centred at its natural size, leaving
  // 125px of empty slot either side. These slots stretch the creative to the
  // column width instead - aspect ratio preserved, so it is scaled rather than
  // distorted, and the slot's max-height still applies.
  //
  // Supply the creative at the column width (1220px, or 2440px for sharpness
  // on high-density screens): anything narrower is upscaled, and text in a
  // banner softens noticeably past about 25%.
  var FULL_WIDTH_SLOTS = {
    "home-leaderboard": true,
    "article-leaderboard": true,
    "home-billboard": true
  };

  // Match on the data attribute OR the slot's CSS class.
  //
  // Pages generated before the attribute existed are never rebuilt -
  // generate_pages.py only writes the articles currently in articles.json,
  // so the archive keeps whatever template produced it. Those pages carry
  // <div class="ad-slot ad-slot-leaderboard"> with no data-ad-slot, which
  // this script could not see: the slot stayed a dashed placeholder and the
  // inventory was simply lost. Reading the class as a fallback means every
  // page works regardless of when it was written, with no rewrite needed.
  var SLOT_BY_CLASS = {
    "ad-slot-leaderboard": "article-leaderboard",
    "ad-slot-incontent": "article-incontent",
    "ad-slot-mrec": "article-mrec"
  };

  function slotNameFor(container) {
    var named = container.getAttribute("data-ad-slot");
    if (named) return named;
    for (var css in SLOT_BY_CLASS) {
      if (container.classList.contains(css)) return SLOT_BY_CLASS[css];
    }
    return "";
  }

  var selector = "[data-ad-slot], .ad-slot-leaderboard, .ad-slot-incontent, .ad-slot-mrec";

  function renderBanner(container, ad, base, sample) {
    var slot = slotNameFor(container);
    var maxH = SLOT_MAX_HEIGHT[slot] || 300;
    var widthRule = FULL_WIDTH_SLOTS[slot] ? "width:100%;" : "width:auto;";
    var imgStyle = "max-width:100%;max-height:" + maxH + "px;" + widthRule + "height:auto;display:block;margin:0 auto";
    var src = esc(ad.image);
    var mobile = ad.image_mobile ? esc(ad.image_mobile) : "";
    var picture = mobile
      ? '<picture><source media="(max-width: 640px)" srcset="' + mobile + '">' +
        '<img src="' + src + '" alt="' + esc(ad.alt || ad.advertiser || "Advertisement") + '" loading="lazy" style="' + imgStyle + '"></picture>'
      : '<img src="' + src + '" alt="' + esc(ad.alt || ad.advertiser || "Advertisement") + '" loading="lazy" style="' + imgStyle + '">';
    container.innerHTML =
      '<a href="' + esc(clickUrl(base, ad)) + '" rel="sponsored noopener" target="_blank" ' +
      'style="display:block;position:relative;line-height:0;text-align:center">' + picture +
      '<span style="position:absolute;top:0;left:0;background:#111;color:#fff;font:700 9px/1 Arial,sans-serif;' +
      'letter-spacing:.08em;text-transform:uppercase;padding:3px 6px">Advertisement</span></a>';
    container.removeAttribute("aria-hidden");
    container.setAttribute("role", "complementary");
    container.setAttribute("aria-label", "Advertisement: " + (ad.advertiser || ""));
    container.classList.add("ad-live");
    container.style.height = "auto";
    beacon(base, ad, slot, sample);
  }

  function renderDirectory(card, listing, base, sample) {
    var lines = [
      '<span class="sponsored">Sponsored listing</span>',
      "<h3>" + esc(listing.category) + "</h3>",
      '<p><strong>' + esc(listing.name) + "</strong><br>" + esc(listing.blurb || "") + "</p>"
    ];
    if (listing.phone) {
      lines.push('<a href="tel:' + esc(String(listing.phone).replace(/\s+/g, "")) + '">' + esc(listing.phone) + "</a>");
    }
    if (listing.url) {
      lines.push(' <a href="' + esc(clickUrl(base, listing)) + '" rel="sponsored noopener" target="_blank">Visit website</a>');
    }
    card.innerHTML = lines.join("");
    card.classList.add("ad-live");
    beacon(base, listing, "directory", sample);
  }

  // Kept so slots created after load can still be filled. The homepage opens
  // articles in a modal built from JavaScript, so its advert slots do not
  // exist when this script first runs.
  var loaded = null;

  function init(data) {
    if (data && typeof data === "object") loaded = data;
    if (!data || typeof data !== "object") return;
    var config = data.config || {};
    var base = String(config.tracker_base || "").trim();
    var sample = config.impression_sample;
    var today = todayKey();

    var placements = (data.placements || []).filter(function (p) { return isActive(p, today); });
    document.querySelectorAll(selector).forEach(function (container) {
      // Already carrying a creative: leave it. Re-rendering would reroll the
      // rotation and fire a second impression for a slot nobody re-viewed.
      if (container.classList.contains("ad-live")) return;
      var slot = slotNameFor(container);
      if (!slot) return;
      var candidates = placements.filter(function (p) { return p.slot === slot; });
      if (!candidates.length) {
        // Leaves the placeholder in place. Logged because a slot silently
        // staying empty is indistinguishable from a rendering fault, and that
        // cost a lot of time to tell apart.
        if (window.console) console.warn("[ads] no placement for slot:", slot);
        return;
      }
      try {
        renderBanner(container, pickWeighted(candidates), base, sample);
      } catch (error) {
        // One bad creative must not stop the slots after it. forEach aborts on
        // a throw, so without this a single failure emptied the rest of the page.
        if (window.console) console.warn("[ads] could not render slot:", slot, error);
      }
    });

    var listings = (data.directory || []).filter(function (d) { return isActive(d, today); });
    document.querySelectorAll("[data-ad-directory]").forEach(function (card) {
      var category = card.getAttribute("data-category") || "";
      var sold = listings.filter(function (d) { return d.category === category; });
      if (sold.length) renderDirectory(card, pickWeighted(sold), base, sample);
    });
  }

  // Call after injecting markup that contains [data-ad-slot] containers.
  // Safe to call repeatedly: live slots are skipped.
  window.rdFillAds = function () {
    if (loaded) init(loaded);
  };

  // Fill slots the moment they appear, without anyone having to call us.
  //
  // The homepage opens articles in a modal built from JavaScript. That relied
  // on openArticle() calling rdFillAds, which meant index.html and this file
  // had to be in step: if a reader had an older copy of either cached, the
  // call was a no-op and every slot in the modal stayed a placeholder - with
  // no error, because the call site guards on the function existing. Watching
  // the DOM removes the dependency entirely.
  if (typeof MutationObserver === "function") {
    var pending = false;
    new MutationObserver(function (records) {
      if (pending || !loaded) return;
      for (var i = 0; i < records.length; i++) {
        var added = records[i].addedNodes;
        for (var j = 0; j < added.length; j++) {
          var node = added[j];
          if (node.nodeType !== 1) continue;
          if (node.matches(selector) || node.querySelector(selector)) {
            // Coalesce: a single innerHTML assignment fires many records.
            pending = true;
            requestAnimationFrame(function () { pending = false; init(loaded); });
            return;
          }
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  // Keep the Democracy service compact until a reader asks for one of its
  // sections. The existing homepage code still fetches and renders the data;
  // this layer only controls disclosure, so it remains compatible with cached
  // versions of index.html.
  function initialiseDemocracyDisclosure() {
    var section = document.getElementById("democracy");
    if (!section || section.getAttribute("data-disclosure-ready") === "true") return;

    var tabs = Array.prototype.slice.call(section.querySelectorAll(".dem-tab"));
    var status = section.querySelector("[data-dem-status]");
    var grid = section.querySelector("[data-dem-grid]");
    var wardPick = section.querySelector("#dem-ward-pick");
    var note = section.querySelector(".dem-note");
    var openKey = "";

    if (!tabs.length || !status || !grid) return;
    section.setAttribute("data-disclosure-ready", "true");

    function setContentVisible(visible) {
      [status, grid, note].forEach(function (element) {
        if (element) element.style.display = visible ? "" : "none";
      });
      if (!visible && wardPick) wardPick.style.display = "none";
      if (visible && wardPick) wardPick.style.removeProperty("display");
    }

    function setCollapsedState() {
      openKey = "";
      tabs.forEach(function (tab) {
        tab.classList.remove("active");
        tab.setAttribute("aria-selected", "false");
        tab.setAttribute("aria-expanded", "false");
      });
      grid.setAttribute("aria-hidden", "true");
      setContentVisible(false);
    }

    tabs.forEach(function (tab) {
      tab.setAttribute("aria-expanded", "false");
      tab.addEventListener("click", function () {
        var key = tab.getAttribute("data-dem") || "";
        var shouldClose = openKey === key;

        // Let the homepage's existing tab handler render the requested data,
        // then apply the disclosure state after that handler has completed.
        window.setTimeout(function () {
          if (shouldClose) {
            setCollapsedState();
            return;
          }

          openKey = key;
          tabs.forEach(function (item) {
            var selected = item === tab;
            item.classList.toggle("active", selected);
            item.setAttribute("aria-selected", selected ? "true" : "false");
            item.setAttribute("aria-expanded", selected ? "true" : "false");
          });
          grid.setAttribute("aria-hidden", "false");
          setContentVisible(true);
        }, 0);
      });
    });

    // Run after the homepage's own initialisation so its default Petitions
    // render cannot leave the content visible on first paint.
    window.setTimeout(setCollapsedState, 0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialiseDemocracyDisclosure, { once: true });
  } else {
    initialiseDemocracyDisclosure();
  }

  fetch("/adverts.json", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(init)
    .catch(function () { /* placeholders stay */ });
})();

/* Homepage What's On compatibility fix.
   The main feed previously treated only source_kind === "event" as an event,
   and the renderer then restricted the grid again to category === "events".
   That excluded genuine dated listings filed as sport/community and made the
   time-filter buttons appear broken. Keep this here as a compatibility layer
   for cached homepage markup until the inline homepage script is split out. */
(function () {
  "use strict";

  if (typeof window.renderEvents !== "function") return;

  function eventStart(value) {
    var start = new Date(value || "").getTime();
    return Number.isFinite(start) ? start : NaN;
  }

  window.isCurrentOrFutureEvent = function (article) {
    var start = eventStart(article && article.event_start_at);
    return Number.isFinite(start) && start >= Date.now() - (12 * 60 * 60 * 1000);
  };

  function weekendBounds(now) {
    var start = new Date(now);
    start.setHours(0, 0, 0, 0);
    var day = start.getDay();
    var daysToSaturday;
    if (day === 6) daysToSaturday = 0;
    else if (day === 0) daysToSaturday = -1;
    else daysToSaturday = 6 - day;
    start.setDate(start.getDate() + daysToSaturday);

    var end = new Date(start);
    end.setDate(end.getDate() + 2);
    return { start: start.getTime(), end: end.getTime() };
  }

  function tagsFor(story, date) {
    var tags = [];
    var text = ((story.title || "") + " " + (story.summary || "")).toLowerCase();
    var now = new Date();
    var time = date && Number.isFinite(date.getTime()) ? date.getTime() : NaN;

    if (Number.isFinite(time)) {
      if (typeof window.ukDateKey === "function" && ukDateKey(date) === ukDateKey(now)) {
        tags.push("tonight");
      } else if (date.toDateString() === now.toDateString()) {
        tags.push("tonight");
      }

      if (time >= now.getTime() - (12 * 60 * 60 * 1000) &&
          time <= now.getTime() + (7 * 24 * 60 * 60 * 1000)) {
        tags.push("week");
      }

      var weekend = weekendBounds(now);
      if (time >= weekend.start && time < weekend.end) tags.push("weekend");
    }

    if (/\bfree\b|no charge|free entry/.test(text)) tags.push("free");
    if (/family|children|kids|all ages/.test(text)) tags.push("family");
    return tags;
  }

  window.eventTagsForStory = tagsFor;

  window.renderEvents = function (filter) {
    var active = document.querySelector("[data-event-filter].active");
    var selected = filter || (active && active.dataset.eventFilter) || "all";

    var liveEvents = stories
      .filter(function (story) {
        var start = eventStart(story.eventStartAt);
        return story.category === "events" || Number.isFinite(start);
      })
      .map(function (story) {
        var parsedDate = story.eventStartAt ? new Date(story.eventStartAt) : null;
        var validDate = parsedDate && Number.isFinite(parsedDate.getTime()) ? parsedDate : null;
        return { story: story, date: validDate, tags: tagsFor(story, validDate) };
      })
      .filter(function (item) {
        return !item.date || item.date.getTime() >= Date.now() - (12 * 60 * 60 * 1000);
      })
      .sort(function (a, b) {
        return (a.date ? a.date.getTime() : Infinity) - (b.date ? b.date.getTime() : Infinity);
      });

    var list = selected === "all"
      ? liveEvents
      : liveEvents.filter(function (item) { return item.tags.indexOf(selected) !== -1; });

    var grid = document.getElementById("events-grid");
    if (!grid) return;
    if (!list.length) {
      grid.innerHTML = '<div class="no-results"><strong>No verified events match this filter yet.</strong><br>The event feed is checking public Rochdale listings.</div>';
      return;
    }

    grid.innerHTML = list.slice(0, 12).map(function (item) {
      var story = item.story;
      var date = item.date;
      var fallback = story.imageFallback || stockImage("events");
      var dateLabel = date ? formatEventDate(date) : "Date shown in full listing";
      return '<article class="event-card">' +
        '<img src="' + story.image + '" alt="" onerror="this.onerror=null;this.src=\'' + fallback + '\'">' +
        '<div class="event-body">' +
          '<div class="event-date">' + dateLabel + '</div>' +
          '<h3>' + story.title + '</h3>' +
          '<p>' + story.summary + '</p>' +
          '<div class="event-facts">' +
            (story.eventLocation ? '<span><strong>Location:</strong> ' + story.eventLocation + '</span>' : '') +
            '<span><strong>Area:</strong> ' + areaLabel(story.area) + '</span>' +
          '</div>' +
          (story.sourceUrl ? '<a class="event-cta" href="' + story.sourceUrl + '" target="_blank" rel="noopener noreferrer">View organiser listing</a>' : '') +
        '</div>' +
      '</article>';
    }).join("");
  };

  // Re-read the feed once so events discarded by the old source_kind check
  // are restored immediately rather than waiting for the next one-minute poll.
  if (typeof window.loadArticleFeed === "function") {
    window.setTimeout(function () { loadArticleFeed({ quiet: true }); }, 0);
  } else {
    window.renderEvents();
  }
})();
