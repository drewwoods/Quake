# Before Quake: what DOOM could not do

Quake's architecture is best understood as a series of answers to the
limitations of DOOM's engine. Released in December 1993, DOOM used a
two-dimensional binary space partitioning (BSP) tree, sprites for moving
objects, and a fixed camera orientation. While these design choices enabled
playable frame rates on 386 computers, they became constraints that Quake's
engine had to overcome. This chapter establishes the nature of these
constraints using id Software's own 1993 announcement, John Carmack's later
retrospective on the DOOM code, and John Romero's 1994 announcement of Quake,
which described the game before its engine existed.

> **First pass.** DOOM's BSP tree was two-dimensional and used only for
> drawing. In contrast, Quake's BSP is three-dimensional and used for
> rendering, collision detection, and network visibility. Nearly all of Quake's
> runtime characteristics stem from the expansion of this single data structure
> and the subsequent effort to leverage it fully. [Next: the year of prototypes
> that determined *how* to use it](#sec-2).

## The 1993 feature list as a ceiling

id's DOOM press release from January 1, 1993 is unusually detailed about the
engine's capabilities
([`doom_press_release_1993.txt`](../../../historical/doom_1993/doom_press_release_1993.txt)).
It promotes a "fantastic fully texture-mapped environment," non-orthogonal
walls, light diminishing and sourcing, variable-height floors and ceilings,
environment animation, palette translation, and four-player networked play.
Carmack provides a performance target: "on a 486/33, we're talking 35 frames
per second, fully texture-mapped at normal detail, for a large area of the
screen."

This list merits a second reading, as its omissions are the true focus of this
guide. Notably absent are any mentions of vertical camera movement, rooms
stacked on top of rooms, geometry at angles to the floor, or three-dimensional
creatures. These are not mere oversights in the marketing copy; they lie
outside the representational capabilities of the engine. DOOM's world is
essentially a floor plan with heights attached. Walls are vertical, floors and
ceilings horizontal, and no two sectors can occupy the same footprint at
different elevations.

However, two core commitments from this list carried forward into Quake, and
they warrant mention now as later chapters rely on them. The first is **light
diminishing and light sourcing**—the recognition that lighting is crucial for
environmental immersion and therefore deserves a substantial portion of the
frame budget. Quake's approach is significantly more ambitious and is discussed
in the [surface caching](#sec-3) chapter, but the underlying commitment is
evident here. The second is the section titled **"An Open Game"**:

> When our last hit, WOLFENSTEIN 3D was released the public responded with an
> almost immediate deluge of home-brewed utilities; map editors, sound editors,
> trainers, etc. All without any help on file formats or game layout from Id
> Software. DOOM will be release as an OPEN GAME. We will provide file formats
> and technical notes for anyone who wants them.  — [id Software, DOOM press
> release, 1 January
> 1993](../../../historical/doom_1993/doom_press_release_1993.txt)

This 1993 statement articulates an architectural policy that Quake takes much
further, from published file formats to a shipped bytecode virtual machine with
the game logic compiled into a replaceable `progs.dat`. The [QuakeC
VM](frame:the-quakec-vm) can be seen as a descendant of this policy. {inferred}
The [QuakeC chapter](#sec-6) explores this lineage.

## A binary tree in two dimensions

DOOM's central data structure was a BSP tree, and Carmack's use of it
popularized the technique. Michael Abrash, writing in 1995 while working with
Carmack, explicitly notes the dimensionality: while searching for Quake's
visibility algorithm, Carmack "spent a week on this, as a byproduct devising a
perfect DOOM (2-D) visibility architecture, whereby a single, linear walk of a
DOOM BSP tree produces zero-overdraw 2-D visibility" ([*Black Book*, ch. 64,
"Quake's Visible-Surface
Determination"](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).
The parenthetical clarification carries weight. A DOOM BSP divides the map with
lines on a plan view; every splitter is a wall segment, and the tree partitions
a floor plan.

This directly constrains the geometry: walls are the map's linedefs, while
floors and ceilings are sector properties the renderer fills in between them.
In his notes accompanying the DOOM source release on December 23, 1997
([`carmack_doom_retrospective.txt`](../../../historical/doom_1993/carmack_doom_retrospective.txt)),
Carmack identified precisely this structure as the element he would change:

> The way the rendering proceded from walls to floors to sprites could be
> collapsed into a single front-to-back walk of the bsp tree to collect
> information, then draw all the contents of a subsector on the way back up the
> tree. It requires treating floors and ceilings as polygons, rather than just
> the gaps between walls, and it requires clipping sprite billboards into
> subsector fragments, but it would be The Right Thing.  — [John Carmack, DOOM
> source release notes, 23 December
> 1997](../../../historical/doom_1993/carmack_doom_retrospective.txt)

Quake eliminates this constraint at the root of the representation. Its
splitting planes carry a full normal vector, not an implied vertical: {code}

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

The critical difference is that `normal` is a `vec3_t`. Polygons can be
oriented at any angle, enabling ramps and arbitrary architecture; leaves are
convex volumes rather than convex floor regions, allowing rooms to stack; and
the tree can resolve queries about points anywhere in 3D space, not just points
on a plan. The tradeoff is a significantly more complex compile process.
Abrash's [chapter 60, "Compiling BSP
Trees"](../../../historical/abrash_black_book/black-book.html#chapter-60-compiling-bsp-trees)
constructs one in two dimensions, over line segments, to illustrate the
technique; building one over arbitrary 3D polygons is the responsibility of
`qbsp`, and the splitter heuristic that made it feasible is documented in
[chapter
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination).
The more challenging consequence is visibility, which [the year of discarded
renderers](#sec-2) covers. The [on-disk BSP format](frame:on-disk-bsp-format)
and the [node and leaf graph it loads
into](frame:loading-in-model-c-from-disk-lumps-to-the-mnode-t-mleaf-t-graph)
are detailed in Life of a Frame.

## The BSP used only for drawing

The dimensional change is the obvious difference. The more impactful one is
what the tree is *used* for, and here the best source is Carmack's assessment
of his own code four years later:

> The movement and line of sight checking against the lines is one of the
> bigger misses that I look back on. It is messy code that had some failure
> cases, and there was a vastly simpler (and faster) solution sitting in front
> of my face. I used the BSP tree for rendering things, but I didn't realize at
> the time that it could also be used for environment testing.  — [John
> Carmack, DOOM source release notes, 23 December
> 1997](../../../historical/doom_1993/carmack_doom_retrospective.txt)

In DOOM, the BSP tree was constructed for the renderer. Movement and hitscan
traversed the linedefs via the blockmap; line of sight walked the BSP. Quake
unifies rendering and environment testing around the same compiled map
geometry: rendering traverses the render BSP, while collision traverses one of
the pre-expanded clip hulls, reusing the map's planes. Life of a Frame covers
the mechanism in detail:
[`SV_RecursiveHullCheck`](frame:sv-recursivehullcheck-the-trace) is the
descent, and [contents
types](frame:contents-types-collision-hulls-vs-render-nodes) explain how the
engine separates render nodes and collision hulls.

Carmack's retrospective proceeds directly to the cost of this approach:

> Sweeping volumes for movement gets a bit tougher, and touches on many of the
> challenges faced in quake / quake2 with edge bevels on polyhedrons.  — [John
> Carmack, DOOM source release notes, 23 December
> 1997](../../../historical/doom_1993/carmack_doom_retrospective.txt)

This is the genesis of one of Quake's most distinctive and least intuitive
structures. Sweeping a player-sized box through a 3D tree is genuinely
challenging; reducing that box to a *point* moving through a tree whose solid
volumes have been pre-expanded by the box's dimensions is straightforward and
reuses the descent unchanged. Consequently, `qbsp` compiles not one tree but
several, and each model carries all of them:

```c
// WinQuake/model.h:355
	hull_t		hulls[MAX_MAP_HULLS];
```

with `MAX_MAP_HULLS` set to 4 in `WinQuake/bspfile.h:24`. The world model uses
hulls 0, 1, and 2; slot 3 is unused by the original runtime. `SV_HullForEntity`
selects between them based solely on width (`WinQuake/world.c:147-153`): under
3 units gets the point hull, up to 32 gets hull 1, and anything larger gets
hull 2. As a result, players and most monsters share hull 1, which is 32x32x56;
hull 2, at 64x64x88, is for large monsters (`WinQuake/model.c:959-981`).

This explains why body sizes come in discrete classes rather than being
arbitrary per-entity dimensions: collision volumes are compiled into the map,
not computed at runtime. This constraint also governed crouching. Hull 1's
vertical extent is standing height, and reducing an entity's bounding box at
runtime does not alter the map hull traced against; crouching would have
required its own compiled hull. Slot 3 was reserved in the format for a fourth
hull, but id never populated it, and the archive does not document why. The
[three hulls](frame:the-three-hulls) and how an entity [selects or fabricates
one](frame:sv-hullforentity-picking-or-fabricating-a-hull) are covered in Life
of a Frame. The "edge bevels" Carmack mentions are the correction needed to
maintain convex expanded polyhedra—a detail that only becomes an issue once you
commit to this strategy.

The third use of the tree has no direct analog in DOOM. Because a leaf is a
volume, and because visibility between volumes can be computed offline, the
same spatial structure that answers "what do I draw" can answer "what does this
client need to be told about." Quake's server gates entity updates on the
[potentially visible set](frame:how-the-server-also-uses-pvs-sv-fatpvs) of the
leaf each client occupies. This is a networking decision built on a rendering
data structure, and the [shipping-constraints](#sec-5) chapter investigates how
dialup bandwidth influenced it.

## Announced as a design, not an engine

Quake was public long before it was real. John Romero's `.plan` from March 18,
1994 announces it by name, with a subtitle, a comparison, and a start date
([`john_romero/1994-03-18.txt`](../../../historical/plans/john_romero/1994-03-18.txt)):

> **.plan.** The next game is going to blow DOOM all to hell. DOOM totally
> sucks in comparison to our next game, QUAKE: The Fight for Justice! QUAKE is
> going to be a bigger step over DOOM than DOOM was over Wolf3D (ya know --
> DOOM = pong). We won't start developing QUAKE until Fall'94, due to Jaguar
> DOOM (Comlynxed!), commercial DOOM (COMPUSA, Babbage's, etc.) and maybe a
> DOOM level pack.  — [John Romero, .plan, 18 March
> 1994](../../../historical/plans/john_romero/1994-03-18.txt)

Two aspects stand out. The first is the ambition, expressed as a ratio rather
than a feature: the leap from DOOM to Quake was intended to be at least as
significant as the leap from Wolfenstein to DOOM. Wolfenstein's walls were
axis-aligned and eight feet thick; DOOM's could be at any angle and any
thickness. The announcement does not specify what the next leap would entail;
the shipped engine made it a full third dimension. {inferred} The chapters on
[discarded renderers](#sec-2) and [surface caching](#sec-3), followed by the
[one-processor](#sec-4) chapter, describe the cost.

The second is the timeline. Quake was announced in March 1994, development was
not scheduled to begin until autumn, and the game shipped in June 1996. Abrash
did not join id until March 1995 ([*Black Book*, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)),
by which point "John already had an engine prototyped and a plan in mind"
([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination))—a
plan that [the year of discarded renderers](#sec-2) examines and that largely
failed to survive contact with the problem. The subtitle *The Fight for
Justice* did not survive either. What shipped shares an ambition with the
announcement and little else, a useful calibration of how much of Quake's
design was intended in advance and how much was discovered under deadline.

The same `.plan` incidentally records the development environment—"To get the
entire world running NEXTSTEP for development" ([Romero, .plan, 18 March
1994](../../../historical/plans/john_romero/1994-03-18.txt)). NeXTSTEP explains
the presence of a `NeXT` build path in the source and the manner in which the
tools are written.

## What Quake had to close

Comparing the two announcements yields a concrete list of what changed, which
structures the remainder of this guide around its costliest items:

| DOOM (1993) | Quake (1996) | Where the cost landed | | --- | --- | --- | |
| 2-D BSP over a floor plan | 3-D BSP over arbitrary planes | Map compile time; a much harder visibility problem ([ch. 2](#sec-2)) |
| Camera fixed to the horizon | [Free pitch, roll and view offsets](frame:view-setup-bob-punchangle-and-color-shifts-view-c) | No screen-space shortcuts; perspective texturing ([ch. 4](#sec-4)) |
| Sprites for monsters and players | [Interpolated triangle models](frame:alias-models-r-drawaliasmodel-and-gl-mesh-c-strips-fans) | Per-frame vertex transform and lighting |
| Light per sector, per band | [Per-surface lightmaps](frame:lightmaps-and-light-styles-r-light-c) | Offline light compile; surface caching to afford it ([ch. 3](#sec-3)) |
| BSP used for rendering only | Same compiled map geometry for render, collision, and network | Expanded hulls; PVS as a bandwidth policy ([ch. 5](#sec-5)) |
| ~3,000 polygons per level | ~10,000 polygons per level | Overdraw becomes the dominant cost ([ch. 2](#sec-2)) |
| 35 Hz fixed timebase | [Variable frame time, 20 Hz server tick](frame:host-filtertime-what-host-frametime-actually-means) | Interpolation on the client |

The table's polygon counts come from Abrash: "a good-sized Quake level contains
on the order of 10,000 polygons, about three times as many polygons as a
comparable DOOM level" ([ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).
The 35 Hz timebase comes from Carmack's retrospective notes, which identified
DOOM's fixed tick as an obstacle to hardware acceleration. In Quake, variable
frame rates decoupled rendering from server simulation: the host runs on a
measured frame delta while a dedicated server targets `sys_ticrate` (a listen
server runs one server tick per accepted host frame), requiring clients to
[interpolate entity
positions](frame:entity-interpolation-entity-t-cl-mtime-cl-relinkentities)
between received network states.

One caveat regarding the evidence in this chapter. The retrospective quoted
above was written in December 1997—after both Quake and Quake II. It is
reliable testimony about how Carmack understood DOOM's limits *in hindsight*,
and it aligns well with what Quake actually does, but it is not evidence of
what he intended in 1994. The contemporaneous record of that period is sparse:
the March 1994 `.plan` is the announcement, and there is no public design
document between it and Abrash's arrival a year later. Where this guide
describes intent before March 1995, it is inferred from the shipped code and
stated as such.

## Further reading

- id Software, DOOM press release, 1 January 1993—the feature list as a
  statement of scope:
  [`docs/historical/doom_1993/doom_press_release_1993.txt`](../../../historical/doom_1993/doom_press_release_1993.txt)
- John Carmack, DOOM source release notes, 23 December 1997—his own assessment
  of the engine's misses:
  [`docs/historical/doom_1993/carmack_doom_retrospective.txt`](../../../historical/doom_1993/carmack_doom_retrospective.txt)
- John Romero, `.plan`, 18 March 1994—the Quake announcement:
  [`docs/historical/plans/john_romero/1994-03-18.txt`](../../../historical/plans/john_romero/1994-03-18.txt)
- Michael Abrash, *Graphics Programming Black Book*, ch. 60, "Compiling BSP
  Trees"—a BSP compiler built in two dimensions, over line segments, and how
  Abrash came to id: [local
  copy](../../../historical/abrash_black_book/black-book.html#chapter-60-compiling-bsp-trees);
  also https://www.jagregory.com/abrash-black-book/
- Michael Abrash, *Graphics Programming Black Book*, ch. 64, "Quake's
  Visible-Surface Determination"—DOOM's 2-D tree contrasted with Quake's, and
  the polygon budgets: [local
  copy](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)
- John Romero, id Software founding history—context on the Wolfenstein-to-DOOM
  step:
  [`docs/historical/idnews/id_history.txt`](../../../historical/idnews/id_history.txt)
- Fabien Sanglard, "Quake Source Code Review":
  https://fabiensanglard.net/quakeSource/index.php
- Matthew Earl (Matt's Ramblings), "Uncovering Quake's unseen collision hulls"
  (2025)—the expanded hulls visualised against the render geometry:
  https://www.youtube.com/watch?v=3KjMjHJ3WQg
- Matthew Earl (Matt's Ramblings), "BSP Trees: The Magic Behind Collision
  Detection in Quake" (2023)—the trace as a tree descent:
  https://www.youtube.com/watch?v=wLHXn8IlAiA
- David Kushner, *Masters of Doom* (Random House, 2003, ISBN
  978-0812972153)—narrative history of id through Quake's release. Secondary
  and journalistic; good for people and chronology, not for technical claims.
