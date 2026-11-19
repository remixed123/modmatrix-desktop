/* TROUBLESHOOTING tab: content/troubleshooting.md in the app's repo (the launcher's
 * /content/troubleshooting: GitHub's copy, else the one from last time or the app's own),
 * rendered by mdpage.js. Read again when the tab is opened after a while, or on REFRESH. */
"use strict";

const help = (() => {
  let text = null, loadedAt = 0;

  async function load(fresh = false) {
    loadedAt = Date.now();
    try {
      const body = await mdpage.getJson("/content/troubleshooting" + (fresh ? "?fresh=1" : ""));
      if (body.data === text) return;
      mdpage.render(body.data, { target: $("help-page"), holder: $("help-parts"), prefix: "h-" });
      text = body.data;
    } catch (e) {
      if (text !== null) return;                         // keep what's on screen
      const p = document.createElement("p");
      p.className = "data-note err";
      p.textContent = `This page could not be loaded (${e.message}).`;
      $("help-page").replaceChildren(p);
    }
  }

  mdpage.bind($("help"));
  mdpage.refreshButton($("help-refresh"), () => load(true));
  load();
  return { shown() { if (Date.now() - loadedAt > 15 * 60 * 1000) load(); } };
})();
