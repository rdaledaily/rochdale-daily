/* Rochdale Daily What's On community-event compatibility layer.
   Keeps approved reader submissions merged after the one-minute news refresh
   and lets "All upcoming" render the full approved event list.

   It used to collapse the whole Events section behind a click on the heading
   (added 8 Aug). That hid every event from every reader who did not know the
   heading was a button -- on 10 Sep the section showed nothing but the "Add
   an event" box while eight upcoming events sat behind it. The disclosure is
   gone; the events are simply shown. */
(function () {
  "use strict";

  function eventStart(value) {
    var start = new Date(value || "").getTime();
    return Number.isFinite(start) ? start : NaN;
  }

  function weekendBounds(now) {
    var start = new Date(now);
    start.setHours(0, 0, 0, 0);
    var day = start.getDay();
    var daysToSaturday = day === 6 ? 0 : (day === 0 ? -1 : 6 - day);
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

  function installEventRenderer() {
    if (window.__rdEventRendererInstalled) return;
    if (typeof window.stories === "undefined") return;

    window.__rdEventRendererInstalled = true;
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
          return !item.date || item.date.getTime() >= Date.now() - 12 * 60 * 60 * 1000;
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

      var rendered = selected === "all" ? list : list.slice(0, 24);
      grid.innerHTML = rendered.map(function (item) {
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
  }

  function initialiseEventsDisclosure() {
    /* Intentionally does nothing. See the header comment. If a disclosure is
       ever wanted again it must default to OPEN, not closed. */
    return true;
  }

  async function mergeApprovedCommunityEvents() {
    if (typeof window.normaliseArticle !== "function" || typeof window.stories === "undefined") return;
    try {
      var response = await fetch('/api/events?v=' + Date.now(), {
        cache: 'no-store',
        headers: { Accept: 'application/json' }
      });
      if (!response.ok) return;
      var payload = await response.json();
      if (!payload || !Array.isArray(payload.events)) return;

      var incoming = payload.events.map(function (event, index) {
        return normaliseArticle(event, index);
      });

      var baseStories = stories.filter(function (story) {
        return story.sourceName !== 'Reader submission';
      });
      stories = orderArticles(baseStories.concat(incoming));

      var active = document.querySelector('[data-event-filter].active');
      if (typeof window.renderEvents === "function") {
        window.renderEvents(active ? active.dataset.eventFilter : 'all');
      }
    } catch (error) {
      /* Community events are additive; never break the homepage on API failure. */
    }
  }

  function boot() {
    installEventRenderer();
    if (!initialiseEventsDisclosure()) {
      window.setTimeout(initialiseEventsDisclosure, 50);
      window.setTimeout(initialiseEventsDisclosure, 250);
      window.setTimeout(initialiseEventsDisclosure, 1000);
    }
    window.setTimeout(installEventRenderer, 0);
    window.setTimeout(installEventRenderer, 250);
    window.setTimeout(mergeApprovedCommunityEvents, 300);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
  window.addEventListener("load", initialiseEventsDisclosure, { once: true });

  window.setInterval(mergeApprovedCommunityEvents, 61 * 1000);
  window.addEventListener('online', mergeApprovedCommunityEvents);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) mergeApprovedCommunityEvents();
  });
})();
