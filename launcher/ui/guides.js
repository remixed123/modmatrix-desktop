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

async function loadMods() {
  const note = $("list-note");
  note.className = "note";
  note.textContent = "Loading the mod list...";
  state.loading = fetch("/guides/mods").then(async (r) => {
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.statusText);
    return body.mods;
  });
  try {
    state.mods = await state.loading;
    note.textContent = "";
    note.hidden = true;
    renderList();
    const last = state.mods.find((m) => m.id === store.get("mod"));
    if (last) openMod(last, null, false);
  } catch (e) {
    note.className = "note err";
    note.textContent = `The mod list could not be loaded (${e.message}). `;
    const again = document.createElement("button");
    again.textContent = "Try again";
    again.className = "retry";
    again.addEventListener("click", loadMods);
    note.append(again);
  } finally {
    state.loading = null;
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

async function openMod(m, anchor = null, focus = true) {
  state.current = m;
  store.set("mod", m.id);
  for (const b of $("list").querySelectorAll("button[data-id]")) {
    if (b.dataset.id === m.id) b.setAttribute("aria-current", "true");
    else b.removeAttribute("aria-current");
  }
  const doc = $("doc");
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
  const parts = [bar(m)];
  if (cached) parts.push(el("p", "offline", "Offline: this is the copy from your last visit."));
  parts.push(render(m, text));
  doc.replaceChildren(...parts);
  const target = anchor && doc.querySelector(`[id="${CSS.escape("g-" + anchor)}"]`);
  if (target) target.scrollIntoView();
  else doc.scrollTop = 0;
  if (focus) doc.focus({ preventScroll: true });
}

function bar(m) {
  const d = el("div", "doc-bar");
  if (m.repo) d.append(el("span", "", `from ${m.repo}`));
  if (m.repo && m.readme) {
    const a = el("a", "", "View on GitHub");
    a.href = ghPage(m, m.readme);
    a.target = "_blank";
    a.rel = "noopener";
    d.append(a);
  }
  return d;
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
  if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
  const next = document.activeElement.id === "tab-matrix" ? "guides" : "matrix";
  showView(next);
  $("tab-" + next).focus();
});
for (const b of $("filter").querySelectorAll("button")) b.addEventListener("click", () => setKind(b.dataset.kind));
$("search").addEventListener("input", (e) => { state.query = e.target.value; renderList(); });
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Escape" && e.target.value) { e.target.value = ""; state.query = ""; renderList(); e.stopPropagation(); }
  if (e.key === "Enter") { const first = $("list").querySelector("button[data-id]"); if (first) first.click(); }
});
if (["mod", "engine"].includes(store.get("kind"))) setKind(store.get("kind"));
loadMods();                                             // in the background: ready when the tab is opened
