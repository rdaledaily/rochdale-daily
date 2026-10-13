/* Rochdale Daily — thumb-reach story navigation.
 *
 * The problem this solves is posture, not decoration. An article on a phone is
 * ~8,000px tall. Until now the only way out of a story was to scroll to the
 * very bottom, past a legal note and a comments box, to reach four links. A
 * reader holding the phone one-handed had no way to say "done, next" without a
 * long scroll with their thumb.
 *
 * Two affordances, both in the bottom third of the screen where a thumb rests:
 *   1. A persistent "Next" bar carrying the actual next headline, so the reader
 *      always knows what they are moving to. It appears once they are properly
 *      into the story, and gets out of the way when they reach the real
 *      Read-next block (no point offering the same thing twice).
 *   2. A left swipe anywhere on the story advances to that same story.
 *
 * On swipe direction: a rightward swipe from the screen edge is the system BACK
 * gesture on both iOS and Android. Binding "next" to it would fight the phone's
 * own navigation, so forward is a LEFT swipe -- the page-turn direction, and
 * the same direction of travel the feed apps use for "onward".
 *
 * The next story is whatever the server already decided: the ward-first card
 * rendered into .read-next. No second source of truth, and if that block is
 * absent this script does nothing at all.
 */
(function () {
  "use strict";

  var MOBILE = window.matchMedia("(max-width: 820px)");
  if (!MOBILE.matches) return;

  var card = document.querySelector(".read-next .rn-card");
  if (!card) return;

  var href = card.getAttribute("href");
  var title = (card.querySelector(".rn-title") || {}).textContent || "Next story";
  var kicker = (card.querySelector(".rn-kicker") || {}).textContent || "";
  if (!href) return;

  var readNext = document.querySelector(".read-next");
  var article = document.querySelector(".article-main") || document.body;
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ---------------------------------------------------------------- the bar */
  var bar = document.createElement("a");
  bar.className = "next-bar";
  bar.href = href;
  bar.setAttribute("aria-label", "Next story: " + title.trim());
  bar.innerHTML =
    '<span class="next-bar-label">Next' + (kicker ? " &middot; " + escapeHtml(kicker.trim()) : "") + "</span>" +
    '<span class="next-bar-title"></span>' +
    '<span class="next-bar-arrow" aria-hidden="true">&rsaquo;</span>';
  bar.querySelector(".next-bar-title").textContent = title.trim();
  document.body.appendChild(bar);

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* Show it once the reader is genuinely reading, and hide it once the real
     Read-next block is on screen so the same offer is not made twice.
     An observer is used rather than scroll arithmetic: the block's position
     moves as images load, and a stale measurement left the bar stuck on. */
  var shown = false;
  var atBlock = false;

  if (readNext && "IntersectionObserver" in window) {
    new IntersectionObserver(function (entries) {
      atBlock = entries[0].isIntersecting;
      update();
    }, { rootMargin: "0px 0px -10% 0px" }).observe(readNext);
  }

  function update() {
    var start = article.getBoundingClientRect().top + window.scrollY;
    var passed = window.scrollY - start;
    var want = passed > window.innerHeight * 0.9 && !atBlock;
    if (want !== shown) {
      shown = want;
      bar.classList.toggle("is-visible", want);
    }
  }
  var ticking = false;
  window.addEventListener(
    "scroll",
    function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () {
        update();
        ticking = false;
      });
    },
    { passive: true }
  );
  update();

  /* --------------------------------------------------------------- the swipe */
  var startX = 0, startY = 0, tracking = false;

  article.addEventListener("touchstart", function (event) {
    if (event.touches.length !== 1) return;
    var t = event.touches[0];
    /* Ignore touches that begin at the very edge: that is the OS back gesture
       territory, and stealing it makes the phone feel broken. */
    if (t.clientX < 24 || t.clientX > window.innerWidth - 24) return;
    startX = t.clientX;
    startY = t.clientY;
    tracking = true;
  }, { passive: true });

  article.addEventListener("touchend", function (event) {
    if (!tracking) return;
    tracking = false;
    var t = event.changedTouches[0];
    var dx = t.clientX - startX;
    var dy = t.clientY - startY;
    /* A deliberate horizontal swipe, not a scroll wobble: far enough across,
       and clearly more sideways than vertical. */
    if (dx < -70 && Math.abs(dx) > Math.abs(dy) * 2) {
      if (!reduced) document.body.classList.add("is-advancing");
      window.location.href = href;
    }
  }, { passive: true });
})();


/* Desktop reading prompt. Mobile keeps its existing thumb-reach next-story bar.
 * Invite a reader who is already engaged with the article to continue with a
 * genuinely selected related report. Never substitute a random archive link.
 */
(function () {
  "use strict";
  if (window.matchMedia("(max-width: 820px)").matches) return;
  const source = document.querySelector(".read-next .rn-card");
  const article = document.querySelector(".article-copy");
  const related = document.querySelector(".read-next");
  if (!source || !article || !related) return;
  let target;
  try { target = new URL(source.getAttribute("href") || "", location.href); }
  catch (_) { return; }
  if (target.origin !== location.origin || !/^\/articles\/[a-z0-9-]+(?:\.html)?$/i.test(target.pathname)) return;
  const title = (source.querySelector(".rn-title")?.textContent || "").trim();
  if (!title) return;
  const key = "rd_read_next_closed:" + location.pathname;
  try { if (sessionStorage.getItem(key)) return; } catch (_) {}

  const style = document.createElement("style");
  style.textContent = [
    ".rd-read-next-prompt{position:fixed;bottom:20px;right:20px;z-index:140;width:min(355px,calc(100vw - 32px));background:#fff;color:#182e3a;border:1px solid #c7dce0;border-top:3px solid #136c76;box-shadow:0 12px 38px rgba(12,37,54,.18);border-radius:7px;padding:19px 45px 19px 19px;transform:translateY(calc(100% + 50px));opacity:0;pointer-events:none;transition:opacity .23s,transform .23s;font:14px/1.4 system-ui,-apple-system,sans-serif}",
    ".rd-read-next-prompt.is-visible{transform:translateY(0);opacity:1;pointer-events:auto}",
    ".rd-read-next-prompt .rd-nrp-label{display:block;color:#136c76;font-size:10px;font-weight:850;letter-spacing:.14em;text-transform:uppercase;margin-bottom:6px}",
    ".rd-read-next-prompt a{display:block;color:#182e3a;text-decoration:none;font:700 18px/1.27 Georgia,serif}",
    ".rd-read-next-prompt a:hover{text-decoration:underline;text-underline-offset:3px}",
    ".rd-read-next-prompt .rd-nrp-end{display:block;color:#136c76;margin-top:10px;font-size:11px;font-weight:800}",
    ".rd-read-next-prompt button{position:absolute;right:12px;top:12px;border:0;background:transparent;color:#516976;font-size:23px;line-height:1;cursor:pointer;padding:2px 6px}",
    ".rd-read-next-prompt button:focus-visible,.rd-read-next-prompt a:focus-visible{outline:3px solid #218c97;outline-offset:3px}",
    "@media(max-width:820px){.rd-read-next-prompt{display:none!important}}",
    "@media(prefers-reduced-motion:reduce){.rd-read-next-prompt{transition:none}}"
  ].join("");
  document.head.appendChild(style);

  const prompt = document.createElement("aside");
  prompt.className = "rd-read-next-prompt";
  prompt.setAttribute("aria-label", "Continue reading on Rochdale Daily");
  const close = document.createElement("button");
  close.type = "button"; close.textContent = "×";
  close.setAttribute("aria-label", "Dismiss read-next suggestion");
  close.addEventListener("click", () => {
    prompt.remove();
    dismissed = true;
    try { sessionStorage.setItem(key, "1"); } catch (_) {}
    window.removeEventListener("scroll", queue);
  });
  const label = document.createElement("span");
  label.className = "rd-nrp-label"; label.textContent = "Read next · From Rochdale Daily";
  const link = document.createElement("a");
  link.href = target.pathname; link.textContent = title;
  const hint = document.createElement("span");
  hint.className = "rd-nrp-end"; hint.textContent = "Continue reading →";
  prompt.append(close,label,link,hint);
  document.body.appendChild(prompt);

  let dismissed = false, visibleAtRelated = false, scheduled = false;
  if ("IntersectionObserver" in window) {
    new IntersectionObserver(entries => {
      visibleAtRelated = entries.some(entry => entry.isIntersecting);
      update();
    },{rootMargin:"0px 0px -10% 0px"}).observe(related);
  }
  function update() {
    if (dismissed) return;
    const bounds = article.getBoundingClientRect();
    const articleTop = bounds.top + window.scrollY;
    const passed = window.scrollY + window.innerHeight * .6 - articleTop;
    const progressed = passed > Math.max(window.innerHeight * 1.1, article.offsetHeight * .48);
    const stillReading = bounds.bottom > window.innerHeight * .1;
    const shouldShow = progressed && stillReading && !visibleAtRelated && document.visibilityState === "visible";
    prompt.classList.toggle("is-visible",shouldShow);
    // Don't obscure the cookie consent choices if they're still visible.
    if (shouldShow) {
      const cookie = document.querySelector(".cookie:not([hidden])");
      const height = cookie && getComputedStyle(cookie).display !== "none" ? cookie.getBoundingClientRect().height : 0;
      prompt.style.bottom = (height > 0 ? height + 15 : 20) + "px";
    }
  }
  function queue() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => { scheduled = false; update(); });
  }
  window.addEventListener("scroll",queue,{passive:true});
  window.addEventListener("resize",queue,{passive:true});
  document.addEventListener("visibilitychange",update);
  update();
})();
