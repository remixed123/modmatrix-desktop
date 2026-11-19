/* The app's own pages written in Markdown (content/*.md in the app's repo): PROCESSOR & MEMORY,
 * TROUBLESHOOTING. Markdown, with:
 *   "<!-- pmm:name -->" alone on a line: one of the app's parts goes there (an element with
 *     data-part="name" in the page's holder; a part without its line goes at the end);
 *   "<!-- toc: Label -->" after a heading: listed in the contents (the "contents" part);
 *   "> [!WARNING]" / "> [!NOTE]": the yellow / blue box;
 *   a little HTML, keeping only the classes in CLASSES (the cards);
 *   links: "#heading-id" on the page, "#view-limits" (or -guides, -news, -help) another tab,
 *     https links in the browser. content/README.md explains it for writers.
 * Also copying a page as a document (no buttons, bars or menus). */
"use strict";

const mdpage = (() => {
  const CLASSES = new Set(["pair", "card", "voices", "first", "badge", "ok", "you", "muted", "lede"]);
  const CALLOUTS = { WARNING: "prelim", CAUTION: "prelim", IMPORTANT: "prelim", NOTE: "aside", TIP: "aside" };
  const VIEWS = ["matrix", "guides", "limits", "news", "help"];

  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  function slugger(prefix) {
    const seen = new Map();
    return (text) => {
      const s = prefix + (text.trim().toLowerCase().replace(/[^\p{L}\p{N}\s-]/gu, "").replace(/\s+/g, "-") || "x");
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

  /* text into target; the parts (data-part) live in holder when not shown; ids start with prefix */
  function render(text, { target, holder, prefix }) {
    const md = text
      .replace(/^<!--\s*pmm:([a-z-]+)\s*-->[ \t]*$/gm, '<div data-pmm="$1"></div>')
      .replace(/^(#{1,4} .*?)\s*<!--\s*toc:\s*(.*?)\s*-->[ \t]*$/gm,
               (_, h, label) => `${h} <span data-toc="${label.replace(/[&<>"]/g, "")}"></span>`);
    const root = mk("div");
    root.innerHTML = sanitize(marked.parse(md, { gfm: true, async: false }));

    for (const q of root.querySelectorAll("blockquote")) {           // > [!WARNING] ... callouts
      const walker = document.createTreeWalker(q, NodeFilter.SHOW_TEXT);
      let t = walker.nextNode();
      while (t && !t.data.trim()) t = walker.nextNode();
      const m = t && /^\s*\[!(\w+)\]\s*/.exec(t.data);
      if (!m || !CALLOUTS[m[1].toUpperCase()]) continue;
      t.data = t.data.slice(m[0].length);
      const box = mk("div", CALLOUTS[m[1].toUpperCase()]);
      box.append(...q.childNodes);
      q.replaceWith(box);
    }
    for (const t of root.querySelectorAll("table")) {
      const wrap = mk("div", "table");
      t.replaceWith(wrap);
      wrap.append(t);
    }
    const slug = slugger(prefix), toc = [];
    for (const h of root.querySelectorAll("h1, h2, h3, h4")) {
      const mark = h.querySelector("span[data-toc]");
      if (mark) mark.remove();
      h.id = slug(h.textContent);
      if (mark) toc.push([h.id, mark.dataset.toc]);
    }
    for (const a of root.querySelectorAll("a[href]")) {
      const href = a.getAttribute("href");
      if (href.startsWith("#")) continue;                              // on the page or a tab: bind()
      if (/^https:\/\//i.test(href)) { a.target = "_blank"; a.rel = "noopener"; } else a.removeAttribute("href");
    }

    // the app's parts back to the holder, then into this text's markers
    for (const p of target.querySelectorAll("[data-part]")) holder.append(p);
    const nav = holder.querySelector('[data-part="contents"]');
    if (nav) nav.replaceChildren(...toc.map(([id, label]) => { const a = mk("a", "", label); a.href = "#" + id; return a; }));
    for (const slot of root.querySelectorAll("[data-pmm]")) {
      const part = holder.querySelector(`[data-part="${CSS.escape(slot.dataset.pmm)}"]`);
      if (part) slot.replaceWith(part); else slot.remove();
    }
    for (const part of [...holder.querySelectorAll("[data-part]")]) {  // a marker missing: at the end
      if (part.dataset.part !== "contents" || toc.length) root.append(part);
    }
    target.replaceChildren(...root.childNodes);
  }

  /* "#..." links in a section: another tab (#view-name), a part (special), or a heading */
  function bind(section, special) {
    section.addEventListener("click", (e) => {
      const a = e.target.closest("a[href^='#']");
      if (!a || !section.contains(a)) return;
      e.preventDefault();
      const id = a.getAttribute("href").slice(1);
      if (id.startsWith("view-") && VIEWS.includes(id.slice(5))) {
        showView(id.slice(5));
        const s = document.querySelector(".page-view:not([hidden])");
        if (s) s.scrollTop = 0;
        return;
      }
      const t = (special && special(a)) || (id && document.getElementById(id));
      if (t) t.scrollIntoView({ behavior: "smooth" });
    });
  }

  async function getJson(url, opts) {
    const r = await fetch(url, opts);
    const body = await r.json();
    if (!r.ok) throw new Error(body.error || r.statusText);
    return body;
  }

  /* a page (or part of one) as a document: no buttons, bars or menus; the planner's choices as text */
  function forCopy(node) {
    const c = mk("div");
    c.append(node);
    for (const n of c.querySelectorAll(".doc-bar, .toc, .plan-cta, .meter, .track, figure.lane, .news-tools, script")) n.remove();
    for (const p of c.querySelectorAll(".pick")) {
      const tag = p.querySelector(".vtag"), sel = p.querySelector("select");
      const o = sel && (sel.querySelector("option[selected]") || sel.querySelector("option"));
      p.replaceWith(mk("p", "", `${tag ? tag.textContent : ""}${o ? ": " + o.textContent : ""}`));
    }
    for (const l of c.querySelectorAll(".fx-pick")) {
      const box = l.querySelector("input");
      l.replaceWith(mk("p", "", `${l.textContent.trim()}: ${box && box.hasAttribute("checked") ? "on" : "off"}`));
    }
    for (const s of c.querySelectorAll("select, input, button")) s.remove();
    // the text as laid out (innerText needs the copy on the page, out of sight)
    c.className = "copy-stage";
    document.body.append(c);
    const text = c.innerText;
    c.remove();
    return { html: cleanHtml(c), text };
  }

  /* COPY / Copy whole page: the page in section (its .limits) */
  function copyAll(section) {
    const page = section.querySelector(".limits");
    const btn = section.querySelector(".copy-page");
    const { html, text } = forCopy(page.cloneNode(true));
    copyWhole(page, btn, html, text);
  }

  /* each page's COPY and PRINT buttons */
  for (const s of document.querySelectorAll(".page-view")) {
    const copy = s.querySelector(".copy-page"), print = s.querySelector(".print-page");
    if (copy) copy.addEventListener("click", () => copyAll(s));
    if (print) print.addEventListener("click", () => window.print());
  }

  /* a page's REFRESH: gets the page again from GitHub (past its cache), and says when it's done
   * (the page may look the same: nothing changed) */
  function refreshButton(btn, load) {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      btn.textContent = "REFRESHING...";
      try { await load(); } finally {
        btn.textContent = "REFRESHED";
        setTimeout(() => { btn.textContent = "REFRESH"; btn.disabled = false; }, 1500);
      }
    });
  }

  return { render, bind, getJson, forCopy, copyAll, refreshButton };
})();
