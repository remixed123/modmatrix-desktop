/* CHECK FOR UPDATES (right of the tabs): asks the launcher what changed since the Mod Matrix
 * started (/updates/check) and shows it in a panel. UPDATE NOW (/updates/apply) is offered only
 * when a build would otherwise miss something: a newer Mod Matrix, or mods added, removed or
 * changed (list, RAM figures, requirements). Mods whose code alone changed need nothing: a
 * build fetches each mod as it is then. A newer app is a download, never automatic.
 *
 * It also checks by itself, quietly: once the Mod Matrix has been running AUTO minutes, and
 * then each time the last check is AUTO minutes old (so hourly), while the window isn't
 * minimised; coming back to the window runs a check that is due straight away. Nothing
 * pops up: the button turns yellow (UPDATES AVAILABLE / UPDATES FOUND) and its tooltip says what
 * was found. It stays so until the person presses CLEAR in the panel (or UPDATE NOW): a check
 * that finds nothing doesn't clear it, and the launcher keeps it (/updates/state), so a page
 * reload doesn't lose it.
 * The quiet check costs GitHub a few small requests; the launcher reads the repos and asks
 * GitHub's API only when something is new (?quiet=1). */
"use strict";

(() => {
  const btn = $("check");
  const panel = $("updates");
  const body = $("updates-body");
  const actions = $("updates-actions");
  const started = Date.now();               // this page loads when the Mod Matrix (re)starts
  const AUTO = Math.max(1, Number(document.querySelector('meta[name="pmm-auto-check"]')?.content) || 60) * 60000;
  let lastCheck = null;
  let found = null;                         // {result, at}: the last check that found something
  let seen = null;                          // the finding the person has cleared: not flagged again
  let busy = false;

  /* its tooltip (tips.js) says how long since the app got the latest */
  const ago = (t) => {
    const min = Math.round((Date.now() - t) / 60000);
    if (min < 1) return "just now";
    if (min < 60) return `${min} min ago`;
    const h = Math.floor(min / 60);
    return h < 48 ? `${h} h ${min % 60 ? (min % 60) + " min " : ""}ago` : `${Math.floor(h / 24)} days ago`;
  };
  btn.addEventListener("tipshow", () => {
    $("check-found").textContent = found ? `Found ${ago(found.at)}: ${summary(found.result)}.` : "";
    $("check-when").textContent = `Mod Matrix started ${ago(started)}` + (lastCheck ? ` \u00b7 last checked ${ago(lastCheck)}` : "");
  });

  /* one line for the tooltip: what a check found */
  function summary(r) {
    const parts = [];
    if (r.framework) parts.push("Mod Matrix updated");
    if (r.added.length) parts.push(`new: ${r.added.map((m) => m.title).join(", ")}`);
    if (r.removed.length) parts.push(`removed: ${r.removed.map((m) => m.title).join(", ")}`);
    if (r.changed.length) parts.push(`changed: ${r.changed.map((m) => m.title).join(", ")}`);
    if (r.code.length) parts.push(`new code (in your next build): ${r.code.map((m) => m.title).join(", ")}`);
    if (r.unknown.length) parts.push("new code (in your next build)");
    if (r.app) parts.push(`new version of this app: ${r.app.version}`);
    return parts.join(" \u00b7 ");
  }

  /* the button: solid yellow UPDATES AVAILABLE when an update needs the person (UPDATE NOW, or a
   * new app not yet cleared); yellow outline UPDATES FOUND when only mods' code changed (in the
   * next build). It stays until the person presses CLEAR (UPDATE NOW stays until done). Checks
   * compare with the Mod Matrix's start, so the same changes come back every time: once cleared,
   * only something new flags the button again. A check that finds nothing keeps the button as it
   * is, unless the person ran it (full) and it reached everything */
  const isNew = () => Boolean(found) && summary(found.result) !== seen;
  const needsAction = () => Boolean(found && (found.result.restart || (found.result.app && isNew())));
  function setButton(r, full) {
    if (r && summary(r)) found = { result: r, at: (found && summary(found.result) === summary(r)) ? found.at : Date.now() };
    else if (r && full && !r.failed.length) found = null;
    const act = needsAction();
    const noted = !act && isNew();
    btn.classList.toggle("found", act);
    btn.classList.toggle("noted", noted);
    btn.textContent = act ? "UPDATES AVAILABLE" : noted ? "UPDATES FOUND" : "CHECK FOR UPDATES";
  }

  const node = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const names = (mods) => mods.map((m) => m.title).join(", ");
  const author = (m) => m.repo.split("/")[0];

  function open() {
    tips.hide();
    panel.hidden = false;
    btn.setAttribute("aria-expanded", "true");
  }
  function close() {                        // hides the panel; the button stays as it is
    if (busy === "apply") return;
    panel.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  }
  function clear() {                        // CLEAR: the person has seen it (not UPDATE NOW's changes)
    close();
    if (!found || found.result.restart) return;
    seen = summary(found.result);
    setButton();
    fetch("/updates/clear", { method: "POST", headers: { "X-PMM": "1", "Content-Type": "application/json" },
      body: JSON.stringify({ key: seen }) }).catch(() => { /* kept on the page only */ });
  }
  function button(label, onClick, primary) {
    const b = node("button", primary ? "primary" : "", label);
    b.type = "button";
    b.addEventListener("click", onClick);
    actions.append(b);
    return b;
  }

  function section(title, lines) {
    body.append(node("h3", "", title));
    for (const l of lines) body.append(typeof l === "string" ? node("p", "", l) : l);
  }
  function list(items, cls) {
    const ul = node("ul", cls);
    for (const i of items) ul.append(node("li", "", i));
    return ul;
  }
  function commits(c) {
    if (!c.commits || !c.commits.length) return [];
    const items = c.commits.slice();
    if (c.more) items.push(`... and ${c.more} more`);
    return [list(items, "commits")];
  }

  function show(r) {
    body.replaceChildren();
    actions.replaceChildren();
    // this app, always: its version, and the newer one with a download when there is one
    const me = r.this_app || {};
    const link = (text, href, cls) => {
      const a = node("a", cls || "", text);
      a.href = href;
      a.target = "_blank";                   // the web browser, not this window
      a.rel = "noopener";
      return a;
    };
    if (r.app) {
      const mac = r.app.file.endsWith(".dmg");
      const p = node("p", "", `Version ${r.app.version} of Perkons Mod Matrix Desktop is available (you have ${me.version}). `);
      const dl = node("p", "download");
      dl.append(link(`Download ${r.app.version} for ${mac ? "Mac" : "Windows"}`, r.app.download, "primary"), " ",
        link("What's new", r.app.url));
      const how = node("p", "muted", mac
        ? "Quit this app, open the downloaded ModMatrixDesktop-macOS.dmg and drag the app to Applications, replacing this one. Your settings and downloads stay."
        : "Quit this app, extract the downloaded ModMatrixDesktop-Windows.zip and run Perkons Mod Matrix Desktop.exe from it. Your settings and downloads stay.");
      section("This app", [p, dl, how]);
    } else if (me.latest) {
      section("This app", [node("p", "ok", `Perkons Mod Matrix Desktop ${me.version}: the latest version.`)]);
    } else if (me.version) {
      section("This app", [node("p", "muted", `Perkons Mod Matrix Desktop ${me.version}. Couldn't check for a newer version (see below).`)]);
    }
    if (r.framework) {
      section("Mod Matrix", ["kiteless has updated the Mod Matrix since the app started.", ...commits(r.framework)]);
    }
    if (r.added.length) section("New mods", [list(r.added.map((m) => `${m.title} (${author(m)})`))]);
    if (r.removed.length) section("Removed", [list(r.removed.map((m) => `${m.title} (${author(m)})`))]);
    if (r.changed.length) {
      section("Changed", [list(r.changed.map((m) => `${m.title}: ${m.what.join(", ")}`))]);
    }
    if (r.code.length) {
      section("Updated code", [`${names(r.code)}. Your next build uses the new code already: nothing to do.`]);
    }
    if (r.unknown.length) {
      section("Updated code", [node("p", "muted", `${r.unknown.join(", ")} changed (GitHub didn't say which mods). Your next build uses the new code already.`)]);
    }
    const nothing = !r.app && !r.restart && !r.code.length && !r.unknown.length;
    if (nothing) body.append(node("p", "ok", "Everything is up to date."));
    body.append(node("p", "remind", "New mods, engines and features are added all the time: if you keep the app " +
      "open, check again now and then (or restart the app)."));
    if (r.failed.length) {
      body.append(node("p", "err", "Could not check: " + r.failed.map(([what, why]) => `${what} (${why})`).join("; ")));
    }
    if (r.restart) {
      body.append(node("p", "warn",
        "UPDATE NOW starts the Mod Matrix again with these changes. The firmware you loaded and the mods " +
        "you ticked are cleared: load your firmware again afterwards. Wait for a build in progress to finish first."));
      button("LATER", close);
      button("UPDATE NOW", apply, true).focus();
    } else if (summary(r)) {
      button("CLEAR", clear).focus();
    } else {
      button("CLOSE", close).focus();
    }
    setButton(r, true);
  }

  async function check() {
    if (busy) return;
    busy = "check";
    open();
    btn.classList.add("busy");
    btn.textContent = "CHECKING...";
    body.replaceChildren(node("p", "muted", "Checking the Mod Matrix, the mod repos and this app on GitHub..."));
    actions.replaceChildren();
    try {
      const r = await fetch("/updates/check");
      const res = await r.json();
      if (!r.ok) throw new Error(res.error || r.statusText);
      lastCheck = Date.now();
      show(res);
    } catch (e) {
      body.replaceChildren(node("p", "err", `The check failed (${e.message}). Check the internet connection.`));
      actions.replaceChildren();
      button("CLOSE", close);
      button("TRY AGAIN", () => { busy = false; check(); }, true);
    } finally {
      if (busy === "check") busy = false;
      btn.classList.remove("busy");
      setButton();
    }
  }

  /* the quiet check: in the background, nothing shown but the button */
  async function quiet() {
    const now = Date.now();
    if (busy || !panel.hidden || now - started < AUTO || (lastCheck && now - lastCheck < AUTO)) return;
    // not document.hasFocus(): with the focus in the Mod Matrix (another origin, in its frame)
    // the Mac's web view says false, and the check never ran. Minimised: wait until shown.
    if (document.visibilityState !== "visible") return;
    busy = "quiet";
    lastCheck = now;                         // a failure waits for the next turn too
    try {
      const r = await fetch("/updates/check?quiet=1");
      if (r.ok) setButton(await r.json());
    } catch { /* offline: try again next time */ }
    finally { if (busy === "quiet") busy = false; }
  }
  window.addEventListener("focus", quiet);
  document.addEventListener("visibilitychange", quiet);
  $("tabs").addEventListener("pointerenter", quiet);     // back at the window: the frame may keep the focus events
  setInterval(quiet, Math.min(5 * 60000, AUTO / 4));   // due checks run on their own, the window open or in front

  async function apply() {
    busy = "apply";
    for (const b of actions.querySelectorAll("button")) b.disabled = true;
    body.replaceChildren(node("p", "", "Updating: downloading the Mod Matrix if it changed, then starting it again. " +
      "This takes a few seconds..."));
    try {
      const r = await fetch("/updates/apply", { method: "POST", headers: { "X-PMM": "1" } });
      const res = await r.json();
      if (!r.ok) throw new Error(res.error || r.statusText);
      const done = res.notice || "Updated: the Mod Matrix has the latest mods. Load your firmware again to build.";
      try { sessionStorage.setItem("updates.notice", done); } catch { /* not kept */ }
      location.reload();                     // the Mod Matrix is on a new port: the page names it
    } catch (e) {
      busy = false;
      body.replaceChildren(node("p", "err", `The update failed: ${e.message}`));
      actions.replaceChildren();
      button("CLOSE", () => location.reload());
    }
  }

  btn.addEventListener("click", () => {
    if (!panel.hidden) close();
    else if (busy === "quiet") setTimeout(() => btn.click(), 300);   // let the quiet check finish
    else check();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) { close(); btn.focus(); }
  });
  document.addEventListener("mousedown", (e) => {
    if (!panel.hidden && !panel.contains(e.target) && e.target !== btn) close();
  });
  window.addEventListener("blur", () => { /* the Mod Matrix frame took a click */
    if (!panel.hidden && document.activeElement === $("matrix")) close();
  });

  // what the launcher found before this page loaded (the page may have been reloaded)
  fetch("/updates/state").then((r) => r.json()).then((st) => {
    if (!st.result || found) return;
    found = { result: st.result, at: st.at * 1000 };
    seen = st.cleared || null;
    setButton();
  }).catch(() => { /* none */ });

  // after UPDATE NOW: say what happened
  let notice = null;
  try { notice = sessionStorage.getItem("updates.notice"); sessionStorage.removeItem("updates.notice"); } catch { /* none */ }
  if (notice) {
    open();
    body.replaceChildren(node("p", "warn", notice));
    button("CLOSE", close);
  }
})();
