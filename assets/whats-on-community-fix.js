/* Rochdale Daily What's On community-event compatibility layer.
   Keeps approved reader submissions merged after the one-minute news refresh,
   lets "All upcoming" render the full approved event list, and keeps the
   Events section collapsed until a reader explicitly opens it. */
(function () {
  "use strict";

  if (typeof window.renderEvents !== "function") return;

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
      if (typeof ukDateKey === "function" && ukDateKey(date) === ukDateKey(now)) {
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

  function initialiseEventsDisclosure() {
    var grid = document.getElementById("events-grid");
    if (!grid) return;

    var section = grid.closest("section") || grid.parentElement;
    if (!section || section.getAttribute("data-events-disclosure-ready") === "true") return;

    var heading = section.querySelector("h1, h2, h3, .section-title");
    if (!heading) return;

    var filterNodes = Array.prototype.slice.call(section.querySelectorAll("[data-event-filter]"));
    var filterContainers = [];
    filterNodes.forEach(function (node) {
      var parent = node.parentElement;
      if (parent && filterContainers.indexOf(parent) === -1) filterContainers.push(parent);
    });

    section.setAttribute("data-events-disclosure-ready", "true");
    heading.setAttribute("role", "button");
    heading.setAttribute("tabindex", "0");
    heading.setAttribute("aria-controls", "events-grid");
    heading.setAttribute("aria-expanded", "false");
    heading.style.cursor = "pointer";
    heading.style.userSelect = "none";

    var indicator = document.createElement("span");
    indicator.setAttribute("aria-hidden", "true");
    indicator.textContent = "  ▾";
    indicator.style.fontFamily = "Arial, sans-serif";
    indicator.style.fontSize = ".7em";
    heading.appendChild(indicator);

    function setOpen(open) {
      grid.style.display = open ? "" : "none";
      grid.setAttribute("aria-hidden", open ? "false" : "true");
      filterContainers.forEach(function (container) {
        container.style.display = open ? "" : "none";
      });
      heading.setAttribute("aria-expanded", open ? "true" : "false");
      indicator.textContent = open ? "  ▴" : "  ▾";
    }

    function toggle() {
      setOpen(heading.getAttribute("aria-expanded") !== "true");
    }

    heading.addEventListener("click", toggle);
    heading.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });

    setOpen(false);
  }

  async function mergeApprovedCommunityEvents() {
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

      /* The normaliser does not retain community_submitted, so use the API's
         source label to remove stale copies before inserting the fresh list. */
      var baseStories = stories.filter(function (story) {
        return story.sourceName !== 'Reader submission';
      });
      stories = orderArticles(baseStories.concat(incoming));

      var active = document.querySelector('[data-event-filter].active');
      window.renderEvents(active ? active.dataset.eventFilter : 'all');
    } catch (error) {
      /* Community events are additive; never break the homepage on API failure. */
    }
  }

  initialiseEventsDisclosure();
  mergeApprovedCommunityEvents();
  window.setInterval(mergeApprovedCommunityEvents, 61 * 1000);
  window.addEventListener('online', mergeApprovedCommunityEvents);
  document.addEventListener('visibilitychange', function () {
    if (!document.hidden) mergeApprovedCommunityEvents();
  });
})();
