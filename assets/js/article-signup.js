/* In-article newsletter sign-up.
 *
 * Why: on 12 Nov 2026 the newsletter had 6 subscribers. The only sign-up
 * boxes were low on the homepage and in the article sidebar, which sits
 * below everything else on a phone, so a reader arriving on a story from
 * Facebook or Google was barely asked.
 *
 * What it does: on a reader's second page view (or any return visit) it
 * places one sign-up box directly under the story. It is part of the page,
 * not a pop-up: nothing covers the article and nothing has to be closed to
 * keep reading. It is not shown to someone who has signed up, to someone who
 * chose "Not now" in the last 30 days, or under sensitive stories.
 *
 * Stored on the reader's own device: only their own choice (signed up, or
 * "Not now"). The second page view is read from the referrer, not counted.
 * Loaded by cookie-consent.js on every article page, old and new.
 */
(function () {
  "use strict";
  var SNOOZE_DAYS = 30;
  var KEY_SUB = "rd_newsletter_done";       // shared with retention.js
  var KEY_SNOOZE = "rd_signup_snooze";
  var AREAS = [["rochdale", "Rochdale"], ["heywood", "Heywood"], ["middleton", "Middleton"],
               ["pennines", "Pennines (Littleborough, Milnrow, Newhey, Wardle)"]];
  var TOPICS = [["crime", "Crime"], ["whats-on", "What's on"], ["sport", "Rochdale AFC and sport"], ["council", "Council and planning"]];

  function get(kind, key) { try { return window[kind].getItem(key); } catch (e) { return null; } }
  function set(kind, key, value) { try { window[kind].setItem(key, value); } catch (e) { /* private mode */ } }

  // Second page view: the reader came here from another page of this site.
  // Read from the referrer, so nothing new is stored to work it out.
  var internal = false;
  try { internal = Boolean(document.referrer) && new URL(document.referrer).host === location.host; } catch (e) { internal = false; }
  // Return visit: retention.js records homepage visits; these are read only.
  var lastVisit = Number(get("localStorage", "rd_last_visit")) || 0;
  var returning = Boolean(get("localStorage", "rd_prev_visit")) || Boolean(lastVisit && Date.now() - lastVisit > 30 * 60 * 1000);

  var article = document.querySelector(".article-main");
  var copy = article && article.querySelector(".article-copy");
  if (!copy || document.getElementById("inline-newsletter")) return;
  if (get("localStorage", KEY_SUB)) return;
  var snoozed = Number(get("localStorage", KEY_SNOOZE)) || 0;
  if (snoozed && Date.now() - snoozed < SNOOZE_DAYS * 864e5) return;
  if (!internal && !returning) return;
  // Sensitive stories carry this legal note; a sign-up box does not belong under them.
  var legal = article.querySelector(".editorial-legal-note");
  if (legal && /No finding of guilt should be inferred/.test(legal.textContent || "")) return;

  function el(tag, attrs, text) {
    var node = document.createElement(tag);
    for (var name in attrs || {}) node.setAttribute(name, attrs[name]);
    if (text) node.textContent = text;
    return node;
  }

  var css = el("style");
  css.textContent =
    ".rd-inline-signup{margin:28px 0;padding:20px;background:var(--brand-navy,#10283b);color:var(--on-dark,#f7f9f9);border-radius:var(--radius,5px);font-family:var(--font-ui,Arial,sans-serif)}" +
    ".rd-inline-signup .rd-is-kicker{margin:0 0 6px;font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--brand-accent-lift,#cce9e9)}" +
    ".rd-inline-signup h2{margin:0 0 6px;font-family:var(--font-display,Georgia,serif);font-size:22px;line-height:1.2;color:#fff}" +
    ".rd-inline-signup p{margin:0 0 14px;font-size:15px;line-height:1.5;color:var(--on-dark-mut,#d0dee2)}" +
    ".rd-inline-signup .rd-is-row{display:flex;gap:8px}" +
    ".rd-inline-signup input[type=email],.rd-inline-signup select{flex:1;min-width:0;width:100%;box-sizing:border-box;padding:13px 14px;border:1px solid var(--line-strong,#aabfc7);border-radius:var(--radius,5px);font:inherit;font-size:16px;background:#fff;color:#111}" +
    ".rd-inline-signup button[type=submit]{padding:13px 20px;border:0;border-radius:var(--radius,5px);background:var(--brand-accent-lift,#cce9e9);color:var(--brand-navy-deep,#0b2233);font:inherit;font-weight:700;font-size:15px;cursor:pointer}" +
    ".rd-inline-signup label{display:flex;gap:8px;align-items:flex-start;margin:10px 0 0;font-size:13px;line-height:1.4;color:var(--on-dark-mut,#d0dee2)}" +
    ".rd-inline-signup a{color:#fff}" +
    ".rd-inline-signup details{margin:12px 0 0;font-size:14px}" +
    ".rd-inline-signup summary{cursor:pointer;color:#fff;font-weight:600;padding:6px 0}" +
    ".rd-inline-signup fieldset{border:0;margin:8px 0 0;padding:0}" +
    ".rd-inline-signup legend,.rd-inline-signup .rd-is-label{display:block;margin:8px 0 6px;font-size:13px;color:#fff;font-weight:600}" +
    ".rd-inline-signup .rd-is-status{min-height:1.4em;margin:10px 0 0;font-size:14px;color:#fff}" +
    ".rd-inline-signup .rd-is-later{margin:6px 0 0;padding:6px 0;border:0;background:none;color:var(--on-dark-mut,#d0dee2);font:inherit;font-size:13px;text-decoration:underline;cursor:pointer}" +
    ".rd-inline-signup :focus-visible{outline:2px solid #fff;outline-offset:2px}" +
    "@media (max-width:560px){.rd-inline-signup .rd-is-row{flex-direction:column}.rd-inline-signup button[type=submit]{width:100%}}";
  document.head.appendChild(css);

  var box = el("section", { "class": "rd-inline-signup", id: "inline-newsletter", "aria-labelledby": "inline-newsletter-title" });
  box.appendChild(el("p", { "class": "rd-is-kicker" }, "Free morning email"));
  box.appendChild(el("h2", { id: "inline-newsletter-title" }, "The borough in your inbox"));
  box.appendChild(el("p", null, "The day's Rochdale news in one email each morning. No spam, and we never sell your address."));

  var form = el("form", { id: "inline-newsletter-form", novalidate: "" });
  var row = el("div", { "class": "rd-is-row" });
  var emailLabel = el("label", { "for": "inline-newsletter-email", style: "position:absolute;left:-9999px" }, "Email address");
  var email = el("input", { id: "inline-newsletter-email", name: "email", type: "email", inputmode: "email", autocomplete: "email", placeholder: "you@example.com", required: "" });
  var button = el("button", { type: "submit" }, "Sign up");
  row.appendChild(email); row.appendChild(button);
  form.appendChild(emailLabel); form.appendChild(row);

  var trap = el("input", { type: "text", name: "website", tabindex: "-1", autocomplete: "off", "aria-hidden": "true", style: "position:absolute;left:-9999px" });
  form.appendChild(trap);

  var consentLabel = el("label");
  var consent = el("input", { type: "checkbox", id: "inline-newsletter-consent", name: "consent", required: "" });
  consentLabel.appendChild(consent);
  var consentText = el("span", null, "Send me the Rochdale Daily newsletter. I can unsubscribe at any time. ");
  consentText.appendChild(el("a", { href: "/privacy#newsletter" }, "Privacy"));
  consentLabel.appendChild(consentText);
  form.appendChild(consentLabel);

  var details = el("details");
  details.appendChild(el("summary", null, "Choose your area and topics (optional)"));
  details.appendChild(el("label", { "class": "rd-is-label", "for": "inline-newsletter-area" }, "Your area"));
  var area = el("select", { id: "inline-newsletter-area", name: "area" });
  area.appendChild(el("option", { value: "" }, "Whole borough"));
  AREAS.forEach(function (pair) { area.appendChild(el("option", { value: pair[0] }, pair[1])); });
  details.appendChild(area);
  var topics = el("fieldset");
  topics.appendChild(el("legend", null, "What you most want to hear about"));
  TOPICS.forEach(function (pair) {
    var label = el("label");
    label.appendChild(el("input", { type: "checkbox", name: "topics", value: pair[0] }));
    label.appendChild(el("span", null, pair[1]));
    topics.appendChild(label);
  });
  details.appendChild(topics);
  form.appendChild(details);

  var status = el("p", { "class": "rd-is-status", id: "inline-newsletter-status", role: "status", "aria-live": "polite" });
  form.appendChild(status);
  var later = el("button", { type: "button", "class": "rd-is-later" }, "Not now");
  form.appendChild(later);
  box.appendChild(form);

  later.addEventListener("click", function () {
    set("localStorage", KEY_SNOOZE, String(Date.now()));
    box.remove();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    if (form.getAttribute("data-submitting") === "yes") return;
    var address = (email.value || "").trim();
    if (address.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(address)) {
      status.textContent = "Please enter a valid email address."; email.focus(); return;
    }
    if (!consent.checked) { status.textContent = "Please tick the box to receive the newsletter."; consent.focus(); return; }
    var chosen = [];
    [].forEach.call(form.querySelectorAll('input[name="topics"]'), function (input) { if (input.checked) chosen.push(input.value); });
    form.setAttribute("data-submitting", "yes"); button.disabled = true;
    status.textContent = "Saving your signup…";
    fetch("/api/newsletter", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: address, consent: true, website: trap.value || "", source: "article-inline", area: area.value || "", topics: chosen })
    }).then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) { return { ok: response.ok && data.ok === true, data: data }; });
    }).then(function (result) {
      if (!result.ok) { status.textContent = result.data.error || "Signup could not be saved. Please try again."; return; }
      set("localStorage", KEY_SUB, "1");
      var done = el("p", { role: "status" }, result.data.message || "Your signup has been saved.");
      form.replaceWith(done);
      try { document.dispatchEvent(new CustomEvent("rd:newsletter-saved")); } catch (e) { /* old browser */ }
    }).catch(function () {
      status.textContent = "Could not connect. Please try again.";
    }).then(function () {
      form.removeAttribute("data-submitting"); button.disabled = false;
    });
  });

  copy.after(box);
})();
