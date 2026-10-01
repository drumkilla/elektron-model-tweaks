# model-tweaks

Small firmware tweaks for the Elektron **Model:Cycles** and **Model:Samples**
(OS 1.13). No firmware is distributed here: you supply **your own** `.syx`, the
script applies the tweaks you pick and writes a new file next to it.

**Python 3 is the only requirement.**

These tweaks are also available as a part of these projects:

   * **[Modded Cycles](https://github.com/18nelli18/Modded-Cycles) by 18nelli18** - Model:Cycles only atm.
   * **[Model-TG](https://github.com/TinyGregAudio/Model-TG) by TinyAudioGreg** - Model:Cycles only atm.

---

## Using it

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

## The tweaks

### Latching track mute — `latching-mute`

* Hold **TRACK** and tap **FUNC**: the mute mode latches and the FUNC key lights up.
* A short tap on **FUNC** alone leaves the mode.
* Combinations with FUNC do not leave the mode, including menus such as
  FUNC + PAGE and holding FUNC to turn the encoders fast.
* TRACK, RETRIG and PATTERN bank select keep working while it is latched.

Holding FUNC to mute tracks behaves exactly as it does in stock firmware.

### Trig preview — `trig-preview`

With the sequencer **stopped**, hold a step (trig button) and press **PAGE**: the step sounds
with its own note, length, p-locks and sound-lock. The page does not turn. It
sounds regardless of the trig condition and probability, and through a muted
track.

### Scroll long names — `browser-scroll`

A selected name in the sound/sample/folder browser scrolls left when it does not
fit: about 0.17 s per character, with a ~0.5 s pause at each end. A name that
already fits stays put.

The three are independent; any combination works.

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
* Tweaks are tested on real Model:Cycles and Model:Samples hardware, but you do this at your
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
```

A tweak is plain JSON you can read yourself — offset, expected original bytes,
replacement bytes:

```json
{"off": 1344610, "old": "2f02", "new": "4ef9"}
```

---

## Disclaimer

This project is not affiliated with, endorsed by or connected to Elektron Music
Machines in any way. Elektron, Model:Cycles and Model:Samples are their
trademarks. No Elektron firmware or code is distributed here — the tweaks are
applied to a file you supply yourself.

## License

MIT, see [LICENSE](LICENSE). The license covers this tooling only, not the
firmware it is applied to.

## Credits
Building scripts are based on **[elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool)** (MIT) by **mischa85**
