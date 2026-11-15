/* PROCESSOR & MEMORY tab: the engine table and the kit planner.
 *
 * Costs are the sound processor's (M7) work per sample, counted in the emulator: the stock
 * engines with perkons-re's voice renderer (after the attack, every ALGO and MODE), the mod
 * engines from their own measurements. The limit was found on a unit with real engines (four
 * Akords on formant presets played clean, one changed to Hollow broke): clean up to ~1,850 for
 * everything together, broken from ~2,100, counted as the planner counts (triggers + each voice's
 * own cost). An earlier test padded with cheap dummy instructions gave 2,300 / 2,600: real DSP
 * code takes more time per instruction. Voices 1 + 2 (rendered last): that test's 1,750 / 2,050,
 * scaled the same way; not reached in the real-engine test. Update ENGINES when an engine's cost
 * changes. */
"use strict";

const limits = (() => {
  const OFFICIAL = 175;                                  // a stock voice, about
  const TRIGGERS = 100;                                  // the step triggers, rendered before voice 3
  const SIDECHAIN = 130;                                 // FX Sidechain while ducking (both halves)
  const CLEAN = 1850, BROKE = 2100;                      // everything together
  const CLEAN_12 = 1400, BROKE_12 = 1650;                 // voices 1 + 2
  const SCALE = 2800;                                    // the planner bar's full width

  const ENGINES = [
    { id: "o1", name: "Official engine 1", short: "Official 1", algos: "Fold Drum 1, Wavetable, Simple",
      from: "Erica Synths", low: 140, high: 175, heaviest: "about the same on every ALGO and MODE" },
    { id: "o2", name: "Official engine 2", short: "Official 2", algos: "Fold Drum 2, Wavetable, Complex",
      from: "Erica Synths", low: 165, high: 195, heaviest: "about the same on every ALGO and MODE" },
    { id: "o3", name: "Official engine 3", short: "Official 3", algos: "Resonant drums, Slap, Karplus–Chord",
      from: "Erica Synths", low: 140, high: 310, heaviest: "depends on ALGO and MODE" },
    { id: "o4", name: "Official engine 4", short: "Official 4", algos: "Noise hat, Noise–tone, Acoustic hats",
      from: "Erica Synths", low: 55, high: 490, heaviest: "depends on ALGO and MODE; the sample hats are the lightest" },
    { id: "zb", name: "Zibens", short: "Zibens", from: "kiteless", low: 125, high: 325,
      heaviest: "the wavefolded sine; the square is the lightest" },
    { id: "ss", name: "Step Sampler", short: "Step Sampler", from: "kiteless", low: 175, high: 510,
      heaviest: "granular with PARAM1 (texture) fully left: tiny, dense grains; forward and reverse cost about the same as an official voice" },
    { id: "sy", name: "Synth Lab", short: "Synth Lab", from: "remixed123", low: 250, high: 420,
      heaviest: "three oscillators with sync, the wavefolder, every LFO, hot drive" },
    { id: "kl", name: "Kick Lab", short: "Kick Lab", from: "remixed123", low: 190, high: 480,
      heaviest: "drive, delay, rumble and noise all on; most presets alone are close to an official voice" },
    { id: "ak", name: "Akords", short: "Akords", from: "remixed123", low: 380, high: 660,
      heaviest: "Hollow, then Bell, Organ and Keys; every chord type costs about the same; the formant presets (Talk, Wah) are the lightest" },
  ];
  const byId = new Map(ENGINES.map((e) => [e.id, e]));

  const LEVELS = [                                       // by times an official voice
    { key: "light", name: "Light", upTo: 1.5, says: "up to 1½× an official voice" },
    { key: "medium", name: "Medium", upTo: 3, says: "1½× to 3×" },
    { key: "heavy", name: "Heavy", upTo: 4, says: "3× to 4×" },
    { key: "vheavy", name: "Very heavy", upTo: Infinity, says: "more than 4×" },
  ];
  const TRACK = 4.5;                                     // the table meter's full width, in times
  const level = (cost) => LEVELS.find((l) => cost / OFFICIAL <= l.upTo);
  const times = (cost) => {                             // to the nearest half: "½×", "1×", "2½×"
    const x = cost / OFFICIAL;
    if (x < 0.5) return "under ½×";
    const h = Math.round(x * 2) / 2;
    return `${h === 0.5 ? "" : Math.floor(h)}${h % 1 ? "½" : ""}×`;
  };
  const span = (lo, hi) => (times(lo) === times(hi) ? times(lo) : `${times(lo)} to ${times(hi)}`);

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const pct = (v, of) => `${Math.max(0, Math.min(100, (100 * v) / of)).toFixed(2)}%`;

  /* -- the table -------------------------------------------------------------------------------- */

  function legend() {
    for (const l of LEVELS) {
      const li = el("li");
      li.append(el("span", `chip lv-${l.key}`, l.name), document.createTextNode(` ${l.says}`));
      $("legend").append(li);
    }
  }

  function rows() {
    for (const e of ENGINES) {
      const tr = el("tr");
      const name = el("td");
      name.append(el("strong", "", e.name));
      if (e.algos) name.append(el("div", "muted", e.algos));
      const lo = level(e.low), hi = level(e.high);
      const cell = el("td", "cost");
      const track = el("div", "track");
      track.title = `${e.name}: ${lo === hi ? lo.name : lo.name + " to " + hi.name}`;
      for (const l of LEVELS.slice(0, -1)) {
        const t = el("span", "tick");
        t.style.left = pct(l.upTo, TRACK);
        track.append(t);
      }
      const band = el("span", `band lv-${hi.key}`);
      band.style.left = pct(e.low / OFFICIAL, TRACK);
      band.style.width = `max(8px, ${pct((e.high - e.low) / OFFICIAL, TRACK)})`;
      track.append(band);
      cell.append(track, el("div", "lv-text", lo === hi ? lo.name : `${lo.name} to ${hi.name}`));
      const x = el("td", "", span(e.low, e.high));
      tr.append(name, el("td", "", e.from), cell, x, el("td", "", e.heaviest));
      $("engine-rows").append(tr);
    }
  }

  /* -- the planner ------------------------------------------------------------------------------ */

  const store = {
    get() { try { return JSON.parse(localStorage.getItem("limits.picks") || "null"); } catch { return null; } },
    set(v) { try { localStorage.setItem("limits.picks", JSON.stringify(v)); } catch { /* private window */ } },
  };
  const picks = { 1: "o1", 2: "o2", 3: "o3", 4: "o4", sc: false };

  function pickers() {
    const saved = store.get();
    if (saved) {
      for (const v of [1, 2, 3, 4]) if (byId.has(saved[v])) picks[v] = saved[v];
      picks.sc = !!saved.sc;
    }
    for (const v of [1, 2, 3, 4]) {
      const label = el("label", "pick");
      label.append(el("span", `vtag v${v}`, `VOICE ${v}`));
      const sel = el("select");
      sel.id = `pick-${v}`;
      const groups = [["Official engines", ENGINES.filter((e) => e.from === "Erica Synths")],
                      ["Mod engines", ENGINES.filter((e) => e.from !== "Erica Synths")]];
      for (const [title, list] of groups) {
        const g = el("optgroup");
        g.label = title;
        for (const e of list) {
          const o = el("option", "", e.short);
          o.value = e.id;
          g.append(o);
        }
        sel.append(g);
      }
      sel.value = picks[v];
      sel.addEventListener("change", () => { picks[v] = sel.value; changed(); });
      label.append(sel);
      $("picks").append(label);
    }
    $("pick-sc").checked = picks.sc;
    $("pick-sc").addEventListener("change", () => { picks.sc = $("pick-sc").checked; changed(); });
    $("mark-clean").style.left = pct(CLEAN, SCALE);
    $("mark-broke").style.left = pct(BROKE, SCALE);
  }

  function changed() {
    store.set(picks);
    plan();
  }

  function plan() {
    const cost = (v) => byId.get(picks[v]).high;
    const sc = picks.sc ? SIDECHAIN / 2 : 0;
    const segs = [["trig", "triggers", TRIGGERS], ["v3", "voice 3", cost(3)], ["v4", "voice 4", cost(4)],
                  ...(sc ? [["sc", "sidechain", sc]] : []),
                  ["v1", "voice 1", cost(1)], ["v2", "voice 2", cost(2)], ...(sc ? [["sc", "sidechain", sc]] : [])];
    const total = segs.reduce((s, x) => s + x[2], 0);
    const last = cost(1) + cost(2) + sc;
    const bar = $("bar");
    bar.textContent = "";
    let at = 0;
    for (const [cls, name, v] of segs) {
      const s = el("span", `seg s-${cls}`);
      if (at + v > CLEAN) s.classList.add(at + v > BROKE ? "late" : "near");
      s.style.width = pct(Math.min(v, Math.max(0, SCALE - at)), SCALE);
      s.title = `${name}: ${times(v)} an official voice`;
      if (cls !== "sc" && cls !== "trig") s.textContent = v / SCALE > 0.08 ? name : v / SCALE > 0.025 ? cls.toUpperCase() : "";
      bar.append(s);
      at += v;
    }

    const red = total > BROKE || last > BROKE_12, amber = !red && (total > CLEAN || last > CLEAN_12);
    const verdict = $("verdict");
    verdict.className = `verdict ${red ? "bad" : amber ? "warn" : "good"}`;
    verdict.textContent = "";
    const share = Math.round((100 * total) / CLEAN);
    verdict.append(el("strong", "", red ? "Likely to crackle." : amber ? "Near the limit." : "Should play clean."), " ",
      red ? `This kit takes about ${share}% of what played clean. Expect crackle on voices 1 and 2 when the `
            + "engines play their heaviest sounds: choose lighter sounds, or a lighter engine on one voice."
        : amber ? `This kit takes about ${share}% of what played clean: untested ground. It may crackle on voices 1 `
            + "and 2 with the heaviest sounds. Listen for it, or lighten a voice."
        : `This kit takes about ${share}% of what played clean, even with every engine on its heaviest sound.`);
    if (cost(1) + cost(2) > cost(3) + cost(4) + 50) {
      verdict.append(el("span", "tip-line",
        "Tip: put the heavier engines on voices 3 and 4. They're done first; voices 1 and 2 get what's left."));
    }
  }

  legend();
  rows();
  pickers();
  plan();
  $("limits-print").addEventListener("click", () => window.print());
  for (const a of document.querySelectorAll("#limits .toc a, #limits .plan-cta")) {
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const t = document.querySelector(a.getAttribute("href"));
      if (t) t.scrollIntoView({ behavior: "smooth" });
    });
  }
  return { ENGINES };
})();
