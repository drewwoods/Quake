# The Year of Discarded Renderers

Between March 1995 and the middle of 1996, Quake's visible-surface determination was rebuilt from scratch repeatedly. A beam tree was written, tuned, and abandoned. At least five other approaches were prototyped or seriously argued and dropped. The design that shipped — precompute, for every leaf in the map, the set of leaves potentially visible from it, then at runtime draw only those — was not on the original plan and arrived roughly a year in. This chapter follows that sequence, because the shape of the surviving code is unintelligible without it: the potentially visible set looks like an obvious idea in hindsight, and reading it as an obvious idea gets its cost model exactly backwards.

> **First pass.** Quake's problem was never "how do I draw a polygon fast." It was overdraw: in a ten-thousand-polygon level most of what is inside the view frustum is hidden behind something else, and drawing it anyway is wasted work that scales with level complexity. Every discarded approach here is an attempt to find the visible set at runtime. The one that shipped gave up and moved the work offline. Next: what that decision made affordable.

## The problem, stated precisely

Abrash defines the target in [chapter 64, "Quake's Visible-Surface Determination"](../../../historical/abrash_quake_1995/chapter-64.md), and the definition is worth keeping in mind because every rejected approach failed against one clause of it:

> The process of VSD would ideally work as follows: First, you would cull all polygons that are completely outside the view frustum (view pyramid), and would clip away the irrelevant portions of any polygons that are partially outside. Then, you would draw only those pixels of each polygon that are actually visible from the current viewpoint [...] Finally, in a perfect world, the tests to figure out what parts of which polygons are visible would be free, and the processing time would be the same for all possible viewpoints, giving the game a smooth visual flow.

Two of those three clauses were already solved. Frustum culling is cheap against a BSP, because each *node* bounds a convex subspace, so rejecting a node rejects every polygon beneath it at once. Correct draw order is free, because BSP leaves can be walked front-to-back or back-to-front by construction. What remained was the middle clause and, critically, the last one.

The last clause is the one that does the damage. A painter's-algorithm renderer draws every polygon in the frustum, hidden or not; Abrash estimates worst-case overdraw in a Quake level "10 times or more," meaning each pixel written ten times on average. The problem is not only that this is slow. It is that best case and worst case diverge, so the frame rate swings as the player turns. A design that is fast in a corridor and unplayable in an atrium has not solved the problem.

> **.plan.** In terms of graphics, Quake is to DOOM as DOOM was to its predecessor, Wolfenstein 3-D. [...] Already, a good-sized Quake level contains on the order of 10,000 polygons, about three times as many polygons as a comparable DOOM level. — Abrash, [ch. 64](../../../historical/abrash_quake_1995/chapter-64.md)

## The prototype, and how long it lasted

Abrash joined id in March 1995, expecting to optimize an existing design:

> When I arrived at id at the beginning of March 1995, John already had an engine prototyped and a plan in mind, and I assumed that our work was a simple matter of finishing and optimizing that engine. If I had been aware of id's history, however, I would have known better.

The correction is the useful part. By Abrash's count Carmack had by then written "perhaps 20 distinct engines over a four-year period," including "four engines in four weeks" on one occasion. Rewriting the renderer was the normal state of the project, not a crisis in it. Three months after Abrash arrived, "only one element of the original VSD design was anywhere in sight."

This is the single most important piece of context for reading Quake's source. The code is not a first draft that was optimized; it is the last survivor of a long elimination.

## The beam tree

The original design drew front-to-back and tracked, in a second BSP tree, which parts of the screen were still unpainted. That tree was three-dimensional: a *beam tree*, a set of wedges bounded by planes radiating from the viewpoint.

It starts as one beam — the frustum — with everything outside marked solid and the inside empty. Walking the world tree front-to-back, each polygon is converted into a beam by running planes from its edges through the viewpoint. Whatever part of that beam intersects empty space in the beam tree is visible; it gets drawn and added to the beam tree as solid. When the beam tree is entirely solid, nothing further can be visible and the walk stops.

The reason to use 3-D beams rather than a 2-D screen region is arithmetic. Every beam plane passes through the viewpoint, so testing a vertex against one is a dot product with the plane normal and a sign check, and generating a beam from a polygon edge is a single cross product. There is no projection and no division in the inner test.

It failed on the last clause of the specification. The early-out looks like it caps the worst case, but a view across the top of a level, or out to the sky, never fills the beam tree, so every polygon in the frustum gets tested. Numerical precision left thin cracks that also prevented the tree closing. Abrash's verdict:

> in scenes with long view distances, such as views across the top of a level, the total cost of beam processing slowed Quake's frame rate to a crawl. So, in the end, the beam-tree approach proved to suffer from much the same malady as the painter's algorithm: The worst case was much worse than the average case, and it didn't scale well with increasing level complexity.

## Five that did not ship

Abrash lists the alternatives that were prototyped "in overnight or weekend-long bursts of coding" or argued and dropped. They are worth recording individually, because each one fails differently and the failures map the design space.

**Subdividing raycast.** Cast rays on an 8×8 screen grid — cheap, because a ray is just a clip into the BSP tree until it reaches a solid leaf. Where adjacent rays hit different surfaces, cast another between them, recursively, until neighbours agree or are adjacent pixels. This scales with pixel count rather than polygon count, and has no overdraw at all: exactly the right scaling behaviour. It was rejected for correctness, not speed — small polygons can fall between rays and disappear.

**Vertex-free surfaces.** Store the world as planes only, and extract polygons from plane intersections just before drawing. Clipping becomes fast and the dataset shrinks considerably, since a plane is far more compact than a polygon. Rejected because extracting polygons from planes is expensive at exactly the wrong moment. Note that the shipped format keeps the compact-plane idea in a weaker form — planes are shared and deduplicated in the [on-disk BSP](frame:on-disk-bsp-format) — without paying the extraction cost.

**The draw-buffer.** A one-bit-per-pixel z-buffer recording only whether a pixel has been written. This eliminates overdraw, at the cost of a test in the inner loop, extra writes, cache misses, and, in Abrash's summary, "considerable complexity." The variations considered are a good illustration of how far the search went: test the buffer a byte at a time and skip fully-occluded bytes, or branch from each byte into one of 256 unrolled loops for drawing 0–8 pixels, using the spare cycles to run the perspective divide in parallel.

**Span-based drawing.** Rasterize polygons into spans, clip each new span against a global span list, keep only the nearest at each pixel. Front-to-back walking means little sorting is needed — if there is overlap, the span already in the list is nearer. No overdraw, but every polygon still has to be turned into spans, and the span arithmetic is substantial. This one did not die: it is the ancestor of the [edge list and span sorting](frame:software-renderer-edge-based-visible-surface-determination) that shipped, and the section below returns to it.

**Portals.** Track the holes in surfaces, since line-of-sight only extends through them. Draw front-to-back; on reaching a portal, clip the polygons and portals behind it to its limits, recursively, until nothing visible remains. This draws only the visible parts of visible polygons — the ideal — but pays for it in a great deal of portal clipping.

The portal approach is the one to keep in view, because the shipped design is a precomputed version of it.

## The breakthrough

Carmack next tried extracting visibility directly from the world BSP tree, reasoning that the beam tree was a second-order structure holding information the world tree already contained implicitly. A week of that produced, as a side effect, a perfect zero-overdraw visibility algorithm for *two-dimensional* DOOM trees — and, in three dimensions, mounting complexity and persistent glitches. Abrash's account of the weekend that followed is the most-quoted passage in the chapter:

> When I came in on Monday, John had the look of a man who had broken through to the other side—and also the look of a man who hadn't had much sleep. [...] At 3:30 Monday morning, as he lay in bed, thinking about portals, he thought of precalculating and storing in each leaf a list of all leaves visible from that leaf, and then at runtime just drawing the visible leaves back-to-front for whatever leaf the viewpoint happens to be in, ignoring all other leaves entirely.

The move is to stop computing visibility and start looking it up. Every runtime approach above was an attempt to make the visibility calculation cheaper; this one deletes it. Abrash draws the general lesson through a colleague's aphorism — "almost all programming can be viewed as an exercise in caching" — and calls the reframing the inspired part, rather than the algorithm.

One correction the chapter itself supplies, and which this guide should not sand off: Carmack did not experience it as a eureka. Abrash reports him saying "precalculating the PVS was a logical evolution of the approaches he had been considering, that there was no moment when he said 'Eureka!'" The dramatic version is Abrash's framing of a colleague's work; the participant's version is that it fell out of a week of thinking about portals. Both are in the same paragraph, and the disagreement is itself informative about how such designs actually arrive.

Nor was the underlying idea unprecedented. Abrash's own reference list for the chapter cites Seth Teller's *Visibility Preprocessing for Interactive Walkthroughs* (SIGGRAPH 91) and his dissertation on visibility in densely occluded polyhedral environments. The archive does not record whether that work was an input; it does establish that precomputed visibility was known in the literature, and that the achievement was making it fit in a 1996 consumer product.

## Making it fit

A first implementation was several megabytes — unusable when the whole game had to run in 8 MB. Four changes brought it down to roughly 20 KB for a good-sized level:

1. Store the set as a bit vector, one bit per leaf, rather than a list.
2. Compress it with run-length encoding of zero bytes, which works extremely well because the rows are sparse. Life of a Frame covers [the decompressor](frame:mod-leafpvs-mod-decompressvis-rle-decompression).
3. Change the BSP splitter heuristic to produce fewer leaves. Abrash: "choosing as the next splitter the polygon that splits the fewest other polygons appears to be the best heuristic."
4. Seal the outside of levels, so the compiler can discard exterior surfaces that can never be seen.

The fourth is the origin of a rule every Quake mapper has met: a level with a hole in it fails to compile, because the visibility computation has no bounded outside. That constraint is not arbitrary strictness — it is what makes the surface count, and therefore the leaf count, and therefore the size of the visibility data, tractable. The format reserves a megabyte for it (`MAX_MAP_VISIBILITY` at `WinQuake/bspfile.h:44`) against real usage of about a fiftieth of that.

## What it bought, and what it cost

The PVS is deliberately imprecise. It records what is visible from *anywhere* in a leaf, not from the actual viewpoint, so it over-reports. Abrash gives the resulting overdraw as "typically on the order of 50 percent but ranging up to 150 percent."

That inaccuracy is the entire point. Every rejected approach bought precision with runtime work that grew with scene complexity; the PVS accepts bounded imprecision in exchange for a lookup. The payoff is in the third clause of the original specification:

> precalculating the PVS results in a leveling of performance; worst case is no longer much worse than best case, because there's no longer extra VSD processing—just more polygons and perhaps some extra overdraw—associated with complex scenes. The first time John showed me his working prototype, I went to the most complex scene I knew of, a place where the frame rate used to grind down into the single digits, and spun around smoothly, with no perceptible slowdown.

The cost moved to the map toolchain, where it is paid once by the author rather than sixty times a second by the player. That trade is why `vis` is slow enough to have its own folklore, and Carmack's `.plan` of 27 August 1996 records a full-size lighting job needing `vis` to have run first or take "about 1000 times longer," with a working set above 100 MB. Life of a Frame covers [how the runtime consumes the result](frame:r-markleaves-visframe-and-r-novis); the GL path keeps a `r_novis` cvar (`WinQuake/gl_rmain.c:86`) that switches the whole mechanism off, which is the fastest way to feel what it does.

## The PVS stops being a renderer feature

The clearest evidence that this was a structural decision rather than a rendering optimization is what happened to it afterwards. Carmack's 1996 worklogs show the PVS being reached for by subsystems that have nothing to do with drawing. The entries are terse and follow a consistent shape, with `*` marking completed work and `+` marking immediate next steps; a plain line is a backlog item. Tracked across six weeks:

> **.plan.** `PVS for net update` — [15 March 1996, backlog](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt); then `* changed network update to client PVS specific` — [23 April 1996, done](../../../historical/plans/carmack/by_day/johnc_plan_19960423.txt).

That is the moment visibility became a bandwidth policy: the server stopped telling each client about entities the client could not possibly see. The mechanism is [`SV_FatPVS`](frame:how-the-server-also-uses-pvs-sv-fatpvs), and chapter 5 argues that dialup, not elegance, is what forced it. The same worklogs show a fix for a "monster sighting PVS problem" on [11 March](../../../historical/plans/carmack/by_day/johnc_plan_19960311.txt) — gameplay-visible behaviour now depending on the compiled visibility data — and, on [6 April](../../../historical/plans/carmack/by_day/johnc_plan_19960406.txt), Carmack probing for further uses:

> **.plan.** `use PVS to speed line of sight checks? Is that any faster than doing the line check, because it involves two point checks?` — [Carmack, 6 April 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960406.txt)

Note that this one is a question, and that it is asked on cost grounds rather than accepted on principle. It is a useful corrective to the tidy version of this story: by 1996 the PVS was infrastructure, but its applicability was still being evaluated case by case.

## What the PVS did not solve

The PVS answers "which leaves might be visible." It does not answer "which pixels are visible," and its deliberate over-reporting actively creates overdraw. Something still has to resolve the remainder.

That is where span-based drawing, rejected on its own above, returns. Abrash describes the shipped renderer at the end of the chapter as the PVS "together with a still-in-development sorted-edge rasterizer that completely eliminates overdraw." The two halves are complementary: the PVS discards most of the world for free, and the edge list resolves what is left exactly. Neither would have been sufficient alone, and the PVS's tolerance for imprecision is affordable precisely because a zero-overdraw rasterizer sits behind it.

Quake also ends up with a z-buffer after all — not for the world, but filled by it, so that [entities, particles and sprites](frame:alias-models-sprites-particles-and-the-entity-list) can be sorted into the scene without the edge list. The rejected draw-buffer idea survives in a narrowed form, applied only where its costs are affordable.

The mechanism of both is Life of a Frame's subject, not this guide's. What belongs here is the shape of the decision: two mechanisms with different cost models, deliberately combined so that neither has to be perfect.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, ch. 64, "Quake's Visible-Surface Determination" — the primary source for this entire chapter: [local copy](../../../historical/abrash_quake_1995/chapter-64.md); also https://www.jagregory.com/abrash-black-book/
- Michael Abrash, *Graphics Programming Black Book*, ch. 66, "Quake's Hidden-Surface Removal" — the edge list and the limited use of a z-buffer: [local copy](../../../historical/abrash_quake_1995/chapter-66.md)
- Michael Abrash, *Graphics Programming Black Book*, ch. 67, "Sorted Spans in Action" — the span-sorting decision benchmarked: [local copy](../../../historical/abrash_quake_1995/chapter-67.md)
- John Carmack, `.plan` archive, March–August 1996 — the PVS in use as general infrastructure: [15 Mar](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt), [11 Mar](../../../historical/plans/carmack/by_day/johnc_plan_19960311.txt), [6 Apr](../../../historical/plans/carmack/by_day/johnc_plan_19960406.txt), [23 Apr](../../../historical/plans/carmack/by_day/johnc_plan_19960423.txt), [27 Aug](../../../historical/plans/carmack/by_day/johnc_plan_19960827.txt)
- Seth Teller, *Visibility Preprocessing for Interactive Walkthroughs*, SIGGRAPH 91, pp. 61–69, and *Visibility Computations in Densely Occluded Polyhedral Environments* (dissertation) — prior art on precomputed visibility, cited in Abrash's own reference list
- Fabien Sanglard, "Quake Source Code Review" — the runtime side of the PVS: https://fabiensanglard.net/quakeSource/index.php
