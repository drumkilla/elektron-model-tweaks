"""Browser glue for the web flasher: links the chosen .elemod mods into the user's stock
firmware with elekloader (its copy in elekloader/, GPL-2.0), in Pyodide.

The page copies elekloader/, mods/ and this file into the Pyodide file system under /app
(see files.json), then calls inspect() and build() below. The mods shown are the ones in
mods/<device>/ made for the user's firmware; a mod's requirements (core, modkit) are
added by themselves and not shown.
"""
import contextlib
import hashlib
import io
import json
import os
import sys

APP = os.environ.get('FLASHER_APP', '/app')   # (the page's; a local check sets it)
sys.path.insert(0, APP)

from elekloader import elemod, formats, patch          # noqa: E402

HIDDEN = {'core', 'modkit'}                              # added when required, never offered
_state = {}


def _mods(dev_key):
    """-> {id: (path, its JSON)} of the mods for this device."""
    folder = os.path.join(APP, 'mods', dev_key)
    out = {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith('.elemod'):
            p = os.path.join(folder, name)
            with open(p) as f:
                doc = json.load(f)
            out[doc['id']] = (p, doc)
    return out


def inspect(data, filename):
    """data: the user's .syx bytes. Returns JSON: device, OS, the mods to offer."""
    path = '/tmp/stock.syx'
    with open(path, 'wb') as f:
        f.write(bytes(data))
    try:
        stock, dev, rel = formats.load(path)
    except Exception as e:                               # noqa: BLE001 (any unreadable file)
        return json.dumps({'ok': False, 'error': str(e)})
    mods = _mods(dev.key)
    fits = {i: m for i, m in mods.items()
            if m[1].get('target', {}).get('syx_sha256') and m[1]['target'].get('os') == rel.version}
    if not fits:
        return json.dumps({'ok': False, 'device': dev.name,
                           'error': 'no mods here for %s OS %s' % (dev.name, rel.version)})
    digest = hashlib.sha256(bytes(data)).hexdigest()
    _state.update(path=path, mods=fits, filename=filename)
    offered = [{'id': i, 'name': d.get('title') or i, 'version': d.get('version', ''),
                'description': [d.get('description', '')], 'links': []}
               for i, (p, d) in sorted(fits.items(), key=lambda kv: kv[1][1].get('title', kv[0]).lower())
               if i not in HIDDEN]
    return json.dumps({
        'ok': True, 'device': dev.name, 'os': rel.version, 'sha256': digest,
        'exact': digest == getattr(rel, 'syx_sha256', digest),
        'tweaks': offered,
    })


def _with_requirements(ids):
    """The chosen ids, the core and everything they require, in no particular order."""
    mods = _state['mods']
    out, todo = set(), list(ids) + ['core']
    while todo:
        i = todo.pop()
        if i in out or i not in mods:
            continue
        out.add(i)
        todo.extend(mods[i][1].get('requires', []))
    return out


def build(ids_json):
    """Link the chosen mods (and what they require) into the inspected file, verified.
    Returns JSON; the built file is left in /tmp/out.syx for the page to read."""
    ids = _with_requirements(json.loads(ids_json))
    paths = [_state['mods'][i][0] for i in sorted(ids)]
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            outputs, man = patch.build(_state['path'], paths, log=print)
    except (patch.PatchError, elemod.ModError) as e:
        return json.dumps({'ok': False, 'error': str(e), 'checks': log.getvalue().splitlines()})
    if not outputs or 'syx' not in outputs:
        return json.dumps({'ok': False, 'error': 'nothing was built',
                           'checks': log.getvalue().splitlines()})
    blob = outputs['syx']
    with open('/tmp/out.syx', 'wb') as f:
        f.write(blob)
    stem = _state['filename']
    stem = stem[:-4] if stem.lower().endswith('.syx') else stem
    return json.dumps({
        'ok': True, 'changed': len(ids), 'size': len(blob),
        'sha256': hashlib.sha256(blob).hexdigest(), 'name': stem + '_mods.syx',
        'mods': sorted(ids), 'checks': log.getvalue().rstrip().splitlines(),
        'error': None,
    })
