"""aPLib-variant codec, only as much as patching needs.

The section stream is an interlaced Elias-gamma bit stream of two op kinds:
a literal byte, or a match copying `n` bytes from `off` back in the output.

Recompressing 1.7 MB from scratch in Python would be slow and would gain
nothing, so instead the original stream is decoded into its op list and then
re-encoded verbatim. Only ops whose output - or, for a match, whose source -
touches a patched byte are replaced by literals. Everything else is emitted
exactly as it came in, so the result stays as tight as the vendor's own
packer and takes a couple of seconds.
"""

SECT_HDR = 8
OFFSET_BIAS = 767
REUSE_GAMMA = 2
FAR_THRESHOLD = 3328
END_GAMMA = 0x1000002          # (END_GAMMA << 8) + 0xFF wraps to OFFSET_BIAS

LITERAL, MATCH = 1, 0


class _Reader:
    def __init__(self, src, pos):
        self.src, self.ip, self.tag = src, pos, 0

    def bit(self):
        self.tag <<= 1
        if (self.tag & 0xFF) == 0:
            by = self.src[self.ip]
            self.ip += 1
            self.tag = (by << 1) | 1
            return (by >> 7) & 1
        return (self.tag >> 8) & 1

    def gamma(self):
        v = 1
        while True:
            v = (v << 1) + self.bit()
            if self.bit():
                return v
            if v > 0x02000000:
                raise ValueError('corrupt stream: gamma overflowed')


def depack(stream):
    """stream = section bytes including the 8-byte header.

    Returns (data, ops) where ops is a list of (kind, out_pos, off, n).
    """
    if len(stream) < SECT_HDR:
        raise ValueError('section shorter than its header')
    r = _Reader(stream, SECT_HDR)
    out = bytearray()
    ops = []
    last_off = 1
    while True:
        if r.bit():
            ops.append((LITERAL, len(out), 0, 1))
            out.append(stream[r.ip])
            r.ip += 1
            continue
        g = r.gamma()
        if g == REUSE_GAMMA:
            off = last_off
        else:
            off = ((g << 8) + stream[r.ip]) & 0xFFFFFFFF
            r.ip += 1
            if off == OFFSET_BIAS:
                break
            off -= OFFSET_BIAS
            last_off = off
        sl = 2 * r.bit() + r.bit()
        L = sl if sl else r.gamma() + 2
        if off > FAR_THRESHOLD:
            L += 1
        n = L + 1
        if off == 0 or off > len(out):
            raise ValueError('corrupt stream: offset past the output')
        ops.append((MATCH, len(out), off, n))
        src = len(out) - off
        if off >= n:
            out += out[src:src + n]
        else:                                   # overlapping run
            for k in range(n):
                out.append(out[src + k])
    return bytes(out), ops


class _Writer:
    __slots__ = ('o', 'tagpos', 'tagbits')

    def __init__(self):
        self.o = bytearray(SECT_HDR)
        self.tagpos = -1
        self.tagbits = 0

    def bit(self, v):
        if self.tagbits == 0:
            self.tagpos = len(self.o)
            self.o.append(0)
            self.tagbits = 8
        if v:
            self.o[self.tagpos] |= 1 << (self.tagbits - 1)
        self.tagbits -= 1

    def gamma(self, v):
        for i in range(v.bit_length() - 2, -1, -1):
            self.bit((v >> i) & 1)
            self.bit(1 if i == 0 else 0)

    def literal(self, b):
        self.bit(1)
        self.o.append(b)

    def match(self, off, n, last_off):
        self.bit(0)
        if off == last_off:
            self.gamma(REUSE_GAMMA)
        else:
            raw = off + OFFSET_BIAS
            self.gamma(raw >> 8)
            self.o.append(raw & 0xFF)
        base = n - 1 - (1 if off > FAR_THRESHOLD else 0)
        if base <= 3:
            self.bit(base >> 1)
            self.bit(base & 1)
        else:
            self.bit(0)
            self.bit(0)
            self.gamma(base - 2)

    def end(self):
        self.bit(0)
        self.gamma(END_GAMMA)
        self.o.append(0xFF)


def repack(data, ops, dirty):
    """Re-encode `ops` against patched `data`.

    `dirty` is a bytearray of len(data), 1 where a byte was changed. Ops that
    read or write a changed byte become literals; the rest are copied through.
    """
    w = _Writer()
    last_off = 1
    lo = dirty.find(b'\x01')
    hi = dirty.rfind(b'\x01')
    if lo < 0:
        lo = hi = -1
    for kind, pos, off, n in ops:
        if kind == LITERAL:
            w.literal(data[pos])
            continue
        end = pos + n
        src = pos - off
        touched = False
        if lo >= 0 and src <= hi and end > lo:
            touched = (dirty.find(b'\x01', pos, end) >= 0 or
                       dirty.find(b'\x01', src, src + n) >= 0)
        if touched:
            for k in range(pos, end):
                w.literal(data[k])
        else:
            w.match(off, n, last_off)
            last_off = off
    w.end()
    body = w.o
    stream_len = len(body) - SECT_HDR
    body[0:4] = stream_len.to_bytes(4, 'big')
    body[4:8] = (sum(body[SECT_HDR:]) & 0xFFFFFFFF).to_bytes(4, 'big')
    return bytes(body)
