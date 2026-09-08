# Designing for One Processor

The surface cache left Quake with a simpler texture mapper. Making that mapper affordable depended on the machine executing it. The Pentium could issue paired integer instructions and perform integer work while a floating-point divide ran. Quake arranged work to exploit both. Abrash's *Graphics Programming Black Book*, especially [chapter 63, “Floating-Point for Real-Time 3-D”](../../../historical/abrash_black_book/chapter-63.md), explains why assumptions inherited from earlier x86 processors no longer held. “One processor” here means a performance target: Quake retained portable C, but its software renderer's costs were shaped around the Pentium.

> **First pass.** Quake did not merely replace C instructions with faster assembly. Its rendering stages provided independent work that the Pentium could execute together: simple integer pixel drawing while the FPU calculated a later perspective correction. Assembly made that arrangement pay; reduced precision shortened the divide itself. Next: [shipping constraints](#sec-5), where bandwidth, memory, and deadlines impose further limits.

## Two pipes, one instruction stream

The Pentium's U- and V-pipes could execute two integer instructions together, subject to pairing rules. They were not two processors running separate jobs. Abrash's [chapter 20, “Pentium Rules”](../../../historical/abrash_black_book/chapter-20.md#an-instruction-in-every-pipe), describes one instruction stream whose next two instructions could sometimes issue as a pair. The U-pipe handled more operations; the V-pipe handled a restricted subset. Fewer instructions therefore did not automatically mean fewer cycles.

Dependencies mattered as much as instruction choice. If one operation needed the preceding operation's result, putting them beside each other could leave the second pipe idle. Even an otherwise valid pair could stall while an address was being prepared. [Chapter 21, “Unleashing the Pentium's V-Pipe”](../../../historical/abrash_black_book/chapter-21.md), explains those address-generation interlocks and the lockstep execution that could stall both pipes.

These chapters establish the processor's constraints, not a dated account of Quake's development. Their relevance becomes concrete in chapter 68: separating lighting and tiling from texture mapping made the loops small enough to keep almost all their variables in registers. {quoted}

> moving lighting and tiling into a separate loop from texture mapping allows each of the two loops to be optimized very effectively, with almost all variables kept in registers.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 68, “Decoupling Lighting from Rasterization”](../../../historical/abrash_black_book/chapter-68.md#decoupling-lighting-from-rasterization).

The connection to [chapter 3](#sec-3) is structural. Surface caching removed lighting calculations from the pixel drawer, leaving fewer live values and simpler repeated operations. This suggests why the separation helped at the instruction level as well as across frames. It does not establish that pairing was the original reason for inventing surface caching; Abrash's account gives the lighting problems that led to it. {inferred}

## Floating-point stops being the slow alternative

Abrash opens chapter 63 by revisiting his own preference for fixed-point arithmetic. He attributes the change to faster floating-point instructions, a pipelined FPU, and the ability to overlap `FXCH`, which rearranges the FPU register stack, with other floating-point work. The FPU also supplied eight registers separate from the integer registers. Quake used floating-point inside the span rasterizer, not only for high-level geometry. {quoted}

> Quake uses FP all the way down into the inner loop of the span rasterizer, performing several FP operations every 16 pixels.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 63, “Not Your Father's Floating-Point”](../../../historical/abrash_black_book/chapter-63.md#not-your-fathers-floating-point).

The important distinction was between the time an operation took and the useful work possible before its result arrived. Chapter 63 describes pipelined addition, subtraction, and multiplication, but division was different: `FDIV` occupied the FPU until it finished. Integer instructions could still execute during most of that interval. A following floating-point instruction would stop that progress; the instruction order had to leave enough independent integer work before the next FPU operation.

That made floating-point and fixed-point arithmetic complementary. Floating-point could supply perspective-correct coordinates at intervals, while integer arithmetic advanced through the pixels between them. The [assembly walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from) follows the resulting implementation.

## Give the divide something to overlap

A perspective texture mapper cannot simply advance texture coordinates at a constant rate across an entire receding floor. Quake approximated the curve in short pieces. Abrash's [chapter 70, “Quake: A Post-Mortem and a Glimpse into the Future”](../../../historical/abrash_black_book/chapter-70.md#rasterization), describes calculating perspective-correct coordinates every 16 pixels and interpolating between them. He acknowledges slight error, occasionally visible as a small ripple, in return for avoiding the full calculation at every pixel.

Those pixel runs also supplied work to hide division latency. Once the current run's coordinates were ready, the integer side could draw it while the FPU calculated the reciprocal needed for a later correction. Abrash describes the scheduling explicitly. {quoted}

> the FDIV to calculate the reciprocal of 1/z is overlapped with drawing 16 pixels, taking advantage of the Pentium's ability to perform floating-point in parallel with integer instructions, so the FDIV effectively takes only one cycle.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 70, “Rasterization”](../../../historical/abrash_black_book/chapter-70.md#rasterization).

“Effectively” matters. The divide still took many cycles to finish; useful integer work covered the waiting time. This depended on having work ready that did not need its result. Short runs, setup, and cleanup did not become free. In the surviving eight-pixel assembly drawer, the comment beside `FDIV` identifies the overlap as the purpose of the preceding setup (`WinQuake/d_draw.s:230-234`). {code}

The source also preserves a boundary that the historical summary can obscure: the x86 build can select either the eight- or sixteen-pixel drawer, while the portable path selects the eight-pixel drawer (`WinQuake/d_init.c:148-155`). {code} Abrash's sixteen-pixel account should not be read as a description of every build or setting.

## Precision was part of the budget

Overlap reduced exposed waiting time. Lower precision reduced the division's actual duration. In [chapter 63's “Projection”](../../../historical/abrash_black_book/chapter-63.md#projection), Abrash reports 19 cycles for single-precision division; earlier in the chapter he gives 39 at full precision and 33 at double precision. These are Pentium instruction timings, not frame-rate measurements.

The price was changed arithmetic. Abrash warns that reducing FPU precision also affects other operations and can alter clipping results or the tolerances needed for comparisons. Quake's rendering code makes the trade explicit: it calls `Sys_LowFPPrecision` with a comment saying the purpose is to make `FDIV` fast, and that leaving this mode active globally would reduce timing precision after extended execution (`WinQuake/r_main.c:972-976`). It restores high precision before leaving that rendering routine (`WinQuake/r_main.c:1047-1048`). {code}

The mode switch is evidence of a numerical boundary around the rendering work. It is not evidence that less precision was harmless everywhere. The [runtime walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from) traces the control-word changes.

## A target, not a portability ban

Chapter 68 reports 7.5 cycles per mapped pixel for the optimized Pentium loop. That figure describes a loop supplied with spans and a surface to sample. Visibility, surface construction, entities, sound, and game logic still consumed time. Neither pairing nor hiding one divide establishes a twofold improvement in the whole game.

Portable implementations survived alongside the specialized code. Carmack's [23 November 1996 worklog](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt) makes the distinction concrete while discussing an ordered NT Alpha machine:

> **.plan.** We aren't going to be able to spend time writing assembly language for it like the intel version has, but it should still run at a pretty decent clip. — [Carmack, 23 November 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt).

That records an intended port and a limit on available effort, not measured Alpha performance. It also bounds the chapter's claim: the renderer was portable, while equal tuning across processors was not promised. The Pentium influenced the division of work, the arithmetic precision, and the schedule of the inner loop. Those choices made sense together on the target machine; carrying the C elsewhere did not carry the same costs with it.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, [chapter 20, “Pentium Rules”](../../../historical/abrash_black_book/chapter-20.md), and [chapter 21, “Unleashing the Pentium's V-Pipe”](../../../historical/abrash_black_book/chapter-21.md) — pairing and dependency constraints.
- Abrash, [chapter 63, “Floating-Point for Real-Time 3-D”](../../../historical/abrash_black_book/chapter-63.md) — FPU scheduling, division overlap, precision, and numerical risks.
- Abrash, [chapter 68, “Quake's Lighting Model”](../../../historical/abrash_black_book/chapter-68.md), and [chapter 70, “Quake: A Post-Mortem and a Glimpse into the Future”](../../../historical/abrash_black_book/chapter-70.md#rasterization) — the connection between rendering stages and optimized loops.
- John Carmack, [23 November 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt) — planned portability without equivalent assembly work.
- [Life of a Frame: assembly walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from) — the span drawer, precision switches, and C comparison.
