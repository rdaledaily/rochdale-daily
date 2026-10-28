/* Reasons to come back, built on the research rather than on tricks.
 *
 * Medill's study of 13 TB of local-paper reader data found visit FREQUENCY
 * was the strongest predictor of keeping a reader; reading more articles per
 * visit was not. Their follow-up put it at ten times more important. So this
 * file serves the returning reader, and nothing here manufactures urgency:
 *
 *  1. "New since your last visit": how many stories are new to THIS reader,
 *     with a NEW mark on those headlines. Honest: it says so when nothing is
 *     new, and counts only stories published since their last visit.
 *  2. A one-line invitation to the morning briefing for someone who has come
 *     back three times in a fortnight and has not signed up (newsletters were
 *     Badische Zeitung's habit builder: about 7% of site sessions).
 *  3. Rochdale AFC's next confirmed match, linking to the matchday hub.
 *
 * Everything is stored on the reader's own device (last visit time, visit
 * days, whether they signed up or dismissed the invitation). Nothing is sent
 * anywhere.
 */
(function () {
  "use strict";
  var GAP_MS = 30 * 60 * 1000;          // a new visit after 30 minutes away
  var KEY_LAST = "rd_last_visit";
  var KEY_PREV = "rd_prev_visit";
  var KEY_DAYS = "rd_visit_days";
  var KEY_SUB = "rd_newsletter_done";

  function get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }
  function set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } }

  var now = Date.now();
  var last = Number(get(KEY_LAST)) || 0;
  var prev = Number(get(KEY_PREV)) || 0;
  if (last && now - last > GAP_MS) {
    prev = last;                         // a new visit: compare with the last one
    set(KEY_PREV, String(prev));
  }
  set(KEY_LAST, String(now));
  window.addEventListener("pagehide", function () { set(KEY_LAST, String(Date.now())); });

  // Distinct days visited in the last 14 (for the newsletter invitation).
  var today = new Date().toISOString().slice(0, 10);
  var days = [];
  try { days = JSON.parse(get(KEY_DAYS) || "[]"); } catch (e) { days = []; }
  days = days.filter(function (d) { return typeof d === "string" && Date.parse(d) > now - 14 * 864e5; });
  if (days.indexOf(today) === -1) days.push(today);
  set(KEY_DAYS, JSON.stringify(days.slice(-14)));

  document.addEventListener("submit", function (event) {
    if (event.target && /newsletter/i.test(event.target.id || "")) set(KEY_SUB, "1");
  }, true);

  function clock(ms) {
    return new Intl.DateTimeFormat("en-GB", { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: "Europe/London" }).format(new Date(ms));
  }

  /* 1 + 2: the line under "Live now" ----------------------------------- */
  var line = document.getElementById("since-last");
  var shown = false;
  window.addEventListener("rd:feed", function (event) {
    if (!line || !prev) return;
    var items = (event.detail || []).filter(function (s) {
      return s && s.slug && Number.isFinite(s.minutesAgo) && now - s.minutesAgo * 60000 > prev;
    });
    var fresh = {};
    items.forEach(function (s) { fresh[s.slug] = true; });
    markNew(fresh);
    if (shown) return;
    shown = true;
    line.textContent = "";
    var text = items.length
      ? (items.length === 1 ? "1 new story" : items.length + " new stories") + " since your last visit (" + clock(prev) + "). "
      : "Nothing new since your last visit (" + clock(prev) + "). ";
    line.appendChild(document.createTextNode(text));
    if (days.length >= 3 && !get(KEY_SUB)) {
      var a = document.createElement("a");
      a.href = "#newsletter";
      a.textContent = "Get the morning briefing by email";
      line.appendChild(a);
    }
    line.hidden = false;
  });

  function markNew(fresh) {
    var root = document.getElementById("main-content");
    if (!root) return;
    root.querySelectorAll('a[href*="articles/"]').forEach(function (a) {
      var m = (a.getAttribute("href") || "").match(/articles\/([a-z0-9-]+)/);
      if (!m || !fresh[m[1]] || a.querySelector(".rd-new-badge")) return;
      var title = a.querySelector(".latest-title, .lead-headline, .secondary-headline, .card-headline, h2, h3") || a;
      var badge = document.createElement("span");
      badge.className = "rd-new-badge";
      badge.textContent = "New";
      title.insertBefore(badge, title.firstChild);
    });
  }

  /* 3: Rochdale AFC's next confirmed match ------------------------------ */
  var strip = document.getElementById("afc-strip");
  if (strip) {
    fetch("/afc_fixtures.json").then(function (r) { return r.ok ? r.json() : null; }).then(function (data) {
      var rows = (data && data.fixtures) || [];
      var todayKey = new Intl.DateTimeFormat("en-CA", { timeZone: "Europe/London" }).format(new Date());
      var next = rows.filter(function (f) {
        return f && f.verified === true && /^https:\/\//.test(f.source_url || "") && !f.result && String(f.date) >= todayKey;
      }).sort(function (a, b) { return String(a.date).localeCompare(String(b.date)); })[0];
      if (!next) return;
      var home = String(next.venue).toLowerCase() === "home";
      strip.querySelector(".afc-strip-match").textContent = home ? "Rochdale v " + next.opponent : next.opponent + " v Rochdale";
      var day = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "Europe/London" })
        .format(new Date(next.date + "T12:00:00Z"));
      strip.querySelector(".afc-strip-meta").textContent = [day + (next.kickoff ? ", " + next.kickoff : ""), next.competition, next.tv].filter(Boolean).join(" · ");
      strip.hidden = false;
    }).catch(function () { /* no strip, nothing else changes */ });
  }
})();
