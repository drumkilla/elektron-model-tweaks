# SPDX-License-Identifier: GPL-2.0-or-later
"""Model:Samples: the Model:Cycles platform (model_cycles.py has the facts
and how they were found) with its own addresses. Measured on OS 1.13:

- Section 3 depacks to 1,733,184 bytes: it ends at 0x401A7640. The seal's
  seed is "DELAY TIME".
- At reset it copies 0x401A05A0-0x401A24F0 to SRAM 0x80000000 and
  0x401A24F0-0x401A7640 to 0x80008000, and clears DDR 0x401A05A0-
  0x4211F510 (its 16 MB heap at 0x410DC5F0 included).
- Above .bss: the DSP's rings (0x4A1Bxxxx-0x4A1Fxxxx), the sample pool,
  0x4A2DD490 + 0x4000050 (0x422DD490-0x462DD4E0 cached), a 0x160-byte
  block at 0x4E2DD4E0 and a 4 MB buffer at 0x4E400000 (0x46400000), so
  DDR is used up to 0x46800000. The linker's area is the Model:Cycles one,
  0x47E00000-0x47E40000.
"""
from . import Device, Release
from .model_cycles import DEVICE as _MC

DEVICE = Device(
    key='model-samples',
    name='Model:Samples',
    sysex_id=0x0F,
    releases={
        '1.13': Release(
            version='1.13',
            syx_sha256='e11859b68deb7e5e3fe86ab32581212093849c4be5d3950add011eac398a2ce8',
            main_sha256='a351392c62ec1c6c3324a807baf46934690d54edfc76029a4b4882541cad1ab2',
            main_len=1733184),
    },
    main_section=3,
    main_load=0x40000400,
    stage=0x40200000,
    flash_at=0x20000,
    flash_limit=0x1E0000,
    trailer='hmac',
    hmac_key_from=(2, b'DELAY TIME'),
    isa='coldfire',
    version_at=0x0C,
    version_optional=True,
    areas={k: v for k, v in _MC.areas.items() if not k.startswith('sram-chord')},
    ddr=_MC.ddr,
    recovery=_MC.recovery,
    toolchain=_MC.toolchain,
)
