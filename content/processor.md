<!-- pmm:page format=1 updated=2026-11-19 -->

# Processor and memory

> [!WARNING]
> **Work in progress.** This is what we know so far, not the final word.
> The numbers and advice come from measurements and listening on a Pērkons, and they will change as
> we learn more and as the engines are made lighter. Treat them as a guide, and trust your ears.

<p class="lede">Every mod and engine you add takes some of the Pērkons's memory, and an engine takes
processor time while it plays. The Mod Matrix looks after memory for you. The processor is yours
to manage: how much it takes depends on which engines play on which voices and how they're set,
and that changes from moment to moment.</p>

<div class="pair">
<div class="card">

## Memory <span class="badge ok">MANAGED FOR YOU</span>

The MEMORY pane in the Mod Matrix shows how much room the mods you tick take. A mod that
wouldn't fit can't be ticked, and the build checks again. A build that fits always fits:
memory doesn't change with what you play.

</div>
<div class="card">

## Processor <span class="badge you">UP TO YOU</span>

No one can check it for you before you play: it depends on what's playing. Too much
shows up as crackle on voices 1 and 2. Put the heavy engines on voices 3 and 4, and use
the planner below to check a kit.

</div>
</div>

<!-- pmm:plan-button -->

<!-- pmm:contents -->

## Memory <!-- toc: Memory -->

The Pērkons has three blocks of memory that mods can use. The **MEMORY** pane in the
Mod Matrix has a meter for each. Grey is the firmware's own part, green is what your ticked mods
take, and FREE is what's left.

| meter | what it holds | room for mods |
|---|---|---|
| **MAIN** | Fast memory on the panel processor: effects, pages, and what mods keep while they run | about 64 KB |
| **VOICE** | Memory on the sound processor: the engines' working memory, set aside for the engines from the start | about 76 KB |
| **STORE** | Larger, a little slower: settings and data such as what mods save with your kits | about 111 KB |

- **A mod you can't tick** doesn't fit beside the ones already ticked. Untick another
  mod to make room.
- **An engine in your build costs memory, not processor time.** It only uses the
  processor while it's chosen on a voice. Install the engines you like; choose them per kit.

## Processor <!-- toc: Processor -->

The Pērkons has two processors. The **panel processor** runs the panel, pages, sequencer,
kit saving, the SD card and the effects (the delay, FX Reverb, FX Freeze). The **sound
processor** works out the sound of the four voices, and only that work competes with the
voices.

It works in tiny blocks: every 32 samples, about two thirds of a millisecond, it works out the next
bit of sound for all four voices. It does **voices 3 and 4 first** (with the step
triggers), **then voices 1 and 2**, and everything has to be ready before the block is
due. If it isn't, voices 1 and 2, done last, come out broken, while voices 3 and 4 stay clean.

<!-- pmm:diagram -->

**Why the Mod Matrix can't check it.** Memory is fixed when you build, so the Mod
Matrix can add it up. Processor time depends on what's playing: which engine is on each voice (you
choose that on the Pērkons, per kit), the preset, how many notes, drive, filter settings. The same
build can play one kit cleanly and crackle on another.

## Signs of too much processor <!-- toc: Signs of too much -->

- **Crackle, grit, clicks or dropouts on voice 1 or 2 only**, while voices 3 and 4 stay
  clean. Mute voices one at a time to find which one breaks.
- It **comes and goes with how busy the heavy engines are**: bigger chords, more
  oscillators, drive on, held notes overlapping, several heavy voices sounding at once.
- It **starts with a kit or engine change** rather than when you turn something up.
- It **stops** when you mute a heavy voice, choose a lighter preset, or move a heavy
  engine to voice 3 or 4.

> [!NOTE]
> **Too loud, not too busy.** Crackle on loud, held sounds that goes away when you turn
> down the voice's LEVEL, the MASTER, or the compressor's Amount and Threshold is the analog output
> running out of headroom, not the processor. Turn those down instead (the Akords guide has more on
> this, "Crackle on held chords").

### What to do

1. **Move the heavy engine to voice 3 or 4.** Hold KIT and press MOD for the engine page:
   rows 1 to 4 are the voices. The engine then plays from that voice's steps, trigger key and output,
   so move its steps too.
2. **Choose a lighter sound**: fewer notes in a chord, a lighter preset, drive off.
3. **Swap one heavy engine** for a light one or an official engine.

## Where to put engines <!-- toc: Where to put engines -->

<div class="pair">
<div class="card voices">

### Voices 1 and 2 <span class="muted">done last</span>

The **official engines** and **light** engines (Zibens, Step Sampler playing forward or reverse).
At most **one** medium or heavy engine here, beside a light one.

</div>
<div class="card voices first">

### Voices 3 and 4 <span class="muted">done first</span>

The **medium**, **heavy** and **very heavy** engines:
Akords, Synth Lab, Kick Lab with its effects on, Step Sampler on granular.

</div>
</div>

- Avoid two heavy engines on voices 1 and 2 together, Akords especially.
- Four heavy engines at once is too much wherever they are. The planner below shows how much a kit
  takes.
- An engine uses no processor while it isn't chosen on a voice, but it still takes memory: a build
  can include as many as the memory allows (the Mod Matrix shows it).

## How much processor each engine uses <!-- toc: Engine table -->

While playing, compared with an official engine. Each engine's range runs from its lightest sound
to its heaviest.

> [!WARNING]
> **Engines change.** These are the engines as they were when we measured
> them. An update can make an engine lighter on the processor, or heavier when it adds features, so
> the numbers here may be behind. As always, trust your ears.

<!-- pmm:engines -->

### Mods that aren't engines

<!-- pmm:other-mods -->

<p class="muted">Engines and mods not listed here: see their user guide.</p>

## Plan a kit <!-- toc: Plan a kit -->

Choose the engine on each voice. The bar adds them up the way the sound processor does, with each
engine's **heaviest** sound, so most of the time you have more room than it shows.

<!-- pmm:planner -->

## How these numbers were found

Each engine was run with the real firmware in an emulator, counting the work it does per sample,
and the limit was found by ear on a Pērkons, with real engines playing. The four official voices
together use about half of what played clean. The numbers are a guide: the chip also loses some time to memory, and the limit
between "played clean" and "broke" hasn't been tested, so leave some room.
