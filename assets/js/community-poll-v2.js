(function () {
  "use strict";

  var host = document.getElementById("community-poll");
  if (!host || host.getAttribute("data-poll-v2") === "1") return;
  host.setAttribute("data-poll-v2", "1");

  var API = "/api/poll";
  var TOKEN_KEY = "rd-community-poll-voter";
  var VOTE_KEY_PREFIX = "rd-community-poll-vote:";
  var payload = null;
  var selected = "";
  var busy = false;
  var refreshTimer = null;

  function esc(value) {
    return String(value == null ? "" : value).replace(/[&<>\"]/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;" }[character];
    });
  }

  function storageGet(key) {
    try { return window.localStorage.getItem(key) || ""; } catch (error) { return ""; }
  }

  function storageSet(key, value) {
    try { window.localStorage.setItem(key, value); } catch (error) { /* no-op */ }
  }

  function voteKey(pollId) {
    return VOTE_KEY_PREFIX + String(pollId || "");
  }

  function storedVote(pollId) {
    return storageGet(voteKey(pollId));
  }

  function voterId() {
    var id = storageGet(TOKEN_KEY);
    if (id) return id;

    if (window.crypto && window.crypto.getRandomValues) {
      var bytes = new Uint8Array(24);
      window.crypto.getRandomValues(bytes);
      var parts = [];
      for (var i = 0; i < bytes.length; i += 1) {
        var hex = bytes[i].toString(16);
        parts.push(hex.length < 2 ? "0" + hex : hex);
      }
      id = parts.join("");
    } else {
      id = String(Date.now()) + "_" + Math.random().toString(36).slice(2) + Math.random().toString(36).slice(2);
    }

    storageSet(TOKEN_KEY, id);
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

  function findResult(results, optionId) {
    var options = results.options || [];
    for (var i = 0; i < options.length; i += 1) {
      if (String(options[i].id) === String(optionId)) return options[i];
    }
    return null;
  }

  function applyOptimisticVote(data, optionId) {
    if (!data || !data.results || !optionId) return data;
    var result = findResult(data.results, optionId);
    if (!result) return data;

    var total = Number(data.results.total || 0);
    var knownVotes = Number(result.votes || 0);

    /* KV list results can lag behind a successful write. Mark one local vote
       until the backend count catches up, then percentages are recalculated. */
    if (!result._localVoteApplied) {
      result.votes = knownVotes + 1;
      result._localVoteApplied = true;
      total += 1;
      data.results.total = total;
      for (var i = 0; i < data.results.options.length; i += 1) {
        var item = data.results.options[i];
        item.percentage = total ? Math.round((Number(item.votes || 0) / total) * 1000) / 10 : 0;
      }
    }
    return data;
  }

  function leaderText(results) {
    if (!results || !results.total) return "Be the first to vote";
    var sorted = (results.options || []).slice().sort(function (a, b) {
      return Number(b.votes || 0) - Number(a.votes || 0);
    });
    if (!sorted.length) return "Be the first to vote";
    var secondVotes = sorted[1] ? Number(sorted[1].votes || 0) : 0;
    var margin = Number(sorted[0].votes || 0) - secondVotes;
    if (!margin) return "The lead is tied";
    return sorted[0].label + " leads by " + margin + " vote" + (margin === 1 ? "" : "s");
  }

  function render(message) {
    if (!payload || !payload.poll || !payload.state || !payload.results) {
      showError("The community poll is temporarily unavailable.");
      return;
    }

    var poll = payload.poll;
    var state = payload.state;
    var results = payload.results;
    var chosen = storedVote(poll.id);
    var canVote = state.open && !chosen;
    var options = poll.options || [];
    var rows = "";

    for (var i = 0; i < options.length; i += 1) {
      var option = options[i];
      var result = findResult(results, option.id) || { votes: 0, percentage: 0 };
      var active = selected === String(option.id);
      var percentage = Number(result.percentage || 0);
      var votes = Number(result.votes || 0);

      if (canVote) {
        rows += '<button type="button" class="rd-poll-choice' + (active ? ' is-selected' : '') + '" data-poll-option="' + esc(option.id) + '" aria-pressed="' + (active ? 'true' : 'false') + '">' +
          '<span class="rd-poll-radio" aria-hidden="true"></span>' +
          '<span class="rd-poll-choice-copy"><strong>' + esc(option.label) + '</strong>' +
          '<span class="rd-poll-choice-result">' + percentage + '% (' + votes + ')</span>' +
          '<span class="rd-poll-track" aria-hidden="true"><span style="width:' + Math.max(percentage, votes ? 1 : 0) + '%"></span></span></span>' +
          '</button>';
      } else {
        rows += '<div class="rd-poll-result' + (chosen === String(option.id) ? ' is-chosen' : '') + '">' +
          '<div class="rd-poll-result-head"><span>' + (chosen === String(option.id) ? '<span class="rd-poll-leader">Your vote</span>' : '') + esc(option.label) + '</span>' +
          '<strong>' + percentage + '% <small>(' + votes + ')</small></strong></div>' +
          '<div class="rd-poll-track" aria-hidden="true"><span style="width:' + Math.max(percentage, votes ? 1 : 0) + '%"></span></div></div>';
      }
    }

    var total = Number(results.total || 0);
    host.innerHTML = '<div class="rd-poll-shell">' +
      '<div class="rd-poll-topline"><span class="rd-poll-kicker">Rochdale Daily community poll</span><span class="rd-poll-countdown">' + esc(timeLeft(state.ends_at)) + '</span></div>' +
      '<div class="rd-poll-grid"><div class="rd-poll-main"><h2>' + esc(poll.title) + '</h2><p class="rd-poll-intro">' + esc(poll.description) + '</p>' +
      '<div class="rd-poll-options">' + rows + '</div><p class="rd-poll-message" role="status" aria-live="polite">' + esc(message || "") + '</p>' +
      '<div class="rd-poll-actions">' + (canVote ? '<button class="rd-poll-vote" type="button"' + (busy ? ' disabled' : '') + '>' + (busy ? 'Submitting…' : 'Vote now') + '</button>' : '') + '</div></div>' +
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

    var submittedOption = selected;
    request("POST", {
      poll_id: payload.poll.id,
      option_id: submittedOption,
      voter_id: voterId()
    }, function (ok, data) {
      busy = false;
      if (!data) {
        render("The poll is temporarily unavailable.");
        return;
      }

      if (data.poll && data.state && data.results) payload = data;

      if (ok || data.voted_for) {
        var confirmed = String(data.voted_for || submittedOption);
        storageSet(voteKey(payload.poll.id), confirmed);
        selected = "";
        applyOptimisticVote(payload, confirmed);
        render(ok ? "Your vote has been counted." : (data.error || "Your earlier vote is shown below."));
        return;
      }

      render(data.error || "Your vote could not be recorded.");
    });
  }

  function load(firstLoad) {
    request("GET", null, function (ok, data) {
      if (!ok || !data || !data.poll || !data.state || !data.results) {
        if (firstLoad) showError("The community poll is temporarily unavailable. Please try again shortly.");
        return;
      }

      var localChoice = storedVote(data.poll.id);
      payload = data;
      if (localChoice) applyOptimisticVote(payload, localChoice);
      render("");
    });
  }

  load(true);
  refreshTimer = window.setInterval(function () { load(false); }, 20000);
  window.addEventListener("beforeunload", function () {
    if (refreshTimer) window.clearInterval(refreshTimer);
  });
})();
