(() => {
  const host = document.getElementById("community-poll");
  if (!host) return;

  const API = "/api/poll";
  const TOKEN_KEY = "rd-community-poll-voter";
  const VOTE_KEY_PREFIX = "rd-community-poll-vote:";
  let payload = null;
  let selectedOption = "";
  let timer = null;

  function voterId() {
    let value = localStorage.getItem(TOKEN_KEY);
    if (!value) {
      const bytes = crypto.getRandomValues(new Uint8Array(24));
      value = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
      localStorage.setItem(TOKEN_KEY, value);
    }
    return value;
  }

  function esc(value) {
    return String(value ?? "").replace(/[&<>"]/g, char => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;",
    })[char]);
  }

  function timeLeft(endValue) {
    const distance = Date.parse(endValue) - Date.now();
    if (distance <= 0) return "Voting closed";
    const days = Math.floor(distance / 86400000);
    const hours = Math.floor((distance % 86400000) / 3600000);
    const minutes = Math.floor((distance % 3600000) / 60000);
    if (days) return `${days} day${days === 1 ? "" : "s"}, ${hours} hour${hours === 1 ? "" : "s"} left`;
    if (hours) return `${hours} hour${hours === 1 ? "" : "s"}, ${minutes} min left`;
    return `${Math.max(1, minutes)} min left`;
  }

  function ago(at) {
    const seconds = Math.max(0, Math.floor((Date.now() - Number(at)) / 1000));
    if (seconds < 45) return "Just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hr ago`;
    return `${Math.floor(seconds / 86400)} day ago`;
  }

  function storedVote(pollId) {
    return localStorage.getItem(VOTE_KEY_PREFIX + pollId) || "";
  }

  function leaderText(results) {
    if (!results.total || !results.options.length) return "Be the first to vote";
    const first = results.options[0];
    const second = results.options[1];
    const margin = second ? first.votes - second.votes : first.votes;
    if (margin === 0) return "The lead is tied";
    return `${first.label} leads by ${margin} vote${margin === 1 ? "" : "s"}`;
  }

  function render() {
    if (!payload) return;
    const { poll, state, results } = payload;
    const chosen = storedVote(poll.id);
    const canVote = state.open && !chosen;
    const totalCopy = `${results.total.toLocaleString("en-GB")} vote${results.total === 1 ? "" : "s"}`;
    const byId = new Map(results.options.map(option => [option.id, option]));

    const options = poll.options.map(option => {
      const result = byId.get(option.id) || { votes: 0, percentage: 0 };
      const selected = selectedOption === option.id;
      const chosenClass = chosen === option.id ? " is-chosen" : "";
      if (canVote) {
        return `
          <button class="rd-poll-choice${selected ? " is-selected" : ""}"
                  type="button"
                  data-poll-option="${esc(option.id)}"
                  aria-pressed="${selected ? "true" : "false"}">
            <span class="rd-poll-radio" aria-hidden="true"></span>
            <span class="rd-poll-choice-copy">
              <strong>${esc(option.label)}</strong>
              <span class="rd-poll-choice-result">${result.percentage}% (${result.votes})</span>
              <span class="rd-poll-track" aria-hidden="true"><span style="width:${Math.max(result.percentage, result.votes ? 1 : 0)}%"></span></span>
            </span>
          </button>`;
      }
      return `
        <div class="rd-poll-result${chosenClass}">
          <div class="rd-poll-result-head">
            <span>${chosen === option.id ? '<span class="rd-poll-leader">Your vote</span>' : ""}${esc(option.label)}</span>
            <strong>${result.percentage}% <small>(${result.votes})</small></strong>
          </div>
          <div class="rd-poll-track" aria-hidden="true"><span style="width:${Math.max(result.percentage, result.votes ? 1 : 0)}%"></span></div>
        </div>`;
    }).join("");

    const activity = results.recent?.length
      ? `<div class="rd-poll-activity"><strong>Latest votes</strong>${results.recent.slice(0, 3).map(item => `<span>${ago(item.at)} — ${esc(item.label)}</span>`).join("")}</div>`
      : "";

    host.innerHTML = `
      <div class="rd-poll-shell">
        <div class="rd-poll-topline">
          <span class="rd-poll-kicker">Rochdale Daily community poll</span>
          <span class="rd-poll-countdown" data-poll-countdown>${esc(timeLeft(state.ends_at))}</span>
        </div>
        <div class="rd-poll-grid">
          <div class="rd-poll-main">
            <h2>${esc(poll.title)}</h2>
            <p class="rd-poll-intro">${esc(poll.description)}</p>
            <div class="rd-poll-options" aria-live="polite">${options}</div>
            <p class="rd-poll-message" role="status" aria-live="polite"></p>
            <div class="rd-poll-actions">
              ${canVote ? '<button class="rd-poll-vote" type="button">Vote now</button>' : ""}
            </div>
          </div>
          <aside class="rd-poll-summary">
            <span class="rd-poll-total">${totalCopy}</span>
            <strong>${esc(leaderText(results))}</strong>
            ${activity}
          </aside>
        </div>
        <p class="rd-poll-note">${esc(poll.source_note || "Informal reader poll.")}</p>
      </div>`;

    host.querySelectorAll("[data-poll-option]").forEach(button => {
      button.addEventListener("click", () => {
        selectedOption = button.dataset.pollOption || "";
        render();
      });
    });

    const voteButton = host.querySelector(".rd-poll-vote");
    if (voteButton) voteButton.addEventListener("click", submitVote);
  }

  async function submitVote() {
    const message = host.querySelector(".rd-poll-message");
    const button = host.querySelector(".rd-poll-vote");
    if (!selectedOption) {
      message.textContent = "Choose an eatery before voting.";
      return;
    }
    button.disabled = true;
    button.textContent = "Submitting…";
    try {
      const response = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ poll_id: payload.poll.id, option_id: selectedOption, voter_id: voterId() }),
      });
      const data = await response.json();
      if (!response.ok && !data.results) throw new Error(data.error || "Vote could not be recorded.");
      if (data.voted_for) localStorage.setItem(VOTE_KEY_PREFIX + payload.poll.id, data.voted_for);
      payload = { poll: data.poll || payload.poll, state: data.state || payload.state, results: data.results || payload.results };
      render();
      const updatedMessage = host.querySelector(".rd-poll-message");
      if (updatedMessage) updatedMessage.textContent = response.ok ? "Your vote has been counted." : (data.error || "You have already voted.");
    } catch (error) {
      button.disabled = false;
      button.textContent = "Vote now";
      message.textContent = error.message || "The poll is temporarily unavailable.";
    }
  }

  async function refresh(quiet = false) {
    try {
      const response = await fetch(API, { headers: { "Accept": "application/json" }, cache: "no-store" });
      if (!response.ok) throw new Error("Poll unavailable");
      payload = await response.json();
      render();
    } catch {
      if (!quiet) host.innerHTML = '<div class="rd-poll-shell"><p class="rd-poll-error">The community poll is temporarily unavailable. Please try again shortly.</p></div>';
    }
  }

  refresh();
  timer = window.setInterval(() => refresh(true), 20000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refresh(true);
  });
  window.addEventListener("beforeunload", () => window.clearInterval(timer));
})();
