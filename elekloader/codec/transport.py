# SPDX-License-Identifier: GPL-2.0-or-later
# Vendored from digikit (https://github.com/m-dwyer/digikit), dt2/build.py (the transport encoders and checksums only),
# under the GNU GPL version 2 or (at your option) any later version. By Em D; changes by irpina. See NOTICE.
"""The SysEx transport of an Elektron OS file: 8-in-7, the 128-byte
messages with their counters and checksums, the framing messages' count,
and the container's content checksum."""
import struct

MFR = b'\x00\x20\x3c'           # Elektron's SysEx manufacturer id
FIRST_COUNTER = 242
CHUNK_SIZE = 101       # decoded bytes carried by one 128-byte message


def encode_8in7(data):
    """bytes -> 8-in-7 encoded bytes. Exact inverse of the decode loop in
    dt2/container.py:37-44: one marker byte per up-to-7 data bytes, holding
    their high bits MSB-first, followed by those bytes with the high bit
    stripped. A short final group is handled the same way as a full one."""
    out = bytearray()
    for start in range(0, len(data), 7):
        group = data[start:start + 7]
        marker = 0
        for n, b in enumerate(group):
            if b & 0x80:
                marker |= 1 << (6 - n)
        out.append(marker)
        out.extend(b & 0x7F for b in group)
    return bytes(out)


def content_checksum(container):
    """The preamble's 32-bit checksum (bytes 4..7 of the 8-byte preamble).

    Sum of (1-based word index XOR big-endian u32 word) over the whole
    container, trailer included, mod 2**32. Recovered from the bootstrap's
    own verifier at 0x80003ca6 and confirmed byte-exact against all four
    firmwares in the repo root."""
    acc = 0
    for idx in range(1, (len(container) >> 2) + 1):
        word, = struct.unpack_from('>I', container, (idx - 1) * 4)
        acc = (acc + (idx ^ word)) & 0xFFFFFFFF
    return acc


def packet_checksum(body, k):
    """Message byte 125, from the 125 bytes of header+payload before it.

    `body` is the SysEx message between F0 and F7; `k` is the transfer-type
    constant carried in the framing message (0x0F Digitakt II, 0x10
    Digitone II). Covers body[6:125] -- the 3 counter bytes plus the 116
    payload bytes. Recovered from the bootstrap at 0x80003748 and confirmed
    against 64,053 messages across four firmwares."""
    total = k
    for i in range(119):
        total += body[6 + i] ^ (i + k)
    return total & 0x7F


def _patch_framing_count(msg, n):
    """16-byte framing message -> same message with body bytes 11..13 (the
    data-message count) rewritten to `n`, 21-bit big-endian base-128.
    Verified on all four firmwares: body[7] is the transfer constant;
    body bytes 11..13 are the message count (13344, 14694, 17259, 18666)."""
    body = bytearray(msg[1:-1])
    body[11] = (n >> 14) & 0x7F
    body[12] = (n >> 7) & 0x7F
    body[13] = n & 0x7F
    return bytes([0xF0]) + bytes(body) + bytes([0xF7])


def encode_syx(stream, device_id, framing_start, framing_end, checksum=None):
    """Decoded byte stream -> .syx bytes.

    Chunks `stream` into CHUNK_SIZE (101)-byte pieces -- the amount one
    128-byte message carries, structurally, regardless of content -- 8-in-7
    encodes each into a 116-byte payload, and wraps each in the 9-byte
    header (constant fields, plus a 21-bit base-128 counter starting at
    FIRST_COUNTER) and a checksum byte, then F0/F7. `framing_start` and
    `framing_end` are the complete 16-byte messages to emit first and last,
    patched here so their message-count field (body bytes 11..13) matches
    the number of data messages actually emitted, since that count changes
    with content.

    The final chunk may be short: it is zero-padded to CHUNK_SIZE bytes.
    That padding value is an inference -- no sample file has a partial
    final chunk to confirm it against.

    `checksum(body)` computes byte 125 from the 125-byte header+payload
    that precedes it. By default this is packet_checksum() using the
    transfer-type constant taken from `framing_start`; `checksum` overrides
    this only for testing.
    """
    k = framing_start[1:-1][7]     # transfer-type const; see packet_checksum
    if checksum is None:
        checksum = lambda body: packet_checksum(body, k)

    n_msgs = (len(stream) + CHUNK_SIZE - 1) // CHUNK_SIZE
    framing_start = _patch_framing_count(framing_start, n_msgs)
    framing_end = _patch_framing_count(framing_end, n_msgs)

    out = bytearray()
    out += framing_start
    counter = FIRST_COUNTER
    for start in range(0, len(stream), CHUNK_SIZE):
        chunk = stream[start:start + CHUNK_SIZE]
        if len(chunk) < CHUNK_SIZE:
            chunk = chunk + bytes(CHUNK_SIZE - len(chunk))  # placeholder pad; see above
        payload = encode_8in7(chunk)
        b6 = (counter >> 14) & 0x7F
        b7 = (counter >> 7) & 0x7F
        b8 = counter & 0x7F
        body = MFR + bytes([device_id, 0x00, 0x7E, b6, b7, b8]) + payload
        body += bytes([checksum(body) & 0x7F])
        out.append(0xF0)
        out += body
        out.append(0xF7)
        counter += 1
    out += framing_end
    return bytes(out)
