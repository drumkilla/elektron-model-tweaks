# SPDX-License-Identifier: GPL-2.0-or-later
# Vendored from digikit (https://github.com/m-dwyer/digikit), dt2/aplib.py,
# under the GNU GPL version 2 or (at your option) any later version. By Em D; the match-finder and the compressed output by irpina. The module's __main__, which needs the emulator, is left out. See NOTICE.
"""An encoder for this firmware's aPLib-shaped container streams.

Byte-exact compression was never the requirement: the device's own depacker
(emu/oracle.py:depack, 0x80000432; the updater carries an identical copy at
0x80005710, see emu/extract.py) accepts any stream that is a *valid*
encoding of the bytes it should produce -- nothing anywhere in the acceptance
path hashes or compares the compressed bytes, only the decompressed result.
So this module began as store-only, every byte a literal, which is still
what `compress=False` does and is still sufficient for correctness. It makes
the output about 12.5% *larger* than the input: one extra tag byte per 8
literal bytes, plus a ~16-byte terminator.

What that costs is size, and size was the last untested risk before
flashing -- a rebuilt image 2.7x the original, handed to an updater whose
limits nobody knows. So `compress=True` (the default) now runs a real match
finder as well, emitting the LZ events the format already defines and this
module already documents below. It is not aPLib-compatible output and does
not try to be; it is a valid stream for *this* depacker. Every section of
Digitakt_OS1.53 round-trips byte-identically through dt2/elz.py, checked
per section before any size is looked at, because a smaller stream that
decodes to different bytes would be worse than a large one.

WHAT WAS EMPIRICALLY CONFIRMED, by single-stepping the real depacker under
Unicorn (see the disassembly at 0x80000432 in section 2 -- 354 bytes, one
`rts`) and cross-checking every claim below against emu/oracle.py:depack() on
hand-built streams:

  * The 8-byte section header ([u32 compressed_len][u32 byte_sum], big
    endian, sum over the bytes following the header) is skipped unconditionally
    (`addq.l #8,a0`) by the depacker itself. This module does not re-derive
    that convention -- it was already established by dt2/container.py and
    emu/extract.py -- but every round-trip below exercises it.

  * Tag bits are read MSB-first from a byte, refilled one byte at a time, via
    a classic "sentinel bit" shift register (not a separate bit counter).

  * LITERAL is tag bit **1** followed by one raw byte, copied straight to the
    output. This is the *opposite* polarity of the public aPLib reference
    (where 0 = literal) -- confirmed by single-stepping: the branch that does
    `move.b (a0),(a1)` and loops is the one taken when the extracted bit is 1.

  * Tag bit **0** enters a match path: an aPLib-style "gamma2" code is read
    (result=1; repeat result=result*2+databit until a raw stop-bit is seen).
    That much is confirmed. Two things about it are NOT fully reverse
    engineered, because this module never needs to emit a real match:
      - the stop-bit's polarity is INVERTED relative to the public reference
        (confirmed empirically: the loop keeps going while the raw bit is 0,
        and stops when the raw bit is 1);
      - what the gamma result and a following raw byte become (an LZ77
        offset, almost certainly) and how length is then coded, was traced
        only far enough to find the one thing this module actually uses --
        see below. The full match format is NOT documented here and this
        module cannot decode or emit one.

  * There is NO "first byte is always a literal" special case (the public
    aPLib reference has one; this device's routine does not). Confirmed
    because an all-terminator stream (no literals at all) round-trips to
    b'' -- see _self_test().

  * END OF STREAM was the hard part, and what was found is worth flagging
    clearly: the *only* branch in the whole 354-byte routine that reaches its
    epilogue (`movem.l (a7),d2-d5/a2; rts`) is
        cmpi.l #$2ff,d3 ; beq.w <epilogue>
    where d3 was *just* computed, on the "not a short 2-code" match path, as
    `(gamma_result << 8) + next_raw_byte` (confirmed by breakpointing that
    exact instruction and sweeping gamma_result/byte combinations). That
    formula's smallest possible value is 3*256+0 = 768 -- it can never
    naturally land on 0x2FF (767). This module's terminator exploits 32-bit
    wraparound instead: it gamma-codes the value 2**24 + 2 with a trailing
    byte of 0xFF, so (2**24+2)*256 + 255 == 0x2FF (mod 2**32) exactly. That
    branch has no side effects on the destination pointer, so it cleanly ends
    the stream after any run of literals, and it was verified against the
    real depacker for every case in _self_test() and every extracted section
    (see this file's __main__). Whether Elektron's own encoder ends its
    streams the same way is NOT known -- a real compressed stream is not
    available to compare against (only decompressed sections are, in
    sections/) -- so this is flagged as found-but-unexplained, not assumed.

Everything in the module docstring above is a hypothesis this module tests
against the real device, not documentation trusted on faith: run this file's
__main__ against a sections/ directory to see it re-confirmed.
"""
import struct

REUSE = 2      # dt2/elz.py: a gamma of 2 reuses the last offset


def _gamma_bits(value):
    """MSB-first bit sequence this depacker's gamma2 reader would consume to
    decode to `value` (excluding the implicit leading 1): for each bit of
    `value` after its leading 1, emit that bit, then a raw stop-bit (1 on the
    last one, 0 otherwise) -- the inverted-continue polarity confirmed above.
    """
    if value < 2:
        raise ValueError('gamma2 cannot encode values below 2, got %d' % value)
    tail = bin(value)[3:]  # binary digits after the leading '1'
    out = []
    for i, ch in enumerate(tail):
        out.append(int(ch))
        out.append(1 if i == len(tail) - 1 else 0)
    return out


# The terminator: a match dispatch (tag bit 0) whose gamma-coded value is
# 2**24 + 2, followed by one raw byte 0xFF. See the module docstring for why.
_TERMINATOR_GAMMA_VALUE = (1 << 24) + 2
_TERMINATOR_TRAILER_BYTE = 0xFF


# Match coding, read off dt2/elz.py's decoder. See this patch's rationale in
# the git history; the constants are that decoder's.
_BIAS = 767              # offset = ((g << 8) + byte) - 767
_FAR = 3328              # past this, the decoder adds 1 to the length
_MIN_MATCH = 3           # below this a match costs more bits than literals
_MAX_OFFSET = 1 << 16    # further back only makes the gamma longer
_MAX_COUNT = 1 << 12     # long enough for any run worth coding in one match


def _match_events(offset, count):
    """-> events for one back-reference: copy `count` bytes from `offset` back.

    Raises rather than emitting something the decoder would read differently,
    because a silently wrong match produces a stream that depacks to the wrong
    bytes and nothing downstream compares compressed bytes.
    """
    if not 1 <= offset <= _MAX_OFFSET:
        raise ValueError('offset %d out of range' % offset)
    length = count - 1
    if offset > _FAR:
        length -= 1          # the decoder will add it back
    if length < 1:
        raise ValueError('count %d too small for offset %d' % (count, offset))
    raw = offset + _BIAS
    g, trailer = raw >> 8, raw & 0xFF
    if g == REUSE:
        raise ValueError('offset %d would encode as the reuse code' % offset)

    out = [(0, b'')]                                   # tag bit 0: a match
    gbits = _gamma_bits(g)
    for i, bit in enumerate(gbits):                    # the offset's gamma,
        out.append((bit, bytes((trailer,))             # its raw byte riding
                    if i == len(gbits) - 1 else b''))  # the last bit
    if 1 <= length <= 3:
        out.append(((length >> 1) & 1, b''))
        out.append((length & 1, b''))
    else:
        out.append((0, b''))                           # 00: a gamma follows
        out.append((0, b''))
        for bit in _gamma_bits(length - 2):
            out.append((bit, b''))
    return out


def _find_matches(data, min_match=_MIN_MATCH, max_offset=_MAX_OFFSET,
                  max_count=_MAX_COUNT, candidates=24):
    """-> [(pos, offset, count), ...] greedy, non-overlapping, in order.

    A hash of the next three bytes to the positions they last appeared at.
    Greedy and bounded rather than optimal: this has to run over a 2.4 MB
    section, and the requirement is a smaller file, not the smallest one.
    """
    n = len(data)
    if n < min_match:
        return []
    table = {}
    out = []
    i = 0
    while i < n - min_match:
        key = data[i:i + min_match]
        best_off = best_len = 0
        chain = table.get(key)
        if chain:
            for j in reversed(chain[-candidates:]):
                off = i - j
                if off <= 0 or off > max_offset:
                    continue
                # A far offset needs one more byte to be worth coding at all.
                limit = min(max_count, n - i)
                k = 0
                while k < limit and data[j + k] == data[i + k]:
                    k += 1
                need = min_match + (1 if off > _FAR else 0)
                if k >= need and k > best_len:
                    best_off, best_len = off, k
                    if k >= 64:
                        break
        chain = table.setdefault(key, [])
        chain.append(i)
        if len(chain) > candidates:
            del chain[:-candidates]
        if best_len:
            out.append((i, best_off, best_len))
            # Index the covered positions so later matches can reach into them.
            for k in range(1, best_len):
                p = i + k
                if p < n - min_match:
                    c = table.setdefault(data[p:p + min_match], [])
                    c.append(p)
                    if len(c) > candidates:
                        del c[:-candidates]
            i += best_len
        else:
            i += 1
    return out


def _events_lz(data):
    """_events(), but emitting back-references where they pay."""
    matches = {pos: (off, count) for pos, off, count in _find_matches(data)}
    events = []
    i, n = 0, len(data)
    while i < n:
        hit = matches.get(i)
        if hit:
            off, count = hit
            events.extend(_match_events(off, count))
            i += count
        else:
            events.append((1, bytes((data[i],))))
            i += 1
    events.append((0, b''))
    gbits = _gamma_bits(_TERMINATOR_GAMMA_VALUE)
    last = len(gbits) - 1
    for k, bit in enumerate(gbits):
        events.append((bit, bytes((_TERMINATOR_TRAILER_BYTE,)) if k == last else b''))
    return events


def _events(data):
    """-> [(tag_bit, payload_bytes), ...] in stream order: one event per tag
    bit the depacker will read, paired with whatever raw bytes it reads
    immediately after that bit (empty for bits that consume none)."""
    events = [(1, bytes((b,))) for b in data]
    events.append((0, b''))                      # enter the match/terminator path
    gbits = _gamma_bits(_TERMINATOR_GAMMA_VALUE)
    last = len(gbits) - 1
    for i, bit in enumerate(gbits):
        events.append((bit, bytes((_TERMINATOR_TRAILER_BYTE,)) if i == last else b''))
    return events


def _assemble(events):
    """Pack (bit, payload) events into the tag-byte-interleaved-with-payload
    layout the depacker expects: 8 bits per tag byte, MSB first, with that
    group's payload bytes appended right after it, in event order."""
    out = bytearray()
    for i in range(0, len(events), 8):
        chunk = events[i:i + 8]
        tagbyte = 0
        payload = bytearray()
        for j, (bit, pl) in enumerate(chunk):
            tagbyte |= (bit & 1) << (7 - j)
            payload += pl
        out.append(tagbyte)
        out += payload
    return bytes(out)


def pack(data, compress=True):
    """-> a valid stream for this depacker, WITHOUT the section header.

    `compress=True` (the default) emits back-references; False keeps the
    original store-only behaviour, every byte a literal, which is always
    slightly LARGER than the input and is retained because it is the simplest
    thing that can possibly be correct and is useful when a match-finder bug
    is the thing being ruled out.
    """
    return _assemble(_events_lz(data) if compress else _events(data))


def pack_section(data, compress=True):
    """pack(data), prepended with the section's 8-byte header: big-endian
    [u32 compressed_len][u32 byte_sum], where compressed_len is the packed
    stream's length (not counting this header) and byte_sum is the plain sum,
    mod 2**32, of the packed stream's bytes. Matches the convention
    dt2/container.py and emu/extract.py already use to read sections."""
    body = pack(data, compress)
    return struct.pack('>II', len(body), sum(body) & 0xFFFFFFFF) + body


def _shadow_decode(comp):
    """A from-scratch reference decoder for ONLY the subset of the format
    this module emits -- literals, and this module's own terminator. It is
    NOT a general aPLib decompressor (it cannot decode a real match) and it
    is deliberately independent of pack()'s own bit-packing code, so that
    _self_test() below is checking two independent implementations against
    each other rather than a function against itself. The real authority is
    the device's own depacker, exercised separately in __main__.
    """
    pos = 0
    tag = 0
    bitcount = 0

    def read_byte():
        nonlocal pos
        b = comp[pos]
        pos += 1
        return b

    def getbit():
        nonlocal tag, bitcount
        if bitcount == 0:
            tag = read_byte()
            bitcount = 8
        bit = (tag >> 7) & 1
        tag = (tag << 1) & 0xFF
        bitcount -= 1
        return bit

    out = bytearray()
    while True:
        if getbit() == 1:
            out.append(read_byte())
            continue
        result = 1
        while True:
            result = (result << 1) | getbit()
            if getbit() == 1:
                break
        if result != _TERMINATOR_GAMMA_VALUE:
            raise NotImplementedError(
                'shadow decoder only understands this module\'s own '
                'terminator, not a real match (gamma result=%d)' % result)
        trailer = read_byte()
        if trailer != _TERMINATOR_TRAILER_BYTE:
            raise NotImplementedError(
                'unexpected terminator trailer byte 0x%02x' % trailer)
        break
    return bytes(out)


def _self_test():
    """Sanity checks runnable without Unicorn or any firmware: pack()'s
    bit-packing is round-tripped through an independently-written decoder
    (_shadow_decode), and pack_section()'s header arithmetic is checked
    directly. This does NOT confirm the format against the real device --
    see __main__ for that.
    """
    import os

    cases = [b'', b'A', b'AB', b'\x00', b'\xff' * 3, bytes(range(256)),
             os.urandom(500),
             # The shapes a match-finder must not get wrong: a long run, a
             # repeat just past the near/far boundary, overlapping copies,
             # and a match that reaches the very end of the input.
             b'\x00' * 5000,
             b'ab' * 4000,
             (b'x' * 4000) + (b'ab' * 100) + (b'x' * 4000),
             bytes(range(64)) * 80,
             os.urandom(64) * 60,
             b'q' + os.urandom(200) + b'q' * 64]

    # The store-only path, against the independent decoder.
    for data in cases:
        got = _shadow_decode(pack(data, compress=False))
        assert got == data, ('store', data[:16], got[:16])

    # The compressing path, against dt2/elz.py -- the decoder that matches the
    # device byte for byte on every packed section of two real firmwares.
    from .elz import depack_section
    smaller = 0
    for data in cases:
        got = depack_section(pack_section(data, compress=True))
        assert got == data, ('lz', len(data), data[:16], got[:16])
        if data and len(pack(data, compress=True)) < len(data):
            smaller += 1
    assert smaller, 'compression never actually shrank anything'

    # pack_section's header: length excludes the header, sum is over the
    # packed body only, and packing never counts as *shrinking* the input.
    data = b'roundtrip me'
    section = pack_section(data)
    ln, sm = struct.unpack_from('>II', section, 0)
    body = section[8:]
    assert ln == len(body) == len(pack(data))
    assert sm == sum(body) & 0xFFFFFFFF
    # Store-only always grows; the compressing path must not grow this much
    # either, but on twelve bytes there is nothing to find, so only the
    # store-only claim is asserted here.
    assert len(pack_section(data, compress=False)) > len(data) + 8

    print('aplib self_test OK')
