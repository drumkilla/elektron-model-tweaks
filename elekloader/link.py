# SPDX-License-Identifier: GPL-2.0-or-later
"""The linker: format-2 mods -> one patched main OS (docs/FORMAT.md).

A format-2 mod is a relocatable object in JSON:
- its sections: .boot (the core mod only), .run, .fast and .bss;
- the symbols it defines and exports, and what it imports (some weakly);
- its relocations;
- sites in the image, with relocations of their own;
- the tables it declares, and the entries it adds to other mods' tables;
- its resources.

The linker checks the mods, lays them out in the device's areas, resolves
symbols, builds the tables, relocates, and enforces the budgets and the
copied-block rules.

A relocation target is one of:
- "sym:NAME": this mod's own symbol, else another mod's export, else, if
  the import is weak, core_zero;
- "sec:NAME": this mod's section;
- "abs": zero, so the addend is the value.
"""
import struct

from .elemod import (ModError, sha, _int, _hex, common_checks, insn_check, overlaps, summarize,
                    parse_parts, parse_resources, parse_sites, parts_bytes, resolve_target,
                    format_of,
                    COMMON)

FORMAT2 = 2
SECTIONS = ('.boot', '.run', '.fast', '.bss')
RTYPES = ('abs32', 'pc32', 'pc16')
FAST_ENTRY = 16                   # a .fast copy entry: src, dst, len, 0
MAX_ALIGN = 4096                  # a section's alignment: a power of two up to this
LINKER_SYMS = {'__run_load', '__run_start', '__run_words', '__bss_start', '__bss_end',
               '__bss_words'}


def _align(v, a):
    return (v + a - 1) // a * a


class Mod2:
    """A loaded, validated format-2 mod."""

    def __init__(self, doc, name='<mod>', raw=None):
        self.doc, self.name = doc, name
        self.sha256 = sha(raw) if raw is not None else None
        if format_of(doc) != FORMAT2:
            raise ModError('%s: not a format-2 .elemod file' % name)
        extra = set(doc) - COMMON - {'sections', 'symbols', 'exports', 'imports', 'weak',
                                     'relocs', 'collections', 'contribute', 'copied'}
        if extra:
            raise ModError('%s: unknown fields %s' % (name, sorted(extra)))
        for k in ('id', 'version', 'target', 'sections'):
            if k not in doc:
                raise ModError('%s: no "%s"' % (name, k))
        self.id, self.version = str(doc['id']), str(doc['version'])
        self.dev, self.rel = resolve_target(doc, name)
        self.sections = {}
        for sec, d in doc['sections'].items():
            if sec not in SECTIONS:
                raise ModError('%s: unknown section %s' % (name, sec))
            align = _int(d.get('align', 4), name)
            if align < 1 or align & (align - 1) or align > MAX_ALIGN:
                raise ModError('%s %s: alignment %d (a power of two up to %d)'
                               % (name, sec, align, MAX_ALIGN))
            if sec == '.bss':
                self.sections[sec] = {'align': align, 'size': _int(d['size'], name)}
                continue
            parts = parse_parts(d.get('parts', []), name + ' ' + sec, self.dev, self.rel)
            n = sum(len(p[1]) if p[0] == 'hex' else p[2] for p in parts)
            if n != _int(d.get('len', n), name):
                raise ModError('%s %s: parts make %d bytes, not %s' % (name, sec, n, d.get('len')))
            self.sections[sec] = {'align': align, 'parts': parts, 'len': n}
        self.symbols = {}
        for nm, v in doc.get('symbols', {}).items():
            if not isinstance(v, list) or len(v) != 2:
                raise ModError('%s: symbol %s' % (name, nm))
            if v[0] != 'abs' and v[0] not in self.sections:
                raise ModError('%s: symbol %s in a section it lacks (%s)' % (name, nm, v[0]))
            self.symbols[nm] = (v[0], _int(v[1], name))
        self.exports = [str(x) for x in doc.get('exports', [])]
        for x in self.exports:
            if x not in self.symbols:
                raise ModError('%s: exports %s, which it does not define' % (name, x))
        self.imports = [str(x) for x in doc.get('imports', [])]
        self.weak = set(str(x) for x in doc.get('weak', []))
        if not self.weak <= set(self.imports):
            raise ModError('%s: a weak name it does not import' % name)
        self.relocs = []
        for r in doc.get('relocs', []):
            sec, off, typ, tgt, add = r
            off = _int(off, name)
            self._reloc_ok(sec, off, typ, tgt)
            self.relocs.append((sec, off, typ, tgt, _int(add, name)))
        self.sites = parse_sites(doc, name, self.dev, self.rel, relocs=True)
        self.collections = {}
        for c, d in doc.get('collections', {}).items():
            e = _int(d.get('entry'), name)
            if e <= 0 or e % 4:
                raise ModError('%s: table %s entry size %d' % (name, c, e))
            self.collections[c] = e
        self.contribute = []
        for i, c in enumerate(doc.get('contribute', [])):
            what = '%s contribution %d' % (name, i)
            data = _hex(c.get('data'), what)
            rel = []
            for r in c.get('relocs', []):
                off, typ, tgt, add = r
                off = _int(off, what)
                if typ not in RTYPES or off < 0 or off + 4 > len(data):
                    raise ModError('%s: bad relocation %r' % (what, r))
                rel.append((off, typ, tgt, _int(add, what)))
            claims = [(_int(a, what), _int(b, what)) for a, b in c.get('claims', [])]
            self.contribute.append({'to': str(c['to']), 'order': _int(c.get('order', 50), what),
                                    'data': data, 'relocs': rel, 'claims': claims, 'i': i})
        self.copied = [(_int(c['lo'], name), _int(c['hi'], name), _int(c['to'], name))
                       for c in doc.get('copied', [])]
        self.regions, self.names = parse_resources(doc, name, self.dev)
        self.requires = [str(x) for x in doc.get('requires', [])]
        self.conflicts = [str(x) for x in doc.get('conflicts', [])]
        self.blob = None                       # (format 1 only)

    def _reloc_ok(self, sec, off, typ, tgt):
        if sec not in self.sections or sec == '.bss':
            raise ModError('%s: relocation in %s' % (self.name, sec))
        if typ not in RTYPES:
            raise ModError('%s: relocation type %s' % (self.name, typ))
        if off < 0 or off + (2 if typ == 'pc16' else 4) > self.sections[sec]['len']:
            raise ModError('%s: relocation at %s+%d is outside it' % (self.name, sec, off))
        if not (tgt == 'abs' or tgt.startswith('sym:') or tgt.startswith('sec:')):
            raise ModError('%s: relocation target %r' % (self.name, tgt))

    def label(self):
        return '%s %s' % (self.id, self.version)

    def size(self, sec):
        d = self.sections.get(sec)
        if not d:
            return 0
        return d['size'] if sec == '.bss' else d['len']


# ---- checks ---------------------------------------------------------------------------

def check(mods, image):
    """Static checks that need no layout. -> [problems]."""
    spans = []
    for m in mods:
        for s in m.sites:
            spans.append((s['addr'], s['addr'] + s['len'], m, 'site 0x%08x' % s['addr']))
        for c in m.contribute:
            for a, b in c['claims']:
                spans.append((a, b, m, '%s entry (claims 0x%08x-0x%08x)' % (c['to'], a, b)))
    bad = common_checks(mods, image, spans)
    if bad and bad[0].startswith('the mods are for different firmware'):
        return bad
    dev = mods[0].dev
    if not dev.linkable():
        return ['the %s has no linkable (format-2) mods yet: only whole builds (format 1) '
                'can be used on it' % dev.name]
    ids = [m.id for m in mods]
    cores = [m for m in mods if '.boot' in m.sections]
    if len(cores) != 1:
        bad.insert(0, 'exactly one mod must carry .boot (core); got %s'
                   % ([m.label() for m in cores] or 'none'))
    owner = {}
    for m in mods:
        for x in m.exports:
            if x in owner:
                bad.append('%s and %s both export %s' % (owner[x].label(), m.label(), x))
            owner[x] = m
    tables = {}
    for m in mods:
        for c, e in m.collections.items():
            if c in tables:
                bad.append('%s and %s both declare the table %s'
                           % (tables[c][0].label(), m.label(), c))
            if c in owner:
                bad.append('table %s has the name of a symbol %s exports' % (c, owner[c].label()))
            tables[c] = (m, e)
    for m in mods:
        for x in m.imports:
            if x in owner or x in tables or x in LINKER_SYMS or x in m.weak \
                    or (x.endswith('_n') and x[:-2] in tables):
                continue
            bad.append('%s imports %s, which no given mod exports' % (m.label(), x))
        for c in m.contribute:
            if c['to'] not in tables:
                bad.append('%s adds to table %s, which no given mod declares' % (m.label(), c['to']))
            elif len(c['data']) % tables[c['to']][1]:
                bad.append('%s: an entry for %s is not %d bytes'
                           % (m.label(), c['to'], tables[c['to']][1]))
        if m.size('.fast') and (not dev.fast_table or dev.fast_table not in tables):
            bad.append('%s has .fast code, which needs the mod that declares %s'
                       % (m.label(), dev.fast_table or 'a .fast copy table'))
    regs = [(g['lo'], g['hi'], m, 'region ' + g['name']) for m in mods for g in m.regions]
    if dev.sram_code[1] > dev.sram_code[0]:
        regs.append((dev.sram_code[0], dev.sram_code[1], None, 'the .fast area'))
    for a, b in overlaps(regs):
        la = a[2].label() if a[2] else 'the linker'
        lb = b[2].label() if b[2] else 'the linker'
        bad.append('%s %s and %s %s overlap' % (la, a[3], lb, b[3]))
    return bad


def _copied_rules(mods, patched, dev):
    """Sites of other mods inside a copied block: no PC-relative operand, no
    relative branch, whole instructions in the patched image."""
    isa = dev.decoder()
    bad = []
    read = isa.reader(patched, dev.main_load)
    for owner in mods:
        for lo, hi, _to in owner.copied:
            for m in mods:
                if m is owner:
                    continue
                for s in m.sites:
                    if not (lo <= s['addr'] < hi or lo < s['addr'] + s['len'] <= hi):
                        continue
                    if s['kind'] != 'code':
                        bad.append('%s site 0x%08x: data inside %s\'s copied block'
                                   % (m.label(), s['addr'], owner.label()))
                        continue
                    a = s['addr']
                    while a < s['addr'] + s['len']:
                        ins = isa.decode(read(a), a)
                        if ins.flags & isa.PCREL or ins.flow in (isa.F_BRA, isa.F_BCC, isa.F_BSR):
                            bad.append('%s site 0x%08x: %s at 0x%08x is PC-relative, inside '
                                       '%s\'s copied block' % (m.label(), s['addr'], ins.op, a,
                                                                owner.label()))
                        a += ins.length
                    if a != s['addr'] + s['len']:
                        bad.append('%s site 0x%08x: its new bytes are not whole instructions'
                                   % (m.label(), s['addr']))
    return bad


# ---- the link -------------------------------------------------------------------------

class Linked:
    pass


def link(mods, image):
    """-> Linked: .image (the patched main OS), .map ({name: address}),
    .layout, .tables ({name: (address, count, entry)}), .order. Raises ModError."""
    if not mods:
        raise ModError('no mods')
    dev, rel = mods[0].dev, mods[0].rel
    if sha(image) != rel.main_sha256:
        raise ModError('the stock main OS is not %s %s' % (dev.name, rel.version))
    bad = summarize(check(mods, image), mods)
    if bad:
        raise ModError('the mods do not combine:\n  ' + '\n  '.join(bad))
    image_end = dev.image_end(rel)
    ddr_base, ddr_end = dev.ddr
    fast_base, fast_end = dev.sram_code
    core = [m for m in mods if '.boot' in m.sections][0]
    order = [core] + sorted((m for m in mods if m is not core), key=lambda m: m.id)
    tables = {c: (m, e) for m in order for c, e in m.collections.items()}

    entries = {c: [] for c in tables}
    for m in order:
        for c in m.contribute:
            entries[c['to']].append((c['order'], m.id, c['i'], m, c))
    fast_mods = [m for m in order if m.size('.fast')]
    for c in entries:
        entries[c].sort(key=lambda e: e[:3])

    def table_len(c):
        n = sum(len(e[4]['data']) for e in entries[c])
        if c == dev.fast_table:
            n += FAST_ENTRY * len(fast_mods)
        return n + tables[c][1]                # the zero entry

    # layout
    base = {}                                  # (mod id, section) -> address
    boot_len = core.size('.boot')
    base[(core.id, '.boot')] = image_end
    at = ddr_base
    for m in order:
        if m.size('.run'):
            at = _align(at, max(4, m.sections['.run']['align']))
            base[(m.id, '.run')] = at
            at += m.size('.run')
    tab_at = {}
    for c in sorted(tables):
        at = _align(at, 4)
        tab_at[c] = at
        at += table_len(c)
    fast_at, fload = fast_base, {}
    for m in fast_mods:
        fast_at = _align(fast_at, max(4, m.sections['.fast']['align']))
        base[(m.id, '.fast')] = fast_at
        at = _align(at, 4)
        fload[m.id] = at
        n = _align(m.size('.fast'), 4)
        fast_at += n
        at += n
    run_end = _align(at, 4)
    at = run_end
    for m in order:
        if m.size('.bss'):
            at = _align(at, max(4, m.sections['.bss']['align']))
            base[(m.id, '.bss')] = at
            at += m.size('.bss')
    bss_end = _align(at, 4)
    if bss_end > ddr_end:
        raise ModError('the mods need RAM to 0x%08x, past 0x%08x (%d bytes over)'
                       % (bss_end, ddr_end, bss_end - ddr_end))
    if fast_at > fast_end:
        raise ModError('.fast code needs SRAM to 0x%08x, past 0x%08x' % (fast_at, fast_end))
    run_load = _align(image_end + boot_len, 16)

    # symbols
    addr, glob = {}, {}
    for m in order:
        for nm, (sec, off) in m.symbols.items():
            v = off if sec == 'abs' else base[(m.id, sec)] + off
            addr[(m.id, nm)] = v
            if nm in m.exports:
                glob[nm] = v
    for c in tables:
        glob[c] = tab_at[c]
        glob[c + '_n'] = table_len(c) // tables[c][1] - 1
    glob.update({'__run_load': run_load, '__run_start': ddr_base,
                 '__run_words': (run_end - ddr_base) // 4, '__bss_start': run_end,
                 '__bss_end': bss_end, '__bss_words': (bss_end - run_end) // 4})
    zero = glob.get('core_zero')

    def resolve(m, tgt, where):
        if tgt == 'abs':
            return 0
        kind, nm = tgt.split(':', 1)
        if kind == 'sec':
            if (m.id, nm) not in base:
                raise ModError('%s: %s refers to its empty section %s' % (m.label(), where, nm))
            return base[(m.id, nm)]
        if (m.id, nm) in addr and nm in m.symbols:
            return addr[(m.id, nm)]
        if nm in glob:
            return glob[nm]
        if nm in m.weak and zero is not None:
            return zero
        raise ModError('%s: %s refers to %s, which nothing defines' % (m.label(), where, nm))

    def put(buf, off, typ, value, p, where):
        if typ == 'abs32':
            struct.pack_into('>I', buf, off, value & 0xFFFFFFFF)
        elif typ == 'pc32':
            struct.pack_into('>i', buf, off, value - p)
        else:
            d = value - p
            if not -0x8000 <= d < 0x8000:
                raise ModError('%s: a 16-bit PC-relative reference spans %d bytes' % (where, d))
            struct.pack_into('>h', buf, off, d)

    content = {}
    for m in order:
        for sec in ('.boot', '.run', '.fast'):
            if m.size(sec):
                content[(m.id, sec)] = parts_bytes(m.sections[sec]['parts'], image, dev)
        for sec, off, typ, tgt, add in m.relocs:
            where = '%s+0x%x' % (sec, off)
            put(content[(m.id, sec)], off, typ, resolve(m, tgt, where) + add,
                base[(m.id, sec)] + off, where)
    tab = {}
    for c in tables:
        buf = bytearray()
        for _o, _id, _i, m, e in entries[c]:
            d = bytearray(e['data'])
            for off, typ, tgt, add in e['relocs']:
                where = 'an entry of %s' % c
                put(d, off, typ, resolve(m, tgt, where) + add, tab_at[c] + len(buf) + off, where)
            buf += d
        if c == dev.fast_table:
            for m in fast_mods:
                buf += struct.pack('>IIII', fload[m.id], base[(m.id, '.fast')],
                                   _align(m.size('.fast'), 4), 0)
        buf += bytes(tables[c][1])
        tab[c] = buf
    ddr = bytearray(run_end - ddr_base)
    for m in order:
        if m.size('.run'):
            o = base[(m.id, '.run')] - ddr_base
            ddr[o:o + m.size('.run')] = content[(m.id, '.run')]
        if m.id in fload:
            o = fload[m.id] - ddr_base
            ddr[o:o + m.size('.fast')] = content[(m.id, '.fast')]
    for c in tables:
        o = tab_at[c] - ddr_base
        ddr[o:o + len(tab[c])] = tab[c]
    blob = bytearray(content[(core.id, '.boot')])
    blob += bytes(run_load - image_end - len(blob))
    blob += ddr
    img = bytearray(image)
    for m in order:
        for s in m.sites:
            new = bytearray(s['new'])
            for off, typ, tgt, add in s['relocs']:
                where = 'site 0x%08x' % s['addr']
                put(new, off, typ, resolve(m, tgt, where) + add, s['addr'] + off, where)
            o = s['addr'] - dev.main_load
            img[o:o + s['len']] = new
    img += blob
    bad = _copied_rules(order, bytes(img), dev)
    for m in order:
        for s in m.sites:
            if s['kind'] == 'code':
                ok, note = insn_check(bytes(img), s['addr'], s['len'], dev, sweeps=0)
                if not ok:
                    bad.append('%s site 0x%08x after relocation: %s' % (m.label(), s['addr'], note))
    if bad:
        raise ModError('the linked mods break a rule:\n  ' + '\n  '.join(bad))

    out = Linked()
    out.image = bytes(img)
    out.order = [m.label() for m in order]
    out.map = {}
    for (mid, nm), v in addr.items():
        out.map['%s:%s' % (mid, nm)] = v
    out.map.update(glob)
    uniq = {}
    for (mid, nm), v in addr.items():
        uniq.setdefault(nm, set()).add(v)
    for nm, vs in uniq.items():
        if len(vs) == 1 and nm not in out.map:
            out.map[nm] = vs.pop()
    out.tables = {c: (tab_at[c], table_len(c) // tables[c][1] - 1, tables[c][1]) for c in tables}
    out.layout = {
        'boot': [image_end, image_end + boot_len], 'run_load': run_load,
        'ddr': [ddr_base, run_end], 'bss': [run_end, bss_end],
        'fast': [fast_base, fast_at], 'blob_len': len(blob),
        'sections': {'%s %s' % k: v for k, v in sorted(base.items(), key=lambda kv: kv[1])},
        'ddr_spare': ddr_end - bss_end, 'fast_spare': fast_end - fast_at,
        'ddr_size': ddr_end - ddr_base, 'fast_size': fast_end - fast_base,
    }
    return out
