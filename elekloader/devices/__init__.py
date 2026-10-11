# SPDX-License-Identifier: GPL-2.0-or-later
"""Device profiles: everything elekloader knows about one Elektron product.

A profile names the stock releases it supports (by hash, so a file is
recognised by its content, not its name) and the facts the patcher,
the linker and the verifier need about that product's firmware:

  - the container: which section is the main OS, its load address, how it
    is stored, whether the file carries a trailer;
  - the bootloader: where it stages the main OS before unpacking it in
    place (the verifier simulates that), and the flash budget;
  - the CPU: which instruction decoder checks patch sites;
  - where mods may live at run time (the free memory areas), and where the
    linker puts their code and data.

To add a device, write a module here with a Device subclass and add it to
DEVICES (docs/DEVICES.md).
"""
from dataclasses import dataclass, field


class UnknownFirmware(ValueError):
    pass


@dataclass(frozen=True)
class Release:
    version: str                 # the OS version, as Elektron names it
    syx_sha256: str              # the stock .syx file
    main_sha256: str             # its main OS section, depacked
    main_len: int                # ... and that section's length
    bin_sha256: str = ''         # the stock card file (.bin), where the device has one


@dataclass
class Device:
    key: str                     # 'digitakt-mk1'
    name: str                    # 'Digitakt mk1'
    sysex_id: int                # the device byte of its SysEx messages
    releases: dict               # version -> Release
    main_section: int            # the container's main OS section id
    main_load: int               # where the main OS runs
    stage: int                   # where the bootloader stages it before unpacking in place;
                                 # None: unknown, so the in-place unpack is not simulated
    flash_at: int                # where the container starts in flash
    flash_limit: int             # where it must end
    trailer: str                 # None: no trailer (mk1); 'hmac': sealed (syx.seal_key)
    isa: str                     # 'coldfire'
    hmac_key_from: tuple = ()    # for 'hmac': (section id, seed string); the key is read from
                                 # the stock file's own section, never stored here (syx.seal_key)
    container: str = 'ele3'      # the file family: 'ele3' (syx.py) or 'elek' (elek.py)
    version_len: int = 4         # the characters of the version field the unit shows
    version_at: int = 0x14       # 'ele3': where that field is in the container header
    version_optional: bool = False   # True: a build given no version keeps stock's field
    protected: tuple = ()        # ((lo, hi, why), ...): main OS bytes no mod may change
    relocatable: tuple = ()      # ((lo, n, (ref, ...), what), ...): data in a protected range
                                 # the OS reaches only through the 4-byte operands at the refs,
                                 # and never writes, so a mod may serve its own copy instead
    blob_max: int = None         # the most a whole build may append (None: the flash budget)
    areas: dict = field(default_factory=dict)   # name -> (lo, hi): free at run time
    ddr: tuple = (0, 0)          # the linker's area for .run, tables and .bss
    sram_code: tuple = (0, 0)    # the linker's area for .fast code
    fast_table: str = ''         # the table .fast sections are copied through
    image_free: tuple = ()       # ((lo, hi), ...): zero runs inside the main OS that
                                 # fixed code may take (sdk.build's "fixed")
    recovery: str = ''           # how to get back to stock, said to the user
    toolchain: dict = field(default_factory=dict)   # for the SDK: prefix, asflags, cflags
    notes: str = ''

    def release_for(self, syx_sha256=None, main_sha256=None):
        for r in self.releases.values():
            if syx_sha256 and syx_sha256 in (r.syx_sha256, r.bin_sha256):
                return r
            if main_sha256 and r.main_sha256 == main_sha256:
                return r
        return None

    def linkable(self):
        """Whether format-2 mods (a core, the linker's areas) exist for it."""
        return self.ddr[1] > self.ddr[0]

    def image_end(self, release):
        """Where an appended blob loads: the stock main OS's end."""
        return self.main_load + release.main_len

    def decoder(self):
        if self.isa == 'coldfire':
            from ..isa import coldfire
            return coldfire
        raise UnknownFirmware('no instruction decoder for %s' % self.isa)


def _all():
    from . import digitakt_mk1, digitakt_mk2, digitone_mk1, octatrack, model_cycles, model_samples
    return [digitakt_mk1.DEVICE, digitakt_mk2.DEVICE, digitone_mk1.DEVICE, octatrack.DEVICE,
            model_cycles.DEVICE, model_samples.DEVICE]


DEVICES = None


def devices():
    global DEVICES
    if DEVICES is None:
        DEVICES = _all()
    return DEVICES


def version_at(sysex_id):
    """-> where the version field of an 'ele3' file with this device byte is."""
    for d in devices():
        if d.container == 'ele3' and d.sysex_id == sysex_id:
            return d.version_at
    return 0x14


def identify(syx_sha256):
    """-> (Device, Release) for a stock .syx, by its hash."""
    for d in devices():
        r = d.release_for(syx_sha256=syx_sha256)
        if r:
            return d, r
    raise UnknownFirmware('not a stock firmware elekloader knows (sha256 %s). Supported: %s'
                          % (syx_sha256, supported()))


def for_target(target):
    """-> (Device, Release) a .elemod's "target" names."""
    if not isinstance(target, dict):
        raise UnknownFirmware('no target')
    key = target.get('device')
    for d in devices():
        if key and d.key != key:
            continue
        r = d.release_for(syx_sha256=target.get('syx_sha256'))
        if r and r.main_sha256 == target.get('section3_sha256', r.main_sha256) \
                and r.main_len == target.get('section3_len', r.main_len):
            return d, r
    raise UnknownFirmware('made for a firmware elekloader does not know (%s %s)'
                          % (target.get('product', '?'), target.get('os', '?')))


def target_of(device, release):
    """-> the "target" object a .elemod for this firmware carries."""
    return {'device': device.key, 'product': device.name, 'os': release.version,
            'syx_sha256': release.syx_sha256, 'section3_sha256': release.main_sha256,
            'section3_len': release.main_len}


def supported():
    return ', '.join('%s %s' % (d.name, v) for d in devices() for v in d.releases)
