# SPDX-License-Identifier: GPL-2.0-or-later
"""One interface over the OS file families a device profile names
(`Device.container`):
- 'ele3': the Digitakt mk1's ELE3 container and SysEx transport (syx.py);
- 'elek': the Octatrack's ELEK container, legacy SysEx and ELUP card file
  (elek.py).

    stock, dev, rel = load(path)            # a stock file (or Elektron's zip of it), known by its hash
    built = parse(path, dev)                # any file of that device's family
    image = main_image(stock, dev)
    outputs = write(stock, stored_main, dev, version)   # {'syx': ..., 'bin': ...}
    facts = verify(outputs, stock, want_main, dev, version)
"""
import hashlib

from . import devices, elek, syx
from .codec import aplib


class FormatError(ValueError):
    pass


def _read(path_or_bytes):
    if isinstance(path_or_bytes, (bytes, bytearray)):
        return bytes(path_or_bytes)
    with open(path_or_bytes, 'rb') as fh:
        return fh.read()


def parse(path_or_bytes, dev):
    """A file of `dev`'s family -> its parsed form (syx.Syx or elek.ElekFile)."""
    raw = _read(path_or_bytes)
    try:
        if dev.container == 'ele3':
            return syx.Syx(raw)
        if dev.container == 'elek':
            return elek.ElekFile(raw)
    except (syx.SyxError, elek.ElekError) as e:
        raise FormatError(str(e))
    raise FormatError('%s: no reader for the %s family' % (dev.name, dev.container))


def _from_zip(raw):
    """The known stock OS file inside a zip, as Elektron publishes them (a .syx
    first, then a .bin). -> its bytes."""
    import io
    import zipfile
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = sorted((i for i in z.infolist() if not i.is_dir() and i.file_size <= 64 << 20
                        and i.filename.lower().endswith(('.syx', '.bin'))),
                       key=lambda i: (not i.filename.lower().endswith('.syx'), i.filename))
        for i in names:
            data = z.read(i)
            try:
                devices.identify(hashlib.sha256(data).hexdigest())
            except devices.UnknownFirmware:
                continue
            return data
    except (zipfile.BadZipFile, OSError, RuntimeError) as e:
        raise FormatError('the zip cannot be read: %s' % e)
    raise devices.UnknownFirmware(
        'the zip holds no stock firmware elekloader knows (%s). Supported: %s'
        % (', '.join(i.filename for i in names) or 'no .syx or .bin file', devices.supported()))


def load(path_or_bytes):
    """A stock OS file -> (parsed, Device, Release). Known by its sha256. A zip
    stands for the known OS file inside it."""
    raw = _read(path_or_bytes)
    if raw[:4] == b'PK\x03\x04':
        raw = _from_zip(raw)
    dev, rel = devices.identify(hashlib.sha256(raw).hexdigest())
    return parse(raw, dev), dev, rel


def main_image(parsed, dev):
    return parsed.section(dev.main_section)


def check_version(dev, version):
    """Refuse a version the device's field cannot show."""
    v = version.encode('ascii', 'replace') if version is not None else None
    if v is None:
        return
    if dev.container == 'ele3' and len(v) != dev.version_len:
        raise FormatError('the version is exactly %d ASCII characters' % dev.version_len)
    if not 0 < len(v) <= dev.version_len:
        raise FormatError('the version is 1 to %d ASCII characters' % dev.version_len)


def pack_main(image):
    return aplib.pack_section(bytes(image))


def write(stock, stored_main, dev, version=None):
    """-> {'syx': bytes} or, for a family with a card file too, {'syx', 'bin'}."""
    check_version(dev, version)
    try:
        if dev.container == 'ele3':
            return {'syx': syx.write(stock, stored_main, dev, version)}
        return elek.write(stock, stored_main, dev, version)
    except (syx.SyxError, elek.ElekError) as e:
        raise FormatError(str(e))


def verify(outputs, stock, want_main, dev, version=None):
    """Re-read every output with the decoder and refuse it unless only the
    main OS (and the version field) changed, and the protected ranges are
    stock's. -> facts."""
    stock_main = main_image(stock, dev)
    try:
        if dev.container == 'ele3':
            facts = syx.verify(outputs['syx'], stock, want_main, dev, version)
            facts['untouched'] = ['sections %s, byte for byte' % ', '.join(
                s for s, v in sorted(facts['sections'].items()) if v['stock'])]
        else:
            facts = elek.verify(outputs, stock, want_main, dev, stock_main, version)
    except (syx.SyxError, elek.ElekError) as e:
        raise FormatError(str(e))
    for lo, hi, why in dev.protected:
        a, b = lo - dev.main_load, hi - dev.main_load
        if bytes(want_main[a:b]) != stock_main[a:b]:
            raise FormatError('0x%08x-0x%08x (%s) is not stock' % (lo, hi, why))
    return facts


def header_problems(stock, built, dev):
    """What differs between two files of one device besides the main OS and
    the version field. -> problems (empty: only those differ)."""
    bad = []
    if dev.container == 'ele3':
        if [(s, d) for s, _o, _l, d in built.table] != [(s, d) for s, _o, _l, d in stock.table]:
            bad.append('the section table differs from stock')
        for sid in stock.stored:
            if sid != dev.main_section and built.section(sid) != stock.section(sid):
                bad.append('section %d differs from stock; a mod can only change the main OS'
                           % sid)
        n = 0x1C
        lo, hi = dev.version_at, dev.version_at + 4
    else:
        n, (lo, hi) = elek.SECT, elek.VERSION
    hd = [i for i in range(n) if built.header[i] != stock.header[i]]
    if any(not lo <= i < hi for i in hd):
        bad.append('the container header differs outside the version field')
    return bad
