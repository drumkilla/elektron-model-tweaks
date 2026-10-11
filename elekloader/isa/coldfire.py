# SPDX-License-Identifier: GPL-2.0-or-later
# Vendored from digikit (https://github.com/m-dwyer/digikit), emu/cfisa.py,
# under the GNU GPL version 2 or (at your option) any later version. By irpina. See NOTICE.
"""ColdFire instruction decoder: lengths, operand classes and control flow.

The emulator runs Unicorn's ColdFire V4e model, which is a superset of the
MCF5441x core: V4e has an FPU, the MCF5441x does not. A float instruction
in a custom build runs under emulation and raises a line-F exception on the
device. So anything that has to say "this would run on the hardware" must
look at the instructions themselves. That is this module's job, and also
the base of the cycle model in emu/cftiming.py.

It decodes one instruction at a time into an `Insn`: its length, an
operation key the timing tables use, the operand size, the effective-address
class of the source and destination, whether and where it transfers
control, the register it writes and the registers its address generation
reads. It covers ISA_C (the MCF5441x's revision, CFPRM: ISA_A, ISA_B,
ISA_C) plus the EMAC unit, and recognises the FPU and other line-F opcodes
well enough to report them and step over them.

Encodings are the ColdFire Family Programmer's Reference Manual's. Where
the EMAC opcodes overlap, the order below follows QEMU's ColdFire decoder
(the one Unicorn runs), in which a later, more specific pattern wins. Only
the length and the class matter here, and every overlapping pair has the
same length.

Nothing here reads guest memory itself: `decode(read16, addr)` takes a
callable that returns the big-endian 16-bit word at a byte offset from
`addr`, so it runs on a firmware image, a bytes object or live guest memory
alike.
"""
from typing import NamedTuple

# Effective-address classes, the columns of the MCF54418RM timing tables
# (section 3.3.5). PC-relative modes share their An-relative column, as the
# manual says they do.
R, IND, POST, PRE, D16, IDX, ABS, IMM, NONE = range(9)
EA_NAMES = ('Rn', '(An)', '(An)+', '-(An)', '(d16,An)', '(d8,An,Xi)',
            'xxx.wl', '#imm', '-')

# Control flow of the instruction.
F_NONE, F_BCC, F_BRA, F_BSR, F_JMP, F_JSR, F_RTS, F_RTE, F_TRAP = range(9)

# Flags.
FPU = 1          # a float instruction: the MCF5441x has no FPU (line F)
LINEF = 2        # any other line-F opcode the core does not implement
ILLEGAL = 4      # not a ColdFire ISA_C / EMAC instruction at all
PRIV = 8         # supervisor-only
MOVEC = 16       # MOVEC: Unicorn aborts on some; the harness intercepts
EMAC_OP = 32     # a MAC/MSAC or an EMAC load (for the store-after-MAC stall)
PCREL = 64       # the EA is PC-relative

# Address-generation uses, for the pipeline stall rule of 3.3.5.1 (3).
BASE, INDEX1, INDEXN = 1, 2, 3


class Insn(NamedTuple):
    length: int
    op: str
    size: int = 0           # operand bytes: 1, 2, 4, or 0
    src: int = NONE
    dst: int = NONE
    flow: int = F_NONE
    target: object = None   # static branch target, when there is one
    writes: int = -1        # register number written (D0-D7 0-7, A0-A7 8-15)
    agen: tuple = ()        # ((reg, BASE|INDEX1|INDEXN), ...)
    flags: int = 0
    extra: int = 0          # op-specific: MOVEM register count, cache field,
                            # MOVE #imm,SR immediate, trap number


def _s16(v):
    return v - 0x10000 if v & 0x8000 else v


def _s8(v):
    return v - 0x100 if v & 0x80 else v


def _s32(v):
    return v - 0x100000000 if v & 0x80000000 else v


class _Bad(Exception):
    pass


def _ea(mode, reg, size, read16, pos):
    """-> (class, extension bytes, agen, flags) of one effective address.

    `pos` is the byte offset of the EA's first extension word. `size` is
    the immediate's operand size in bytes (1 and 2 take one word).
    """
    if mode == 0 or mode == 1:
        return R, 0, (), 0
    if mode == 2:
        return IND, 0, ((8 + reg, BASE),), 0
    if mode == 3:
        return POST, 0, ((8 + reg, BASE),), 0
    if mode == 4:
        return PRE, 0, ((8 + reg, BASE),), 0
    if mode == 5:
        return D16, 2, ((8 + reg, BASE),), 0
    if mode == 6:
        ext = read16(pos)
        if ext & 0x0100:
            raise _Bad('full-format extension word')   # not on ColdFire
        xi, scale = ext >> 12, (ext >> 9) & 3
        return IDX, 2, ((8 + reg, BASE),
                        (xi, INDEX1 if scale == 0 else INDEXN)), 0
    # mode 7
    if reg == 0:
        return ABS, 2, (), 0
    if reg == 1:
        return ABS, 4, (), 0
    if reg == 2:
        return D16, 2, (), PCREL
    if reg == 3:
        ext = read16(pos)
        if ext & 0x0100:
            raise _Bad('full-format extension word')
        xi, scale = ext >> 12, (ext >> 9) & 3
        return IDX, 2, ((xi, INDEX1 if scale == 0 else INDEXN),), PCREL
    if reg == 4:
        if size <= 0:
            raise _Bad('immediate not allowed here')
        return IMM, 4 if size == 4 else 2, (), 0
    raise _Bad('mode 7 register %d' % reg)


def _one(op, w, read16, size, *, writes_ea=False, alt=False, imm_ok=True,
         extra_words=0, flags=0, dst_side=False, extra=0):
    """An instruction with a single EA in bits 5-0 and `extra_words`
    extension words (register masks, specifiers) before the EA's own."""
    mode, reg = (w >> 3) & 7, w & 7
    if mode == 1 and alt:
        raise _Bad('An not allowed')
    cls, ext, agen, f = _ea(mode, reg, size if imm_ok else 0, read16,
                            2 + 2 * extra_words)
    writes = -1
    if writes_ea and cls == R:
        writes = (8 if mode == 1 else 0) + reg
    if dst_side:
        return Insn(2 + 2 * extra_words + ext, op, size, NONE, cls,
                    writes=writes, agen=agen, flags=flags | f, extra=extra)
    return Insn(2 + 2 * extra_words + ext, op, size, cls, NONE,
                writes=writes, agen=agen, flags=flags | f, extra=extra)


def decode(read16, addr=0):
    """-> Insn for the instruction at `addr`. Never raises for bad input:
    an opcode that is not ColdFire ISA_C/EMAC decodes as length 2 with the
    ILLEGAL flag (or FPU/LINEF for line F), which is what the core does
    with it too -- it takes an exception and never runs the next word."""
    try:
        return _decode(read16, addr)
    except (_Bad, IndexError):
        w = read16(0)
        if w >> 12 == 0xF:
            flags = FPU if (w & 0xFE00) == 0xF200 or (w & 0xFF80) == 0xF300 \
                else LINEF
            return Insn(2, 'linef', flags=flags)
        return Insn(2, 'illegal', flags=ILLEGAL)


def _decode(read16, addr):
    w = read16(0)
    line = w >> 12
    mode, reg = (w >> 3) & 7, w & 7
    dn = (w >> 9) & 7

    if line == 0:
        hi = w & 0xFFF8
        if hi in (0x0080, 0x0280, 0x0480, 0x0680, 0x0A80, 0x0C80):
            op = 'cmpi' if hi == 0x0C80 else 'alu_imm'
            return Insn(6, op, 4, IMM, R, writes=-1 if op == 'cmpi' else reg)
        if hi in (0x0C00, 0x0C40):
            return Insn(4, 'cmpi', 1 if hi == 0x0C00 else 2, IMM, R)
        if hi == 0x00C0:
            return Insn(2, 'bitrev', 4, R, R, writes=reg)
        if hi == 0x02C0:
            return Insn(2, 'byterev', 4, R, R, writes=reg)
        if hi == 0x04C0:
            return Insn(2, 'ff1', 4, R, R, writes=reg)
        if (w & 0xF100) == 0x0100:          # btst/bchg/bclr/bset Dy,<ea>
            kind = (w >> 6) & 3
            if mode == 1:
                raise _Bad('bit op on An')
            ins = _one('btst' if kind == 0 else 'bchg', w, read16,
                       4 if mode == 0 else 1, imm_ok=(kind == 0))
            return ins._replace(src=R, dst=ins.src,
                                writes=reg if (mode == 0 and kind) else -1)
        if (w & 0xFF00) == 0x0800:          # the same, #bit,<ea>
            kind = (w >> 6) & 3
            if mode == 1 or (mode == 7 and reg >= 2):
                raise _Bad('static bit op EA')
            ins = _one('btsti' if kind == 0 else 'bchgi', w, read16,
                       4 if mode == 0 else 1, extra_words=1)
            return ins._replace(src=IMM, dst=ins.src,
                                writes=reg if (mode == 0 and kind) else -1)
        raise _Bad('line 0')

    if line in (1, 2, 3):                   # MOVE.B / MOVE.L / MOVE.W
        size = {1: 1, 2: 4, 3: 2}[line]
        dmode, dreg = (w >> 6) & 7, (w >> 9) & 7
        if dmode == 1 and size == 1:
            raise _Bad('movea.b')
        scls, sext, sagen, sf = _ea(mode, reg, size, read16, 2)
        if dmode == 7 and dreg >= 2:
            raise _Bad('move destination')
        dcls, dext, dagen, df = _ea(dmode, dreg, 0, read16, 2 + sext)
        writes = -1
        if dcls == R:
            writes = (8 if dmode == 1 else 0) + dreg
        return Insn(2 + sext + dext, 'movea' if dmode == 1 else 'move', size,
                    scls, dcls, writes=writes, agen=sagen + dagen,
                    flags=sf | df)

    if line == 4:
        if (w & 0xF1C0) == 0x41C0:          # lea <ea>,An
            if mode in (0, 1, 3, 4) or (mode == 7 and reg == 4):
                raise _Bad('lea EA')
            ins = _one('lea', w, read16, 4, imm_ok=False)
            return ins._replace(dst=R, writes=8 + dn)
        if w == 0x40E7:                     # stldsr #imm (ISA_C)
            if read16(2) != 0x46FC:
                raise _Bad('stldsr')
            return Insn(6, 'stldsr', 2, IMM, NONE, flags=PRIV,
                        extra=read16(4))
        hi = w & 0xFFF8
        if hi == 0x4080:
            return Insn(2, 'negx', 4, R, R, writes=reg)
        if hi == 0x40C0:
            return Insn(2, 'move_from_sr', 2, NONE, R, writes=reg, flags=PRIV)
        if (w & 0xFFC0) in (0x4200, 0x4240, 0x4280):
            size = {0x4200: 1, 0x4240: 2, 0x4280: 4}[w & 0xFFC0]
            if mode == 1:
                raise _Bad('clr An')
            return _one('clr', w, read16, size, writes_ea=True, imm_ok=False,
                        dst_side=True)
        if hi == 0x42C0:
            return Insn(2, 'move_from_ccr', 2, NONE, R, writes=reg)
        if hi == 0x4480:
            return Insn(2, 'neg', 4, R, R, writes=reg)
        if (w & 0xFFC0) == 0x44C0:          # move <ea>,ccr
            if mode not in (0,) and not (mode == 7 and reg == 4):
                raise _Bad('move to ccr EA')
            return _one('move_to_ccr', w, read16, 2)
        if hi == 0x4680:
            return Insn(2, 'not', 4, R, R, writes=reg)
        if (w & 0xFFC0) == 0x46C0:          # move <ea>,sr
            if mode not in (0,) and not (mode == 7 and reg == 4):
                raise _Bad('move to sr EA')
            ins = _one('move_to_sr', w, read16, 2, flags=PRIV)
            return ins._replace(extra=read16(2) if ins.src == IMM else -1)
        if hi == 0x4840:
            return Insn(2, 'swap', 4, R, R, writes=reg)
        if (w & 0xFFC0) == 0x4840:          # pea <ea>
            if mode in (0, 1, 3, 4) or (mode == 7 and reg == 4):
                raise _Bad('pea EA')
            return _one('pea', w, read16, 4, imm_ok=False)
        if hi == 0x4880:
            return Insn(2, 'ext', 2, R, R, writes=reg)
        if hi == 0x48C0:
            return Insn(2, 'ext', 4, R, R, writes=reg)
        if (w & 0xFFC0) == 0x48C0:          # movem.l regs,<ea>
            if mode not in (2, 5):
                raise _Bad('movem EA')
            mask = read16(2)
            ins = _one('movem', w, read16, 4, extra_words=1, dst_side=True,
                       extra=bin(mask).count('1'))
            return ins
        if hi == 0x49C0:
            return Insn(2, 'extb', 4, R, R, writes=reg)
        if w == 0x4AC8:
            return Insn(2, 'halt', flags=PRIV)
        if w == 0x4ACC:
            return Insn(2, 'pulse')
        if w == 0x4AFC:
            return Insn(2, 'illegal', flags=ILLEGAL)
        if (w & 0xFFC0) in (0x4A00, 0x4A40, 0x4A80):
            size = {0x4A00: 1, 0x4A40: 2, 0x4A80: 4}[w & 0xFFC0]
            return _one('tst', w, read16, size)
        if (w & 0xFFC0) == 0x4AC0:
            if mode in (0, 1) or (mode == 7 and reg >= 2):
                raise _Bad('tas EA')
            return _one('tas', w, read16, 1, dst_side=True)
        if (w & 0xFFC0) == 0x4C00:          # mul{u,s}.l <ea>,Dx
            if mode == 1 or mode == 6 or (mode == 7 and reg in (0, 1, 3)):
                raise _Bad('mul.l EA')
            ext = read16(2)
            ins = _one('mul_l', w, read16, 4, extra_words=1)
            return ins._replace(dst=R, writes=(ext >> 12) & 7)
        if (w & 0xFFC0) == 0x4C40:          # div{u,s}.l / rem{u,s}.l
            if mode == 1 or mode == 6 or (mode == 7 and reg in (0, 1, 3, 4)):
                raise _Bad('div.l EA')
            ext = read16(2)
            dq, dr = (ext >> 12) & 7, ext & 7
            ins = _one('div_l', w, read16, 4, extra_words=1)
            return ins._replace(dst=R, writes=dq if dq == dr else dr)
        if hi == 0x4C80:
            return Insn(2, 'sats', 4, R, R, writes=reg)
        if (w & 0xFFC0) == 0x4CC0:          # movem.l <ea>,regs
            if mode not in (2, 5):
                raise _Bad('movem EA')
            mask = read16(2)
            return _one('movem', w, read16, 4, extra_words=1,
                        extra=bin(mask).count('1'))
        if (w & 0xFFF0) == 0x4E40:
            return Insn(2, 'trap', flow=F_TRAP, extra=w & 15)
        if hi == 0x4E50:
            return Insn(4, 'link', 4, R, NONE, writes=8 + reg,
                        agen=((15, BASE),))
        if hi == 0x4E58:
            return Insn(2, 'unlk', 4, R, NONE, writes=8 + reg)
        if hi in (0x4E60, 0x4E68):
            return Insn(2, 'move_usp', 4, R, R, flags=PRIV,
                        writes=8 + reg if hi == 0x4E68 else -1)
        if w == 0x4E71:
            return Insn(2, 'nop')
        if w == 0x4E72:
            return Insn(4, 'stop', 2, IMM, flags=PRIV, extra=read16(2))
        if w == 0x4E73:
            return Insn(2, 'rte', flow=F_RTE, flags=PRIV)
        if w == 0x4E75:
            return Insn(2, 'rts', flow=F_RTS)
        if w in (0x4E7A, 0x4E7B):
            return Insn(4, 'movec', 4, R, NONE, flags=PRIV | MOVEC,
                        extra=read16(2) & 0x0FFF)
        if (w & 0xFFC0) in (0x4E80, 0x4EC0):    # jsr / jmp <ea>
            if mode in (0, 1, 3, 4) or (mode == 7 and reg == 4):
                raise _Bad('jmp EA')
            jsr = (w & 0xFFC0) == 0x4E80
            ins = _one('jsr' if jsr else 'jmp', w, read16, 4, imm_ok=False)
            target = None
            if mode == 7 and reg == 0:
                target = _s16(read16(2)) & 0xFFFFFFFF
            elif mode == 7 and reg == 1:
                target = read16(2) << 16 | read16(4)
            elif mode == 7 and reg == 2:
                target = (addr + 2 + _s16(read16(2))) & 0xFFFFFFFF
            return ins._replace(flow=F_JSR if jsr else F_JMP, target=target)
        raise _Bad('line 4')

    if line == 5:
        if w == 0x51FA:
            return Insn(4, 'tpf')
        if w == 0x51FB:
            return Insn(6, 'tpf')
        if w == 0x51FC:
            return Insn(2, 'tpf')
        if (w & 0xF1C0) in (0x5080, 0x5180):    # addq.l / subq.l #q,<ea>
            if mode == 7 and reg >= 2:
                raise _Bad('addq EA')
            return _one('addq', w, read16, 4, writes_ea=True, dst_side=True)
        if (w & 0xF0F8) == 0x50C0:
            return Insn(2, 'scc', 1, NONE, R, writes=reg)
        raise _Bad('line 5')

    if line == 6:
        cond = (w >> 8) & 15
        d8 = w & 0xFF
        if d8 == 0:
            n, disp = 4, _s16(read16(2))
        elif d8 == 0xFF:
            n, disp = 6, _s32(read16(2) << 16 | read16(4))
        else:
            n, disp = 2, _s8(d8)
        target = (addr + 2 + disp) & 0xFFFFFFFF
        flow = F_BRA if cond == 0 else (F_BSR if cond == 1 else F_BCC)
        op = {F_BRA: 'bra', F_BSR: 'bsr', F_BCC: 'bcc'}[flow]
        return Insn(n, op, flow=flow, target=target)

    if line == 7:
        if not w & 0x0100:
            return Insn(2, 'moveq', 4, IMM, R, writes=dn)
        # MVS/MVZ take any source, An included: the Digitakt OS has
        # `mvz.w a0,d0` (0x71C8) and `mvs.w a4,d0` (0x714C).
        ss = (w >> 6) & 3
        ins = _one('mvsz', w, read16, 1 if ss in (0, 2) else 2)
        return ins._replace(dst=R, writes=dn)

    if line in (0x8, 0x9, 0xC, 0xD):
        opmode = (w >> 6) & 7
        name = {0x8: 'or', 0x9: 'sub', 0xC: 'and', 0xD: 'add'}[line]
        if opmode == 2:                     # op.l <ea>,Dn
            if mode == 1 and line in (0x8, 0xC):
                raise _Bad('and/or from An')
            ins = _one('alu_ea_r', w, read16, 4)
            return ins._replace(dst=R, writes=dn)
        if opmode == 6:                     # op.l Dn,<ea> (or addx/subx)
            if line in (0x9, 0xD) and mode == 0:
                return Insn(2, 'addx', 4, R, R, writes=dn)
            if mode in (0, 1) or (mode == 7 and reg >= 2):
                raise _Bad('op Dn,<ea> EA')
            ins = _one('alu_r_ea', w, read16, 4, dst_side=True)
            return ins._replace(src=R)
        if opmode == 7 and line in (0x9, 0xD):  # suba.l / adda.l
            ins = _one('alu_ea_r', w, read16, 4)
            return ins._replace(dst=R, writes=8 + dn)
        if opmode in (3, 7) and line == 0x8:    # divu.w / divs.w
            if mode == 1:
                raise _Bad('div.w An')
            ins = _one('div_w', w, read16, 2)
            return ins._replace(dst=R, writes=dn)
        if opmode in (3, 7) and line == 0xC:    # mulu.w / muls.w
            if mode == 1:
                raise _Bad('mul.w An')
            ins = _one('mul_w', w, read16, 2)
            return ins._replace(dst=R, writes=dn)
        raise _Bad('line %x opmode %d' % (line, opmode))

    if line == 0xA:                         # EMAC, and MOV3Q (ISA_B)
        if (w & 0xF1C0) == 0xA140:
            if mode == 7 and reg >= 2:
                raise _Bad('mov3q EA')
            return _one('mov3q', w, read16, 4, writes_ea=True, dst_side=True)
        if (w & 0xFFC0) == 0xAD00:
            return _one('to_mask', w, read16, 4)
        if (w & 0xFBC0) == 0xAB00:
            return _one('to_accext', w, read16, 4)
        if (w & 0xFFC0) == 0xA900:
            return _one('to_macsr', w, read16, 4)
        if (w & 0xF9C0) == 0xA100:
            return _one('to_acc', w, read16, 4, flags=EMAC_OP)
        if w == 0xA9C0:
            return Insn(2, 'macsr_ccr')
        if (w & 0xFBF0) == 0xAB80:
            return Insn(2, 'from_emac', 4, NONE, R,
                        writes=(8 if w & 8 else 0) + reg)
        if (w & 0xFFF0) in (0xAD80, 0xA980):
            return Insn(2, 'from_emac', 4, NONE, R,
                        writes=(8 if w & 8 else 0) + reg)
        if (w & 0xF1FE) == 0xA110:
            return Insn(2, 'acc_to_acc')
        if (w & 0xF9B0) == 0xA180:
            return Insn(2, 'from_acc', 4, NONE, R,
                        writes=(8 if w & 8 else 0) + reg)
        if (w & 0xF100) == 0xA000:          # mac / msac, maybe with a load
            if w & 0x30:
                if mode not in (2, 3, 4, 5):
                    raise _Bad('mac load EA')
                ins = _one('mac', w, read16, 4, extra_words=1, flags=EMAC_OP)
                # The loaded register Rw: opword bits 11-9 and bit 6 (A/D).
                rw = ((w >> 9) & 7) + (8 if w & 0x40 else 0)
                return ins._replace(writes=rw)
            return Insn(4, 'mac', 4, R, NONE, flags=EMAC_OP)
        raise _Bad('line A')

    if line == 0xB:
        opmode = (w >> 6) & 7
        if opmode in (0, 1, 2):             # cmp.b/w/l <ea>,Dn
            size = (1, 2, 4)[opmode]
            if mode == 1 and size == 1:
                raise _Bad('cmp.b An')
            ins = _one('alu_ea_r', w, read16, size)
            return ins._replace(dst=R)
        if opmode in (3, 7):                # cmpa.w / cmpa.l
            ins = _one('alu_ea_r', w, read16, 2 if opmode == 3 else 4)
            return ins._replace(dst=R)
        if opmode == 6:                     # eor.l Dn,<ea>
            if mode == 1 or (mode == 7 and reg >= 2):
                raise _Bad('eor EA')
            ins = _one('alu_r_ea', w, read16, 4, writes_ea=True, dst_side=True)
            return ins._replace(src=R)
        raise _Bad('line B')

    if line == 0xE:                         # asl/asr/lsl/lsr .L
        if (w & 0xC0) != 0x80 or (w & 0x10):
            raise _Bad('shift form')
        return Insn(2, 'shift', 4, R, R, writes=reg)

    if line == 0xF:
        if (w & 0xFF38) == 0xF428:          # cpushl / intouch (An)
            cache = (w >> 6) & 3
            if cache == 0:
                return Insn(2, 'intouch', 4, IND, NONE,
                            agen=((8 + reg, BASE),), flags=PRIV)
            return Insn(2, 'cpushl', 4, IND, NONE, agen=((8 + reg, BASE),),
                        flags=PRIV, extra=cache)
        if (w & 0xFFC0) == 0xFBC0:          # wdebug <ea>
            if read16(2) != 0x0003:
                raise _Bad('wdebug')
            return _one('wdebug', w, read16, 4, extra_words=1, imm_ok=False,
                        flags=PRIV)
        if (w & 0xFF00) == 0xFB00 and (w & 0xC0) != 0xC0:   # wddata
            size = (1, 2, 4)[(w >> 6) & 3]
            return _one('wddata', w, read16, size, imm_ok=False)
        if (w & 0xFE00) == 0xF200 or (w & 0xFF80) == 0xF300:
            return Insn(_fpu_length(w, read16), 'fpu', flags=FPU)
        return Insn(2, 'linef', flags=LINEF)

    raise _Bad('line %x' % line)


_FP_SIZES = {0: 4, 1: 4, 2: 12, 3: 12, 4: 2, 5: 8, 6: 1, 7: 12}


def _fpu_length(w, read16):
    """Enough of the ColdFire FPU's encodings to step over one: the core
    raises line F on the first word anyway, so this only keeps a linear
    decode in step."""
    if (w & 0xFF80) == 0xF280:              # fbcc.w / fbcc.l
        return 6 if w & 0x40 else 4
    if (w & 0xFF80) == 0xF300:              # fsave / frestore <ea>
        try:
            return 2 + _ea((w >> 3) & 7, w & 7, 0, read16, 2)[1]
        except _Bad:
            return 2
    ext = read16(2)
    mode, reg = (w >> 3) & 7, w & 7
    size = _FP_SIZES.get((ext >> 10) & 7, 4) if ext & 0x4000 else 0
    if (ext & 0xE000) in (0x8000, 0xA000, 0xC000, 0xE000):  # fmove(m) ctl
        size = 4
    try:
        n = _ea(mode, reg, size if size else 4, read16, 4)[1] \
            if (mode or reg) and (ext & 0x4000 or ext & 0x8000) else 0
    except _Bad:
        n = 0
    if size and mode == 7 and reg == 4:
        n = size if size > 2 else 2
    return 4 + n


def reader(data, base=0):
    """-> read16 for decode() over a bytes-like `data` loaded at `base`."""
    def read16_at(addr):
        def read16(off):
            i = addr - base + off
            return data[i] << 8 | data[i + 1]
        return read16
    return read16_at


def disassemble_lengths(data, base, start, end):
    """Yield (addr, Insn) linearly over [start, end) of `data` at `base`."""
    at = reader(data, base)
    pc = start
    while pc < end:
        ins = decode(at(pc), pc)
        yield pc, ins
        pc += ins.length
