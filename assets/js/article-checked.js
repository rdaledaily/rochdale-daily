/* Shows "Checked by the newsdesk HH:MM" for a check recorded since the page
 * was last built. The built page carries the line itself once the next
 * newsroom run has read the check; this only covers the gap. A check exists
 * only when the editor tapped "Checked" on /checked.html, and the time is the
 * server's (functions/api/checks.js). */
(function () {
  "use strict";
  var main = document.querySelector(".article-main[data-live-slug]");
  var byline = document.querySelector(".article-byline");
  if (!main || !byline || byline.querySelector(".article-checked")) return;
  var slug = main.getAttribute("data-live-slug") || "";
  if (!/^[a-z0-9][a-z0-9-]{3,180}$/.test(slug)) return;

  function label(iso) {
    var when = new Date(iso);
    if (isNaN(when.getTime())) return "";
    var opts = { timeZone: "Europe/London", hour: "2-digit", minute: "2-digit", hour12: false };
    var time = new Intl.DateTimeFormat("en-GB", opts).format(when);
    var zoneName = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", timeZoneName: "short" })
      .formatToParts(when).filter(function (p) { return p.type === "timeZoneName"; })[0];
    // en-GB names London's zone "GMT" or "BST"; some engines give "GMT+1".
    var zone = zoneName && (zoneName.value === "BST" || zoneName.value === "GMT+1") ? "BST" : "GMT";
    var day = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", day: "numeric", month: "short" }).format(when);
    var today = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", day: "numeric", month: "short" }).format(new Date());
    return "Checked by the newsdesk " + (day === today ? "" : day + " ") + time + " " + zone;
  }

  fetch("/api/checks?slug=" + encodeURIComponent(slug), { headers: { Accept: "application/json" } })
    .then(function (response) { return response.ok ? response.json() : null; })
    .then(function (data) {
      if (!data || !data.checked_at || byline.querySelector(".article-checked")) return;
      var text = label(data.checked_at);
      if (!text) return;
      var span = document.createElement("span");
      span.className = "article-checked";
      var link = document.createElement("a");
      link.href = "/editorial-standards#checking";
      link.style.color = "inherit";
      link.style.textDecoration = "none";
      var tick = document.createElement("span");
      tick.setAttribute("aria-hidden", "true");
      tick.style.color = "#137a45";
      tick.textContent = "\u2713 ";
      link.appendChild(tick);
      var time = document.createElement("time");
      time.setAttribute("datetime", data.checked_at);
      time.textContent = text;
      link.appendChild(time);
      span.appendChild(link);
      var share = byline.querySelector(".share-icons, .share-row");
      byline.insertBefore(span, share || null);
    })
    .catch(function () {});
})();
