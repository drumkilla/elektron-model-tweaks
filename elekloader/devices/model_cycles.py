# SPDX-License-Identifier: GPL-2.0-or-later
"""Model:Cycles: an NXP MCF54415 (ColdFire V4m, EMAC, no FPU); the main OS
runs from DDR at 0x40000400. Measured on OS 1.13 (model-cycles-os research,
work/FINDINGS.md there); Model:Samples (model_samples.py) is the same
platform with its own addresses.

- The container: sections 5 (the build string), 2 (the bootstrap, run at
  0x80000400 in SRAM; its `dest` is 0x04000000), 3 (MAIN OS) and 4 (the
  updater, stored raw). Section 3 is packed in the aPLib-shaped codec,
  1,744,192 bytes depacked: it ends at 0x401AA140.
- Sealed, as the Digitakt II: a 32-byte HMAC-SHA256 after the last
  section's padding. The key comes from the bootstrap's seed string
  "REVERB SEND", a NUL and 32 bytes (Model:Samples: "DELAY TIME"). From a
  stock file's own main OS stream, syx.write reproduces it byte for byte.
- The version the unit shows is the header's "1.13" at 0x0C (the build
  "0038" is at 0x08): the OS caches the container's first 0x20 bytes from
  flash 0x20000 (0x4008f2c4) and prints +0x0C and +0x08 at boot. Nothing
  reads 0x14-0x18, which the Digitakt's family uses for its version.
- Staging: the bootstrap's loader (0x80000820) finds section 3 in the table
  at flash 0x20020, reads it from its offset + 0x20000 to 0x40200000 and
  unpacks it from there to 0x40000400 (0x800006bc), as the Digitakt mk1.
- Flash: SPI NOR on DSPI0. The bootstrap is at 0x10000, the container from
  0x20000. The OS keeps two stores at 0x1E0000 and 0x1F0000 (0x40042b28:
  erased and written by sector). Its in-OS upgrade (0x40092304, the route
  Transfer takes) erases from 0x20000 sector by sector for the container's
  length and writes it, so the container must end below 0x1E0000: 1.75 MB,
  of which stock takes 0.70 MB.
- At reset (0x400004e8) the OS sets its stack to 0x48000000, copies
  0x4019B590-0x401A2A50 to SRAM 0x80000000 and 0x401A2A50-0x401AA140 to
  0x80008000 (zeroing the rest of each 32 KB half) through the call at
  0x4000052c, then clears DDR 0x4019B590-0x423380B0 (.bss: its 16 MB heap
  at 0x412FEE70 included) through the call at 0x40000530. Caches go on
  after both, at 0x40000548.
- DDR above .bss: the DSP's rings (0x4A3xxxxx, the uncached alias of
  0x423xxxxx) and a 4 MB buffer at 0x4A400000 (0x42400000), cleared at
  start (0x40057260). No decoded instruction names anything from there to
  the boot stack, cached or uncached.
- Free at run time: DDR 0x47E00000-0x47E40000, 1.75 MB below the boot
  stack, the same window on Model:Samples (whose sample pool and buffer end
  at 0x46800000). Not yet watched at run time.
- SRAM 0x8000F700-0x80010000 (2304 B): past the data the reset copies into
  the second half (to 0x8000F6F0 here, 0x8000D150 on Model:Samples), so
  zeroed at reset; no decoded instruction names it on either model. The
  Digitakt mk1 has the same tail free (its profile, from a write watch).
  A mod claims what it uses as a region. No .fast area (no copy table).
- SRAM 0x80001C5C-0x800074B4 and 0x8000CAC0-0x8000EAE0: CHORD's 30
  wavetables (1028 B each), read through 31 pointers at 0x40118594 and by
  nothing else (no other instruction names them; a write through a4 at
  0x400a8906 stops at 0x8000CAC0). Free only for a mod that serves CHORD
  its tables from elsewhere and points those pointers there (fast-audio).
  Model:Samples has no CHORD: it has neither area.
"""
from . import Device, Release

DEVICE = Device(
    key='model-cycles',
    name='Model:Cycles',
    sysex_id=0x11,
    releases={
        '1.13': Release(
            version='1.13',
            syx_sha256='44fe586269631a0ca7da25a3383fc6733c314809505fc3cc52f1e0ed9800640c',
            main_sha256='cc99d4f0175d34d1e91d046e6ec85a5e8ab58ab9edbb3c24406acd48cb99ee98',
            main_len=1744192),
    },
    main_section=3,
    main_load=0x40000400,
    stage=0x40200000,
    flash_at=0x20000,
    flash_limit=0x1E0000,
    trailer='hmac',
    hmac_key_from=(2, b'REVERB SEND'),
    isa='coldfire',
    version_at=0x0C,
    version_optional=True,
    areas={
        'ddr': (0x47E00000, 0x47E40000),          # above every buffer, below the boot stack
        'sram-tail': (0x8000F700, 0x80010000),    # zeroed at reset, named by no instruction
        'sram-chord-a': (0x80001C5C, 0x800074B4),  # CHORD's tables: see above
        'sram-chord-b': (0x8000CAC0, 0x8000EAE0),
    },
    ddr=(0x47E00000, 0x47E40000),
    recovery=('hold FUNC while powering on for the STARTUP MENU, press TRIG 4 (OS UPGRADE), '
              'then send the stock .syx over 5-pin MIDI (not USB)'),
    toolchain={
        'prefix': 'm68k-elf-',                      # bare-metal binutils (+ gcc for C)
        'asflags': ['-mcpu=54418'],                 # ColdFire V4 with EMAC (the MCF5441x's ISA)
        'cflags': ['-mcpu=54418', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
                   '-fno-pic', '-fno-pie', '-fomit-frame-pointer', '-Wall'],
    },
)
