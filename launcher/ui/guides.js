/* The app's page: MOD MATRIX / USER GUIDES tabs, and the user guides (each mod's README).
 * The mod list comes from the launcher (/guides/mods: the Mod Matrix's mods, all repos, A-Z);
 * each README from /guides/readme (GitHub, or the copy from last time when offline). README
 * HTML is cleaned with DOMPurify: the READMEs come from other people's repos. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = { mods: [], kind: "all", query: "", current: null, docs: new Map(), loading: null };

const store = {
  get(k) { try { return localStorage.getItem("guides." + k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem("guides." + k, v); } catch { /* private window */ } },
};

/* -- tabs -------------------------------------------------------------------------------------- */

function showView(view) {
  for (const t of document.querySelectorAll(".tab")) t.setAttribute("aria-selected", String(t.dataset.view === view));
  $("matrix").classList.toggle("off", view !== "matrix");
  $("guides").hidden = view !== "guides";
  if (view === "guides" && !state.mods.length && !state.loading) loadMods();
}

/* -- the list ---------------------------------------------------------------------------------- */

/* fresh: Refresh. The Mod Matrix reads the repos once, when the app starts; the launcher reads
 * them again, so mods released since show up, and the guides are fetched again too. */
let noteTimer = null;
async function loadMods(fresh = false) {
  const note = $("list-note");
  const before = new Set(state.mods.map((m) => m.id));
  clearTimeout(noteTimer);
  note.className = "note";
  note.hidden = false;
  note.textContent = fresh && state.mods.length ? "Checking for new mods and guides..." : "Loading the mod list...";
  $("refresh").disabled = true;
  $("refresh").classList.add("busy");
  state.loading = fetch("/guides/mods" + (fresh ? "?fresh=1" : "")).then(async (r) => {
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.statusText);
    return body.mods;
  });
  try {
    state.mods = await state.loading;
    renderList();
    if (fresh) {
      state.docs.clear();                              // the guides too: fetched again when shown
      const added = before.size ? state.mods.filter((m) => !before.has(m.id)) : [];
      note.textContent = added.length
        ? `New: ${added.map((m) => m.title).join(", ")}. To build with ${added.length > 1 ? "them" : "it"}, use CHECK FOR UPDATES (top right) and UPDATE NOW.`
        : "Up to date: no new mods since the list was loaded. Guides reloaded.";
      noteTimer = setTimeout(() => { note.hidden = true; }, added.length ? 20000 : 4000);
      const cur = state.current && state.mods.find((m) => m.id === state.current.id);
      if (cur) openMod(cur, null, false, true);
    } else {
      note.textContent = "";
      note.hidden = true;
      const last = state.mods.find((m) => m.id === store.get("mod"));
      if (last) openMod(last, null, false);
    }
  } catch (e) {
    note.className = "note err";
    note.textContent = `The mod list could not be loaded (${e.message}). `;
    const again = document.createElement("button");
    again.textContent = "Try again";
    again.className = "retry";
    again.addEventListener("click", () => loadMods(fresh));
    note.append(again);
  } finally {
    state.loading = null;
    $("refresh").disabled = false;
    $("refresh").classList.remove("busy");
  }
}

function setKind(kind) {
  state.kind = kind;
  store.set("kind", kind);
  for (const b of $("filter").querySelectorAll("button")) b.setAttribute("aria-checked", String(b.dataset.kind === kind));
  renderList();
}

function renderList() {
  const ul = $("list");
  ul.replaceChildren();
  const words = state.query.toLowerCase().split(/\s+/).filter(Boolean);
  const shown = state.mods.filter((m) => (state.kind === "all" || m.kind === state.kind) && matches(m, words));
  for (const m of shown) {
    const b = document.createElement("button");
    b.dataset.id = m.id;
    if (state.current && state.current.id === m.id) b.setAttribute("aria-current", "true");
    const head = el("div", "row-head");
    head.append(el("span", "title", m.title));
    if (m.repo) {
      const from = el("span", "from", m.repo.split("/")[0]);
      from.title = `from ${m.repo}`;
      head.append(from);
    }
    head.append(el("span", `kind ${m.kind}`, m.kind === "engine" ? "ENGINE" : "MOD"));
    b.title = m.title;
    b.append(head);
    if (m.summary) b.append(el("div", "summary", m.summary));
    b.addEventListener("click", () => openMod(m));
    const li = document.createElement("li");
    li.append(b);
    ul.append(li);
  }
  if (!shown.length && state.mods.length) {
    const what = state.kind === "engine" ? "engines" : "mods";
    const li = el("li", "note", words.length ? `No ${what} match "${state.query.trim()}".` : `No ${what} in these repos.`);
    ul.append(li);
  }
}

/* every word somewhere in the name, summary, repo or folder (any order, any case) */
function matches(m, words) {
  if (!words.length) return true;
  const hay = [m.title, m.summary, m.repo, m.dir, m.kind].filter(Boolean).join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}

function el(tag, cls, text) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  return e;
}

/* -- a guide ----------------------------------------------------------------------------------- */

const ghPage = (m, path) => `https://github.com/${m.repo}/blob/${m.ref}/${path}`;
const ghRaw = (m, path) => `https://raw.githubusercontent.com/${m.repo}/${m.ref}/${path}`;

async function openMod(m, anchor = null, focus = true, keepScroll = false) {
  state.current = m;
  store.set("mod", m.id);
  for (const b of $("list").querySelectorAll("button[data-id]")) {
    if (b.dataset.id === m.id) b.setAttribute("aria-current", "true");
    else b.removeAttribute("aria-current");
  }
  const doc = $("doc");
  const top = doc.scrollTop;
  if (!m.readme) {
    doc.replaceChildren(bar(m), el("p", "note", "This mod has no user guide."));
    return;
  }
  if (!state.docs.has(m.id)) {
    doc.replaceChildren(bar(m), el("p", "note", "Loading the guide..."));
    try {
      const q = new URLSearchParams({ repo: m.repo, ref: m.ref, path: m.readme });
      const r = await fetch(`/guides/readme?${q}`);
      const body = await r.json();
      if (!r.ok) throw new Error(body.error || r.statusText);
      state.docs.set(m.id, body);
    } catch (e) {
      if (state.current !== m) return;
      const p = el("p", "note err", e.message + " ");
      const again = el("button", "retry", "Try again");
      again.addEventListener("click", () => openMod(m, anchor));
      p.append(again);
      doc.replaceChildren(bar(m), p);
      return;
    }
  }
  if (state.current !== m) return;                 // another one was chosen meanwhile
  const { text, cached } = state.docs.get(m.id);
  const parts = [bar(m, true)];
  if (cached) parts.push(el("p", "offline", "Offline: this is the copy from your last visit."));
  parts.push(render(m, text));
  doc.replaceChildren(...parts);
  const target = anchor && doc.querySelector(`[id="${CSS.escape("g-" + anchor)}"]`);
  if (target) target.scrollIntoView();
  else doc.scrollTop = keepScroll ? top : 0;
  if (focus) doc.focus({ preventScroll: true });
}

function bar(m, tools = false) {
  const d = el("div", "doc-bar");
  if (m.repo) d.append(el("span", "", `from ${m.repo}`));
  if (m.repo && m.readme) {
    const a = el("a", "", "View on GitHub");
    a.href = ghPage(m, m.readme);
    a.target = "_blank";
    a.rel = "noopener";
    d.append(a);
  }
  if (tools) {
    const t = el("span", "doc-tools");
    const copy = el("button", "", "COPY");
    copy.type = "button";
    copy.title = "Copy the whole guide, to paste into a document or a message";
    copy.addEventListener("click", () => copyGuide(copy));
    const print = el("button", "", "PRINT");
    print.type = "button";
    print.title = "Print the guide, or save it as a PDF";
    print.addEventListener("click", () => window.print());
    t.append(copy, print);
    d.append(t);
  }
  return d;
}

/* -- copy and print ---------------------------------------------------------------------------- */

/* What goes on the clipboard from a guide: its HTML without the page's colours (the browser
 * would copy them inline: pale purple text in a document) and its text. A selection outside
 * the guide is copied as the browser does it. */
let copying = null;                                    // set by COPY: the whole guide
document.addEventListener("copy", (e) => {
  const md = $("doc").querySelector(".md");
  let html, text;
  if (copying) {
    ({ html, text } = copying);
  } else {
    const sel = window.getSelection();
    if (!md || !sel.rangeCount || sel.isCollapsed || !md.contains(sel.getRangeAt(0).commonAncestorContainer)) return;
    const div = document.createElement("div");
    div.append(sel.getRangeAt(0).cloneContents());
    html = cleanHtml(div);
    text = sel.toString();
  }
  e.clipboardData.setData("text/html", html);
  e.clipboardData.setData("text/plain", text);
  e.preventDefault();
});

function cleanHtml(node) {
  const c = node.cloneNode(true);
  for (const a of c.querySelectorAll("a[href]")) {
    if (a.getAttribute("href").startsWith("#")) a.replaceWith(...a.childNodes);   // links within the app
  }
  for (const e of c.querySelectorAll("[id]")) e.removeAttribute("id");
  for (const w of c.querySelectorAll("div.table")) w.replaceWith(...w.childNodes);
  return c.innerHTML;
}

/* Right-click in a guide: the app's own menu (pywebview empties or turns off the system one in a
 * release build). The selection is kept while the menu is open: its items don't take focus on
 * mouse down. */
const ctx = { menu: null, range: null };

function ctxMenu() {
  if (ctx.menu) return ctx.menu;
  const m = el("div");
  m.id = "ctx";
  m.setAttribute("role", "menu");
  m.hidden = true;
  const item = (label, run) => {
    const b = el("button", "", label);
    b.type = "button";
    b.setAttribute("role", "menuitem");
    b.addEventListener("mousedown", (e) => e.preventDefault());
    b.addEventListener("click", () => { closeCtx(); run(); });
    m.append(b);
    return b;
  };
  ctx.copy = item("Copy", () => {
    restoreSel();
    try { document.execCommand("copy"); } catch { /* nothing selected */ }
  });
  item("Select all", () => {
    const md = $("doc").querySelector(".md");
    if (!md) return;
    const r = document.createRange();
    r.selectNodeContents(md);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(r);
  });
  m.append(el("hr"));
  item("Copy whole guide", () => { const b = $("doc").querySelector(".doc-tools button"); if (b) copyGuide(b); });
  item("Print guide", () => window.print());
  m.addEventListener("keydown", (e) => {
    const items = [...m.querySelectorAll("button:not(:disabled)")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
    }
  });
  document.body.append(m);
  ctx.menu = m;
  return m;
}

function restoreSel() {
  if (!ctx.range) return;
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(ctx.range);
}

function openCtx(x, y) {
  const m = ctxMenu();
  const sel = window.getSelection();
  const md = $("doc").querySelector(".md");
  ctx.range = sel.rangeCount && !sel.isCollapsed && md && md.contains(sel.getRangeAt(0).commonAncestorContainer)
    ? sel.getRangeAt(0).cloneRange() : null;
  ctx.copy.disabled = !ctx.range;
  m.hidden = false;
  const w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = Math.max(4, Math.min(x, window.innerWidth - w - 4)) + "px";
  m.style.top = Math.max(4, Math.min(y, window.innerHeight - h - 4)) + "px";
}

function closeCtx() {
  if (ctx.menu && !ctx.menu.hidden) ctx.menu.hidden = true;
}

$("doc").addEventListener("contextmenu", (e) => {
  if (!e.target.closest(".md")) return;
  e.preventDefault();
  openCtx(e.clientX, e.clientY);
});
document.addEventListener("mousedown", (e) => { if (ctx.menu && !ctx.menu.contains(e.target)) closeCtx(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeCtx();
  if (e.key === "ContextMenu" || (e.shiftKey && e.key === "F10")) {     // the keyboard's menu key
    const md = $("doc").querySelector(".md");
    if (!md || $("guides").hidden) return;
    e.preventDefault();
    const r = md.getBoundingClientRect();
    openCtx(r.left + 40, Math.max(r.top, 60) + 20);
    ctx.menu.querySelector("button:not(:disabled)").focus();
  }
});
$("doc").addEventListener("scroll", closeCtx);
window.addEventListener("blur", closeCtx);
window.addEventListener("resize", closeCtx);

async function copyGuide(btn) {
  const md = $("doc").querySelector(".md");
  if (!md) return;
  const html = cleanHtml(md), text = md.innerText;
  let ok = false;
  // the copy event above, with the guide selected (WebKit copies only with a selection)
  const sel = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(md);
  sel.removeAllRanges();
  sel.addRange(range);
  copying = { html, text };
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  copying = null;
  sel.removeAllRanges();
  if (!ok && navigator.clipboard && window.ClipboardItem) {
    try {
      await navigator.clipboard.write([new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([text], { type: "text/plain" }),
      })]);
      ok = true;
    } catch { ok = false; }
  }
  btn.textContent = ok ? "COPIED" : "NOT COPIED";
  btn.classList.toggle("done", ok);
  setTimeout(() => { btn.textContent = "COPY"; btn.classList.remove("done"); }, 1800);
}

/* GitHub's heading anchors: lower case, punctuation dropped, spaces to dashes, repeats -1, -2 */
function slugger() {
  const seen = new Map();
  return (text) => {
    let s = text.trim().toLowerCase().replace(/[^\p{L}\p{N}\s_-]/gu, "").replace(/\s/g, "-");
    const n = seen.get(s) || 0;
    seen.set(s, n + 1);
    return n ? `${s}-${n}` : s;
  };
}

function render(m, text) {
  const html = DOMPurify.sanitize(marked.parse(text, { gfm: true, async: false }), {
    FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "iframe", "object", "embed"],
    FORBID_ATTR: ["style"],
  });
  const div = el("div", "md");
  div.innerHTML = html;
  const slug = slugger();
  for (const h of div.querySelectorAll("h1, h2, h3, h4, h5, h6")) h.id = "g-" + slug(h.textContent);   // prefixed: no clash with the page's ids
  for (const t of div.querySelectorAll("table")) {
    const wrap = el("div", "table");
    t.replaceWith(wrap);
    wrap.append(t);
  }
  for (const img of div.querySelectorAll("img[src]")) {
    const src = img.getAttribute("src");
    if (!/^(https:|data:)/i.test(src)) img.src = new URL(src, ghRaw(m, m.readme)).href;
  }
  for (const a of div.querySelectorAll("a[href]")) linkUp(m, a);
  return div;
}

/* Where a README link goes: its own headings and other mods' guides stay here; the rest opens
 * in the browser (GitHub for the repo's other files). */
function linkUp(m, a) {
  const href = a.getAttribute("href");
  if (href.startsWith("#")) {
    a.addEventListener("click", (e) => { e.preventDefault(); jump(decodeURIComponent(href.slice(1))); });
    return;
  }
  let url;
  try { url = new URL(href, ghPage(m, m.readme)); } catch { a.removeAttribute("href"); return; }
  const hit = guideAt(url);
  if (hit) {
    a.href = "#";
    a.addEventListener("click", (e) => {
      e.preventDefault();
      if (hit.mod === state.current && hit.anchor) jump(hit.anchor);
      else openMod(hit.mod, hit.anchor);
    });
    return;
  }
  if (!/^(https?|mailto):$/.test(url.protocol)) { a.removeAttribute("href"); return; }
  a.href = url.href;
  a.target = "_blank";
  a.rel = "noopener";
}

function jump(anchor) {
  const t = $("doc").querySelector(`[id="${CSS.escape("g-" + anchor)}"]`);
  if (t) t.scrollIntoView({ behavior: "smooth" });
}

/* A GitHub link to a mod's folder or README, in any listed repo -> {mod, anchor} */
function guideAt(url) {
  if (url.hostname !== "github.com") return null;
  const parts = decodeURIComponent(url.pathname).split("/").filter(Boolean);   // owner name blob|tree ref... path...
  if (parts.length < 4 || !["blob", "tree"].includes(parts[2])) return null;
  const repo = `${parts[0]}/${parts[1]}`.toLowerCase();
  const rest = parts.slice(3).join("/");
  for (const mod of state.mods) {
    if (!mod.repo || mod.repo.toLowerCase() !== repo || !rest.startsWith(mod.ref + "/")) continue;
    const path = rest.slice(mod.ref.length + 1).replace(/\/$/, "");
    if (path === mod.dir || path === mod.readme || (mod.readme && path + "/README.md" === mod.readme)) {
      return { mod, anchor: url.hash ? decodeURIComponent(url.hash.slice(1)) : null };
    }
  }
  return null;
}

/* -- start ------------------------------------------------------------------------------------- */

for (const t of document.querySelectorAll(".tab")) t.addEventListener("click", () => showView(t.dataset.view));
$("tabs").addEventListener("keydown", (e) => {
  if ((e.key !== "ArrowLeft" && e.key !== "ArrowRight") || !e.target.classList.contains("tab")) return;
  const next = document.activeElement.id === "tab-matrix" ? "guides" : "matrix";
  showView(next);
  $("tab-" + next).focus();
});
for (const b of $("filter").querySelectorAll("button")) b.addEventListener("click", () => setKind(b.dataset.kind));
$("refresh").addEventListener("click", () => loadMods(true));
$("search").addEventListener("input", (e) => { state.query = e.target.value; renderList(); });
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Escape" && e.target.value) { e.target.value = ""; state.query = ""; renderList(); e.stopPropagation(); }
  if (e.key === "Enter") { const first = $("list").querySelector("button[data-id]"); if (first) first.click(); }
});
if (["mod", "engine"].includes(store.get("kind"))) setKind(store.get("kind"));
loadMods();                                             // in the background: ready when the tab is opened
