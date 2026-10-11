# elekloader (a copy)

The part of [elekloader](https://github.com/irpina/elekloader) (irpina and
contributors) that links .elemod mods into a stock firmware file, copied unchanged
from a fork that adds the Model:Cycles and Model:Samples (OS 1.13). It is licensed
under the GNU GPL version 2 or later: see LICENSE and NOTICE in this folder. The
rest of this repository is under its own licence (the LICENSE at its root).

It is here until elekloader itself supports the Model devices; the web flasher
(flasher/) runs it in the browser.

core-source/ is the source of the core mod, mods/<device>/core-0.1.elemod, built
by elekloader's SDK from core/core.s with core-ms/ or core-mc/mod.json (GPL too).
