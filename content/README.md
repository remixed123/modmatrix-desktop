# Content the app reads from this repo

Files here are read by the app from GitHub (`main`) while it runs, so changing them updates
every installed copy without a new release. The app keeps the last copy it got for use
offline, and carries a copy of its own (from when it was built) for its first start offline.

Push changes to `main` only when they are ready for everyone. GitHub's raw file server can
take a few minutes to serve the new version.

## troubleshooting.md: the TROUBLESHOOTING tab

Written the same way as processor.md below (first line, `<!-- toc: ... -->` on headings, boxes,
classes). Its only part is `<!-- pmm:contents -->`, the row of links.

## Links to the app's tabs

In either page, `[text](#view-limits)` opens PROCESSOR & MEMORY, `#view-news` WHAT'S NEW,
`#view-help` TROUBLESHOOTING, `#view-guides` USER GUIDES and `#view-matrix` the MOD MATRIX.

## processor.md: the PROCESSOR & MEMORY tab's text

The whole page except the parts the app builds. Plain Markdown (headings, paragraphs, **bold**,
lists, tables, links), plus:

* **The first line** must stay `<!-- pmm:page format=1 updated=YYYY-MM-DD -->`. Change the date
  with every edit (offline, the app uses whichever copy is newer). Leave `format` at 1: an app
  ignores a page with a format it doesn't know and keeps its saved copy.
* **The app's parts**: a line holding only `<!-- pmm:name -->`, with a blank line before and
  after, puts that part there. The parts: `plan-button` (the PLAN A KIT box), `contents` (the
  row of links), `diagram` (the two-row block picture), `engines` (the level key and the engine
  table), `other-mods` (the "Mods that aren't engines" table), `planner`. A part whose line is
  missing goes at the end of the page, so nothing is lost.
* **The contents row**: add `<!-- toc: Short label -->` at the end of a heading to list it.
  Headings without one aren't listed.
* **Boxes**: a quote starting with `> [!WARNING]` is the yellow box, `> [!NOTE]` the blue one.
* **Cards** and a few touches need HTML with the page's classes. Only these are kept:
  `pair` (two side by side), `card`, `voices`, `first` (yellow border), `badge` with `ok`
  (green) or `you` (yellow), `muted` (small grey), `lede` (the larger opening paragraph). Leave
  a blank line after `<div class="card">` and before `</div>`, or the Markdown inside isn't read:

  ```html
  <div class="pair">
  <div class="card">

  ## Memory <span class="badge ok">MANAGED FOR YOU</span>

  Text with **bold**.

  </div>
  </div>
  ```

Images, styles, scripts and ids are removed; links to other sites open in the browser. A new
kind of box or layout needs an app release; new or changed text, sections, lists and tables
don't. Check a change before pushing by running the app from source
(`python launcher/modmatrix_launcher.py`) with the network off: it then uses this folder's copy,
as long as its date is newer than the one it saved last time.

## processor.json: the PROCESSOR & MEMORY tab's numbers

The engine table, the "Mods that aren't engines" table and the PLAN A KIT planner are built
from this file.

| field | meaning |
|---|---|
| `format` | The file's layout version. Leave it at 1. An app that knows a lower number ignores the file and keeps its saved copy, so raise it only with an app release that reads the new layout. |
| `updated` | The date of the numbers (YYYY-MM-DD). Not shown; offline, the app uses whichever copy is newer, its saved one or its own. Change it with every edit. |
| `official` | A stock voice's cost, in instructions per sample. Every "×" on the page is a multiple of this. |
| `limits.triggers` | The step triggers' cost, done before voice 3. |
| `limits.clean`, `limits.broke` | Everything together: played clean up to, broke from. |
| `limits.clean_12`, `limits.broke_12` | The same for voices 1 + 2 (done last). |
| `limits.tip_margin` | The planner suggests moving engines to voices 3 and 4 when voices 1 + 2 cost this much more than 3 + 4. |
| `display.table_track` | The engine table meter's full width, in × an official voice (widened by itself if an engine is heavier). |
| `display.planner_scale` | The planner bar's full width, in instructions (widened by itself if needed). |
| `levels` | Light / Medium / Heavy / Very heavy: `up_to` in × an official voice (`null` = no limit, the last one). `key` picks the colour: `light`, `medium`, `heavy` or `vheavy`. |
| `engines` | One per engine, in any order: the page shows the official engines first, then the rest A-Z by `name`. `id` (short, unique, kept: the planner remembers choices by it), `name`, `short` (the planner's name, if shorter), `official` (true for the four stock engines: their own group in the planner), `algos` (optional line under the name), `from`, `low` and `high` (instructions per sample, lightest and heaviest sound; the planner uses `high`), `heaviest`, `hidden` (optional, true: left out of the page, to add an engine before it is released). |
| `other_mods` | Rows of "Mods that aren't engines": `name`, `runs_on`, `takes`. A mod that costs the sound processor something also gets `planner`: `id` (unique, kept), `label` (the planner's tick box), `voices_34` and `voices_12` (its cost added after voices 3 + 4 and after voices 1 + 2). |
| `planner.defaults` | The four engine ids the planner starts with. |

Text fields are shown as plain text (no HTML or Markdown).
