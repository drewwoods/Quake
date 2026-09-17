# QuakeC: Why a Virtual Machine

In Quake, a new map changes where the player goes, but new game code changes what happens there - how monsters attack, what weapons fire, and which actions score points. By making the game rules reside in an interpreted `progs.dat` file, Quake allowed such changes without rebuilding the engine. id Software had to decide where to draw the boundary: mod authors could replace behaviors while the engine retained control over rendering, networking, and movement mechanics.

## From Editing Files to Changing Rules

id's [1993 DOOM announcement](../../../historical/doom_1993/doom_press_release_1993.txt) had promised an "open game" by documenting file formats for custom content. Quake took this further by making behavior executable. While the sources don't pinpoint exactly when id chose a virtual machine, QuakeC was in use before release:

> It includes quake.exe winded.exe progs.dat, and a zip of the latest .qc files.
> — [Carmack, .plan, 13 September 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960913.txt)

Publishing replaceable game code, not just assets, let mod authors change the rules that give content meaning.

## Where the Engine Stops

The boundary is clear in entity callbacks. The engine handles movement and collision, then invokes QuakeC `touch` and `think` functions for game-specific responses. `ED_LoadFromFile` looks up an entity's `classname` to call its spawn function, so maps can introduce new object types.

Conversely, QuakeC uses engine builtins to spawn entities, trace lines, play sounds, and move objects, accessing engine capabilities through controlled entry points. A mod author has considerable flexibility without every subsystem being replaceable.

## A Program That Travels With the Game

`progs.dat` contains instructions, functions, strings, variables, and globals for Quake's interpreter, not native code. This allows engine ports to run the same game logic, although maps and assets must still be compatible.

The concrete interface has the loader check shared definitions and size entities based on the program's field count. Conventions like `OP_STATE` for monster animation are baked into the instruction set. It's a small, game-specific machine.

## Still Being Built Near Release

March 1996 entries show the machinery evolving alongside the game:

> * crunched progs.dat file structure
> * culled unused edict fields
> — [Carmack, 13 March 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960313.txt)

> * made an execution stack for progs
> — [Carmack, 15 March 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt)

Diagnosis features like per-function instruction counts and runaway loop checks aided authors without guarding against malicious code. Validation was still the engine's job.

## The Bill Came Due in Quake II

On 13 March 1997, Carmack proposed native game DLLs for Quake II, tying it to dropping DOS support:

> I am strongly considering dropping qc in Quake 2 in favor of exporting most of the game logic to a seperate .dll file. This wasn't an option when we had to support dos, but I think it is the correct choice now.
> — [Carmack, .plan, 13 March 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970313.txt)

He forecast a 5-10% full-game speedup with less gain for simple mods, wanted better language and debugging features, but acknowledged the cost: per-platform compilation, security issues with untrusted native code, and a higher barrier to entry.

QuakeC had become an onramp to programming that DLLs would block for some tinkerers. Ambitious mods might run faster but be harder to share.

## What Survived the Language

By November 1998, Carmack returned to interpreted code for Quake Arena's client-side mods. Having players automatically receive native modules posed risks.

> The only real solution to these problems is to use an interpreted language like Quake 1 did. I have reached the conclusion that the benefits of a standard language outweigh the benefits of a custom language for our purposes.
> — [Carmack, .plan, 3 November 1998](../../../historical/plans/carmack/by_day/johnc_plan_19981103.txt)

This separated two bundled decisions: making game logic a portable program, and inventing QuakeC to express it. The VM's portability remained valuable even if the language could be swapped. Later games kept renegotiating the tradeoffs of that separation.

## Further reading

- id Software, [DOOM press release, 1 January 1993](../../../historical/doom_1993/doom_press_release_1993.txt) — what the original “open game” promise actually offered.
- Carmack, [13 March](../../../historical/plans/carmack/by_day/johnc_plan_19960313.txt) and [15 March 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt) — program-format, entity-field, and execution-stack work before release.
- Carmack, [13 September 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960913.txt) — distributing game source alongside `progs.dat`.
- Carmack, [13 March 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970313.txt) — the proposed native-library replacement and its trade-offs.
- Carmack, [3 November 1998](../../../historical/plans/carmack/by_day/johnc_plan_19981103.txt) — returning to interpretation for Quake Arena, using a standard language.
- Life of a Frame: the [QuakeC VM](frame:the-quakec-vm), [scheduler](frame:sv-runthink-the-quakec-scheduler), and [builtins](frame:builtins) — how the boundary works at runtime.
