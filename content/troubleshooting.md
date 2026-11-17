<!-- pmm:page format=1 updated=2026-11-17 -->

<!-- For writers: every entry needs a known source (a mod's README, the Mod Matrix's docs, this
     app's README, or something tested). Leave out anything unconfirmed until it is. Problems in
     someone else's code: give them time to fix it before listing it here. -->

# Troubleshooting

<p class="lede">Common problems with modded firmware and with this app, and what to do about them.</p>

<!-- pmm:contents -->

## Crackle, clicks or grit <!-- toc: Crackle -->

- **Only on voice 1 or 2, while voices 3 and 4 stay clean**: the sound processor has too much to
  do. Move the heavy engine to voice 3 or 4, or choose a lighter sound. The
  [Processor & Memory](#view-limits) tab explains it, and its planner checks a kit.
- **On loud, held sounds, and it goes away when you turn down the voice's LEVEL, the MASTER, or
  the compressor's Amount and Threshold**: the analog output is running out of headroom. Turn
  those down instead.

## A mod can't be ticked in the Mod Matrix <!-- toc: Can't tick a mod -->

- **Not enough memory**: the MEMORY pane shows what the ticked mods take. Untick another mod to
  make room.
- **Two mods use the same buttons**: the Mod Matrix asks which one to keep. OK swaps them,
  CANCEL keeps the first.
- **A mod changes what a stock button combination does**: the Mod Matrix tells you what changes
  before it's ticked.

## Do I need to build again? <!-- toc: Build again? -->

Your Pērkons only changes when you install new firmware. When a mod you use is updated, build
your firmware again in the Mod Matrix and install it to get the update.

The [What's New](#view-news) tab shows every mod's recent changes, and marks the ones that
arrived since you last looked. CHECK FOR UPDATES (top right) shows them too.

## The app can't connect <!-- toc: Offline -->

- **The first start needs the internet**, to download the Mod Matrix.
- **After that, offline**, the app uses the Mod Matrix it downloaded last time, and the guides
  and pages from your last visit.

## Windows: the app won't start <!-- toc: Windows -->

- **Extract the zip first**: right-click it and choose **Extract All**, then run
  `Perkons Mod Matrix Desktop.exe` from the extracted folder. It won't run from inside the zip.
- **"Windows protected your PC"**: the app isn't signed for Windows yet. Click **More info**, then
  **Run anyway**.

## Still stuck <!-- toc: Still stuck -->

- **A problem with a mod or engine**: read its user guide, then contact its author. The USER
  GUIDES tab shows which repo each mod is from.
- **A problem with this app**: [open an issue](https://github.com/remixed123/modmatrix-desktop/issues).
  Attach the app's log file, `launcher.log`:
  - Mac: `~/Library/Application Support/Perkons Mod Matrix/launcher.log`
  - Windows: `%LOCALAPPDATA%\PerkonsModMatrix\launcher.log`
