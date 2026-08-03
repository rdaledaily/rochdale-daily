(function () {
  "use strict";

  var host = document.getElementById("community-poll");
  if (!host || host.getAttribute("data-poll-v2") === "1") return;
  host.setAttribute("data-poll-v2", "1");

  var API = "/api/poll";
  var TOKEN_KEY = "rd-community-poll-voter";
  var payload = null;
  var selected = "";
  var busy = false;
  var refreshTimer = null;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>\"]/g, function (character) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;"
      }[character];
    });
  }

  function voterId() {
    var id = "";
    try {
      id = window.localStorage.getItem(TOKEN_KEY) || "";
      if (!id) {
        if (window.crypto && window.crypto.getRandomValues) {
          var bytes = new Uint8Array(24);
          window.crypto.getRandomValues(bytes);
          var parts = [];
          for (var i = 0; i < bytes.length; i += 1) {
            parts.push(bytes[i].toString(16).padStart(2, "0"));
          }
          id = parts.join("");
        } else {
          id = String(Date.now()) + "-" + Math.random().toString(16).slice(2);
        }
        window.localStorage.setItem(TOKEN_KEY, id);
      }
    } catch (error) {
      id = String(Date.now()) + "-" + Math.random().toString(16).slice(2);
    }
    return id;
  }

  function timeLeft(value) {
    var milliseconds = Date.parse(value) - Date.now();
    if (!isFinite(milliseconds) || milliseconds <= 0) return "Voting closed";
    var days = Math.floor(milliseconds / 86400000);
    var hours = Math.floor((milliseconds % 86400000) / 3600000);
    var minutes = Math.floor((milliseconds % 3600000) / 60000);
    if (days) return days + " day" + (days === 1 ? "" : "s") + ", " + hours + " hour" + (hours === 1 ? "" : "s") + " left";
    if (hours) return hours + " hour" + (hours === 1 ? "" : "s") + ", " + minutes + " min left";
    return Math.max(1, minutes) + " min left";
  }

  function sortedResults(results) {
    return (results.options || []).slice().sort(function (a, b) {
      return Number(b.votes || 0) - Number(a.votes || 0);
    });
  }

  function leaderText(results) {
    if (!results || !results.total) return "Be the first to vote";
    var sorted = sortedResults(results);
    if (!sorted.length) return "Be the first to vote";
    var secondVotes = sorted[1] ? Number(sorted[1].votes || 0) : 0;
    var margin = Number(sorted[0].votes || 0) - secondVotes;
    if (!margin) return "The lead is tied";
    return sorted[0].label + " leads by " + margin + " vote" + (margin === 1 ? "" : "s");
  }

  function findResult(results, optionId) {
    var options = results.options || [];
    for (var i = 0; i < options.length; i += 1) {
      if (String(options[i].id) === String(optionId)) return options[i];
    }
    return { votes: 0, percentage: 0 };
  }

  function render(message) {
    if (!payload || !payload.poll || !payload.state || !payload.results) {
      showError("The community poll is temporarily unavailable.");
      return;
    }

    var poll = payload.poll;
    var state = payload.state;
    var results = payload.results;
    var options = poll.options || [];
    var choices = "";

    for (var i = 0; i < options.length; i += 1) {
      var option = options[i];
      var result = findResult(results, option.id);
      var active = selected === String(option.id);
      var percentage = Number(result.percentage || 0);
      var votes = Number(result.votes || 0);
      choices += '<button type="button" class="rd-poll-choice' + (active ? ' is-selected' : '') + '" data-poll-option="' + esc(option.id) + '" aria-pressed="' + (active ? 'true' : 'false') + '">' +
        '<span class="rd-poll-radio" aria-hidden="true"></span>' +
        '<span class="rd-poll-choice-copy"><strong>' + esc(option.label) + '</strong>' +
        '<span class="rd-poll-choice-result">' + percentage + '% (' + votes + ')</span>' +
        '<span class="rd-poll-track" aria-hidden="true"><span style="width:' + Math.max(percentage, votes ? 1 : 0) + '%"></span></span></span>' +
        '</button>';
    }

    var total = Number(results.total || 0);
    host.innerHTML = '<div class="rd-poll-shell">' +
      '<div class="rd-poll-topline"><span class="rd-poll-kicker">Rochdale Daily community poll</span><span class="rd-poll-countdown">' + esc(timeLeft(state.ends_at)) + '</span></div>' +
      '<div class="rd-poll-grid"><div class="rd-poll-main"><h2>' + esc(poll.title) + '</h2><p class="rd-poll-intro">' + esc(poll.description) + '</p>' +
      '<div class="rd-poll-options">' + choices + '</div><p class="rd-poll-message" role="status" aria-live="polite">' + esc(message || "") + '</p>' +
      '<div class="rd-poll-actions">' + (state.open ? '<button class="rd-poll-vote" type="button"' + (busy ? ' disabled' : '') + '>' + (busy ? 'Submitting…' : 'Vote now') + '</button>' : '') + '</div></div>' +
      '<aside class="rd-poll-summary"><span class="rd-poll-total">' + total.toLocaleString("en-GB") + ' vote' + (total === 1 ? '' : 's') + '</span><strong>' + esc(leaderText(results)) + '</strong></aside></div>' +
      '<p class="rd-poll-note">' + esc(poll.source_note || "Informal reader poll.") + '</p></div>';

    var optionButtons = host.querySelectorAll("[data-poll-option]");
    for (var j = 0; j < optionButtons.length; j += 1) {
      optionButtons[j].addEventListener("click", function () {
        selected = this.getAttribute("data-poll-option") || "";
        render("");
      });
    }

    var voteButton = host.querySelector(".rd-poll-vote");
    if (voteButton) voteButton.addEventListener("click", submit);
  }

  function showError(message) {
    host.innerHTML = '<div class="rd-poll-shell"><p class="rd-poll-error">' + esc(message) + '</p></div>';
  }

  function request(method, body, callback) {
    var xhr = new XMLHttpRequest();
    xhr.open(method, API, true);
    xhr.setRequestHeader("Accept", "application/json");
    if (method === "POST") xhr.setRequestHeader("Content-Type", "application/json");
    xhr.timeout = 12000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) return;
      var data = null;
      try { data = JSON.parse(xhr.responseText || "null"); } catch (error) { data = null; }
      callback(xhr.status >= 200 && xhr.status < 300, data, xhr.status);
    };
    xhr.onerror = function () { callback(false, null, 0); };
    xhr.ontimeout = function () { callback(false, null, 0); };
    xhr.send(body ? JSON.stringify(body) : null);
  }

  function submit() {
    if (!selected) {
      render("Choose an option before voting.");
      return;
    }
    if (busy) return;
    busy = true;
    render("");

    request("POST", {
      poll_id: payload.poll.id,
      option_id: selected,
      voter_id: voterId()
    }, function (ok, data) {
      busy = false;
      if (data && data.poll && data.state && data.results) payload = data;
      if (!data) {
        render("The poll is temporarily unavailable.");
        return;
      }
      render(ok ? "Your vote has been counted." : (data.error || "Your vote could not be recorded."));
    });
  }

  function load(firstLoad) {
    request("GET", null, function (ok, data) {
      if (!ok || !data || !data.poll || !data.state || !data.results) {
        if (firstLoad) showError("The community poll is temporarily unavailable. Please try again shortly.");
        return;
      }
      payload = data;
      render("");
    });
  }

  load(true);
  refreshTimer = window.setInterval(function () { load(false); }, 20000);
  window.addEventListener("beforeunload", function () {
    if (refreshTimer) window.clearInterval(refreshTimer);
  });
})();
