(() => {
  const host = document.getElementById("community-poll");
  if (!host || host.dataset.pollV2 === "1") return;
  host.dataset.pollV2 = "1";

  const API = "/api/poll";
  const TOKEN_KEY = "rd-community-poll-voter";
  let payload = null;
  let selected = "";
  let busy = false;

  const esc = value => String(value ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"})[c]);

  function voterId() {
    let id = localStorage.getItem(TOKEN_KEY);
    if (!id) {
      const bytes = crypto.getRandomValues(new Uint8Array(24));
      id = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
      localStorage.setItem(TOKEN_KEY, id);
    }
    return id;
  }

  function timeLeft(value) {
    const ms = Date.parse(value) - Date.now();
    if (ms <= 0) return "Voting closed";
    const days = Math.floor(ms / 86400000);
    const hours = Math.floor((ms % 86400000) / 3600000);
    return days ? `${days} day${days === 1 ? "" : "s"}, ${hours} hour${hours === 1 ? "" : "s"} left` : `${hours} hour${hours === 1 ? "" : "s"} left`;
  }

  function leaderText(results) {
    if (!results.total) return "Be the first to vote";
    const sorted = [...results.options].sort((a,b) => b.votes - a.votes);
    const margin = sorted[0].votes - (sorted[1]?.votes || 0);
    return margin ? `${sorted[0].label} leads by ${margin} vote${margin === 1 ? "" : "s"}` : "The lead is tied";
  }

  function render(message = "") {
    if (!payload) return;
    const { poll, state, results } = payload;
    const byId = new Map(results.options.map(item => [item.id, item]));
    const choices = poll.options.map(option => {
      const result = byId.get(option.id) || { votes: 0, percentage: 0 };
      const active = selected === option.id;
      return `<button type="button" class="rd-poll-choice${active ? " is-selected" : ""}" data-poll-option="${esc(option.id)}" aria-pressed="${active}">
        <span class="rd-poll-radio" aria-hidden="true"></span>
        <span class="rd-poll-choice-copy"><strong>${esc(option.label)}</strong><span class="rd-poll-choice-result">${result.percentage}% (${result.votes})</span><span class="rd-poll-track" aria-hidden="true"><span style="width:${Math.max(result.percentage, result.votes ? 1 : 0)}%"></span></span></span>
      </button>`;
    }).join("");

    host.innerHTML = `<div class="rd-poll-shell">
      <div class="rd-poll-topline"><span class="rd-poll-kicker">Rochdale Daily community poll</span><span class="rd-poll-countdown">${esc(timeLeft(state.ends_at))}</span></div>
      <div class="rd-poll-grid"><div class="rd-poll-main"><h2>${esc(poll.title)}</h2><p class="rd-poll-intro">${esc(poll.description)}</p>
      <div class="rd-poll-options">${choices}</div><p class="rd-poll-message" role="status">${esc(message)}</p>
      <div class="rd-poll-actions">${state.open ? `<button class="rd-poll-vote" type="button"${busy ? " disabled" : "">${busy ? "Submitting…" : "Vote now"}</button>` : ""}</div></div>
      <aside class="rd-poll-summary"><span class="rd-poll-total">${results.total.toLocaleString("en-GB")} vote${results.total === 1 ? "" : "s"}</span><strong>${esc(leaderText(results))}</strong></aside></div>
      <p class="rd-poll-note">${esc(poll.source_note || "Informal reader poll.")}</p></div>`;

    host.querySelectorAll("[data-poll-option]").forEach(button => button.addEventListener("click", () => {
      selected = button.dataset.pollOption || "";
      render();
    }));
    host.querySelector(".rd-poll-vote")?.addEventListener("click", submit);
  }

  async function submit() {
    if (!selected) return render("Choose an eatery before voting.");
    busy = true; render();
    try {
      const response = await fetch(API, {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({poll_id:payload.poll.id,option_id:selected,voter_id:voterId()})});
      const data = await response.json();
      if (data.poll && data.state && data.results) payload = data;
      busy = false;
      render(response.ok ? "Your vote has been counted." : (data.error || "You have already voted."));
    } catch (_) {
      busy = false;
      render("The poll is temporarily unavailable.");
    }
  }

  async function load() {
    try {
      const response = await fetch(API, {cache:"no-store",headers:{Accept:"application/json"}});
      if (!response.ok) throw new Error();
      payload = await response.json();
      render();
    } catch (_) {
      host.innerHTML = '<div class="rd-poll-shell"><p class="rd-poll-error">The community poll is temporarily unavailable.</p></div>';
    }
  }

  load();
  setInterval(load, 20000);
})();
