# SPDX-License-Identifier: GPL-2.0-or-later
# Vendored from digikit (https://github.com/m-dwyer/digikit), dt2/elz.py,
# under the GNU GPL version 2 or (at your option) any later version. By Em D. See NOTICE.
"""Decoder for the LZ codec used in Elektron ELE3 firmware sections.

Brought in from Em's sharc-spec work (fw/elz.py) on 2026-09-15.
emu/extract.py uses it by default. It matches the device's own depacker byte
for byte on every packed section of Digitakt II 1.15C and Digitone II 1.10E,
and it also reads 1.16 and 1.11, whose depacker the Unicorn path cannot use.

Format reference: mischa85/elektron-firmware-tool (MIT, (c) 2026 Marcel Bierling),
aplib.c `ap_depack`; this is a separate Python implementation of that format:

  * a section is [u32 BE stream length][u32 BE byte sum] + stream (+ zero padding);
  * control bits are read MSB first from tag bytes fetched on demand;
    1 = literal byte, 0 = match;
  * a match begins with an interlaced Elias-gamma g (data bit, then a stop bit:
    1 stops). g == 2 reuses the last offset; otherwise raw = (g << 8) + byte,
    raw == 767 ends the stream, and offset = raw - 767 (32-bit arithmetic);
  * two bits give a short length 1..3; 00 means gamma + 2 follows. Past offset
    3328 the length gains 1. The copy count is length + 1.
"""
import struct

BIAS = 767
REUSE = 2
FAR = 3328


class Bits:
    def __init__(self, data, pos, end):
        self.d, self.p, self.end = data, pos, end
        self.tag = 0

    def byte(self):
        if self.p >= self.end:
            raise EOFError
        v = self.d[self.p]
        self.p += 1
        return v

    def bit(self):
        self.tag = (self.tag << 1) & 0x1FF
        if self.tag & 0xFF == 0:
            b = self.byte()
            self.tag = (b << 1) | 1
            return b >> 7
        return self.tag >> 8

    def gamma(self):
        v = 1
        while True:
            v = (v << 1) | self.bit()
            if self.bit():
                return v
            if v > 0x02000000:
                raise ValueError("gamma overflow")


def depack(data, pos, end):
    """Return (output bytes, input position after the end marker)."""
    s = Bits(data, pos, end)
    out = bytearray()
    last = 1
    while True:
        if s.bit():
            out.append(s.byte())
            continue
        g = s.gamma()
        if g == REUSE:
            off = last
        else:
            raw = ((g << 8) + s.byte()) & 0xFFFFFFFF
            if raw == BIAS:
                return bytes(out), s.p
            off = (raw - BIAS) & 0xFFFFFFFF
            last = off
        short = 2 * s.bit() + s.bit()
        length = short if short else s.gamma() + 2
        if off > FAR:
            length += 1
        if off == 0 or off > len(out):
            raise ValueError(f"offset {off} outside {len(out)} bytes of output")
        for _ in range(length + 1):
            out.append(out[-off])


def depack_section(stream):
    """Depack a section that starts with its [u32 length][u32 sum] header.

    -> bytes. Raises ValueError when the end marker does not land exactly on
    the declared stream length.
    """
    length = struct.unpack_from(">I", stream, 0)[0]
    out, end = depack(stream, 8, 8 + length)
    if end != 8 + length:
        raise ValueError("end marker at %d of %d stream bytes" % (end - 8, length))
    return bytes(out)
