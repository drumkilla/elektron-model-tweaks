"""Elektron OS-update SysEx transport: 7-bit packing, per-packet checksums.

The payload is packed MSB-first: every group of 7 data bytes becomes 8 SysEx
bytes, the first carrying the high bit of each of the following seven.
"""

ELEKTRON = b'\x00\x20\x3c'
MSG_LEN = 128
PAYLOAD_OFF = 10
PAYLOAD_END = 126
CS_OFF = 126
BYTES_PER_MSG = 101          # 116 packed bytes -> 101 plain bytes
START_SEQ = 114

# product id -> (name, device byte, mask seed V, checksum base C0)
PRODUCTS = {
    0x11: ('Model:Cycles', 0x0C, 0x3A, 0x22),
    0x0F: ('Model:Samples', 0x0A, 0x3C, 0x1E),
}


def unpack7(p):
    out = bytearray()
    for i in range(0, len(p), 8):
        hi = p[i]
        for k in range(7):
            if i + 1 + k >= len(p):
                break
            out.append(((hi << (k + 1)) & 0x80) | p[i + 1 + k])
    return bytes(out)


def pack7(b):
    out = bytearray()
    for i in range(0, len(b), 7):
        chunk = b[i:i + 7]
        hi = 0
        for k, v in enumerate(chunk):
            hi |= (v >> 7) << (6 - k)
        out.append(hi)
        out.extend(v & 0x7F for v in chunk)
    return bytes(out)


def _mask(V):
    return [(V - i) & 0x3F for i in range(MSG_LEN)]


def checksum(msg, V, C0):
    m = _mask(V)
    return (C0 - sum(msg[i] ^ m[i] for i in range(8, 126))) & 0x7F


def _split(raw):
    msgs, i = [], 0
    while True:
        a = raw.find(0xF0, i)
        if a < 0:
            break
        b = raw.find(0xF7, a)
        if b < 0:
            break
        msgs.append(raw[a:b + 1])
        i = b + 1
    return msgs


def _u21(b):
    return (b[0] << 14) | (b[1] << 7) | b[2]


def _p21(v):
    return bytes(((v >> 14) & 0x7F, (v >> 7) & 0x7F, v & 0x7F))


def unwrap(raw):
    """SysEx file bytes -> (decoded stream, info). Validates every checksum."""
    msgs = _split(raw)
    if len(msgs) < 3:
        raise ValueError('not an Elektron SysEx file: too few messages')
    head, tail, data = msgs[0], msgs[-1], msgs[1:-1]
    if head[1:4] != ELEKTRON or tail[1:4] != ELEKTRON:
        raise ValueError('not an Elektron SysEx file')
    prod = head[4]
    if prod not in PRODUCTS:
        raise ValueError('unknown product id 0x%02x' % prod)
    name, dev, V, C0 = PRODUCTS[prod]
    if head[6:8] != b'\x7f\x01' or tail[6:8] != b'\x7f\x02':
        raise ValueError('start/end markers missing')
    start, count = _u21(head[9:12]), _u21(head[12:15])
    if count != len(data):
        raise ValueError('marker declares %d messages, found %d' % (count, len(data)))
    body = bytearray()
    for n, m in enumerate(data):
        if len(m) != MSG_LEN:
            raise ValueError('message %d: length %d' % (n, len(m)))
        if m[CS_OFF] != checksum(m, V, C0):
            raise ValueError('message %d: checksum mismatch' % n)
        body += unpack7(m[PAYLOAD_OFF:PAYLOAD_END])
    return bytes(body), dict(product=prod, name=name, start_seq=start, count=count)


def wrap(body, product, start_seq=START_SEQ):
    """Inverse of unwrap. len(body) must be a multiple of BYTES_PER_MSG."""
    name, dev, V, C0 = PRODUCTS[product]
    if len(body) % BYTES_PER_MSG:
        raise ValueError('body length must be a multiple of %d' % BYTES_PER_MSG)
    count = len(body) // BYTES_PER_MSG
    pre = b'\xf0' + ELEKTRON + bytes((product, 0x00))
    out = bytearray()
    out += pre + b'\x7f\x01' + bytes((dev,)) + _p21(start_seq) + _p21(count) + b'\xf7'
    for n in range(count):
        seq = start_seq + n
        m = bytearray(pre + b'\x7e\x00' + bytes((seq >> 7, seq & 0x7F)))
        m += pack7(body[n * BYTES_PER_MSG:(n + 1) * BYTES_PER_MSG])
        m.append(0)
        m.append(0xF7)
        m[CS_OFF] = checksum(m, V, C0)
        out += m
    out += pre + b'\x7f\x02' + bytes((dev,)) + _p21(start_seq) + _p21(count) + b'\xf7'
    return bytes(out)
