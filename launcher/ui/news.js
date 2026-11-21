/* WHAT'S NEW tab: the recent changes of the Mod Matrix (perkons-re) and every mod, from the
 * launcher's /news (GitHub's change feed of each mod's folder, kept for offline use). Changes the
 * person hasn't marked as seen are NEW; MARK ALL AS SEEN marks them (/news/seen). Once they've
 * built a firmware in the Mod Matrix, NEW is only what changed in that build's mods (and the Mod
 * Matrix) since: "since your build on ..." instead of "since you last looked". This tab is the
 * one place for the mods' changes: it tells the rest of the page with a "pmm-news" event, for the
 * tab's count and one line in the updates panel (updates.js). */
"use strict";

const whatsnew = (() => {
  const PAGE = 50;                                       // changes shown, then SHOW MORE
  const KINDS = { engine: "ENGINE", mod: "MOD", framework: "MOD MATRIX" };
  let data = null, loadedAt = 0, shownCount = PAGE, kind = "all", onlyNew = false, busy = null;

  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const day = (iso) => {
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const year = d.getFullYear() !== new Date().getFullYear() ? "numeric" : undefined;
    return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "long", year });
  };
  /* "21 November, 17:41" (the person's own clock format) */
  const at = (d) => d.toLocaleString(undefined, { day: "numeric", month: "long", hour: "numeric", minute: "2-digit" });
  const sinceText = (secs) => at(new Date(secs * 1000));
  /* "your build on 12 November" or "you last looked (12 November)" */
  const sinceWhat = (i) => i.build
    ? `your build on ${at(new Date(i.build.when))}`
    : `you last looked (${sinceText(i.since)})`;

  /* what's new, in short: for the tab's count, the updates panel's line and the summary box */
  function info() {
    if (!data) return null;
    const changed = [], added = [];
    let count = 0;
    for (const it of data.items) {
      if (it.added) { added.push(it.title); continue; }
      const n = it.changes.filter((c) => c.new).length;
      if (n) { changed.push({ title: it.title, n, kind: it.kind }); count += n; }
    }
    return { count, changed, added, removed: data.removed || [], since: data.since, build: data.build || null,
             any: Boolean(count || added.length || (data.removed || []).length) };
  }

  function announce() {
    const i = info();
    const badge = $("news-count");
    const n = i ? i.count + i.added.length : 0;
    badge.hidden = !n;
    badge.textContent = n ? String(n) : "";
    $("tab-news").setAttribute("aria-label", n ? `What's new: ${n} new` : "What's new");
    document.dispatchEvent(new CustomEvent("pmm-news", { detail: i }));
  }

  /* -- the page --------------------------------------------------------------------------------- */

  function summary() {
    const box = $("news-summary");
    box.replaceChildren();
    const i = info();
    if (!i) return;
    if (i.any) {
      const d = mk("div", "prelim news-since");
      d.append(mk("strong", "", `Since ${sinceWhat(i)}:`));
      const ul = mk("ul");
      for (const c of i.changed) ul.append(mk("li", "", `${c.title}: ${c.n} ${c.n === 1 ? "change" : "changes"}`));
      for (const t of i.added) ul.append(mk("li", "", `New: ${t}`));
      for (const t of i.removed) ul.append(mk("li", "", `No longer offered: ${t}`));
      d.append(ul, mk("p", "", (i.build
        ? "To get the changes, build your firmware again in the Mod Matrix and install it. "
        : "If any of these are in the firmware on your Pērkons, build it again in the Mod Matrix and install it to get them. ")
        + "MARK ALL AS SEEN when you're done."));
      box.append(d);
    } else {
      box.append(mk("p", "data-note", `Nothing new since ${sinceWhat(i)}.`));
    }
    if (i.build) {
      box.append(mk("p", "data-note", `Your build: ${i.build.mods.length ? i.build.mods.join(", ") : "no mods"}. `
        + "Changes to other mods aren't marked NEW."));
    }
    if (data.offline && data.offline.length) {
      box.append(mk("p", "data-note offline-note", `Couldn't reach GitHub for: ${data.offline.join(", ")}.`));
    } else if (data.items.some((it) => it.offline)) {
      box.append(mk("p", "data-note offline-note", "Offline: some of these are from your last visit, and may be behind."));
    }
  }

  function list() {
    const out = $("news-list");
    out.replaceChildren();
    if (!data) return;
    // one row per change: a change to several mods at once lists them all
    const bySha = new Map();
    for (const it of data.items) {
      if (kind !== "all" && it.kind !== kind) continue;
      for (const c of it.changes) {
        const isNew = it.added || c.new;
        if (onlyNew && !isNew) continue;
        const row = bySha.get(c.sha) || bySha.set(c.sha, { c, mods: [], isNew: false }).get(c.sha);
        row.mods.push({ it, isNew });
        row.isNew = row.isNew || isNew;
      }
    }
    const rows = [...bySha.values()];
    rows.sort((a, b) => (a.c.date < b.c.date ? 1 : a.c.date > b.c.date ? -1 : 0));
    if (!rows.length) {
      out.append(mk("p", "data-note", onlyNew ? `Nothing new here since ${sinceWhat(info())}.` : "No changes to show."));
      return;
    }
    let lastDay = null;
    for (const { c, mods, isNew } of rows.slice(0, shownCount)) {
      const d = day(c.date);
      if (d !== lastDay) { out.append(mk("h3", "news-day", d)); lastDay = d; }
      const art = mk("article", "news-item" + (isNew ? " is-new" : ""));
      const head = mk("div", "news-head");
      for (const { it } of mods) {
        const who = mk("span", "news-who");
        if (it.id) {
          const a = mk("a", "news-mod", it.title);
          a.href = "#";
          a.title = `Open the ${it.title} user guide`;
          a.addEventListener("click", (e) => { e.preventDefault(); openGuideById(it.id); });
          who.append(a);
        } else {
          who.append(mk("strong", "news-mod", it.title));
        }
        who.append(mk("span", `kind ${it.kind === "engine" ? "engine" : ""}`, KINDS[it.kind] || "MOD"));
        head.append(who);
      }
      head.append(mk("span", "from", [...new Set(mods.map((m) => m.it.author))].join(", ")));
      if (isNew) head.append(mk("span", "badge new", "NEW"));
      art.append(head, mk("p", "news-title", c.title));
      if (c.body) {
        const det = mk("details");
        det.append(mk("summary", "", "More"), mk("p", "news-body", c.body));
        art.append(det);
      }
      const gh = mk("a", "news-gh", "The change on GitHub");
      gh.href = c.url;
      gh.target = "_blank";
      gh.rel = "noopener";
      art.append(gh);
      out.append(art);
    }
    if (rows.length > shownCount) {
      const more = mk("button", "retry news-more", `SHOW MORE (${rows.length - shownCount} older)`);
      more.type = "button";
      more.addEventListener("click", () => { shownCount += PAGE; list(); });
      out.append(more);
    }
  }

  function render() {
    summary();
    list();
  }

  /* -- loading ---------------------------------------------------------------------------------- */

  async function load(fresh = false) {
    if (busy) return busy;
    loadedAt = Date.now();
    $("news-refresh").disabled = true;
    busy = (async () => {
      try {
        data = await mdpage.getJson("/news" + (fresh ? "?fresh=1" : ""));
        render();
        announce();
      } catch (e) {
        if (!data) $("news-list").replaceChildren(mk("p", "data-note err", `The changes could not be loaded (${e.message}).`));
      } finally {
        $("news-refresh").disabled = false;
        busy = null;
      }
    })();
    return busy;
  }

  async function markSeen() {
    try {
      data = await mdpage.getJson("/news/seen", { method: "POST", headers: { "X-PMM": "1" } });
      render();
      announce();
    } catch { /* kept as it was: try again */ }
  }

  for (const b of $("news-filter").querySelectorAll("button")) {
    b.addEventListener("click", () => {
      kind = b.dataset.kind;
      shownCount = PAGE;
      for (const x of $("news-filter").querySelectorAll("button")) x.setAttribute("aria-checked", String(x === b));
      list();
    });
  }
  $("news-only-new").addEventListener("change", (e) => { onlyNew = e.target.checked; shownCount = PAGE; list(); });
  $("news-refresh").addEventListener("click", () => load(true));
  $("news-seen").addEventListener("click", markSeen);
  load();                                                // in the background: the tab's count and the button

  /* a build downloaded in the Mod Matrix: what's new changes at once ("since your build"), so ask
   * the launcher every few seconds (a local question; GitHub is only read when there is a new build).
   * One question at a time, and none while the window is hidden: asked again as soon as it's back. */
  let timer = null, asking = false;
  async function checkBuild() {
    clearTimeout(timer);
    timer = null;
    if (document.hidden || asking) return;
    asking = true;
    try {
      if (data && !busy) {
        const b = await mdpage.getJson("/news/build");
        if ((b.when || null) !== (data.build_when || null)) await load();
      }
    } catch { /* the launcher is busy or restarting: next time */ }
    asking = false;
    if (!document.hidden) timer = setTimeout(checkBuild, 5000);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) checkBuild(); });
  checkBuild();

  return {
    load, markSeen, info, sinceWhat,
    shown() { if (Date.now() - loadedAt > 10 * 60 * 1000) load(); },
  };
})();
