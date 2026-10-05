#!/usr/bin/env python3
"""Model:Cycles / Model:Samples OS tweaks, applied to your own firmware file.

Put the original .syx next to this script and run it. Nothing but Python 3 is
needed: no Ghidra, no compiler, no downloads.

    python3 tweak.py                       pick tweaks interactively
    python3 tweak.py --list                show what is available
    python3 tweak.py -i FW.syx --all       apply everything
    python3 tweak.py -i FW.syx -t trig-preview,browser-scroll
    python3 tweak.py --verify FW_mod.syx   recheck a finished file
    python3 tweak.py --version             which release this is (CHANGELOG.md)
"""

import argparse
import glob
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mtlib import aplib, container            # noqa: E402
from mtlib.syx import unwrap, wrap, BYTES_PER_MSG   # noqa: E402

TWEAKS_DIR = os.path.join(HERE, 'tweaks')
__version__ = '1.2.0'             # the top entry of CHANGELOG.md (make_manifest.py --check)


# --------------------------------------------------------------------------- #

def die(msg):
    print('ERROR: ' + msg, file=sys.stderr)
    sys.exit(1)


def load_catalogue():
    """{(device, os): {'dir':..., 'meta':..., 'tweaks':[...]}}"""
    cat = {}
    for d in sorted(glob.glob(os.path.join(TWEAKS_DIR, '*'))):
        mf = os.path.join(d, 'device.json')
        if not os.path.isfile(mf):
            continue
        meta = json.load(open(mf, encoding='utf-8'))
        tws = [json.load(open(p, encoding='utf-8'))
               for p in sorted(glob.glob(os.path.join(d, '[0-9]*.json')))]
        cat[(meta['device'], meta['os'])] = dict(dir=d, meta=meta, tweaks=tws)
    return cat


def read_firmware(path):
    raw = open(path, 'rb').read()
    try:
        stream, info = unwrap(raw)
    except ValueError as e:
        die('%s: %s' % (os.path.basename(path), e))
    c = container.parse(stream)
    sec = {s['id']: s for s in c['sections']}
    if 3 not in sec:
        die('the container has no section 3 (MAIN OS)')
    s3 = sec[3]
    main_os, ops = aplib.depack(c['blob'][s3['off']:s3['off'] + s3['size']])
    return dict(raw=raw, stream=stream, info=info, cont=c, s3=s3,
                main_os=main_os, ops=ops, plain=plain_sections(c))


def plain_sections(c):
    """Every section we can decompress. The trailer key hides in one of them."""
    out = []
    for s in c['sections']:
        body = c['blob'][s['off']:s['off'] + s['size']]
        try:
            out.append(aplib.depack(body)[0])
        except (ValueError, IndexError):
            out.append(body)                 # stored raw
    return out


def pick_entry(cat, fw, path):
    name = fw['info']['name']
    matches = [(k, v) for k, v in cat.items() if k[0] == name]
    if not matches:
        die('no tweaks for %s' % name)
    want = hashlib.sha256(fw['main_os']).hexdigest()
    for k, v in matches:
        if v['meta']['section_sha256'] == want:
            return k, v
    print('This is a %s, but its MAIN OS matches no version we know.'
          % name, file=sys.stderr)
    print('Supported: ' + ', '.join('OS ' + k[1] for k, _ in matches), file=sys.stderr)
    print('It is probably a different OS version, or already patched.', file=sys.stderr)
    die('nothing to apply to %s' % os.path.basename(path))


# --------------------------------------------------------------------------- #

def apply_tweaks(main_os, tweaks):
    data = bytearray(main_os)
    dirty = bytearray(len(main_os))
    for t in tweaks:
        for w in t['writes']:
            off, old, new = w['off'], bytes.fromhex(w['old']), bytes.fromhex(w['new'])
            if bytes(data[off:off + len(old)]) != old:
                die('%s: unexpected bytes at 0x%X - the firmware is already '
                    'modified, or two tweaks collide' % (t['id'], off))
            data[off:off + len(new)] = new
            for k in range(off, off + len(new)):
                dirty[k] = 1
    return bytes(data), dirty


def build(fw, data, dirty):
    stream = aplib.repack(data, fw['ops'], dirty)
    c = fw['cont']
    msg = c['blob'][:len(c['blob']) - container.DIGEST_LEN]
    expect = c['blob'][len(c['blob']) - container.DIGEST_LEN:]
    key = container.find_key(fw['plain'], msg, expect)
    if key is None:
        die('could not recover the trailer key from this firmware')
    blob = container.rebuild(c, {3: stream}, key)
    out = container.build_stream(blob, BYTES_PER_MSG)
    return wrap(out, fw['info']['product'], fw['info']['start_seq'])


def verify(path, quiet=False):
    """Re-derive every checksum in a finished file. Returns True if all agree."""
    raw = open(path, 'rb').read()
    ok = True
    try:
        stream, info = unwrap(raw)          # checks every packet checksum
    except ValueError as e:
        print('  SysEx transport      : FAILED - %s' % e)
        return False
    if not quiet:
        print('  device               : %s' % info['name'])
        print('  packets              : %d, every checksum agrees' % info['count'])
    c = container.parse(stream)
    declared = int.from_bytes(stream[0:4], 'big')
    calc = container.content_checksum(c['blob'])
    stored = int.from_bytes(stream[4:8], 'big')
    ok &= (calc == stored) and (declared == len(c['blob']))
    if not quiet:
        print('  content checksum     : stored 0x%08X, computed 0x%08X  %s'
              % (stored, calc, 'ok' if calc == stored else 'MISMATCH'))
    sec = {s['id']: s for s in c['sections']}
    plain = []
    for sid in sorted(sec):
        s = sec[sid]
        body = c['blob'][s['off']:s['off'] + s['size']]
        if len(body) >= 8:
            slen = int.from_bytes(body[0:4], 'big')
            ssum = int.from_bytes(body[4:8], 'big')
            acc = sum(body[8:8 + slen]) & 0xFFFFFFFF
            if 0 < slen <= len(body) - 8:
                good = acc == ssum
                ok &= good
                if not quiet:
                    print('  section %d stream sum : %s' % (sid, 'ok' if good else 'MISMATCH'))
        try:
            plain.append(aplib.depack(body)[0])
        except (ValueError, IndexError):
            plain.append(body)
    msg = c['blob'][:len(c['blob']) - container.DIGEST_LEN]
    expect = c['blob'][len(c['blob']) - container.DIGEST_LEN:]
    key = container.find_key(plain, msg, expect)
    ok &= key is not None
    if not quiet:
        print('  HMAC-SHA256          : %s' % ('ok' if key else 'MISMATCH'))
    return ok


# --------------------------------------------------------------------------- #

def choose(entry):
    tws = entry['tweaks']
    sel = [True] * len(tws)
    while True:
        print()
        print('  %s OS %s' % (entry['meta']['device'], entry['meta']['os']))
        print()
        for i, t in enumerate(tws):
            print('   %d) [%s] %s' % (i + 1, 'x' if sel[i] else ' ', t['name']))
            for line in t['description']:
                print('         %s' % line)
        print()
        print('   number toggles, a = all, n = none, Enter = build, q = quit')
        try:
            s = input('  > ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if s == 'q':
            sys.exit(0)
        if s == '':
            if not any(sel):
                print('  Nothing selected.')
                continue
            return [t for t, on in zip(tws, sel) if on]
        if s == 'a':
            sel = [True] * len(tws)
        elif s == 'n':
            sel = [False] * len(tws)
        elif s.isdigit() and 1 <= int(s) <= len(tws):
            sel[int(s) - 1] ^= True
        else:
            print('  Did not understand that.')


def find_input():
    here = [p for p in sorted(glob.glob('*.syx')) if '_mod' not in os.path.basename(p)]
    if not here:
        die('no .syx here - put the original firmware in this folder')
    if len(here) == 1:
        return here[0]
    print('\n  Several firmware files found:\n')
    for i, p in enumerate(here):
        print('   %d) %s' % (i + 1, p))
    while True:
        try:
            s = input('\n  pick a number > ').strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(1)
        if s.isdigit() and 1 <= int(s) <= len(here):
            return here[int(s) - 1]


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument('-i', '--input')
    ap.add_argument('-o', '--output')
    ap.add_argument('-t', '--tweaks')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--verify')
    ap.add_argument('-h', '--help', action='store_true')
    ap.add_argument('--version', action='store_true')
    a = ap.parse_args()

    if a.help:
        print(__doc__)
        return
    if a.version:
        print('model-tweaks %s' % __version__)
        return
    if a.verify:
        print('\n%s' % os.path.basename(a.verify))
        sys.exit(0 if verify(a.verify) else 1)

    cat = load_catalogue()
    if not cat:
        die('the tweaks/ folder is empty')
    if a.list:
        print('model-tweaks %s' % __version__)
        for (dev, osv), e in sorted(cat.items()):
            print('\n%s OS %s' % (dev, osv))
            for t in e['tweaks']:
                print('  %-16s %s' % (t['id'], t['name']))
        return

    path = a.input or find_input()
    if not os.path.isfile(path):
        die('no such file: %s' % path)
    fw = read_firmware(path)
    key, entry = pick_entry(cat, fw, path)

    digest = hashlib.sha256(fw['raw']).hexdigest()
    exact = digest == entry['meta']['stock_syx_sha256']
    print('\n  model-tweaks %s' % __version__)
    print('  File     : %s' % os.path.basename(path))
    print('  Firmware : %s OS %s' % key)
    print('  SHA-256  : %s' % digest)
    if exact:
        print('             matches the known original')
    else:
        print('             MAIN OS matches the original, the file itself does not;')
        print('             normal if the .syx was repacked. Carrying on.')

    if a.all:
        chosen = entry['tweaks']
    elif a.tweaks:
        want = [x.strip() for x in a.tweaks.split(',') if x.strip()]
        known = {t['id']: t for t in entry['tweaks']}
        bad = [w for w in want if w not in known]
        if bad:
            die('unknown tweaks: %s' % ', '.join(bad))
        chosen = [known[w] for w in want]
    else:
        chosen = choose(entry)

    print('\n  Applying:')
    for t in chosen:
        print('    - %s' % t['name'])
    data, dirty = apply_tweaks(fw['main_os'], chosen)
    print('  %d of %d MAIN OS bytes changed.' % (sum(dirty), len(data)))

    out = a.output
    if not out:
        stem = os.path.basename(path)
        stem = stem[:-4] if stem.lower().endswith('.syx') else stem
        out = os.path.join(os.path.dirname(os.path.abspath(path)), stem + '_mod.syx')
    print('  Building the image...')
    blob = build(fw, data, dirty)
    open(out, 'wb').write(blob)

    print('\n  Done: %s  (%d bytes)' % (os.path.basename(out), len(blob)))
    print('  SHA-256: %s' % hashlib.sha256(blob).hexdigest())
    print('\n  Checking what was built:')
    if not verify(out):
        die('the built file failed verification - do not flash it')
    print('\n  All checks passed. Send it with Elektron Transfer or any SysEx tool.')


if __name__ == '__main__':
    main()
