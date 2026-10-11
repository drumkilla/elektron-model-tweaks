# SPDX-License-Identifier: GPL-2.0-or-later
"""Digitone (mk1), and Digitone Keys: one OS file serves both. Two ColdFire
MCF5441x CPUs; the main OS runs from DDR at 0x40000400. Measured on OS 1.43
(the numbers below are its own). 1.44's file differs from 1.43's only in
the main OS (and the version string's section): the same bootstrap, updater
and second CPU's image, the same SRAM operands, and nothing in its code near
the DDR area, so what follows holds for both:

- The container: sections 5, 2 (the bootstrap, with the startup menu),
  3 (MAIN OS, packed in the aPLib-shaped codec), 4 (the updater, raw, at
  0x80000400), 6, 7 (the second CPU's image, which renders the FM voices)
  and 8. Seven table entries, so the sections start at 0xA0 (the Digitakt
  mk1's five start at 0x80). Only section 3 ever changes.
- No trailer, the Digitakt mk1's layout otherwise: each section padded to 16
  bytes, the preamble's length the 16-aligned end of the last, zero padding
  to the last 101-byte data message. From its own section-3 stream, the
  writer reproduces the stock file byte for byte.
- The bootstrap loads the updater, and the updater unpacks MAIN OS. It reads
  section 3 from flash (its container offset + 0x80000) to 0x40200000, then
  depacks it from there to 0x40000400, over itself. This is the Digitakt
  mk1's loader, instruction for instruction, 8 bytes further on
  (0x80003518). In place, stock's writer stays at least 403,540 bytes behind
  its reader.
- The flash limit is the Digitakt mk1's (its bootstrap reads a block at
  0x380000). The stock container ends at 0x1C2400.
- Recovery: the bootstrap's startup menu (section 2's strings) has
  "4 ... OS UPGRADE", as on the Digitakt mk1.
- Linkable mods run with the Digitone's core (mods/core-dn1), from
  0x47BE0000-0x47C00000, the Digitakt mk1's area. The OS clears
  0x4028E000-0x43229E60 at start and runs its stack down from 0x48000000.
  No instruction operand in its code points between 0x43EB0000 and the
  stack; the highest is 0x4BEA72C8, the uncached view of 0x43EA72C8. And in
  a settled emulator run, no DDR page from 0x43400000 to 0x47C00000 is ever
  mapped.
- No .fast area: the free SRAM (0x800058F0-0x80008000, zero in the same
  run) is not claimed yet.
"""
from . import Device, Release

DEVICE = Device(
    key='digitone-mk1',
    name='Digitone mk1',
    sysex_id=0x0D,
    releases={
        '1.43': Release(
            version='1.43',
            syx_sha256='c5a54cc05b921f2e4bd814834c5365c2a5aa01d7772a9a2961fac1c3095bf9aa',
            main_sha256='3831a477a2a22befb23c42e47e782853da49566ef5d0a1767fcf6c30e6767414',
            main_len=2732208),
        '1.44': Release(
            version='1.44',
            syx_sha256='d4f200d04484333d82822db7744e6484d0def8f2db8ddf55ee2b780cc13c9659',
            main_sha256='fce648a97c6c5d93b961732e8f8db6b02e0820c6d344c7e2131fa05a4b3168e4',
            main_len=2736304),
    },
    main_section=3,
    main_load=0x40000400,
    stage=0x40200000,
    flash_at=0x80000,
    flash_limit=0x380000,
    trailer=None,
    isa='coldfire',
    areas={
        'ddr': (0x47BE0000, 0x47C00000),          # below the stack's page, above anything the OS uses
    },
    ddr=(0x47BE0000, 0x47C00000),
    recovery=('hold FUNC while powering on for the startup menu, press TRIG 4 (OS UPGRADE), '
              'then send the stock .syx'),
    toolchain={
        'prefix': 'm68k-linux-gnu-',                # binutils + gcc for m68k/ColdFire
        'asflags': ['-mcpu=54455'],                 # ColdFire V4 (the MCF5441x's ISA)
        'cflags': ['-mcpu=54455', '-O2', '-ffreestanding', '-fno-builtin', '-nostdlib',
                   '-fno-pic', '-fno-pie', '-fomit-frame-pointer', '-Wall'],
    },
)
