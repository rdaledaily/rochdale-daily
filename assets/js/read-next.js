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
