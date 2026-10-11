# SPDX-License-Identifier: GPL-2.0-or-later
"""The Octatrack family's OS files: the ELEK container, the legacy SysEx
transport (.syx) and the ELUP card file (.bin). Read, rebuild with a new
main OS, verify.

The ELEK container (every value big-endian):
    0x00  "ELEK"
    0x04  the build code, 4 ASCII digits ("0178"); the updater refuses a
          lower one
    0x08  the version the unit shows, 10 characters, right-justified
    0x12  the main OS section: [u32 stream length][u32 byte sum], then the
          packed stream (the same aPLib-shaped codec as the ELE3 devices)
    ...   zero padding: to an even length in the .syx, to a multiple of 4
          in the .bin

The legacy SysEx transport, one message per 63 container bytes:
    F0 00 20 3C <dev> 00 7E  ck_hi ck_lo  n0..n5  <8-in-7 of up to 63 bytes>  F7
- n0..n5 are six nibbles giving 0x4000 plus the offset of the message's
  first byte.
- The checksum is C = (sum of the message's container bytes + (n1 & 7)
  + n3 + n5 + ((n2 + n4) << 4)) & 0xFF, sent as its two nibbles.
- The data messages are followed by an empty one, F0 00 20 3C <dev> 00 7E
  F7, and an end marker, F0 00 20 3C <dev> 00 7F n0..n5 F7, carrying the
  container's length.

The ELUP card file, in big-endian 32-bit words:
- "ELUP", then the seed.
- Then the payload, [u32 length][the container padded to 4], ciphered
  word by word with feedback. The previous cipher word selects the variant:
  bit 23 clear gives c = rot16(p ^ k ^ 0x360FA955) ^ 0x9E3B16A2, and set
  gives c = bswap(p ^ k ^ 0xEF4A9AB6) ^ 0x764E28CA.
- The last word is the sum of the plain words, ciphered the same way.

The checksum and the cipher are as elektron-firmware-tool (MIT) and
sambanks/octabam (MIT) describe them. Every rule here is checked against
the stock Octatrack 1.40C files: rebuilding them from their own section
reproduces both files byte for byte (tests/test_octatrack.py).
"""
import hashlib
import struct

from .codec import aplib, elz

MAGIC, BIN_MAGIC = b'ELEK', b'ELUP'
MFR = b'\x00\x20\x3c'
SECT = 0x12                       # the section's [length][sum] header
VERSION = (0x08, 0x12)            # the 10-character version field
CHUNK = 63
FIRST = 0x4000
XOR_A, XOR_B, MIX_A, MIX_B = 0x9E3B16A2, 0x764E28CA, 0x360FA955, 0xEF4A9AB6
M32 = 0xFFFFFFFF


class ElekError(ValueError):
    pass


def sha(b):
    return hashlib.sha256(b).hexdigest()


# ---- the legacy SysEx transport --------------------------------------------------

def _nibbles(v):
    return bytes((v >> s) & 0xF for s in (20, 16, 12, 8, 4, 0))


def _value(nib):
    v = 0
    for x in nib:
        v = (v << 4) | x
    return v


def packet_checksum(data, nib):
    s = sum(data) + (nib[1] & 7) + nib[3] + nib[5] + ((nib[2] + nib[4]) << 4)
    return s & 0xFF


def _enc87(data, stale=b''):
    """8-in-7. `stale`: what the encoder's buffer held before `data` was
    written over it. Elektron's encoder reuses one 63-byte buffer, so the
    marker of a short final group also carries the high bits of the bytes
    left there from the previous message. They are never sent and decoders
    ignore them, but the stock 1.40C .syx has them (its last message's
    marker is 0x29 for a lone 0x00), so they are kept to stay byte-exact."""
    buf = bytearray(stale[:CHUNK].ljust(CHUNK, b'\0'))
    buf[:len(data)] = data
    out = bytearray()
    for i in range(0, len(data), 7):
        g = data[i:i + 7]
        out.append(sum(0x40 >> n for n, b in enumerate(buf[i:i + 7]) if b & 0x80))
        out += bytes(b & 0x7F for b in g)
    return bytes(out)


def _dec87(p):
    out, k = bytearray(), 0
    while k < len(p):
        ms = p[k]
        k += 1
        for n in range(7):
            if k >= len(p):
                break
            out.append(p[k] | (0x80 if (ms >> (6 - n)) & 1 else 0))
            k += 1
    return bytes(out)


def encode_syx(container, dev_id):
    head = b'\xf0' + MFR + bytes([dev_id, 0x00])
    out = bytearray()
    prev = b''
    for off in range(0, len(container), CHUNK):
        data = container[off:off + CHUNK]
        nib = _nibbles(FIRST + off)
        c = packet_checksum(data, nib)
        out += head + b'\x7e' + bytes([c >> 4, c & 0xF]) + nib + _enc87(data, prev) + b'\xf7'
        prev = data
    out += head + b'\x7e\xf7'
    out += head + b'\x7f' + _nibbles(len(container)) + b'\xf7'
    return bytes(out)


def decode_syx(raw):
    """-> (device id, container). Checks every message; raises ElekError."""
    msgs, i = [], 0
    while i < len(raw):
        if raw[i] != 0xF0:
            raise ElekError('byte %d is not F0' % i)
        j = raw.find(b'\xf7', i)
        if j < 0:
            raise ElekError('the message at %d has no F7' % i)
        msgs.append(raw[i:j + 1])
        i = j + 1
    if len(msgs) < 3:
        raise ElekError('too few messages for an OS file')
    dev = msgs[0][4] if len(msgs[0]) > 4 else None
    for n, m in enumerate(msgs):
        if m[1:4] != MFR or m[4] != dev or m[5] != 0:
            raise ElekError('message %d: not an Elektron message for device 0x%02x' % (n, dev))
    *data, empty, end = msgs
    if empty != b'\xf0' + MFR + bytes([dev, 0, 0x7E, 0xF7]):
        raise ElekError('no empty data message before the end marker')
    if len(end) != 14 or end[6] != 0x7F:
        raise ElekError('no end marker')
    out = bytearray()
    for n, m in enumerate(data):
        if m[6] != 0x7E or len(m) < 17:
            raise ElekError('message %d is not a data message' % n)
        nib = m[9:15]
        if any(x > 0xF for x in m[7:15]):
            raise ElekError('message %d: a nibble field over 0xF' % n)
        if _value(nib) != FIRST + len(out):
            raise ElekError('message %d carries offset 0x%x, not 0x%x'
                            % (n, _value(nib), FIRST + len(out)))
        d = _dec87(m[15:-1])
        if not 0 < len(d) <= CHUNK or (len(d) < CHUNK and n != len(data) - 1):
            raise ElekError('message %d carries %d bytes' % (n, len(d)))
        if packet_checksum(d, nib) != (m[7] << 4 | m[8]):
            raise ElekError('message %d fails its checksum' % n)
        out += d
    if _value(end[7:13]) != len(out):
        raise ElekError('the end marker says %d bytes, the messages carry %d'
                        % (_value(end[7:13]), len(out)))
    return dev, bytes(out)


# ---- the ELUP card file -------------------------------------------------------------

def _rot16(v):
    return ((v << 16) | (v >> 16)) & M32


def _bswap(v):
    return struct.unpack('<I', struct.pack('>I', v))[0]


def _cipher(k, p):
    if not k & 0x800000:
        return _rot16(p ^ k ^ MIX_A) ^ XOR_A
    return _bswap(p ^ k ^ MIX_B) ^ XOR_B


def _plain(k, c):
    if not k & 0x800000:
        return (k ^ MIX_A ^ _rot16(c ^ XOR_A)) & M32
    return (k ^ MIX_B ^ _bswap(c ^ XOR_B)) & M32


def encode_bin(container, seed):
    body = container + bytes(-len(container) % 4)
    plain = struct.unpack('>%dI' % (1 + len(body) // 4), struct.pack('>I', len(body)) + body)
    out, k, acc = [], seed, 0
    for p in plain:
        c = _cipher(k, p)
        out.append(c)
        acc = (acc + p) & M32
        k = c
    out.append(_cipher(k, acc))
    return BIN_MAGIC + struct.pack('>I', seed) + struct.pack('>%dI' % len(out), *out)


def decode_bin(raw):
    """-> (seed, container padded to 4). Checks the checksum; raises ElekError."""
    if raw[:4] != BIN_MAGIC or len(raw) % 4 or len(raw) < 16:
        raise ElekError('not an ELUP card file')
    w = struct.unpack('>%dI' % (len(raw) // 4), raw)
    seed, k, acc, plain = w[1], w[1], 0, []
    for c in w[2:-1]:
        p = _plain(k, c)
        plain.append(p)
        acc = (acc + p) & M32
        k = c
    if _plain(k, w[-1]) != acc:
        raise ElekError('the card file fails its checksum')
    pb = struct.pack('>%dI' % len(plain), *plain)
    n = struct.unpack('>I', pb[:4])[0]
    if n != len(pb) - 4:
        raise ElekError('the card file declares %d bytes and carries %d' % (n, len(pb) - 4))
    return seed, pb[4:]


# ---- the container ----------------------------------------------------------------------

class ElekFile:
    """A parsed Octatrack-family OS file, from its .syx or its .bin."""

    def __init__(self, raw):
        self.raw = bytes(raw)
        self.sha256 = sha(self.raw)
        if self.raw[:4] == BIN_MAGIC:
            self.kind = 'bin'
            self.seed, cont = decode_bin(self.raw)
            self.device_id = None
        else:
            self.kind = 'syx'
            self.device_id, cont = decode_syx(self.raw)
            self.seed = None
        if cont[:4] != MAGIC or len(cont) < SECT + 8:
            raise ElekError('no ELEK container')
        n, s = struct.unpack_from('>II', cont, SECT)
        if SECT + 8 + n > len(cont):
            raise ElekError('the section runs past the container')
        stream = cont[SECT + 8:SECT + 8 + n]
        if sum(stream) & M32 != s:
            raise ElekError('the section fails its byte sum')
        self.container = cont
        self.header = cont[:SECT]
        self.stored = {3: cont[SECT:SECT + 8 + n]}
        self.tail = cont[SECT + 8 + n:]
        self.table = [(3, SECT, 8 + n, 0)]

    @classmethod
    def load(cls, path):
        with open(path, 'rb') as fh:
            return cls(fh.read())

    @property
    def build(self):
        return self.header[4:8].decode('ascii', 'replace')

    @property
    def version(self):
        return self.header[VERSION[0]:VERSION[1]].decode('ascii', 'replace').strip()

    def section(self, sid):
        if sid != 3:
            raise ElekError('an ELEK container has one section, the main OS')
        return elz.depack_section(self.stored[3])


def version_field(dev, version):
    """-> the header's 10 version bytes: right-justified, padded with spaces."""
    v = version.encode('ascii')
    if not 0 < len(v) <= dev.version_len:
        raise ElekError('the version is 1 to %d ASCII characters' % dev.version_len)
    return v.rjust(dev.version_len, b' ')


def container(stock, stored_main, dev, version=None):
    """-> the ELEK container: `stock`'s header (its version field set to
    `version`, if given), the new section, padding to an even length."""
    head = bytearray(stock.header)
    if version is not None:
        head[VERSION[0]:VERSION[1]] = version_field(dev, version)
    cont = bytes(head) + bytes(stored_main)
    return cont + bytes(len(cont) % 2)


def write(stock, stored_main, dev, version=None, seed=None):
    """-> {'syx': bytes, 'bin': bytes}: `stock` with the main OS replaced."""
    cont = container(stock, stored_main, dev, version)
    dev_id = stock.device_id if stock.device_id is not None else dev.sysex_id
    if seed is None:
        seed = stock.seed if stock.seed is not None else 0x2F1349D2
    return {'syx': encode_syx(cont, dev_id), 'bin': encode_bin(cont, seed)}


def verify(outputs, stock, want_main, dev, stock_main, version=None):
    """Refuse (ElekError) unless every output is `stock` with only the main
    OS (and the version field) changed, the main OS depacks to `want_main`,
    and the protected ranges are stock's. -> facts."""
    o = ElekFile(outputs['syx'])            # every message, checksum, offset
    if o.device_id != dev.sysex_id:
        raise ElekError('device id 0x%02x, not 0x%02x' % (o.device_id, dev.sysex_id))
    hd = [i for i in range(SECT) if o.header[i] != stock.header[i]]
    if any(not VERSION[0] <= i < VERSION[1] for i in hd):
        raise ElekError('the ELEK header differs outside the version field: %s' % hd)
    if version is not None and o.header[VERSION[0]:VERSION[1]] != version_field(dev, version):
        raise ElekError('the version field is %r, not %r' % (o.version, version))
    if any(o.tail) or len(o.container) % 2:
        raise ElekError('the container\'s padding is not zeros to an even length')
    img = o.section(3)
    if img != bytes(want_main):
        raise ElekError('the main OS does not depack to the patched image')
    for lo, hi, why in dev.protected:
        a, b = lo - dev.main_load, hi - dev.main_load
        if img[a:b] != stock_main[a:b]:
            raise ElekError('0x%08x-0x%08x (%s) is not stock' % (lo, hi, why))
    budget = dev.flash_limit - dev.flash_at
    if len(o.container) > budget:
        raise ElekError('the container is %d bytes; the OS region in flash holds %d'
                        % (len(o.container), budget))
    facts = {'sha256': sha(outputs['syx']), 'bytes': len(outputs['syx']),
             'messages': outputs['syx'].count(b'\xf7'), 'container_len': len(o.container),
             'flash_end': '0x%06x' % (dev.flash_at + len(o.container)),
             'flash_headroom': budget - len(o.container), 'version': o.version,
             'main': {'section': 3, 'stored': len(o.stored[3]), 'image': len(img),
                      'sha256': sha(img), 'inplace_min_gap': None,
                      'inplace': 'not simulated: where the bootloader unpacks from is unknown'},
             'untouched': ['the container header but for the version'] +
                          ['%s (0x%08x-0x%08x)' % (why, lo, hi) for lo, hi, why in dev.protected],
             'sections': {'3': {'stored': len(o.stored[3]), 'stored_sha256': sha(o.stored[3]),
                                'stock': False}}}
    if 'bin' in outputs:
        seed, cont = decode_bin(outputs['bin'])
        if cont != o.container + bytes(-len(o.container) % 4):
            raise ElekError('the card file does not carry the same container as the .syx')
        facts['bin'] = {'sha256': sha(outputs['bin']), 'bytes': len(outputs['bin']),
                        'seed': '0x%08x' % seed}
    return facts


def pack_main(image):
    return aplib.pack_section(bytes(image))
