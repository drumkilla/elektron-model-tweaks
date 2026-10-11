# Changelog

Versions follow [semantic versioning](https://semver.org): a new tweak or a new
behaviour raises the minor number, a fix that changes nothing you rely on raises
the patch number. The web flasher shows this file.

## 2.1.0 — 2026-10-11

New mod for **Model:Samples**:

- **Sample edit**: SMPL START and SMPL LENGTH show the sample's waveform while you
  turn them, with a zoom (hold PAGE, or turn LEVEL/DATA); the knob's steps get
  finer as you zoom in, down to 1/256 of a value. Track Setup > Zero puts the
  notes' start and end on zero crossings.

## 2.0.0 — 2026-10-10

The firmware is now linked from `.elemod` mods (in `mods/`) by elekloader's
linker, run in the page; a mod's requirements are added by themselves.

New mods for **Model:Samples**:

- **Attack** parameter via **FUNC + DECAY**. P-locks and LFO are supported too.
- **Stereo samples**: upload stereo WAVs with Transfer (CONFIG > Device >
  Upload = ST) and play them in stereo; Track Setup (FUNC + TRACK) > Chan - 
  sets the track playback mode - mono or stereo. If set to mono, then stereo samples are played in mono (and use less CPU).
- **Stretch** - Akai-style real-time time-stretch: FUNC + TRACK > Strch. BPM
  mode fits the sample to the tempo and follows tempo and pitch changes. All its
  settings can be p-locked per step (trigless trigs included), e.g. a sample
  lock that plays a 1-bar loop on a track set to Len 64.
- **Modkit** foundation library to make development easier: lets mods add menu
  items and pages, keep their settings in the project and the device, and
  p-lock them on steps. Adds CONFIG > Device > Last Page option: FUNC + TRACK
  reopens where you left it.

**Model:Cycles**:

- **Fast-audio** (the render's hot code in on-chip SRAM). Based on **18nelli**'s
  research and [irpina/digihealth](https://github.com/irpina/digihealth).

## 1.2.0 — 2026-10-05

- **usb16**: A16 now takes about half the CPU it did. With 16 channels
  streaming, turning knobs (several at once in particular) no longer lags
  behind. Each audio block is rendered once into the processor's on-chip SRAM,
  and the render loops run from there; the 16 channels are byte for byte the
  same as before.
- **trig-preview**: also works with the sequencer paused (PLAY pressed during
  playback), not only stopped. Thanks to 18nelli for the fix.

## 1.1.0 — 2026-10-04

- New tweak **usb16**: 16-channel USB audio. CONFIG > DEVICE > USB MODE cycles
  `A+M` (stock) / `A16` / `MID`. A16 sends the six tracks as stereo pairs after
  VOL and PAN, then the delay and reverb returns, at 48 kHz / 24 bit, with the
  channels named on the host. Based on ms-multi-output by Scott Metoyer and on
  Modded-Cycles by 18nelli.
- **Web flasher**: build and verify the firmware in the browser, then download
  it or send it over USB MIDI. Nothing is uploaded.

## 1.0.0 — 2026-09-19

First release, for Model:Cycles and Model:Samples OS 1.13.

- **latching-mute**: hold TRK and tap FUNC to latch the mute mode; FUNC lights
  up, a short tap on FUNC alone leaves it.
- **trig-preview**: on a stopped sequencer, hold a step and press PAGE to hear
  it with its note, length, p-locks and sound lock.
- **browser-scroll**: names too long for the browser scroll.
- `tweak.py`, `apply.sh` and `apply.bat`: apply the tweaks to your own `.syx`
  with Python 3 alone.
