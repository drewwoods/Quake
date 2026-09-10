# QuakeC: why a virtual machine

A new map changes where the player goes. New game code changes what happens there: how a monster attacks, what a weapon fires, or which actions earn a point. Quake made that second kind of change possible without rebuilding the engine. Its game rules lived in `progs.dat`, a compiled QuakeC program that the engine interpreted. The interesting decision was where id drew the boundary: game authors could replace behaviour while the engine kept control of rendering, networking, and the machinery of movement.

> **First pass.** QuakeC made game logic a replaceable program that could travel between engine ports. It kept expensive engine services in C, but charged an interpreter cost for the rules around them. Carmack's later proposal to replace it with native code makes the bargain explicit: speed and debugging on one side, portability and access for mod authors on the other. Next: the planned VQuake chapter, where hardware puts the surface cache through a similar test.

## From editing files to changing rules

The [1993 DOOM announcement](#the-1993-feature-list-as-a-ceiling) promised an “open game.” That promise was specific: id would document formats so players could write tools and share their work. It did not announce a programming language. {quoted}

> DOOM will be release as an OPEN GAME. We will provide file formats and technical notes for anyone who wants them.
>
> — [id Software, DOOM press release, 1 January 1993](../../../historical/doom_1993/doom_press_release_1993.txt).

Quake extended that opening into executable behaviour. The connection is a continuity of policy, not proof that QuakeC was already planned in 1993. The sources used here do not record the meeting or prototype in which id first chose a virtual machine. They do show it in use before release, and show game source being distributed afterwards.

On [13 September 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960913.txt), Carmack described a beta package containing both the compiled game program and its source. This was an interface id used to ship its own updates, too. {quoted}

> It includes quake.exe winded.exe progs.dat, and a zip of the latest .qc files.
>
> — [Carmack, .plan, 13 September 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960913.txt).

The distinction matters. Publishing file formats lets people supply new material to an existing game. Publishing replaceable game code lets them change the rules that give that material meaning.

## Where the engine stops

Consider a projectile hitting a monster. The engine handles movement and detects contact; game code decides what that contact means. Should the projectile explode, bounce, or do nothing? How much damage should it cause? Those decisions can change while the collision machinery stays the same.

The boundary is visible in the callbacks. `SV_Impact` invokes an entity's QuakeC `touch` function after contact, while `SV_RunThink` invokes its `think` function when `nextthink` comes due (`WinQuake/sv_phys.c:123-174`). {code} QuakeC supplies the response; the C engine supplies the event. The [runtime scheduler](frame:sv-runthink-the-quakec-scheduler) shows how those calls fit into a frame.

Map loading uses the same division. `ED_LoadFromFile` looks up an entity's `classname` in the program's function table and calls the matching spawn function (`WinQuake/pr_edict.c`). {code} A map can therefore name a new kind of object whose setup lives in game code. The loader does not need a new C branch for every door, pickup, or monster a game author invents.

Calls also cross the boundary in the other direction. QuakeC asks the engine to spawn entities, trace lines, play sounds, and place objects through builtins. These are numbered entry points into C, rather than arbitrary operating-system calls. `setorigin`, for example, updates an entity's position and relinks it into the world; assigning the position alone would leave the collision links wrong (`WinQuake/pr_cmds.c:115-128`). {code} The [builtin interface](frame:builtins) is where the language reaches the engine's capabilities and its limits.

This gives a mod author considerable room without making every subsystem replaceable. A new damage rule can fit inside QuakeC. A new renderer cannot. Even movement is a shared responsibility: game code can choose velocities and movement modes, but the engine still implements the underlying physics.

## A program that travels with the game

`progs.dat` contains instructions, functions, strings, variable definitions, and global storage. Its instructions describe operations for Quake's interpreter rather than for a Pentium. A statement has an opcode and three short operands; the instruction set includes arithmetic, branches, function calls, and entity-field access (`WinQuake/pr_comp.h:42-125`). {code} The [program format and interpreter](frame:the-quakec-vm) are covered in Life of a Frame.

The practical gain is that an engine port can understand the same game program. The mod author does not have to supply a different machine-code binary for each processor and operating system. This is portability of the game logic; maps, models, and other required assets still have to be available, and an engine must support the program's interface.

That interface is deliberately concrete. The loader checks the program version and a checksum for the shared system definitions. The engine and QuakeC agree on fields such as `origin`, `think`, and `nextthink`, while the program can add fields of its own; the loader sizes each entity from the program's field count (`WinQuake/pr_edict.c`). {code} Adding game state need not mean recompiling the engine, but changing the shared layout breaks their agreement.

The VM also carries some of Quake's game conventions directly in its instruction set. `OP_STATE` sets an animation frame, chooses the next think function, and normally schedules it one tenth of a second later (`WinQuake/pr_exec.c:649-661`). {code} This is a small machine built around this game, with a monster-animation operation beside its arithmetic instructions.

## Still being built near release

The March worklogs show that this machinery was still changing while the game took shape. They record work on the program format, entity storage, and function execution. {quoted}

> **.plan.** * crunched progs.dat file structure
>
> * culled unused edict fields
>
> — [Carmack, 13 March 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960313.txt).

> **.plan.** * made an execution stack for progs
>
> — [Carmack, 15 March 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt).

These entries establish what was being worked on, not how much memory or time it saved. In the released interpreter, function calls preserve local values on a separate stack before reusing their storage. That makes nested calls and recursion possible; the [interpreter walkthrough](frame:the-interpreter) explains the arrangement. The March entry is consistent with that mechanism, but does not tell us exactly which parts were introduced that day.

QuakeC came with ways to diagnose game code as well. The interpreter counts executed instructions per function and has a runaway-loop guard (`WinQuake/pr_exec.c:382-402`). {code} These help authors locate expensive functions and catch loops that fail to return. They do not turn the VM into a guarantee against hostile programs: the instruction limit does not bound the time spent inside a C builtin, and the engine still has to validate what it loads and executes.

## The bill came due in Quake II

The clearest explanation of QuakeC's costs comes after Quake shipped. On 13 March 1997, Carmack proposed moving Quake II's game logic into a native library. He tied the newly available option to dropping DOS support. {quoted}

> I am strongly considering dropping qc in Quake 2 in favor of exporting most of the game logic to a seperate .dll file. This wasn't an option when we had to support dos, but I think it is the correct choice now.
>
> — [Carmack, .plan, 13 March 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970313.txt).

This is later testimony about the constraint, not a surviving design note from Quake's beginnings. In the same entry, he expected native code to improve overall speed by at least 5–10% on full game levels, with less benefit for simple deathmatch modifications. That was a forecast for the proposed change, not a published benchmark. He also wanted a more capable language and a real debugger.

The cost of that move was just as explicit. A native mod would need a separate build for each target platform. Running someone else's machine code raised security concerns, and needing a native compiler would exclude some of the people already writing QuakeC. Carmack acknowledged that the small language had become an entry point into programming. {quoted}

> You would actually need a compiler to hack quake. For the serious people, this isn't an issue, but it would cut out a number of people that currently enjoy hacking quake.
>
> — [Carmack, .plan, 13 March 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970313.txt).

QuakeC also needed compilation; the distinction here is the move to a native development toolchain. Faster execution would make some ambitious mods easier to build, while the tools and platform-specific binaries would make others harder to share.

## What survived the language

The decision did not settle permanently in favour of native code. In November 1998, discussing Quake Arena, Carmack returned to interpretation when mod code was moving onto clients. A server operator choosing a native module and a player automatically receiving one from an unfamiliar server presented different risks. Platform-specific client modules would also prevent some engine ports from joining a modded server.

His answer preserved the interpreter while abandoning the custom language. {quoted}

> The only real solution to these problems is to use an interpreted language like Quake 1 did. I have reached the conclusion that the benefits of a standard language outweigh the benefits of a custom language for our purposes.
>
> — [Carmack, .plan, 3 November 1998](../../../historical/plans/carmack/by_day/johnc_plan_19981103.txt).

That later choice helps separate two decisions which Quake bundled together: making game logic a portable interpreted program, and inventing QuakeC to express it. The language could be replaced while the reason for the virtual machine remained. Quake had made its rules something an author could compile and distribute separately from the engine. The later games kept renegotiating the cost of that freedom.

## Further reading

- id Software, [DOOM press release, 1 January 1993](../../../historical/doom_1993/doom_press_release_1993.txt) — what the original “open game” promise actually offered.
- Carmack, [13 March](../../../historical/plans/carmack/by_day/johnc_plan_19960313.txt) and [15 March 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt) — program-format, entity-field, and execution-stack work before release.
- Carmack, [13 September 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960913.txt) — distributing game source alongside `progs.dat`.
- Carmack, [13 March 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970313.txt) — the proposed native-library replacement and its trade-offs.
- Carmack, [3 November 1998](../../../historical/plans/carmack/by_day/johnc_plan_19981103.txt) — returning to interpretation for Quake Arena, using a standard language.
- Life of a Frame: the [QuakeC VM](frame:the-quakec-vm), [scheduler](frame:sv-runthink-the-quakec-scheduler), and [builtins](frame:builtins) — how the boundary works at runtime.
