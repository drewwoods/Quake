# Before Quake: What DOOM Could Not Do

Quake's architecture is easier to read as a list of answers to DOOM's limits than as a design in its own right. DOOM shipped in December 1993 with a renderer built on a two-dimensional binary space partition, sprites for every moving thing, and a fixed camera orientation. Each of those was a deliberate trade that bought a playable frame rate on a 386, and each became a wall that the next engine had to go through rather than around. This chapter establishes what that wall was, using id's own 1993 announcement, Carmack's later retrospective on the DOOM code, and Romero's 1994 announcement of Quake — which described the game before its engine existed.

> **First pass.** DOOM's BSP tree was two-dimensional and was used only for drawing. Quake's is three-dimensional and is used for drawing, collision, and network visibility alike. Almost everything distinctive about Quake's runtime follows from widening that one structure and then finding work for it. [Next: the year of prototypes that decided *how* to use it](#sec-2).

## The 1993 feature list, read as a ceiling

id's DOOM press release of 1 January 1993 is unusually specific about what the engine would do ([`doom_press_release_1993.txt`](../../../historical/doom_1993/doom_press_release_1993.txt)). It advertises a "fantastic fully texture-mapped environment," non-orthogonal walls, light diminishing and light sourcing, variable-height floors and ceilings, environment animation, palette translation, and four-player networked play. Carmack is quoted with a performance target: "on a 486/33, we're talking 35 frames per second, fully texture-mapped at normal detail, for a large area of the screen."

The list is worth reading twice, because what it omits is the actual subject of this guide. There is no mention of looking up or down, of rooms stacked over rooms, of geometry at an angle to the floor, or of three-dimensional creatures. Those are not oversights in the marketing copy; they are outside what the engine could represent. DOOM's world is a floor plan with heights attached. Walls are vertical, floors and ceilings are horizontal, and no two sectors can occupy the same footprint at different heights.

Two features on that list, however, survive into Quake essentially unchanged, and it is worth naming them now because later chapters depend on them. The first is **light diminishing and light sourcing** — the observation that lighting is what makes an environment feel like a place, and therefore that lighting is worth spending the frame budget on. Quake's answer is far more ambitious and is covered in the planned chapter on surface caching, but the commitment is already visible here. The second is the section headed **"An Open Game"**:

> When our last hit, WOLFENSTEIN 3D was released the public responded with an almost immediate deluge of home-brewed utilities; map editors, sound editors, trainers, etc. All without any help on file formats or game layout from Id Software. DOOM will be release as an OPEN GAME. We will provide file formats and technical notes for anyone who wants them.
> — [id Software, DOOM press release, 1 January 1993](../../../historical/doom_1993/doom_press_release_1993.txt)

That is a 1993 statement of an architectural policy that Quake pushes much further, from published file formats to a shipped bytecode virtual machine with the game logic compiled into a replaceable `progs.dat`. The [QuakeC VM](frame:the-quakec-vm) reads as a descendant of this policy. {inferred} The planned QuakeC chapter will trace that line.

## A binary tree in two dimensions

DOOM's central data structure was a BSP tree, and Carmack's use of it is the reason the technique became widely known. Michael Abrash, writing in 1995 while working alongside him, is explicit about the dimensionality: while searching for Quake's visibility algorithm, Carmack "spent a week on this, as a byproduct devising a perfect DOOM (2-D) visibility architecture, whereby a single, linear walk of a DOOM BSP tree produces zero-overdraw 2-D visibility" ([*Black Book*, ch. 64, "Quake's Visible-Surface Determination"](../../../historical/abrash_black_book/chapter-64.md)). The parenthesis is doing real work. A DOOM BSP splits the map with lines on a plan view; every splitter is a wall segment, and the tree partitions a floor plan.

That constrains the geometry directly: walls are the map's linedefs, while floors and ceilings are sector properties the renderer fills in between them. Carmack described exactly this structure as the thing he would change, in the notes accompanying the DOOM source release on 23 December 1997 ([`carmack_doom_retrospective.txt`](../../../historical/doom_1993/carmack_doom_retrospective.txt)):

> The way the rendering proceded from walls to floors to sprites could be collapsed into a single front-to-back walk of the bsp tree to collect information, then draw all the contents of a subsector on the way back up the tree. It requires treating floors and ceilings as polygons, rather than just the gaps between walls, and it requires clipping sprite billboards into subsector fragments, but it would be The Right Thing.
> — [John Carmack, DOOM source release notes, 23 December 1997](../../../historical/doom_1993/carmack_doom_retrospective.txt)

Quake removes that constraint at the root of the representation. Its splitting planes carry a full normal vector, not an implied vertical: {code}

```c
// WinQuake/model.h:59-66
typedef struct mplane_s
{
	vec3_t	normal;
	float	dist;
	byte	type;			// for texture axis selection and fast side tests
	byte	signbits;		// signx + signy<<1 + signz<<1
	byte	pad[2];
} mplane_t;
```

The key difference is that `normal` is a `vec3_t`. Polygons can sit at any angle, so ramps and arbitrary architecture become expressible; leaves are convex volumes rather than convex floor regions, so rooms can stack; and the tree can answer questions about points anywhere in space rather than points on a plan. The cost is a much harder compile. Abrash's [chapter 60, "Compiling BSP Trees"](../../../historical/abrash_black_book/chapter-60.md) builds one in two dimensions, over line segments, to teach the technique; doing it over arbitrary 3-D polygons is `qbsp`'s job, and the splitter heuristic that made it tractable is recorded in [chapter 64](../../../historical/abrash_black_book/chapter-64.md). The harder consequence is visibility, which [the year of discarded renderers](#sec-2) covers. The [on-disk BSP format](frame:on-disk-bsp-format) and the [node and leaf graph it loads into](frame:loading-in-model-c-from-disk-lumps-to-the-mnode-t-mleaf-t-graph) are documented in Life of a Frame.

## The BSP that only drew

The dimensional change is the obvious difference. The more consequential one is what the tree gets *used* for, and here the best source is Carmack assessing his own code four years later:

> The movement and line of sight checking against the lines is one of the bigger misses that I look back on. It is messy code that had some failure cases, and there was a vastly simpler (and faster) solution sitting in front of my face. I used the BSP tree for rendering things, but I didn't realize at the time that it could also be used for environment testing.
> — [John Carmack, DOOM source release notes, 23 December 1997](../../../historical/doom_1993/carmack_doom_retrospective.txt)

In DOOM, the BSP tree was built for the renderer. Movement and hitscan traversed the linedefs via the blockmap; line of sight walked the BSP. Quake derives both kinds of query from the same compiled map geometry. Rendering walks the render BSP; collision walks one of the pre-expanded clip hulls, reusing the map's planes. Life of a Frame covers the mechanism in detail: [`SV_RecursiveHullCheck`](frame:sv-recursivehullcheck-the-trace) is the descent, and [contents types](frame:contents-types-collision-hulls-vs-render-nodes) explain how the engine keeps render nodes and collision hulls separate.

Carmack's retrospective continues straight into the price of doing it that way:

> Sweeping volumes for movement gets a bit tougher, and touches on many of the challenges faced in quake / quake2 with edge bevels on polyhedrons.
> — [John Carmack, DOOM source release notes, 23 December 1997](../../../historical/doom_1993/carmack_doom_retrospective.txt)

This is the origin of one of Quake's most distinctive and least intuitive structures. Sweeping a player-sized box through a 3-D tree is genuinely hard; reducing that box to a *point* moving through a tree whose solid volumes have been pre-expanded by the box's dimensions is easy, and reuses the descent unchanged. So `qbsp` compiles not one tree but several, and each model carries all of them:

```c
// WinQuake/model.h:355
	hull_t		hulls[MAX_MAP_HULLS];
```

with `MAX_MAP_HULLS` fixed at 4 in `WinQuake/bspfile.h:24`. The world model uses hulls 0, 1, and 2; slot 3 is unused by the original runtime. `SV_HullForEntity` picks between them purely on width (`WinQuake/world.c:147-153`): under 3 units gets the point hull, up to 32 gets hull 1, anything larger gets hull 2. Players and most monsters therefore share hull 1, 32x32x56; hull 2, 64x64x88, is for the large monsters (`WinQuake/model.c:959-981`).

That is why body sizes come in discrete classes rather than being per-entity: the dimensions are compiled into the map, not chosen at runtime. It is *not* the reason crouching is absent. Hull 1's vertical extent is standing height, and shrinking an entity's bounding box does not change the hull actually traced against, so a crouch would need its own size class. Slot 3, which the format reserves, was never filled, and the archive does not record why. The [three hulls](frame:the-three-hulls) and the way an entity [selects or fabricates one](frame:sv-hullforentity-picking-or-fabricating-a-hull) are covered in Life of a Frame. The "edge bevels" Carmack mentions are the correction needed to keep expanded polyhedra convex — a detail that only becomes a problem once you have committed to this approach.

The third use of the tree has no direct DOOM counterpart. Because a leaf is a volume, and because visibility between volumes can be computed offline, the same spatial structure that answers "what do I draw" can answer "what does this client need to be told about." Quake's server gates entity updates on the [potentially visible set](frame:how-the-server-also-uses-pvs-sv-fatpvs) of the leaf each client occupies. That is a networking decision built on a rendering data structure, and the planned shipping-constraints chapter will examine how dialup bandwidth shaped it.

## Announced as a design, not an engine

Quake was public long before it was real. John Romero's `.plan` of 18 March 1994 announces it by name, with a subtitle, a comparison, and a start date ([`john_romero/1994-03-18.txt`](../../../historical/plans/john_romero/1994-03-18.txt)):

> **.plan.** The next game is going to blow DOOM all to hell. DOOM totally sucks in comparison to our next game, QUAKE: The Fight for Justice! QUAKE is going to be a bigger step over DOOM than DOOM was over Wolf3D (ya know -- DOOM = pong). We won't start developing QUAKE until Fall'94, due to Jaguar DOOM (Comlynxed!), commercial DOOM (COMPUSA, Babbage's, etc.) and maybe a DOOM level pack.
> — [John Romero, .plan, 18 March 1994](../../../historical/plans/john_romero/1994-03-18.txt)

Two things stand out. The first is the ambition, stated as a ratio rather than a feature: the step from DOOM to Quake was to be at least as large as the step from Wolfenstein to DOOM. Wolfenstein's walls were axis-aligned and eight feet thick; DOOM's could be at any angle and any thickness. The announcement does not say what the next leap would be; the engine that shipped made it a full third dimension. {inferred} The planned chapters on discarded renderers, surface caching, and one-processor design describe the cost.

The second is the schedule. Quake is announced in March 1994, development is not to begin until autumn, and the game shipped in June 1996. Abrash did not join id until March 1995 ([*Black Book*, ch. 64](../../../historical/abrash_black_book/chapter-64.md)), by which point "John already had an engine prototyped and a plan in mind" ([Abrash, ch. 64](../../../historical/abrash_black_book/chapter-64.md)) — a plan that [the year of discarded renderers](#sec-2) examines, and that almost entirely failed to survive contact with the problem. The title *The Fight for Justice* did not survive either. What shipped shares an ambition with the announcement and little else, a useful calibration of how much of Quake's design was intended in advance and how much was discovered under deadline.

The same `.plan` records the development environment in passing — "To get the entire world running NEXTSTEP for development" ([Romero, .plan, 18 March 1994](../../../historical/plans/john_romero/1994-03-18.txt)). NeXTSTEP is why the source has a `NeXT` build path and why the tools are written the way they are.

## What Quake had to close

Reading the two announcements against each other gives a concrete list of what changed, and the roadmap above organizes the rest of this guide around the expensive items on it. The chapter numbers in the last column refer to planned chapters.

| DOOM (1993) | Quake (1996) | Where the cost landed |
| --- | --- | --- |
| 2-D BSP over a floor plan | 3-D BSP over arbitrary planes | Map compile time; a much harder visibility problem (ch. 2) |
| Camera fixed to the horizon | [Free pitch, roll and view offsets](frame:view-setup-bob-punchangle-and-color-shifts-view-c) | No screen-space shortcuts; perspective texturing (ch. 4) |
| Sprites for monsters and players | [Interpolated triangle models](frame:alias-models-r-drawaliasmodel-and-gl-mesh-c-strips-fans) | Per-frame vertex transform and lighting |
| Light per sector, per band | [Per-surface lightmaps](frame:lightmaps-and-light-styles-r-light-c) | Offline light compile; surface caching to afford it (ch. 3) |
| BSP used for rendering only | Same compiled map geometry for render, collision, and network | Expanded hulls; PVS as a bandwidth policy (ch. 5) |
| ~3,000 polygons per level | ~10,000 polygons per level | Overdraw becomes the dominant cost (ch. 2) |
| 35 Hz fixed timebase | [Variable frame time, 20 Hz server tick](frame:host-filtertime-what-host-frametime-actually-means) | Interpolation on the client |

The polygon counts are Abrash's: "a good-sized Quake level contains on the order of 10,000 polygons, about three times as many polygons as a comparable DOOM level" ([ch. 64](../../../historical/abrash_black_book/chapter-64.md)). The DOOM timebase is Carmack's own aside in the source release notes, where he lists "there are some issues with DOOM's 35 hz timebase" ([Carmack's DOOM retrospective](../../../historical/doom_1993/carmack_doom_retrospective.txt)) among the obstacles to a hardware-accelerated port. Quake lets the host use a measured delta while a dedicated server targets `sys_ticrate`; a listen server still runs one server tick inside each accepted host frame. Remote clients therefore need to [interpolate entity positions](frame:entity-interpolation-entity-t-cl-mtime-cl-relinkentities) between received states.

One caveat on the evidence in this chapter. The retrospective quoted above was written in December 1997 — after Quake and Quake II. It is reliable testimony about how Carmack understood DOOM's limits *in hindsight*, and it lines up well with what Quake actually does, but it is not evidence of what he intended in 1994. The contemporaneous record of that period is thin: the March 1994 `.plan` is the announcement, and there is no public design document between it and Abrash's arrival a year later. Where this guide describes intent before March 1995, it is inference from the shipped code, and says so.

## Further reading

- id Software, DOOM press release, 1 January 1993 — the feature list as a statement of scope: [`docs/historical/doom_1993/doom_press_release_1993.txt`](../../../historical/doom_1993/doom_press_release_1993.txt)
- John Carmack, DOOM source release notes, 23 December 1997 — his own assessment of the engine's misses: [`docs/historical/doom_1993/carmack_doom_retrospective.txt`](../../../historical/doom_1993/carmack_doom_retrospective.txt)
- John Romero, `.plan`, 18 March 1994 — the Quake announcement: [`docs/historical/plans/john_romero/1994-03-18.txt`](../../../historical/plans/john_romero/1994-03-18.txt)
- Michael Abrash, *Graphics Programming Black Book*, ch. 60, "Compiling BSP Trees" — a BSP compiler built in two dimensions, over line segments, and how Abrash came to id: [local copy](../../../historical/abrash_black_book/chapter-60.md); also https://www.jagregory.com/abrash-black-book/
- Michael Abrash, *Graphics Programming Black Book*, ch. 64, "Quake's Visible-Surface Determination" — DOOM's 2-D tree contrasted with Quake's, and the polygon budgets: [local copy](../../../historical/abrash_black_book/chapter-64.md)
- John Romero, id Software founding history — context on the Wolfenstein-to-DOOM step: [`docs/historical/idnews/id_history.txt`](../../../historical/idnews/id_history.txt)
- Fabien Sanglard, "Quake Source Code Review": https://fabiensanglard.net/quakeSource/index.php
- Matthew Earl (Matt's Ramblings), "Uncovering Quake's unseen collision hulls" (2025) — the expanded hulls visualised against the render geometry: https://www.youtube.com/watch?v=3KjMjHJ3WQg
- Matthew Earl (Matt's Ramblings), "BSP Trees: The Magic Behind Collision Detection in Quake" (2023) — the trace as a tree descent: https://www.youtube.com/watch?v=wLHXn8IlAiA
- David Kushner, *Masters of Doom* (Random House, 2003, ISBN 978-0812972153) — narrative history of id through Quake's release. Secondary and journalistic; good for people and chronology, not for technical claims.
