/* ABOUT (right of CHECK FOR UPDATES): who made what, the version and the licences, the same on
 * every system (the Mac's own About box, in the app menu, has the short form; Windows has no app
 * menu). The text is in shell.html, filled in by the launcher (version, build, disclaimer). */
"use strict";

(() => {
  const btn = $("about-btn");
  const panel = $("about");

  function open() {
    tips.hide();
    if (!$("updates").hidden) $("check").click();          // one panel at a time
    panel.hidden = false;
    btn.setAttribute("aria-expanded", "true");
    $("about-close").focus();
  }
  function close() {
    panel.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  }

  btn.addEventListener("click", () => (panel.hidden ? open() : close()));
  $("about-close").addEventListener("click", () => { close(); btn.focus(); });
  $("about-check").addEventListener("click", () => { close(); $("check").click(); });
  $("check").addEventListener("click", () => { if (!panel.hidden) close(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) { close(); btn.focus(); }
  });
  document.addEventListener("mousedown", (e) => {
    if (!panel.hidden && !panel.contains(e.target) && e.target !== btn) close();
  });
  window.addEventListener("blur", () => {                  // the Mod Matrix frame took a click
    if (!panel.hidden && document.activeElement === $("matrix")) close();
  });
})();
