# SPDX-License-Identifier: GPL-2.0-or-later
"""Your stock OS file + .elemod files -> a custom firmware (the command line).

    python -m elekloader.patch --stock Digitakt_OS1.53.syx \
        --mod core-2.1.elemod --mod sysinfo-2.0a.elemod ... --out CUSTOM.syx \
        [--version 2.0a] [--check]

In this order, stopping at the first failure:
  1. the stock file must be a release elekloader knows (by its sha256), and
     its main OS the known image;
  2. every mod must be made for that release, and every site's stock bytes
     must hash to what the mod expects;
  3. the static conflict check (elemod.check, link.check), including the
     device's protected ranges;
  4. apply the sites, or link the mods;
  5. repack the main OS and rebuild the OS file: only the main OS and the
     version field change;
  6. verify every output with independent code (formats.verify): the rest
     of the file is stock, every checksum, the main OS depacks to the
     patched image (in place, where the device's bootloader staging is
     known), the protected ranges are stock, the flash budget;
  7. write the .syx and, for a device with a card file (the Octatrack), the
     .bin beside it; OUT.json (a manifest with every hash); and, for linked
     mods, OUT.map.json (every symbol's address).

--check stops after step 4 and writes nothing. Nothing here talks to a
device: you flash the file yourself, as with any OS update, and the stock
file recovers the unit because the bootloader is never changed.
"""
import argparse
import json
import os
import sys
import time

from . import devices, elemod, formats, link
from .elemod import sha


class PatchError(Exception):
    pass


def build(stock_path, mod_paths, version=None, check_only=False, log=print):
    """-> (outputs {'syx': bytes[, 'bin': bytes]} or None, manifest dict).
    Raises PatchError."""
    try:
        stock, dev, rel = formats.load(stock_path)
    except OSError as e:
        raise PatchError('cannot read %s: %s' % (stock_path, e))
    except (devices.UnknownFirmware, formats.FormatError) as e:
        raise PatchError('%s: %s' % (stock_path, e))
    img0 = formats.main_image(stock, dev)
    if sha(img0) != rel.main_sha256:
        raise PatchError('its main OS is not the known %s %s image' % (dev.name, rel.version))
    log('stock: %s OS %s (%s)' % (dev.name, rel.version, stock.sha256))
    mods = []
    for p in mod_paths:
        try:
            m = elemod.load_any(p)
        except (OSError, elemod.ModError) as e:
            raise PatchError(str(e))
        if m.dev.key != dev.key or m.rel != rel:
            raise PatchError('%s is made for %s %s; your stock firmware is %s %s'
                             % (m.label(), m.dev.name, m.rel.version, dev.name, rel.version))
        log('mod %-24s %d sites%s  (file sha256 %s)'
            % (m.label(), len(m.sites), ', blob %d bytes' % m.blob['len'] if m.blob else '',
               m.sha256[:16]))
        mods.append(m)
    if not mods:
        raise PatchError('no mods given')
    v2 = [m for m in mods if isinstance(m, link.Mod2)]
    linked = None
    try:
        if v2:
            if len(v2) != len(mods):
                raise elemod.ModError('a whole-build bundle (format 1) cannot be combined '
                                      'with separate mods (format 2)')
            linked = link.link(mods, img0)
            img = linked.image
        else:
            img = elemod.apply(mods, img0)
    except elemod.ModError as e:
        raise PatchError(str(e))
    log('the mods combine: no overlaps, stock bytes as expected, code sites whole instructions')
    if linked:
        L = linked.layout
        log('linked %s: RAM 0x%08x-0x%08x (%d bytes spare), .fast to 0x%08x (%d spare), '
            'blob %d bytes' % (', '.join(linked.order), L['ddr'][0], L['bss'][1],
                               L['ddr_spare'], L['fast'][1], L['fast_spare'], L['blob_len']))
    man = {
        'patcher': 'elekloader', 'device': dev.key,
        'stock': {'path': os.path.abspath(stock_path), 'sha256': stock.sha256,
                  'os': rel.version, 'main_sha256': sha(img0)},
        'mods': [{'id': m.id, 'version': m.version, 'file': m.name, 'sha256': m.sha256,
                  'format': 2 if isinstance(m, link.Mod2) else 1, 'sites': len(m.sites),
                  'regions': [{'name': g['name'], 'lo': '0x%08x' % g['lo'],
                               'hi': '0x%08x' % g['hi'], 'area': g['area']} for g in m.regions],
                  'names': m.names} for m in mods],
        'main_sha256': sha(img),
        'main_len': len(img),
    }
    if linked:
        man['link'] = {'order': linked.order, 'layout': linked.layout,
                       'tables': {c: {'at': '0x%08x' % a, 'entries': n, 'entry': e}
                                  for c, (a, n, e) in sorted(linked.tables.items())}}
        man['_map'] = linked.map
    if len(mods) == 1 and not v2 and (mods[0].doc.get('build') or {}).get('section3_sha256'):
        want = mods[0].doc['build'].get('section3_sha256')
        man['bundle_matches_build'] = want == sha(img)
        if want != sha(img):
            raise PatchError('the bundle does not reproduce its build\'s main OS')
        log('the main OS matches the build the bundle came from (sha256 %s)' % sha(img)[:16])
    if check_only:
        return None, man
    if version is None:
        vs = {m.doc.get('ele3_version') for m in mods} - {None}
        if not vs and dev.version_optional:
            vs = {stock.version}
        if len(vs) != 1:
            raise PatchError('give --version (%s): the mods name %s'
                             % ('%d characters' % dev.version_len if dev.container == 'ele3'
                                else 'up to %d characters' % dev.version_len,
                                sorted(vs) or 'no version'))
        version = vs.pop()
    try:
        formats.check_version(dev, version)
    except formats.FormatError as e:
        raise PatchError(str(e))
    t = time.time()
    stored = formats.pack_main(img)
    log('packed the main OS: %d -> %d bytes (%.1f s)' % (len(img), len(stored), time.time() - t))
    try:
        outputs = formats.write(stock, stored, dev, version)
        facts = formats.verify(outputs, stock, img, dev, version)
    except formats.FormatError as e:
        raise PatchError('the output failed verification: %s' % e)
    gap = facts['main'].get('inplace_min_gap')
    log('verified: %s; the main OS depacks to the patched image%s; flash ends %s (%d bytes spare)'
        % ('; '.join(facts['untouched']),
           ' in place (min gap %d bytes)' % gap if gap is not None else '',
           facts['flash_end'], facts['flash_headroom']))
    man['version'] = version
    man['output'] = facts
    return outputs, man


def companion(path, kind):
    """The path of a second output next to `path` (the .bin beside a .syx)."""
    root, ext = os.path.splitext(path)
    return (root if ext.lower() == '.syx' else path) + '.' + kind


def save(outputs, man, path):
    """Write the .syx at `path` (and the .bin beside it), and the manifest
    (and symbol map) next to it. -> the paths written."""
    written = []
    for kind, data in outputs.items():
        p = path if kind == 'syx' else companion(path, kind)
        tmp = p + '.part'
        with open(tmp, 'wb') as fh:
            fh.write(data)
        os.replace(tmp, p)
        written.append(p)
    man['output']['path'] = os.path.abspath(path)
    if 'bin' in outputs:
        man['output']['bin_path'] = os.path.abspath(companion(path, 'bin'))
    smap = man.pop('_map', None)
    if smap is not None:
        with open(path + '.map.json', 'w') as fh:
            json.dump({k: '0x%08x' % v for k, v in sorted(smap.items())}, fh, indent=0)
        man['map'] = os.path.basename(path) + '.map.json'
    with open(path + '.json', 'w') as fh:
        json.dump(man, fh, indent=1)
    return written


def main(argv=None):
    ap = argparse.ArgumentParser(prog='elekloader.patch', description=__doc__.split('\n')[0])
    ap.add_argument('--stock', required=True, help='your stock OS file (.syx, or the '
                                                   'Octatrack\'s .bin)')
    ap.add_argument('--mod', action='append', default=[], help='a .elemod (repeat for more)')
    ap.add_argument('--out', help='the .syx to write (a .bin is written beside it for devices '
                                  'that have a card file)')
    ap.add_argument('--version', help='what the unit shows as its OS version: 4 characters on '
                                      'a Digitakt, up to 10 on an Octatrack (default: the mod\'s)')
    ap.add_argument('--check', action='store_true', help='check the mods combine; write nothing')
    a = ap.parse_args(argv)
    if not a.check and not a.out:
        ap.error('--out is required (or --check)')
    if a.out and os.path.exists(a.stock) and os.path.exists(a.out) \
            and os.path.samefile(a.stock, a.out):
        ap.error('--out is the stock file')
    try:
        outputs, man = build(a.stock, a.mod, a.version, a.check)
    except PatchError as e:
        print('REFUSED: %s' % e)
        return 1
    if a.check:
        print('OK: the mods combine (nothing written)')
        return 0
    for p in save(outputs, man, a.out):
        print('WROTE %s' % p)
    print('  sha256 %s, version %s, %d bytes' % (man['output']['sha256'], man['version'],
                                                 man['output']['bytes']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
