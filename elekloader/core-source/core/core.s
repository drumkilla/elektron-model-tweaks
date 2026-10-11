| SPDX-License-Identifier: GPL-2.0-or-later
| core: the boot copier and the hook bus every other mod builds on.
| ColdFire V4 (MCF5441x); assemble with -mcpu=54455. One source for every
| device with this hook bus: the Digitakt mk1 (OS 1.53, mods/core), the
| Digitone mk1 (OS 1.43, mods/core-dn1) and the Digitakt II (OS 1.17,
| mods/core-dt2). The SETTINGS and render hooks are in settings.s and
| render.s, for the devices that have those sites. The addresses below are
| not here: each device's mod.json gives them as "defsym", so a missing one
| fails the build instead of using another device's.
|
|   DRAWALL      ViewController::drawAll(ctrl, Bitmap&)
|   KEYDISP      Brain::key(brain, KeyEvent*)
|   ENCDISP      Brain::enc(brain, EncoderEvent*)
|   DTMR0        DMA timer 0 mode;  PPMSR0: the peripheral clock set register
|                (neither, with NO_DTIM0: the core leaves DTIM0 alone)
|   VBR_FN       what the OS entry's call at 0x40000538 called
|
| .boot runs where the bootstrap unpacks it (appended to MAIN OS), once,
| from the OS entry's call at 0x40000538: before the OS zeroes its .bss and
| turns the caches on. It copies the DDR image the linker built to its run
| address, zeroes .bss, starts DTIM0 if nothing has, and goes on to the
| call it replaced. The linker defines the __run_*/__bss_* symbols.
|
| Each shared site calls the handlers mods subscribe to its event, from a
| table the linker builds (docs/ADAPTING.md, "The hook bus"): a list of
| pointers ending in 0. Handlers use the C convention. The sites are in
| mod.json; the comments below give the Digitakt mk1's.

| ============================ .boot =======================================
        .section .boot, "ax"
        .globl  boot
boot:
        lea     __run_load, %a0         | where the DDR image was unpacked
        lea     __run_start, %a1        | where it runs
        move.l  #__run_words, %d0
1:      move.l  (%a0)+, (%a1)+
        subq.l  #1, %d0
        bne.s   1b
        lea     __bss_start, %a1        | DDR holds noise at power-on
        move.l  #__bss_words, %d0
        beq.s   3f
2:      clr.l   (%a1)+
        subq.l  #1, %d0
        bne.s   2b
3:
        .ifndef NO_DTIM0
        | DTIM0: the OS reads its counter as a 132 MHz time base and never
        | starts it, so something before the OS does. Start it only if it is
        | held in reset: rewriting DTMR0 while it runs would stop it. A core
        | that defines NO_DTIM0 (the Digitakt II's) leaves it as stock does.
        move.w  DTMR0, %d0
        btst    #0, %d0
        bne.s   4f
        move.b  #0x1C, %d0
        move.b  %d0, PPMSR0             | its clock on
        clr.l   %d0
        move.w  %d0, DTMR0
        moveq   #3, %d0
        move.w  %d0, DTMR0              | bus clock, free running
4:
        .endif
        .ifdef  VBR_FN2
        | Model:Cycles and Model:Samples: the site is two calls, the SRAM
        | copy (VBR_FN) and the .bss clear (VBR_FN2). The DDR image above
        | lies in what the clear zeroes, so it is copied out first.
        jsr     VBR_FN
        jmp     VBR_FN2                 | its rts returns past the site
        .else
        jmp     VBR_FN                  | its rts returns to 0x4000053e
        .endif

| ============================ .run ========================================
        .section .run, "ax"

| ---- ev_tick: the 30 Hz compose check -------------------------------------
| At 0x4000a770 (was: jsr 0x400ca34c, which returns ctrl->dirty, byte +0x20,
| in d0). (sp) = return, 4(sp) = the view controller. UI task. Handlers:
| f(ctrl); one that wants the frame recomposed sets ctrl+0x20.
        .globl  core_tick
core_tick:
        move.l  %a2, -(%sp)
        lea     ev_tick, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  8(%sp), -(%sp)          | ctrl
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #4, %sp
        bra.s   1b
2:      movea.l (%sp)+, %a2
        movea.l 4(%sp), %a0             | what 0x400ca34c returns
        move.b  0x20(%a0), %d0
        rts

| ---- ev_draw: on top of every composed frame ------------------------------
| At 0x4000a7d6 (was: jsr 0x400ca382, drawAll(ctrl, bmp)). (sp) = return,
| 4(sp) = ctrl, 8(sp) = the frame's Bitmap. d2-d7/a2-a6 must survive.
| Handlers: f(bmp, ctrl), in order, each over the last.
        .globl  core_draw
core_draw:
        move.l  8(%sp), -(%sp)
        move.l  8(%sp), -(%sp)
        jsr     DRAWALL                 | every visible view, as before
        addq.l  #8, %sp
        move.l  %a2, -(%sp)
        lea     ev_draw, %a2
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  8(%sp), -(%sp)          | ctrl
        move.l  16(%sp), -(%sp)         | bmp
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #8, %sp
        bra.s   1b
2:      movea.l (%sp)+, %a2
        rts

| ---- ev_key, ev_enc: the UI main loop's key and encoder dispatch -----------
| At 0x4000b770 (was: jsr 0x400084fe) and 0x4000b7ba (was: jsr 0x40008550).
| (sp) = return, 4 brain, 8 the event. Handlers: f(brain, event) -> d0
| nonzero when they took it; then nothing after them sees it, stock
| included.
        .globl  core_key, core_enc
core_key:
        move.l  %a2, -(%sp)
        lea     ev_key, %a2
        bsr.s   dispatch
        movea.l (%sp)+, %a2
        tst.l   %d0
        bne.s   1f
        jmp     KEYDISP                 | the stock path, same stack
1:      rts

core_enc:
        move.l  %a2, -(%sp)
        lea     ev_enc, %a2
        bsr.s   dispatch
        movea.l (%sp)+, %a2
        tst.l   %d0
        bne.s   1f
        jmp     ENCDISP
1:      rts

| dispatch: a2 = the table; 12(sp) brain, 16(sp) event (after its return
| address and the caller's saved a2). -> d0 = the first nonzero result, or 0.
dispatch:
1:      move.l  (%a2)+, %d0
        beq.s   2f
        move.l  16(%sp), -(%sp)         | the event
        move.l  16(%sp), -(%sp)         | brain
        movea.l %d0, %a0
        jsr     (%a0)
        addq.l  #8, %sp
        tst.l   %d0
        beq.s   1b
2:      rts

| ============================ .bss ========================================
        .section .bss
        .balign 4
| What a weak import resolves to when no mod provides it: reads as zero.
        .globl  core_zero
core_zero:  .skip 16
