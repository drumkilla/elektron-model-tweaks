# SPDX-License-Identifier: GPL-2.0-or-later
"""Digitakt (mk1): a ColdFire MCF54418; the main OS runs from DDR at
0x40000400. Measured on OS 1.53 (the digikit research notes). 1.54's file
differs from 1.53's only in the main OS (and the version string's
section): the same bootstrap, updater and coprocessor image, the same SRAM
operands, and nothing in its code near the DDR area, so what follows holds
for both:

- The container: sections 5, 2 (bootstrap), 3 (MAIN OS), 4 (updater), 8
  (the coprocessor). Section 3 is packed in the aPLib-shaped codec.
- No trailer. The file elektron-firmware-tool writes for mk1 (flashed on
  the owner's unit since CFW 1.5S) has the preamble's length at the
  16-aligned end of the last section, and zero padding to the last 101-byte
  data message.
- The bootstrap (0x800005fe) reads section 3 from flash to 0x40200000 and
  unpacks it from there to 0x40000400, over itself.
- Free at run time: the gap below the audio DMA ring (0x47BE0000-0x47C00000,
  above the sample pool) and two SRAM ranges the OS zeroes and never uses.
"""
from . import Device, Release

DEVICE = Device(
    key='digitakt-mk1',
    name='Digitakt mk1',
    sysex_id=0x0A,
    releases={
        '1.53': Release(
            version='1.53',
            syx_sha256='9bdd44bb6102fb25c143cfab97bc92b7a89c463f795d3112dce89771e29bcc92',
            main_sha256='4b47a9507758ca5669ca02ab2c0374d2c04c98aece445408295cc1dcb265c5df',
            main_len=2475584),
        '1.54': Release(
            version='1.54',
            syx_sha256='f78ba80fa7b1da5fb0e1ff61ad61e9e71aafe79f4364fc49679f3651353e3cf6',
            main_sha256='5c58bf9e3949ef09977c5fc007a61e8d026931f67f1621238379dfb8ee4d31a2',
            main_len=2479680),
    },
    main_section=3,
    main_load=0x40000400,
    stage=0x40200000,
    flash_at=0x80000,
    flash_limit=0x380000,
    trailer=None,
    isa='coldfire',
    areas={
        'ddr': (0x47BE0000, 0x47C00000),          # below the audio DMA ring
        'sram-tail': (0x8000F700, 0x80010000),    # the SRAM's free tail
        'sram-block': (0x80003360, 0x80008000),   # free SRAM (FAST AUDIO's copy)
    },
    ddr=(0x47BE0000, 0x47C00000),
    sram_code=(0x8000F700, 0x80010000),
    fast_table='fa_copies',
    recovery='hold FUNC while powering on for the startup menu, then send the stock .syx',
    toolchain={
        'prefix': 'm68k-linux-gnu-',                # binutils + gcc for m68k/ColdFire
        'asflags': ['-mcpu=54455'],                 # ColdFire V4 (the MCF54418's ISA)
        'cflags': ['-mcpu=54455', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
                   '-fno-pic', '-fno-pie', '-fomit-frame-pointer', '-Wall'],
    },
)
