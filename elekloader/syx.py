# SPDX-License-Identifier: GPL-2.0-or-later
"""Elektron OS .syx files: read, rebuild with a new main OS, verify.

The writer changes one thing: the stored bytes of the device's main OS
section. Every other section's stored bytes, the ELE3 header (but its
4-character version field) and the framing messages (but their message
count) are copied from the stock file.

For the Digitakt mk1, the layout is the one elektron-firmware-tool writes,
which the device has accepted since CFW 1.5S: sections from where the stock
file's first one starts (0x80 after the Digitakt mk1's five table entries,
0xA0 after the Digitone mk1's seven), each padded to 16 bytes; the
preamble's length is the 16-aligned end of the last section; no trailer; the
final 101-byte chunk is padded with zeros. Given that tool's section-3
stream, write() reproduces its .syx byte for byte (tests/test_patcher.py);
given a stock file's own stream, it reproduces that file.

A sealed device (trailer 'hmac': the Digitakt II) is the same, with a 32-byte
HMAC-SHA256 after the last section's padding, inside the preamble's length:
the digest of everything before it. Its bootstrap checks it, and so does the
running OS on an upgrade. The key is derived from the stock file's own
bootstrap (seal_key), as the device derives it (digikit, dt2/authcode.py).

verify() re-reads an output file with the decoder, not the writer. It
refuses the file unless every other section is stock and the main OS
depacks, in place as the bootloader does it, to the expected image.
"""
import hashlib
import hmac
import struct

from .codec import aplib, elz, transport

COUNT_OFF, TABLE_OFF, ENTRY_SZ = 0x1C, 0x20, 16
DIGEST = 32                       # the HMAC-SHA256 trailer of a sealed device
CHUNK = transport.CHUNK_SIZE      # decoded bytes per data message (101)
FIRST_COUNTER = transport.FIRST_COUNTER


class SyxError(ValueError):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


def _messages(raw):
    out, i = [], 0
    while i < len(raw):
        if raw[i] != 0xF0:
            raise SyxError('byte %d is not F0' % i)
        j = raw.find(b'\xf7', i)
        if j < 0:
            raise SyxError('message at %d has no F7' % i)
        out.append(raw[i:j + 1])
        i = j + 1
    return out


def _decode(msgs):
    """Data messages -> the decoded stream (8-in-7)."""
    out = bytearray()
    for m in msgs:
        payload = m[10:126]
        k = 0
        while k < len(payload):
            ms = payload[k]
            k += 1
            for n in range(7):
                if k >= len(payload):
                    break
                out.append(payload[k] | (0x80 if (ms >> (6 - n)) & 1 else 0))
                k += 1
    return bytes(out)


def classify(raw):
    """Stored section bytes -> 'packed' | 'raw-header' | 'raw'."""
    ln, sm = struct.unpack_from('>II', raw, 0) if len(raw) >= 8 else (0, 1)
    if ln + 8 <= len(raw) and (sum(raw[8:8 + ln]) & 0xFFFFFFFF) == sm:
        return 'packed'
    if len(raw) >= 8 and sm == 0:
        return 'raw-header'
    return 'raw'


def unstore(raw):
    kind = classify(raw)
    if kind == 'packed':
        return elz.depack_section(raw)
    if kind == 'raw-header':
        return bytes(raw[8:])
    return bytes(raw)


class Syx:
    """A parsed Elektron OS .syx (bytes in memory)."""

    def __init__(self, raw):
        self.raw = bytes(raw)
        self.sha256 = sha(self.raw)
        msgs = _messages(self.raw)
        if len(msgs) < 3 or len(msgs[0]) != 16 or len(msgs[-1]) != 16:
            raise SyxError('no 16-byte framing messages at both ends')
        self.framing = (msgs[0], msgs[-1])
        self.data = msgs[1:-1]
        if any(len(m) != 128 for m in self.data):
            raise SyxError('a data message is not 128 bytes')
        if any(m[1:4] != transport.MFR for m in msgs):
            raise SyxError('manufacturer id is not Elektron')
        self.device_id = msgs[0][4]
        self.k = msgs[0][8]                     # the transfer constant
        dec = _decode(self.data)
        self.total, self.checksum = struct.unpack_from('>II', dec, 0)
        if dec[8:12] != b'ELE3' or 8 + self.total > len(dec):
            raise SyxError('no ELE3 container')
        self.container = dec[8:8 + self.total]
        self.tail = dec[8 + self.total:]        # the final chunk's padding
        self.header = self.container[:COUNT_OFF]
        n = struct.unpack_from('>I', self.container, COUNT_OFF)[0]
        if not 0 < n <= 16 or TABLE_OFF + n * ENTRY_SZ > self.total:
            raise SyxError('%d sections: not a table this container can hold' % n)
        self.table = [struct.unpack_from('>IIII', self.container, TABLE_OFF + ENTRY_SZ * i)
                      for i in range(n)]
        # the sections follow the table: from the first one's offset on
        self.data_start = min(off for _s, off, _l, _d in self.table)
        if TABLE_OFF + n * ENTRY_SZ > self.data_start:
            raise SyxError('%d sections do not fit the table' % n)
        self.stored = {}
        for sid, off, clen, _dest in self.table:
            if sid in self.stored or off + clen > self.total:
                raise SyxError('section %d: duplicate or outside the container' % sid)
            self.stored[sid] = self.container[off:off + clen]

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as fh:
            return cls(fh.read())

    @property
    def version_at(self):
        from .devices import version_at
        return version_at(self.device_id)

    @property
    def version(self):
        return self.header[self.version_at:self.version_at + 4].decode('ascii', 'replace')

    def section(self, sid):
        """-> the section's decoded bytes."""
        return unstore(self.stored[sid])


def pack_main(image):
    """Main OS image -> its stored section (the aPLib-shaped packer)."""
    return aplib.pack_section(bytes(image))


def seal_key(stock, dev):
    """-> the HMAC key of a sealed device's files, derived from `stock` (a Syx)
    as its bootstrap derives it: in the section dev.hmac_key_from names, the
    seed string, a NUL and a 32-byte constant C; the key is
    C ^ sha256(seed) ^ sha256(reversed seed)."""
    sid, seed = dev.hmac_key_from
    sec = stock.section(sid)
    i = sec.find(seed + b'\0')
    if i < 0 or sec.find(seed + b'\0', i + 1) >= 0:
        raise SyxError('section %d does not hold the seal seed once' % sid)
    const = sec[i + len(seed) + 1:i + len(seed) + 1 + DIGEST]
    if len(const) != DIGEST:
        raise SyxError('section %d ends inside the seal constant' % sid)
    a, b = hashlib.sha256(seed).digest(), hashlib.sha256(seed[::-1]).digest()
    return bytes(x ^ y ^ z for x, y, z in zip(const, a, b))


def _digest(key, data):
    return hmac.new(key, data, hashlib.sha256).digest()


def write(stock, stored_main, dev, version=None):
    """-> .syx bytes: `stock` (a Syx) with the main OS section's stored bytes
    replaced by `stored_main` and, if given, the ELE3 version field set."""
    if dev.trailer not in (None, 'hmac'):
        raise SyxError('%s files are sealed (%s); elekloader cannot write them'
                       % (dev.name, dev.trailer))
    key = seal_key(stock, dev) if dev.trailer == 'hmac' else None
    if key is not None and _digest(key, stock.container[:-DIGEST]) != stock.container[-DIGEST:]:
        raise SyxError('the stock file\'s seal does not verify with the key its bootstrap gives')
    header = bytearray(stock.header)
    if version is not None:
        v = version.encode('ascii')
        if len(v) != 4:
            raise SyxError('the version field is exactly 4 characters')
        header[dev.version_at:dev.version_at + 4] = v
    cont = bytearray(stock.container[:stock.data_start])   # the table area as stock has it
    cont[:COUNT_OFF] = header
    for i, (sid, _o, _l, dest) in enumerate(stock.table):
        data = stored_main if sid == dev.main_section else stock.stored[sid]
        struct.pack_into('>IIII', cont, TABLE_OFF + ENTRY_SZ * i, sid, len(cont), len(data), dest)
        cont += data
        cont += bytes(-len(cont) % 16)
    if key is not None:
        cont += _digest(key, bytes(cont))
    stream = struct.pack('>II', len(cont), transport.content_checksum(bytes(cont))) + bytes(cont)
    return transport.encode_syx(stream, stock.device_id, stock.framing[0], stock.framing[1])


def inplace_depack(stored, dev):
    """Depack the main OS the way the bootloader does it in place: the stored
    section staged at dev.stage, the output written from dev.main_load over
    it. -> (image, the smallest distance in bytes between the writer and the
    next unread stream byte). A distance > 0 throughout means the in-place
    result is the same as depacking elsewhere."""
    length = struct.unpack_from('>I', stored, 0)[0]
    s = elz.Bits(stored, 8, 8 + length)
    out = bytearray()
    base = dev.stage - dev.main_load       # the stream's offset from the load address
    gap = None
    last = 1
    while True:
        if s.bit():
            g = base + s.p - len(out)
            if gap is None or g < gap:
                gap = g
            out.append(s.byte())
            continue
        g = s.gamma()
        if g == elz.REUSE:
            off = last
        else:
            raw = ((g << 8) + s.byte()) & 0xFFFFFFFF
            if raw == elz.BIAS:
                break
            off = (raw - elz.BIAS) & 0xFFFFFFFF
            last = off
        short = 2 * s.bit() + s.bit()
        n = short if short else s.gamma() + 2
        if off > elz.FAR:
            n += 1
        if off == 0 or off > len(out):
            raise SyxError('the main OS: a match reaches before the output')
        g = base + s.p - (len(out) + n)    # the last byte this match writes
        if gap is None or g < gap:
            gap = g
        for _ in range(n + 1):
            out.append(out[-off])
    if s.p != 8 + length:
        raise SyxError('the main OS: the end marker is not at the declared length')
    return bytes(out), gap


def verify(out, stock, want_main, dev, version=None):
    """Refuse (SyxError) unless `out` (bytes) is `stock` (a Syx) with only the
    main OS changed, and it depacks in place to `want_main`. -> facts."""
    o = Syx(out)                       # every message's shape and the ELE3 magic
    main = dev.main_section
    for m in o.data:
        if m[4] != stock.device_id:
            raise SyxError('a data message has device id 0x%02x' % m[4])
    bad = sum(1 for m in o.data if transport.packet_checksum(m[1:-1], o.k) != m[-2])
    if bad:
        raise SyxError('%d data messages fail their checksum' % bad)
    for i, m in enumerate(o.data):
        c = (m[7] << 14) | (m[8] << 7) | m[9]
        if c != FIRST_COUNTER + i:
            raise SyxError('data message %d carries counter %d' % (i, c))
    for fo, fs in zip(o.framing, stock.framing):
        n = (fo[12] << 14) | (fo[13] << 7) | fo[14]
        if n != len(o.data):
            raise SyxError('framing count %d != %d data messages' % (n, len(o.data)))
        if fo[:12] + fo[15:] != fs[:12] + fs[15:]:
            raise SyxError('a framing message differs from stock beyond its count')
    got = transport.content_checksum(o.container)
    if got != o.checksum:
        raise SyxError('content checksum 0x%08x != preamble 0x%08x' % (got, o.checksum))
    if len(o.tail) >= CHUNK or any(o.tail):
        raise SyxError('%d bytes after the container, or not zero' % len(o.tail))
    if [(s, d) for s, _o, _l, d in o.table] != [(s, d) for s, _o, _l, d in stock.table]:
        raise SyxError('section order or destinations differ from stock')
    at = stock.data_start
    for sid, off, clen, _d in o.table:
        if off != at:
            raise SyxError('section %d at 0x%x, not 0x%x' % (sid, off, at))
        at = off + clen + (-(off + clen) % 16)
    if dev.trailer == 'hmac':
        if o.total != at + DIGEST:
            raise SyxError('container length %d is not the 16-aligned end %d and the seal'
                           % (o.total, at))
        if _digest(seal_key(stock, dev), o.container[:-DIGEST]) != o.container[-DIGEST:]:
            raise SyxError('the HMAC trailer does not verify')
    elif o.total != at:
        raise SyxError('container length %d is not the 16-aligned end %d' % (o.total, at))
    if dev.flash_at + o.total > dev.flash_limit:
        raise SyxError('the container ends at flash 0x%x > 0x%x'
                       % (dev.flash_at + o.total, dev.flash_limit))
    hd = [i for i in range(COUNT_OFF) if o.header[i] != stock.header[i]]
    if any(not dev.version_at <= i < dev.version_at + 4 for i in hd):
        raise SyxError('ELE3 header differs outside the version field: %s' % hd)
    if version is not None and o.version != version:
        raise SyxError('version field %r, not %r' % (o.version, version))
    if o.container[TABLE_OFF + ENTRY_SZ * len(o.table):stock.data_start] != \
            stock.container[TABLE_OFF + ENTRY_SZ * len(stock.table):stock.data_start]:
        raise SyxError('the table area after the entries differs from stock')
    for sid in stock.stored:
        if sid == main:
            continue
        if o.stored[sid] != stock.stored[sid]:
            raise SyxError('section %d is not stock' % sid)
        if o.section(sid) != stock.section(sid):
            raise SyxError('section %d does not depack as stock' % sid)
    s3 = o.stored[main]
    if classify(s3) != 'packed':
        raise SyxError('the main OS is not a packed stream with a valid byte sum')
    img, gap = inplace_depack(s3, dev)
    if img != bytes(want_main):
        raise SyxError('the main OS does not depack to the patched image')
    if elz.depack_section(s3) != img:
        raise SyxError('the main OS: the depacker disagrees with the in-place depack')
    if gap <= 0:
        raise SyxError('the main OS: the in-place depack overwrites unread input (gap %d)' % gap)
    return {
        'sha256': sha(out), 'bytes': len(out), 'messages': len(o.data) + 2,
        'content_checksum': '0x%08x' % o.checksum, 'container_len': o.total,
        'flash_end': '0x%06x' % (dev.flash_at + o.total),
        'flash_headroom': dev.flash_limit - dev.flash_at - o.total,
        'ele3_version': o.version,
        'main': {'section': main, 'stored': len(s3), 'image': len(img), 'sha256': sha(img),
                 'staged_to': '0x%08x' % (dev.stage + len(s3)), 'inplace_min_gap': gap},
        'sections': {str(s): {'stored': l, 'stored_sha256': sha(o.stored[s]), 'stock': s != main}
                     for s, _o, l, _d in o.table},
    }
