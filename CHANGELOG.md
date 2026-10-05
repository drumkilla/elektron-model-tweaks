# Changelog

Versions follow [semantic versioning](https://semver.org): a new tweak or a new
behaviour raises the minor number, a fix that changes nothing you rely on raises
the patch number. The web flasher shows this file.

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
