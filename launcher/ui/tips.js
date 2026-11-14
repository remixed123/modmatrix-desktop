/* Tooltips for the header's buttons: each button names its tooltip with aria-describedby (a
 * role="tooltip" element). Shown after a short hover or on keyboard focus, below the button,
 * kept inside the window; hidden on leaving, clicking, Escape. Before showing, the button gets
 * a "tipshow" event, to fill in anything live (CHECK FOR UPDATES: how long ago). */
"use strict";

const tips = (() => {
  const DELAY = 450;
  const GAP = 6, EDGE = 12;
  let timer = null, shown = null;

  function place(btn, tip) {
    const r = btn.getBoundingClientRect();
    tip.style.top = `${Math.round(r.bottom + GAP)}px`;
    const w = tip.offsetWidth;
    const left = r.left + r.width / 2 > innerWidth / 2 ? r.right - w : r.left;   // right half: line up the right edges
    tip.style.left = `${Math.round(Math.max(EDGE, Math.min(left, innerWidth - w - EDGE)))}px`;
  }

  function show(btn) {
    hide();
    timer = setTimeout(() => {
      if (btn.getAttribute("aria-expanded") === "true") return;      // its panel is open
      const tip = document.getElementById(btn.getAttribute("aria-describedby"));
      if (!tip) return;
      btn.dispatchEvent(new Event("tipshow"));
      tip.hidden = false;
      place(btn, tip);
      shown = tip;
    }, DELAY);
  }

  function hide() {
    clearTimeout(timer);
    if (shown) shown.hidden = true;
    shown = null;
  }

  for (const btn of document.querySelectorAll("#tabs button[aria-describedby]")) {
    btn.addEventListener("mouseenter", () => show(btn));
    btn.addEventListener("mouseleave", hide);
    btn.addEventListener("focus", () => { if (btn.matches(":focus-visible")) show(btn); });
    btn.addEventListener("blur", hide);
    btn.addEventListener("mousedown", hide);
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") hide(); });
  window.addEventListener("blur", hide);
  window.addEventListener("resize", hide);

  return { hide };
})();
