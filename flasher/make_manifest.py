#!/usr/bin/env python3
"""Write flasher/files.json: the repository files the web flasher loads into
Pyodide (paths relative to the repository root, which is what GitHub Pages serves).

    python3 flasher/make_manifest.py           regenerate
    python3 flasher/make_manifest.py --check   exit 1 if files.json is stale

Run it after adding or removing a tweak.
"""
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'flasher', 'files.json')


def files():
    pats = ['tweak.py', 'mtlib/*.py', 'tweaks/*/*.json', 'flasher/web.py']
    out = []
    for p in pats:
        out += sorted(os.path.relpath(f, ROOT) for f in glob.glob(os.path.join(ROOT, p)))
    return [f.replace(os.sep, '/') for f in out]


def main():
    text = json.dumps(files(), indent=1) + '\n'
    if '--check' in sys.argv:
        current = open(OUT).read() if os.path.exists(OUT) else ''
        if current != text:
            print('flasher/files.json is stale: run python3 flasher/make_manifest.py')
            sys.exit(1)
        print('flasher/files.json is up to date')
        return
    open(OUT, 'w').write(text)
    print('wrote flasher/files.json (%d files)' % len(files()))


if __name__ == '__main__':
    main()
