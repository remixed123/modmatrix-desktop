/* PROCESSOR & MEMORY tab: the page's text, the engine table, the other mods' table and the planner.
 *
 * Built from content/processor.md (the text) and content/processor.json (the numbers) in the
 * app's repo (the launcher's /limits/page and /limits/data: GitHub's copy, else the one from last
 * time or the app's own), so changes to the page need no app release. content/README.md says
 * how to write both. Costs are the sound processor's
 * (M7) work per sample; the limits were found on a unit with real engines, counted as the planner
 * counts (triggers + each voice's heaviest sound). Text from the file is only ever set as text. */
"use strict";

const limits = (() => {
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const pct = (v, of) => `${Math.max(0, Math.min(100, (100 * v) / of)).toFixed(2)}%`;
  const num = (v, or) => (typeof v === "number" && Number.isFinite(v) ? v : or);
  const str = (v) => (typeof v === "string" ? v : "");
  const LEVEL_KEYS = ["light", "medium", "heavy", "vheavy"];           // the colours shell.css has

  let D = null;                                          // the numbers, from read()
  let loadedAt = 0;

  /* -- the file, checked: anything malformed is left out, never shown half-built ---------------- */

  function read(raw) {
    const L = raw.limits || {}, S = raw.display || {};
    const official = num(raw.official, 175);
    const engines = (Array.isArray(raw.engines) ? raw.engines : [])
      .filter((e) => e && !e.hidden && str(e.id) && str(e.name) && Number.isFinite(e.low) && Number.isFinite(e.high))
      .map((e) => ({ id: e.id, name: e.name, short: str(e.short) || e.name, official: e.official === true,
                     algos: str(e.algos), from: str(e.from), low: e.low, high: Math.max(e.low, e.high),
                     heaviest: str(e.heaviest) }));
    const levels = (Array.isArray(raw.levels) ? raw.levels : [])
      .filter((l) => l && LEVEL_KEYS.includes(l.key) && str(l.name))
      .map((l) => ({ key: l.key, name: l.name, upTo: num(l.up_to, Infinity), says: str(l.says) }))
      .sort((a, b) => a.upTo - b.upTo);
    if (levels.length && levels[levels.length - 1].upTo !== Infinity) levels[levels.length - 1].upTo = Infinity;
    const others = (Array.isArray(raw.other_mods) ? raw.other_mods : [])
      .filter((m) => m && str(m.name))
      .map((m) => {
        const p = m.planner;
        const planner = p && str(p.id) && str(p.label)
          ? { id: p.id, label: p.label, v34: num(p.voices_34, 0), v12: num(p.voices_12, 0) } : null;
        return { name: m.name, runsOn: str(m.runs_on), takes: str(m.takes), planner };
      });
    const clean = num(L.clean, 1850), broke = num(L.broke, 2100);
    const heaviest = Math.max(0, ...engines.map((e) => e.high));
    return {
      updated: str(raw.updated), official, engines, levels, others,
      byId: new Map(engines.map((e) => [e.id, e])),
      triggers: num(L.triggers, 100), clean, broke,
      clean12: num(L.clean_12, 1400), broke12: num(L.broke_12, 1650), tipMargin: num(L.tip_margin, 50),
      track: Math.max(num(S.table_track, 4.5), (heaviest / official) * 1.05),
      scale: Math.max(num(S.planner_scale, 2800), broke * 1.15),
      defaults: Array.isArray(raw.planner && raw.planner.defaults) ? raw.planner.defaults : [],
    };
  }

  const level = (cost) => D.levels.find((l) => cost / D.official <= l.upTo) || D.levels[D.levels.length - 1];
  const times = (cost) => {                              // to the nearest half: "½×", "1×", "2½×"
    const x = cost / D.official;
    if (x < 0.5) return "under ½×";
    const h = Math.round(x * 2) / 2;
    return `${h === 0.5 ? "" : Math.floor(h)}${h % 1 ? "½" : ""}×`;
  };
  const span = (lo, hi) => (times(lo) === times(hi) ? times(lo) : `${times(lo)} to ${times(hi)}`);

  /* -- the tables ------------------------------------------------------------------------------- */

  function note(source) {
    const n = $("data-note");                            // no date on the page: the "Engines change" note says it
    n.className = "data-note offline-note";
    n.textContent = source === "saved" ? "Offline: these are the numbers from your last visit, and may be behind."
      : source === "app" ? "Offline: these are the numbers this app came with, and may be behind." : "";
    n.hidden = !n.textContent;
  }

  function legend() {
    $("legend").replaceChildren();
    for (const l of D.levels) {
      const li = el("li");
      li.append(el("span", `chip lv-${l.key}`, l.name), document.createTextNode(` ${l.says}`));
      $("legend").append(li);
    }
  }

  function rows() {
    $("engine-rows").replaceChildren();
    for (const e of D.engines) {
      const tr = el("tr");
      const name = el("td");
      name.append(el("strong", "", e.name));
      if (e.algos) name.append(el("div", "muted", e.algos));
      const lo = level(e.low), hi = level(e.high);
      const say = lo === hi ? lo.name : `${lo.name} to ${hi.name}`;
      const cell = el("td", "cost");
      const track = el("div", "track");
      track.title = `${e.name}: ${say}`;
      for (const l of D.levels.slice(0, -1)) {
        const t = el("span", "tick");
        t.style.left = pct(l.upTo, D.track);
        track.append(t);
      }
      const band = el("span", `band lv-${hi.key}`);
      band.style.left = pct(e.low / D.official, D.track);
      band.style.width = `max(8px, ${pct((e.high - e.low) / D.official, D.track)})`;
      track.append(band);
      cell.append(track, el("div", "lv-text", say));
      tr.append(name, el("td", "", e.from), cell, el("td", "", span(e.low, e.high)), el("td", "", e.heaviest));
      $("engine-rows").append(tr);
    }
    $("other-rows").replaceChildren();
    for (const m of D.others) {
      const tr = el("tr");
      tr.append(el("td", "", m.name), el("td", "", m.runsOn), el("td", "", m.takes));
      $("other-rows").append(tr);
    }
  }

  /* -- the planner ------------------------------------------------------------------------------ */

  const store = {
    get() { try { return JSON.parse(localStorage.getItem("limits.picks") || "null"); } catch { return null; } },
    set(v) { try { localStorage.setItem("limits.picks", JSON.stringify(v)); } catch { /* private window */ } },
  };
  const picks = { 1: null, 2: null, 3: null, 4: null, fx: {} };

  function pickers() {
    const saved = store.get() || {};
    const fallback = (v) => [saved[v], picks[v], D.defaults[v - 1]].find((id) => D.byId.has(id)) || D.engines[0].id;
    for (const v of [1, 2, 3, 4]) picks[v] = fallback(v);
    const savedFx = saved.fx || (saved.sc ? { sc: true } : {});         // 0.6: { sc: true }
    for (const m of D.others) if (m.planner && !(m.planner.id in picks.fx)) picks.fx[m.planner.id] = !!savedFx[m.planner.id];

    $("picks").replaceChildren();
    for (const v of [1, 2, 3, 4]) {
      const label = el("label", "pick");
      label.append(el("span", `vtag v${v}`, `VOICE ${v}`));
      const sel = el("select");
      sel.id = `pick-${v}`;
      for (const [title, list] of [["Official engines", D.engines.filter((e) => e.official)],
                                   ["Mod engines", D.engines.filter((e) => !e.official)]]) {
        if (!list.length) continue;
        const g = el("optgroup");
        g.label = title;
        for (const e of list) {
          const o = el("option", "", e.short);
          o.value = e.id;
          g.append(o);
        }
        sel.append(g);
      }
      setSelect(sel, picks[v]);
      sel.addEventListener("change", () => { picks[v] = sel.value; setSelect(sel, sel.value); changed(); });
      label.append(sel);
      $("picks").append(label);
    }
    $("pick-fx").replaceChildren();
    for (const m of D.others.filter((o) => o.planner)) {
      const id = m.planner.id;
      const label = el("label", "fx-pick");
      const box = el("input");
      box.type = "checkbox";
      box.checked = box.defaultChecked = picks.fx[id];
      box.addEventListener("change", () => { picks.fx[id] = box.defaultChecked = box.checked; changed(); });
      label.append(box, document.createTextNode(` ${m.planner.label}`));
      $("pick-fx").append(label);
    }
    $("mark-clean").style.left = pct(D.clean, D.scale);
    $("mark-broke").style.left = pct(D.broke, D.scale);
  }

  /* the choice also as the option's attribute: a copy of the page (a clone) shows it */
  function setSelect(sel, id) {
    sel.value = id;
    for (const o of sel.options) o.defaultSelected = o.value === id;
  }

  function changed() {
    store.set(picks);
    plan();
  }

  function plan() {
    const cost = (v) => D.byId.get(picks[v]).high;
    const fx = D.others.filter((m) => m.planner && picks.fx[m.planner.id]).map((m) => m.planner);
    const fxSegs = (k) => fx.filter((p) => p[k] > 0).map((p) => ["fx", p.label, p[k]]);
    const segs = [["trig", "triggers", D.triggers], ["v3", "voice 3", cost(3)], ["v4", "voice 4", cost(4)],
                  ...fxSegs("v34"), ["v1", "voice 1", cost(1)], ["v2", "voice 2", cost(2)], ...fxSegs("v12")];
    const total = segs.reduce((s, x) => s + x[2], 0);
    const last = cost(1) + cost(2) + fx.reduce((s, p) => s + p.v12, 0);
    const bar = $("bar");
    bar.textContent = "";
    let at = 0;
    for (const [cls, name, v] of segs) {
      const s = el("span", `seg s-${cls}`);
      if (at + v > D.clean) s.classList.add(at + v > D.broke ? "late" : "near");
      s.style.width = pct(Math.min(v, Math.max(0, D.scale - at)), D.scale);
      s.title = `${name}: ${times(v)} an official voice`;
      if (cls !== "fx" && cls !== "trig") s.textContent = v / D.scale > 0.08 ? name : v / D.scale > 0.025 ? cls.toUpperCase() : "";
      bar.append(s);
      at += v;
    }

    const red = total > D.broke || last > D.broke12, amber = !red && (total > D.clean || last > D.clean12);
    const verdict = $("verdict");
    verdict.className = `verdict ${red ? "bad" : amber ? "warn" : "good"}`;
    verdict.textContent = "";
    const share = Math.round((100 * total) / D.clean);
    verdict.append(el("strong", "", red ? "Likely to crackle." : amber ? "Near the limit." : "Should play clean."), " ",
      red ? `This kit takes about ${share}% of what played clean. Expect crackle on voices 1 and 2 when the `
            + "engines play their heaviest sounds: choose lighter sounds, or a lighter engine on one voice."
        : amber ? `This kit takes about ${share}% of what played clean: untested ground. It may crackle on voices 1 `
            + "and 2 with the heaviest sounds. Listen for it, or lighten a voice."
        : `This kit takes about ${share}% of what played clean, even with every engine on its heaviest sound.`);
    if (cost(1) + cost(2) > cost(3) + cost(4) + D.tipMargin) {
      verdict.append(el("span", "tip-line",
        "Tip: put the heavier engines on voices 3 and 4. They're done first; voices 1 and 2 get what's left."));
    }
  }

  /* -- the text: content/processor.md ------------------------------------------------------------
   * Markdown, with: "<!-- pmm:name -->" alone on a line where the app puts one of its parts
   * (the [data-part] elements in shell.html); "<!-- toc: Label -->" after a heading to list it
   * in the contents; "> [!WARNING]" / "> [!NOTE]" callouts (yellow / blue box); and a little
   * HTML for the cards, keeping only the page's own classes (CLASSES). README in content/. */

  const CLASSES = new Set(["pair", "card", "voices", "first", "badge", "ok", "you", "muted", "lede"]);
  const CALLOUTS = { WARNING: "prelim", CAUTION: "prelim", IMPORTANT: "prelim", NOTE: "aside", TIP: "aside" };
  let pageText = null;

  function slugger() {
    const seen = new Map();
    return (text) => {
      const s = "l-" + (text.trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-") || "x");
      const n = seen.get(s) || 0;
      seen.set(s, n + 1);
      return n ? `${s}-${n}` : s;
    };
  }

  function sanitize(html) {
    DOMPurify.addHook("uponSanitizeAttribute", (node, data) => {
      if (data.attrName !== "class") return;
      const keep = data.attrValue.split(/\s+/).filter((c) => CLASSES.has(c));
      if (keep.length) data.attrValue = keep.join(" ");
      else data.keepAttr = false;
    });
    try {
      return DOMPurify.sanitize(html, {
        FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "iframe", "object", "embed", "img"],
        FORBID_ATTR: ["style", "id"],
      });
    } finally {
      DOMPurify.removeHook("uponSanitizeAttribute");
    }
  }

  function renderPage(text) {
    const md = text
      .replace(/^<!--\s*pmm:([a-z-]+)\s*-->[ \t]*$/gm, '<div data-pmm="$1"></div>')
      .replace(/^(#{1,4} .*?)\s*<!--\s*toc:\s*(.*?)\s*-->[ \t]*$/gm,
               (_, h, label) => `${h} <span data-toc="${label.replace(/[&<>"]/g, "")}"></span>`);
    const root = el("div");
    root.innerHTML = sanitize(marked.parse(md, { gfm: true, async: false }));

    for (const q of root.querySelectorAll("blockquote")) {           // > [!WARNING] ... callouts
      const walker = document.createTreeWalker(q, NodeFilter.SHOW_TEXT);
      let t = walker.nextNode();
      while (t && !t.data.trim()) t = walker.nextNode();
      const m = t && /^\s*\[!(\w+)\]\s*/.exec(t.data);
      if (!m || !CALLOUTS[m[1].toUpperCase()]) continue;
      t.data = t.data.slice(m[0].length);
      const box = el("div", CALLOUTS[m[1].toUpperCase()]);
      box.append(...q.childNodes);
      q.replaceWith(box);
    }
    for (const t of root.querySelectorAll("table")) {
      const wrap = el("div", "table");
      t.replaceWith(wrap);
      wrap.append(t);
    }
    const slug = slugger(), toc = [];
    for (const h of root.querySelectorAll("h1, h2, h3, h4")) {
      const mark = h.querySelector("span[data-toc]");
      if (mark) mark.remove();
      h.id = slug(h.textContent);
      if (mark) toc.push([h.id, mark.dataset.toc]);
    }
    for (const a of root.querySelectorAll("a[href]")) {
      const href = a.getAttribute("href");
      if (href.startsWith("#")) continue;                              // the page's own: see onClick
      if (/^https:\/\//i.test(href)) { a.target = "_blank"; a.rel = "noopener"; } else a.removeAttribute("href");
    }

    // the app's parts back to the holder, then into this text's markers
    const holder = $("limits-parts");
    for (const p of document.querySelectorAll("#limits-page [data-part]")) holder.append(p);
    const nav = holder.querySelector('[data-part="contents"]');
    nav.replaceChildren(...toc.map(([id, label]) => { const a = el("a", "", label); a.href = "#" + id; return a; }));
    for (const slot of root.querySelectorAll("[data-pmm]")) {
      const part = holder.querySelector(`[data-part="${CSS.escape(slot.dataset.pmm)}"]`);
      if (part) slot.replaceWith(part); else slot.remove();
    }
    for (const part of [...holder.querySelectorAll("[data-part]")]) {  // a marker missing: at the end
      if (part.dataset.part !== "contents" || toc.length) root.append(part);
    }
    $("limits-page").replaceChildren(...root.childNodes);
  }

  /* the heading just before the planner (PLAN A KIT jumps there) */
  function planTarget() {
    const planner = document.querySelector('#limits-page [data-part="planner"]');
    let n = planner;
    while (n && n.previousElementSibling) {
      n = n.previousElementSibling;
      if (/^H[1-3]$/.test(n.tagName)) return n;
    }
    return planner;
  }

  function onClick(e) {
    const a = e.target.closest("#limits a[href^='#']");
    if (!a) return;
    e.preventDefault();
    const id = a.getAttribute("href").slice(1);
    const t = a.dataset.part === "plan-button" ? planTarget() : id && document.getElementById(id);
    if (t) t.scrollIntoView({ behavior: "smooth" });
  }

  /* -- loading ---------------------------------------------------------------------------------- */

  async function getJson(url) {
    const r = await fetch(url);
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.statusText);
    return body;
  }

  async function load() {
    loadedAt = Date.now();
    const [page, nums] = await Promise.allSettled([getJson("/limits/page"), getJson("/limits/data")]);
    if (page.status === "fulfilled") {
      if (page.value.data !== pageText) {
        renderPage(page.value.data);
        pageText = page.value.data;
      }
    } else if (pageText === null) {                      // nothing on screen yet
      $("limits-page").replaceChildren(el("p", "data-note err", `This page could not be loaded (${page.reason.message}).`));
      return;
    }
    try {
      if (nums.status === "rejected") throw nums.reason;
      const next = read(nums.value.data);
      if (!next.engines.length || !next.levels.length) throw new Error("the numbers file has no engines or levels");
      D = next;
      note(nums.value.source);
      legend();
      rows();
      pickers();
      plan();
    } catch (e) {
      if (D) return;                                     // keep what's on screen
      const n = $("data-note");
      n.className = "data-note err";
      n.textContent = `The numbers could not be loaded (${e.message}).`;
    }
  }

  /* -- copying: the page as a document (no buttons, bars or menus; the planner's choices as text) */

  function forCopy(node) {
    const c = el("div");
    c.append(node);
    for (const n of c.querySelectorAll(".doc-bar, .toc, .plan-cta, .meter, .track, figure.lane, script")) n.remove();
    for (const p of c.querySelectorAll(".pick")) {
      const tag = p.querySelector(".vtag"), sel = p.querySelector("select");
      const o = sel && (sel.querySelector("option[selected]") || sel.querySelector("option"));
      p.replaceWith(el("p", "", `${tag ? tag.textContent : ""}${o ? ": " + o.textContent : ""}`));
    }
    for (const l of c.querySelectorAll(".fx-pick")) {
      const box = l.querySelector("input");
      l.replaceWith(el("p", "", `${l.textContent.trim()}: ${box && box.hasAttribute("checked") ? "on" : "off"}`));
    }
    for (const s of c.querySelectorAll("select, input")) s.remove();
    // the text as laid out (innerText needs the copy on the page, out of sight)
    c.className = "copy-stage";
    document.body.append(c);
    const text = c.innerText;
    c.remove();
    return { html: cleanHtml(c), text };
  }

  function copyAll(btn) {
    const page = document.querySelector("#limits .limits");
    const { html, text } = forCopy(page.cloneNode(true));
    copyWhole(page, btn, html, text);
  }

  load();
  $("limits-print").addEventListener("click", () => window.print());
  $("limits-copy").addEventListener("click", () => copyAll($("limits-copy")));
  $("limits").addEventListener("click", onClick);
  return {
    shown() { if (Date.now() - loadedAt > 15 * 60 * 1000) load(); },   // newer numbers while the app stays open
    forCopy,
    copyAll,
  };
})();
