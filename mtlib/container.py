"""ELE3 firmware container: parse, rebuild, checksums, HMAC trailer."""

import hashlib
import hmac

PREAMBLE = 8            # [u32 container length][u32 content checksum]
MAGIC = b'ELE3'
COUNT_OFF = 0x1C
TABLE_OFF = 0x20
ENTRY_SZ = 16
ALIGN = 16
DIGEST_LEN = 32

# The key-derivation material sits right after this constant inside the
# decompressed MAIN OS (it is the tail of the firmware's own SHA-256 table).
KEY_ANCHOR = bytes((0xbe, 0xf9, 0xa3, 0xf7, 0xc6, 0x71, 0x78, 0xf2))
KEY_STR_MAX = 64


def _be32(b, o):
    return int.from_bytes(b[o:o + 4], 'big')


def content_checksum(container):
    """Sum over big-endian words of (index+1) XOR word. Not a CRC."""
    acc = 0
    for k in range(len(container) // 4):
        acc = (acc + ((k + 1) ^ _be32(container, 4 * k))) & 0xFFFFFFFF
    return acc


def parse(stream):
    """Decoded SysEx stream -> dict describing the container."""
    if len(stream) < PREAMBLE + TABLE_OFF:
        raise ValueError('stream too short')
    declared = _be32(stream, 0)
    blob = stream[PREAMBLE:PREAMBLE + declared]
    if blob[:4] != MAGIC:
        raise ValueError('no ELE3 magic - not this firmware format')
    n = _be32(blob, COUNT_OFF)
    if not 1 <= n <= 16:
        raise ValueError('implausible section count: %d' % n)
    secs = []
    for s in range(n):
        e = TABLE_OFF + s * ENTRY_SZ
        secs.append(dict(index=s, id=_be32(blob, e), off=_be32(blob, e + 4),
                         size=_be32(blob, e + 8), attr=_be32(blob, e + 12)))
    return dict(declared=declared, blob=blob, sections=secs,
                version=blob[8:16].decode('latin1').strip('\0'))


def find_key(buffers, message, expect):
    """Recover the trailer key from material inside the firmware itself.

    The material is a printable string followed by a 32-byte constant, sitting
    right after a known anchor. It is not always in the same section, so every
    decompressed section is searched. key = sha256(s) ^ sha256(reverse(s)) ^ c,
    accepted only once its HMAC reproduces the stored digest.
    """
    if isinstance(buffers, (bytes, bytearray)):
        buffers = [buffers]
    for buf in buffers:
        i = buf.find(KEY_ANCHOR)
        while i >= 0:
            s = i + len(KEY_ANCHOR)
            p = s
            while p < len(buf) and 0x20 <= buf[p] < 0x7F and p - s < KEY_STR_MAX:
                p += 1
            if p > s and p < len(buf) and buf[p] == 0 and p + 1 + 32 <= len(buf):
                text = buf[s:p]
                const = buf[p + 1:p + 33]
                h = hashlib.sha256(text).digest()
                hr = hashlib.sha256(text[::-1]).digest()
                key = bytes(a ^ b ^ c for a, b, c in zip(h, hr, const))
                if hmac.compare_digest(hmac.new(key, message, hashlib.sha256).digest(), expect):
                    return key
            i = buf.find(KEY_ANCHOR, i + 1)
    return None


def rebuild(info, replacements, key):
    """New container blob with the given sections replaced (id -> stored bytes)."""
    blob, secs = info['blob'], info['sections']
    first = min(s['off'] for s in secs)
    out = bytearray(blob[:first])
    order = sorted(range(len(secs)), key=lambda i: secs[i]['off'])
    pos = first
    for i in order:
        sec = secs[i]
        data = replacements.get(sec['id'], blob[sec['off']:sec['off'] + sec['size']])
        pos = (pos + ALIGN - 1) & ~(ALIGN - 1)
        if len(out) < pos:
            out += b'\0' * (pos - len(out))
        out[pos:pos + len(data)] = data
        e = TABLE_OFF + sec['index'] * ENTRY_SZ
        out[e + 4:e + 8] = pos.to_bytes(4, 'big')
        out[e + 8:e + 12] = len(data).to_bytes(4, 'big')
        pos += len(data)
    end = pos
    hmac_off = (end + 4 + ALIGN - 1) & ~(ALIGN - 1)
    if len(out) < hmac_off:
        out += b'\0' * (hmac_off - len(out))
    digest = hmac.new(key, bytes(out[:hmac_off]), hashlib.sha256).digest()
    out[hmac_off:hmac_off + DIGEST_LEN] = digest
    return bytes(out[:hmac_off + DIGEST_LEN])


def build_stream(blob, pad_to):
    """Container blob -> decoded SysEx stream, padded to a whole number of packets."""
    stream = bytearray(PREAMBLE)
    stream[0:4] = len(blob).to_bytes(4, 'big')
    stream[4:8] = content_checksum(blob).to_bytes(4, 'big')
    stream += blob
    if len(stream) % pad_to:
        stream += b'\0' * (pad_to - len(stream) % pad_to)
    return bytes(stream)
