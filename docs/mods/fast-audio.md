# Fast audio

Model:Cycles only. Runs the audio render's busiest code from the processor's on-chip
SRAM instead of DDR memory, which leaves about 3 % more CPU for everything else (stock
spends 76–79 % on the sound). The sound is unchanged.

Based on 18nelli's research and the FAST AUDIO of
[irpina/digihealth](https://github.com/irpina/digihealth).
