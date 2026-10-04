"""Browser glue for the web flasher: runs the very same tweak.py / mtlib in Pyodide.

The page copies tweak.py, mtlib/ and tweaks/ into the Pyodide file system under
/app (see files.json), then calls inspect() and build() below. Nothing here
re-implements the pipeline; it only adapts tweak.py's file/console interface.
"""
import contextlib
import hashlib
import io
import json
import os
import sys

APP = '/app'
sys.path.insert(0, APP)
os.chdir(APP)

import tweak                                  # noqa: E402

_state = {}


def _call(fn, *args):
    """Run a tweak.py function; its die() prints and exits, so catch both."""
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            return True, fn(*args), log.getvalue()
    except SystemExit:
        return False, None, log.getvalue()


def inspect(data, filename):
    """data: the user's .syx bytes. Returns JSON: device, OS, tweaks to offer."""
    path = '/tmp/' + (os.path.basename(filename) or 'firmware.syx')   # tweak.py names it in messages
    with open(path, 'wb') as f:
        f.write(bytes(data))
    ok, fw, log = _call(tweak.read_firmware, path)
    if not ok:
        return json.dumps({'ok': False, 'error': log.strip().replace('ERROR: ', '')})
    cat = tweak.load_catalogue()
    ok, picked, log = _call(tweak.pick_entry, cat, fw, path)
    if not ok:
        return json.dumps({'ok': False, 'device': fw['info']['name'],
                           'error': log.strip().replace('ERROR: ', '')})
    key, entry = picked
    digest = hashlib.sha256(fw['raw']).hexdigest()
    _state.update(fw=fw, entry=entry, filename=filename)
    return json.dumps({
        'ok': True, 'device': key[0], 'os': key[1], 'sha256': digest,
        'exact': digest == entry['meta']['stock_syx_sha256'],
        'tweaks': [{'id': t['id'], 'name': t['name'], 'description': t['description'],
                    'links': t.get('links', [])}
                   for t in entry['tweaks']],
    })


def build(ids_json):
    """Apply the chosen tweaks to the inspected file, rebuild and verify it.
    Returns JSON; the built file is left in /tmp/out.syx for the page to read."""
    ids = json.loads(ids_json)
    known = {t['id']: t for t in _state['entry']['tweaks']}
    chosen = [known[i] for i in ids]
    ok, res, log = _call(tweak.apply_tweaks, _state['fw']['main_os'], chosen)
    if not ok:
        return json.dumps({'ok': False, 'error': log.strip().replace('ERROR: ', '')})
    data, dirty = res
    ok, blob, log = _call(tweak.build, _state['fw'], data, dirty)
    if not ok:
        return json.dumps({'ok': False, 'error': log.strip().replace('ERROR: ', '')})
    out = '/tmp/out.syx'
    with open(out, 'wb') as f:
        f.write(blob)
    ok, verified, vlog = _call(tweak.verify, out)
    stem = _state['filename']
    stem = stem[:-4] if stem.lower().endswith('.syx') else stem
    return json.dumps({
        'ok': bool(ok and verified), 'changed': sum(dirty), 'size': len(blob),
        'sha256': hashlib.sha256(blob).hexdigest(), 'name': stem + '_mod.syx',
        'checks': vlog.rstrip().splitlines(),
        'error': None if (ok and verified) else 'the built file failed verification - do not flash it',
    })
