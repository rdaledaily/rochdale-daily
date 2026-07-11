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

  function renderBanner(container, ad, base, sample) {
    var slot = container.getAttribute("data-ad-slot");
    var maxH = SLOT_MAX_HEIGHT[slot] || 300;
    var imgStyle = "max-width:100%;max-height:" + maxH + "px;width:auto;height:auto;display:block;margin:0 auto";
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

  function init(data) {
    if (!data || typeof data !== "object") return;
    var config = data.config || {};
    var base = String(config.tracker_base || "").trim();
    var sample = config.impression_sample;
    var today = todayKey();

    var placements = (data.placements || []).filter(function (p) { return isActive(p, today); });
    document.querySelectorAll("[data-ad-slot]").forEach(function (container) {
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

  fetch("/adverts.json", { cache: "no-store" })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(init)
    .catch(function () { /* placeholders stay */ });
})();
