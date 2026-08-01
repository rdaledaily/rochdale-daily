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

  function renderBanner(container, ad, base, sample) {
    var slot = container.getAttribute("data-ad-slot");
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
    document.querySelectorAll("[data-ad-slot]").forEach(function (container) {
      // Already carrying a creative: leave it. Re-rendering would reroll the
      // rotation and fire a second impression for a slot nobody re-viewed.
      if (container.classList.contains("ad-live")) return;
      var slot = container.getAttribute("data-ad-slot");
      var candidates = placements.filter(function (p) { return p.slot === slot; });
      if (candidates.length) renderBanner(container, pickWeighted(candidates), base, sample);
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
          if (node.matches("[data-ad-slot]") || node.querySelector("[data-ad-slot]")) {
            // Coalesce: a single innerHTML assignment fires many records.
            pending = true;
            requestAnimationFrame(function () { pending = false; init(loaded); });
            return;
          }
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  fetch("/adverts.json", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(init)
    .catch(function () { /* placeholders stay */ });
})();
