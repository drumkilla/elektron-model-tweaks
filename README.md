# model-tweaks

Firmware mods for the Elektron **Model:Cycles** and **Model:Samples** (OS 1.13).
No firmware is distributed here: you supply **your own** `.syx`, and the mods you
pick are built into a new file.

Use the **[web flasher](https://drumkilla.github.io/elektron-model-tweaks/flasher/)**
in Chrome, Edge, Firefox or Safari: it has every mod (see [In the browser](#in-the-browser)).

What changed in each release: [CHANGELOG.md](CHANGELOG.md), also shown in the web
flasher; `python3 tweak.py --version` prints the version you have.

Some tweaks are also available as a part of these projects:

   * **[Modded Cycles](https://github.com/18nelli18/Modded-Cycles) by 18nelli18** - Model:Cycles only atm.
   * **[Model-TG](https://github.com/TinyGregAudio/Model-TG) by TinyGregAudio** - Model:Cycles only atm.

---

## Using it

### In the browser

The [web flasher](flasher/) builds from the mods in [`mods/`](mods/) (`.elemod`
files, one folder per device), which include the command-line tweaks and more: drop
your `.syx`, pick the mods, download the built file (then send it with
**Elektron Transfer**, the fastest way), or send it straight from the page over
USB MIDI in Chrome or Edge. The mods are linked into your firmware by
[elekloader](https://github.com/irpina/elekloader)'s linker (an unchanged copy in
[`elekloader/`](elekloader/), GPL-2.0), in the browser through
[Pyodide](https://pyodide.org); the firmware never leaves your computer. A mod's
requirements (`core`, `modkit`) are added by themselves.

To run it locally: `python3 -m http.server` in this folder, then open
<http://localhost:8000/flasher/>. Published with GitHub Pages from the repository
root (`.nojekyll` keeps `__init__.py` files served). After adding or removing a
mod, run `python3 flasher/make_manifest.py`.

### Command line (outdated)

> **The command-line tool is outdated.** It still works, but only with the
> four original tweaks in `tweaks/` (latching-mute, trig-preview, browser-scroll,
> usb16, as of 1.2.0). The mods added since 2.0.0 (attack, stereo, stretch,
> fast-audio, ...) are in the web flasher only.

1. Download the original firmware from Elektron and drop the `.syx` into this
   folder.
2. Run it:

   * **macOS / Linux:** `./apply.sh`
   * **Windows:** double-click `apply.bat`

3. Toggle tweaks by number, press Enter.
4. `<name>_mod.syx` appears beside the original. Send that one with Elektron
   Transfer, SysEx Librarian, or any SysEx tool.

Without the menu:

```
python3 tweak.py --list                               what is available
python3 tweak.py -i model-cycles_OS1.13.syx --all     everything
python3 tweak.py -i FW.syx -t trig-preview,browser-scroll
python3 tweak.py --verify FW_mod.syx                  recheck a finished file
```

---

## The mods

| Mod | Model:Cycles | Model:Samples |
|---|:-:|:-:|
| [Latching track mute](#latching-track-mute--latching-mute) | ✓ | ✓ |
| [Trig preview](#trig-preview--trig-preview) | ✓ | ✓ |
| [Scroll long names](#scroll-long-names--browser-scroll) | ✓ | ✓ |
| [16-channel USB audio](#16-channel-usb-audio--usb16) | ✓ | ✓ |
| [Amp attack](#amp-attack--attack) | | ✓ |
| [Stereo samples](#stereo-samples--stereo) | | ✓ |
| [Time-stretch](#time-stretch--stretch) | | ✓ |
| [Sample edit](#sample-edit--smpl-edit) | | ✓ |
| [Fast audio](#fast-audio--fast-audio) | ✓ | |
| [modkit](#modkit--modkit) (added when a mod needs it) | | ✓ |

The first four are also in the command-line tool (as tweaks); the rest are in
the web flasher only.

### Latching track mute — `latching-mute`

* Hold **TRACK** and tap **FUNC**: the mute mode latches and the FUNC key lights up.
* A short tap on **FUNC** alone leaves the mode.
* Combinations with FUNC do not leave the mode, including menus such as
  FUNC + PAGE and holding FUNC to turn the encoders fast.
* TRACK, RETRIG and PATTERN bank select keep working while it is latched.

Holding FUNC to mute tracks behaves exactly as it does in stock firmware.

### Trig preview — `trig-preview`

With the sequencer **stopped or paused**, hold a step (trig button) and press **PAGE**: the step sounds
with its own note, length, p-locks and sound-lock. The page does not turn. It
sounds regardless of the trig condition and probability, and through a muted
track. Paused (PLAY pressed during playback) counts as stopped; thanks to
18nelli for this fix.

### Scroll long names — `browser-scroll`

A selected name in the sound/sample/folder browser scrolls left when it does not
fit: about 0.17 s per character, with a ~0.5 s pause at each end. A name that
already fits stays put.

### 16-channel USB audio — `usb16`

Adds a third choice to **CONFIG > DEVICE > USB MODE**, which now cycles
`A+M` → `A16` → `MID`:

| USB MODE | Sent to the computer |
|---|---|
| `A+M` | stock: the stereo mix, plus MIDI |
| `A16` | 16 channels, plus MIDI |
| `MID` | MIDI only |

In `A16` the channels are, at 48 kHz / 24 bit:

| Channels | Name on the host | Content |
|---|---|---|
| 1–12 | `T1 L` … `T6 R` | the six tracks as stereo pairs, **after VOL and PAN** |
| 13–14 | `Delay L`, `Delay R` | the delay return (wet output) |
| 15–16 | `Reverb L`, `Reverb R` | the reverb return (wet output) |

Each channel is exactly what the mixer adds to the main bus, with the same gain
curve and master gain, so the 16 channels sum to the stereo mix (short of
master-bus clipping). A track muted on the device is silent on its channels; its
delay and reverb tail stays on 13–16, as in the stereo mix.

* After flashing the device starts in `A+M`, which behaves as stock. Pick `A16`
  once; it is kept across power cycles. Switching reconnects the device, so the
  DAW may need the input device selected again.
* Recording and playback should run on **one clock**: use the Model as both the
  input and the output device, or an aggregate device with drift correction
  (macOS Audio MIDI Setup). Two separate USB devices without drift correction
  drop host buffers every few minutes.
* Tested on Model:Cycles and Model:Samples hardware with macOS. Windows is
  untested.

Based on [ms-multi-output](https://github.com/scottmetoyer/ms-multi-output) by
Scott Metoyer and the work on it in
[Modded-Cycles](https://github.com/18nelli18/Modded-Cycles) by 18nelli; see
[Credits](#credits).

### Amp attack — `attack`

Model:Samples only. Hold **FUNC** and turn **DECAY**: the Amp **Attack** of the
active track, one value a step, from instant up to a slow fade-in. Like the other
sound parameters it can be p-locked (hold a trig, FUNC + DECAY), is an LFO
destination, and is saved with the sound and the project.

* Back on the stock firmware a project loses its attack, an attack p-lock turns
  into a lock of another parameter, and an LFO set to attack points elsewhere:
  clear them before going back to stock.
* In a p-lock the knob moves slowly (about +5 per 30 clicks): its step curve is
  borrowed from Filter Resonance.

### Stereo samples — `stereo`

Model:Samples only. Stereo WAVs stay stereo:

* **Upload:** set **CONFIG > DEVICE > Upload** to `ST` (default `MON`, as stock)
  and send stereo WAVs with **Elektron Transfer 1.9.5 or newer**. With `MON`
  Transfer mixes them to mono, as stock.
* **Playback:** a track playing a stereo sample is stereo through the filter,
  the amp and the pan; the delay and reverb sends get its mono mix. In USB
  `A16` (`usb16`) the track's pair carries its left and right.
* **Track Setup** (FUNC + TRACK) **> Chan**: `ST` / `MONO`. `MONO` plays the
  track's stereo samples as their mono mix (and saves the CPU of the second
  channel).
* A stereo sample takes twice the sample memory, and each stereo track about
  5 % more CPU. The sample browser's preview plays the mono mix of the first
  ~0.7 s.
* Samples uploaded as stereo play their mono mix on the stock firmware.

Note: stereo samples are CPU hungry. Playing several at once (five stereo tracks reach ~100 % CPU) can make the device stop responding, so use them wisely.

### Time-stretch — `stretch`

Model:Samples only. An Akai-style real-time time-stretch: the sample plays at
its own pitch for a length you choose, cut into short cycles that repeat or
skip (the grainy, metallic sound of the old samplers is part of it). Per track,
in **Track Setup** (FUNC + TRACK) **> Strch**:

| Item | Values | |
|---|---|---|
| Play | `STD` / `STR` / `BPM` | stock playback / stretch by Time / stretch to the tempo |
| Time (`STR`) | 25 – 400 % | the length against the original |
| Len (`BPM`) | 1 – 128 sixteenths | the length at the project tempo |
| Cyc | 20 – 2000 frames | the cycle length: short is smoother on tones, long on beats |
| When (`BPM`) | `POST` / `PRE` | sets when the time-stretch is applied: before (`PRE`) the START SAMPLE and SAMPLE LENGTH knobs value or after (`POST`) |

* In `BPM` the sample follows tempo changes and pitch changes while it plays,
  locked to the sequencer.
* LOOP and REVERSE work as usual.
* Each stretched track costs about 2 % CPU.

#### P-locks

Every Strch item can be locked per step, like a knob on the main screen:

1. Turn on grid recording (RECORD).
2. Open FUNC + TRACK > Strch.
3. Hold one or more trigs and edit an item: the value goes to the held steps
   only. While a trig is held, the page shows that step's values; a locked
   item has `*` after its name (`Len*`).
4. To remove an item's lock, hold the trig and turn the value down past its
   lowest: the item goes back to the track's value.

* Each item is locked on its own: a step with only Len locked still follows
  the track's Play, Cyc and When.
* A step that locks Play to another mode without its own Time / Len gets
  that mode's default value.
* Trigless trigs (FUNC + TRIG) work: the playing note takes the new settings
  from where it is. They cannot switch stretching on or off mid-note
  (STD ↔ STR / BPM).
* The locks are saved with the project and with Save Pattern to Project, and
  come back with Reload pattern and Undo.
* Up to 51 different sets of locked values per pattern (steps with the same
  values share one).
* A project with these locks loads and plays on stock firmware as usual
  (without the stretch), and loads back with all its locks on the mod. Saving it
  on stock firmware will likely lose the stretch locks.

### Sample edit — `smpl-edit`

Model:Samples only. Finer SMPL START and SMPL LENGTH, with the sample in sight.

* While you turn SMPL START or SMPL LENGTH, the popup shows the sample's
  waveform: the whole sample on top (the part that plays solid, the rest
  dotted, lines at the start and the end), and below it a zoomed view around
  the marker you are moving. The value is shown with decimals (`START 21.56`).
* The zoom is ×8; hold **PAGE** for ×128, or turn **LEVEL/DATA** while the
  popup shows to zoom from ×1 to ×4096 (the track level is not changed
  meanwhile; the zoom goes back to automatic when the popup closes).
* The knob's step follows the zoom: one detent moves the marker about as far on
  screen at any zoom. ×8 steps whole values as stock; PAGE (×128) steps 1/16;
  zoomed further in with LEVEL/DATA, down to 1/256 of a value, the finest the
  parameter holds. Hold PAGE on a zoom you chose for a step four times finer.
  P-locks get the same steps.
* **Track Setup** (FUNC + TRACK) **> Zero** `OFF` / `ON`, per track: the notes
  start, end and loop on the zero crossing nearest to SMPL START / SMPL LENGTH
  (searched up to ±512 frames), which avoids clicks. The popup then shows the
  markers where the notes really start and end, and `0` next to the zoom.
  Stretched notes are left as they are.
* The values are stored as the stock firmware stores them: a project plays the
  same on stock firmware, which shows the whole part of the value.
* PAGE in grid recording still turns the pattern pages, as stock.

### Fast audio — `fast-audio`

Model:Cycles only. Runs the audio render's busiest code from the processor's
on-chip SRAM instead of DDR memory, which leaves about 3 % more CPU for
everything else (stock spends 76–79 % on the sound). The sound is unchanged.
Based on 18nelli's research and the FAST AUDIO of
[irpina/digihealth](https://github.com/irpina/digihealth).

### modkit — `modkit`

Model:Samples only. The base the newer mods are built on (menus, pages,
settings saved with the project or the device); the flasher adds it when a mod
needs it. On its own it changes one thing:

* **CONFIG > DEVICE > Last Page** (`ON` by default): FUNC + TRACK opens Track
  Setup on the row you left it, and on a mod's page (such as Strch) if you left
  the menu there; BACK from the page goes back as usual.

Settings for the whole device live in a file on the +Drive, `modkit-settings`
(beside `factory/` and `incoming/`; not in the sample browser). Transfer shows
it: download it to back the settings up, delete it to reset them.

The mods are independent, any combination works; `stereo` and `stretch` need
`modkit`, which the flasher adds by itself.

---

## What gets checked

Before building:

* the file is parsed in full and **every** SysEx packet checksum is verified;
* the SHA-256 of the decompressed MAIN OS is matched against the known original,
  so a different OS version or an already-patched file is refused rather than
  corrupted;
* **every** region about to be written has its original bytes confirmed first.

After building, everything is recomputed: packet checksums, container length and
content checksum, per-section stream sums, and the HMAC-SHA256 trailer. If any
of it disagrees, the file is not offered for flashing.

Only **section 3 (MAIN OS)** is touched. The bootloader and the updater are
carried over byte for byte, so STARTUP MENU recovery stays available and you can
always go back to stock firmware.

---

## Risks

* Modifying the firmware **voids your warranty** and could brick your device.
* Mods are tested on real Model:Cycles and Model:Samples hardware, but you do this at your
  own risk.
* Before flashing, make sure you can reach **STARTUP MENU**: power off, hold
  **FUNC**, power on, then `4 ... OS UPGRADE`. That is the way back.
* Back your projects up first (`#SYSEX DUMP` in Transfer, or a project backup).

---

## How it works

A `.syx` is just transport: 7-bit packing with a checksum per packet. Inside is
an `ELE3` container of four sections; the third, MAIN OS, is compressed with an
aPLib variant.

`tweak.py` unpacks that section, writes the selected byte sets into it and puts
everything back together. It does not recompress from scratch: the original
stream is decoded into its op list and re-emitted as it was, and only the ops
that read or write a changed byte become literals. The result stays as tight as
the vendor's own packer and takes a couple of seconds.

```
apply.sh / apply.bat   launcher
tweak.py               pipeline and menu
mtlib/syx.py           7-bit SysEx transport
mtlib/aplib.py         aPLib codec: decode to ops, re-emit
mtlib/container.py     ELE3: parse, rebuild, checksums, HMAC
tweaks/<firmware>/     the tweaks themselves
flasher/               the web flasher: page, Pyodide glue (web.py), file list
```

A tweak is plain JSON you can read yourself — offset, expected original bytes,
replacement bytes:

```json
{"off": 1344610, "old": "2f02", "new": "4ef9"}
```

The web flasher works another way: the mods in [`mods/`](mods/) are `.elemod`
files (relocatable code plus the changes to the stock image, never the stock
bytes themselves), and [elekloader](https://github.com/irpina/elekloader)'s
linker ([`elekloader/`](elekloader/)) places them into your MAIN OS, checks that
they fit together, repacks and verifies the file, all in the page.

---

## Disclaimer

This project is not affiliated with, endorsed by or connected to Elektron Music
Machines in any way. Elektron, Model:Cycles and Model:Samples are their
trademarks. No Elektron firmware or code is distributed here — the tweaks are
applied to a file you supply yourself.

## Credits

Building scripts are based on
**[elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool)** (MIT) by **mischa85**.

The 16-channel USB audio tweak (`usb16`) builds on:

* **[scottmetoyer/ms-multi-output](https://github.com/scottmetoyer/ms-multi-output)**
  by Scott Metoyer — the original 6-channel USB mod for the Model:Samples and
  Model:Cycles: the USB driver hook points, the descriptor and queue-head
  changes, and the method. MIT License, Copyright (c) 2026 Scott Metoyer.
* **[18nelli18/Modded-Cycles](https://github.com/18nelli18/Modded-Cycles)** by
  18nelli — the further work on it for the Model:Cycles: keeping USB OS updates
  working, freeing sprite masks as code space, and the analysis of the USB queue
  and of the dropouts.

On top of that, `usb16` takes the channels after the mixer's VOL and PAN as stereo
pairs, adds the delay and reverb returns, moves to 24 bit with the transfer ring
in SRAM and a fill-level loop on the packet rate, names the channels, adds the
`A16` USB mode next to the stock stereo, and covers the Model:Samples as well.

## License

MIT, see [LICENSE](LICENSE). The license covers this tooling only, not the
firmware it is applied to.

Third-party work this repository builds on:

| Project | Used for | License |
|---|---|---|
| [mischa85/elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool) | the basis of the building scripts | MIT |
| [irpina/elekloader](https://github.com/irpina/elekloader) | the web flasher's linker of `.elemod` mods, copied unchanged into [`elekloader/`](elekloader/) | GPL-2.0-or-later, Copyright (C) 2026 irpina and contributors — see [elekloader/LICENSE](elekloader/LICENSE), [elekloader/NOTICE](elekloader/NOTICE). Under the GPL: that folder and the core mod built from its `core-source/` (`mods/*/core-0.1.elemod`); everything else here is MIT |
| [scottmetoyer/ms-multi-output](https://github.com/scottmetoyer/ms-multi-output) | the basis of the `usb16` tweak | MIT, Copyright (c) 2026 Scott Metoyer — full text in [LICENSE-ms-multi-output](LICENSE-ms-multi-output) |
| [18nelli18/Modded-Cycles](https://github.com/18nelli18/Modded-Cycles) | further work the `usb16` tweak builds on | no license file published (checked 2026-10-04); credited here |
