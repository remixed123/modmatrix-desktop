/* DEVELOPER: run the Mod Matrix on another perkons-re or offer mod repos at other branches,
 * to try work before it reaches main. Hidden on purpose: ABOUT, then Option-click (Alt-click on
 * Windows) the version line. Drop-downs only, a repo and its branch: perkons-re (kiteless's, or
 * that of someone with a mod repo in kiteless's list), and one mod repo from kiteless's list (the
 * others stay official), so only what kiteless has registered is used.
 * The launcher keeps the
 * settings (developer.json) and starts the Mod Matrix again on them (/dev/apply); BACK TO
 * OFFICIAL (/dev/reset) clears them. The page reloads after: the Mod Matrix is on a new port. */
"use strict";

(() => {
  const panel = $("dev");
  const status = $("dev-status");
  const buttons = ["dev-apply", "dev-reset", "dev-cancel"].map($);
  let busy = false;

  function say(text, err) {
    status.textContent = text || "";
    status.classList.toggle("err", !!err);
  }

  /* a drop-down: the official branch first (value ""), then every other branch, then extra */
  function fill(select, official, branches, chosen, extra) {
    select.replaceChildren();
    const add = (value, text) => select.append(new Option(text, value, false, value === chosen));
    if (official !== null) add("", `${official} (official)`);
    const list = branches.filter((b) => b !== official);
    if (chosen && chosen !== "-" && !branches.includes(chosen)) list.unshift(chosen);   // gone, or not read
    for (const b of list) add(b, branches.includes(b) || !branches.length ? b : `${b} (not found)`);
    if (extra) add(extra[0], extra[1]);
    const mark = () => select.classList.toggle("changed", official === null || select.value !== "");
    select.onchange = mark;
    mark();
  }

  /* Mod repos: one repo of kiteless's list and a branch of it; the others stay as they are
   * officially. Saved settings from before with several repos: the first changed one is shown. */
  let repos = [];

  function modBranches(pick) {
    const r = repos.find((x) => x.repo === $("dev-mods-repo").value);
    fill($("dev-mods"), r.official, r.branches, pick);
    $("dev-mods-note").textContent = r.note;
  }
  $("dev-mods-repo").addEventListener("change", () => modBranches(""));

  async function open() {
    tips.hide();
    for (const id of ["about", "updates"]) {             // one panel at a time
      if (!$(id).hidden) (id === "about" ? $("about-close") : $("check")).click();
    }
    panel.hidden = false;
    $("dev-apply").disabled = true;
    say("Reading the branches from GitHub...");
    try {
      const r = await fetch("/dev/choices");
      const c = await r.json();
      if (!r.ok) throw new Error(c.error || r.statusText);
      const fw = c.framework;
      const repoSel = $("dev-framework-repo");
      repoSel.replaceChildren(...fw.repos.map((r) => new Option(r.repo, r.repo, false, r.repo === fw.chosen.repo)));
      const branchesOf = () => {
        const r = fw.repos.find((x) => x.repo === repoSel.value);
        const official = r.repo === fw.repos[0].repo;          // kiteless's: its main is the official one
        const chosen = r.repo === fw.chosen.repo ? fw.chosen.ref : "";
        if (official) return fill($("dev-framework"), fw.official, r.branches, chosen);
        // someone's perkons-re: every branch, main first; there is no official one to fall back to
        const list = [...r.branches].sort((a, b) => (b === "main") - (a === "main"));
        fill($("dev-framework"), null, list, chosen || list[0] || "");
        repoSel.classList.add("changed");
      };
      repoSel.onchange = () => { repoSel.classList.remove("changed"); branchesOf(); };
      branchesOf();
      const failed = fw.repos.filter((r) => r.failed && r.repo === fw.repos[0].repo).map((r) => r.repo);
      repos = c.repos;
      const mine = repos.find((r) => r.chosen && r.chosen !== "-") || repos[0];
      $("dev-mods-repo").replaceChildren(...repos.map((r) => new Option(r.repo, r.repo, false, r === mine)));
      modBranches(mine.chosen === "-" ? "" : mine.chosen);
      for (const r of repos) if (r.failed) failed.push(r.repo);
      const flags = [c.flags.framework && `--framework ${c.flags.framework}`,
                     c.flags.repos_url && `--repos-url ${c.flags.repos_url}`].filter(Boolean);
      $("dev-flags").hidden = !flags.length;
      $("dev-flags").textContent = flags.length
        ? `Started with ${flags.join(" and ")}: ${flags.length > 1 ? "they take" : "it takes"} precedence over the choices here.` : "";
      const missing = failed.filter(Boolean);
      say(missing.length ? `Could not read the branches of ${missing.join(", ")}.` : "", missing.length > 0);
      $("dev-apply").disabled = false;
    } catch (e) {
      say(e.message, true);
    }
    $("dev-framework-repo").focus();
  }

  function close() {
    if (busy) return;
    panel.hidden = true;
  }

  async function send(path, fields) {
    busy = true;
    buttons.forEach((b) => (b.disabled = true));
    say("Restarting the Mod Matrix... (a new perkons-re is downloaded first)");
    try {
      const r = await fetch(path, { method: "POST", headers: { "X-PMM": "1", "Content-Type": "application/json" },
                                    body: JSON.stringify(fields || {}) });
      const out = await r.json();
      if (!r.ok) throw new Error(out.error || r.statusText);
      if (!out.notice) return location.reload();
      say(out.notice + " Press CLOSE to see the Mod Matrix.");
      busy = false;
      $("dev-cancel").textContent = "CLOSE";
      $("dev-cancel").disabled = false;
      $("dev-cancel").onclick = () => location.reload();
    } catch (e) {
      busy = false;
      buttons.forEach((b) => (b.disabled = false));
      say(e.message, true);
    }
  }

  $("about-version").addEventListener("click", (e) => { if (e.altKey) open(); });
  $("dev-cancel").addEventListener("click", close);
  $("dev-apply").addEventListener("click", () =>
    send("/dev/apply", {
      framework: { repo: $("dev-framework-repo").value, ref: $("dev-framework").value },
      repos: { [$("dev-mods-repo").value]: $("dev-mods").value },
    }));
  $("dev-reset").addEventListener("click", () => send("/dev/reset"));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) close();
  });
})();
