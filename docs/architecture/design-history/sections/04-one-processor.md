# Designing for one processor

Surface caching left Quake with a simple texture-mapping pipeline. Making that
mapper fast depended on one machine: Intel's Pentium. Quake arranged its work to
exploit two properties of that chip — paired integer issue, and integer
execution overlapping floating-point division. Abrash's [chapter 63,
"Floating-Point for Real-Time
3-D"](../../../historical/abrash_black_book/black-book.html#chapter-63-floating-point-for-real-time-3-d)
explains why old assumptions about x86 performance no longer held. Quake's
software renderer could run on other processors, but its fastest loops were
written for the Pentium.

> **First pass.** Rather than just replacing C with faster assembly, Quake's
> rendering pipeline provided opportunities for the Pentium to execute integer
> pixel drawing concurrently with perspective correction calculations in the
> FPU. Carefully crafted assembly unlocked this parallelism, and reduced
> precision accelerated the divides themselves. Next: [shipping
> constraints](#sec-5), where bandwidth, memory, and deadlines further shaped
> the engine.

## Two pipes, one instruction stream

The Pentium's U- and V-pipes could execute a pair of integer instructions
simultaneously, governed by specific pairing rules. This was a single
instruction stream with opportunities for paired issue, not two separate
processors. Abrash's [chapter 20, "Pentium
Rules"](../../../historical/abrash_black_book/black-book.html#an-instruction-in-every-pipe)
details how consecutive instructions could sometimes be issued as a pair. The
U-pipe handled a superset of the V-pipe's capabilities. Consequently, fewer
instructions did not guarantee fewer cycles.

Instruction dependencies were as critical as instruction selection. Placing two
instructions that depend on each other's results in a pair could leave the
second pipe stalled. Even valid pairs could stall due to address generation
interlocks. [Chapter 21, "Unleashing the Pentium's
V-Pipe"](../../../historical/abrash_black_book/black-book.html#chapter-21-unleashing-the-pentiums-v-pipe)
covers these interlocks and the performance impact of lockstep execution.

These rules mattered to Quake because shorter loops gave the programmer more
room to arrange instructions. Chapter 68 describes how separating lighting and
tiling from texture mapping let almost all variables stay in registers. {quoted}

> moving lighting and tiling into a separate loop from texture mapping allows
> each of the two loops to be optimized very effectively, with almost all
> variables kept in registers.  — [Michael Abrash, *Graphics Programming
> Black Book*, ch. 68, "Decoupling Lighting from
> Rasterization"](../../../historical/abrash_black_book/black-book.html#decoupling-lighting-from-rasterization).

The link to [chapter 3](#sec-3) is structural. By moving lighting out of the
pixel loop, surface caching left simpler, more register-friendly code behind.
This suggests instruction-level benefits complementing the frame-level ones.
However, it doesn't prove that pairing was the original motivation for surface
caching, which Abrash attributes to lighting challenges. {inferred}

## Floating-point stops being the slow alternative

Chapter 63 opens with Abrash reevaluating his prior preference for fixed-point
math. Faster floating-point instructions, a pipelined FPU, and the ability to
overlap `FXCH` register stack rotations with other FP work changed the
equation. The FPU's eight registers were also separate from the integer set.
Floating-point permeated Quake's internals down to the span rasterizer.
{quoted}
> Quake uses FP all the way down into the inner loop of the span rasterizer,
> performing several FP operations every 16 pixels.  — [Michael Abrash,
> *Graphics Programming Black Book*, ch. 63, "Not Your Father's
> Floating-Point"](../../../historical/abrash_black_book/black-book.html#not-your-fathers-floating-point).

The key factor was no longer an operation's latency alone, but the amount of
useful work that could be accomplished before its result was needed. While
addition, subtraction and multiplication were pipelined, `FDIV` occupied the
FPU for its entire duration. Integer instructions could still proceed during
most of this interval, but a subsequent floating-point operation would halt
that progress. Careful scheduling was required to ensure sufficient independent
integer work preceded the next FPU instruction.

The two kinds of arithmetic worked together: floating-point calculated
perspective coordinates at intervals, while integer math handled the pixels
in between. The [assembly
walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from)
examines the resulting implementation.

## Give the divide something to overlap

A perspective texture mapper cannot simply advance texture coordinates
uniformly across an entire receding floor. Quake approximated the curve in
short segments. Abrash's [chapter 70, "Quake: A Post-Mortem and a Glimpse into
the
Future"](../../../historical/abrash_black_book/black-book.html#rasterization)
outlines computing perspective-correct coordinates every 16 pixels and linearly
interpolating in between. He concedes minor inaccuracies, sometimes visible as
ripples, in exchange for bypassing the full calculation every pixel.

Those blocks gave the processor useful work to do while it waited for a divide. After the FPU
delivered a span's starting coordinates, integer code could rasterize the span
while the FPU calculated the reciprocal needed for the next correction. Abrash
details this pipelining explicitly. {quoted}

> the FDIV to calculate the reciprocal of 1/z is overlapped with drawing 16
> pixels, taking advantage of the Pentium's ability to perform floating-point in
> parallel with integer instructions, so the FDIV effectively takes only one
> cycle.  — [Michael Abrash, *Graphics Programming Black Book*, ch. 70,
> "Rasterization"](../../../historical/abrash_black_book/black-book.html#rasterization).

"Effectively" is key. The divide still required many cycles to finish; useful
integer work concealed the waiting time. This relied on having work ready that
did not depend on its result. Short runs, setup, and cleanup did not become
free. In the sixteen-pixel assembly drawer Abrash is describing, the comment
next to `FDIV` identifies the overlap as the purpose of the preceding setup
(`WinQuake/d_draw16.s:234-236`); the eight-pixel drawer bears the same comment
(`WinQuake/d_draw.s:230-232`). {code}

The source also settles which drawer that account describes. On x86,
`d_subdiv16` defaults to 1 and selects the sixteen-pixel drawer; clearing it
selects the eight-pixel one, and the portable build has only the eight-pixel
path (`WinQuake/d_init.c:27`, `148-155`). {code} Abrash's sixteen-pixel account
is the default x86 configuration, not every build or setting.

## Precision was part of the budget

Drawing pixels during a divide hid much of the wait. Lower precision made the
divide itself shorter. In [chapter 63's
"Projection"](../../../historical/abrash_black_book/black-book.html#projection-1),
Abrash reports 19 cycles for single-precision division; earlier in the chapter
he gives 39 at full precision and 33 at double precision. These are Pentium
instruction timings, not frame-rate measurements.

The cost was altered arithmetic. Abrash cautions that reducing FPU precision
also affects other operations and can alter clipping results or the tolerances
needed for comparisons. Quake's rendering code makes the trade explicit: it
calls `Sys_LowFPPrecision` with a comment stating the purpose is to make `FDIV`
fast, and that leaving this mode active globally would reduce timing precision
after extended execution (`WinQuake/r_main.c:972-976`). It restores high
precision before exiting that rendering routine
(`WinQuake/r_main.c:1047-1048`). {code}

Quake used lower precision while rendering, then restored it for the rest of
the engine. The [runtime
walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from)
tracks the control word changes.

## A target, not a portability ban

Chapter 68 cites 7.5 cycles per mapped pixel for the tuned Pentium loop. That's
for a loop given spans and surfaces to sample. Visibility, surfaces, entities,
audio, and gameplay still consumed time. Instruction pairing and divide hiding
don't imply a 2x overall speedup.

Portable versions persisted alongside the optimized code. Carmack's [23
November 1996
worklog](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt)
clarifies the distinction, discussing an ordered Alpha NT machine:

> **.plan.** We aren't going to be able to spend time writing assembly language
> for it like the intel version has, but it should still run at a pretty decent
> clip. — [Carmack, 23 November
> 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt).

That records an intended port and a limit on available effort, not measured
Alpha performance. It also bounds the chapter's claim: the renderer was
portable, while equal tuning across processors was not promised. The Pentium
influenced the division of work, the arithmetic precision, and the schedule of
the inner loop. Those choices made sense together on the target machine;
carrying the C elsewhere did not carry the same costs with it.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, [chapter 20, "Pentium
  Rules"](../../../historical/abrash_black_book/black-book.html#chapter-20-pentium-rules),
  and [chapter 21, "Unleashing the Pentium's
  V-Pipe"](../../../historical/abrash_black_book/black-book.html#chapter-21-unleashing-the-pentiums-v-pipe)
  — pairing and dependency constraints.
- Abrash, [chapter 63, "Floating-Point for Real-Time
  3-D"](../../../historical/abrash_black_book/black-book.html#chapter-63-floating-point-for-real-time-3-d)
  — FPU scheduling, division overlap, precision, and numerical risks.
- Abrash, [chapter 68, "Quake's Lighting
  Model"](../../../historical/abrash_black_book/black-book.html#chapter-68-quakes-lighting-model),
  and [chapter 70, "Quake: A Post-Mortem and a Glimpse into the
  Future"](../../../historical/abrash_black_book/black-book.html#rasterization)
  — the connection between rendering stages and optimized loops.
- John Carmack, [23 November
  1996](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt) —
  planned portability without equivalent assembly work.
- [Life of a Frame: assembly
  walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from)
  — the span drawer, precision switches, and C comparison.
