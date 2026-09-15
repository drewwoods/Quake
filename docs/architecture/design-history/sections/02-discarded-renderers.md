# The year of discarded renderers

Throughout 1995 and the first half of 1996, Quake's visible-surface
determination algorithm underwent a series of complete reconstructions. A beam
tree was implemented, optimized, and ultimately discarded. At least five other
approaches were prototyped or seriously considered before being abandoned. The
final design, which precomputes the set of potentially visible leaves for each
leaf in the map and then draws only those leaves at runtime, was not part of
the original plan. It emerged a few months after Michael Abrash joined the
team, roughly a year before release. This chapter traces that evolution, as
understanding the surviving code requires knowing its history: the potentially
visible set might seem like an obvious solution in hindsight, but viewing it
that way misses the true cost of the approach.

> **First pass.** Quake's challenge was never "how to draw polygons quickly."
> Rather, it was overdraw: in a level with ten thousand polygons, most of what
> falls inside the view frustum is occluded by other geometry, and drawing it
> anyway wastes work that scales with level complexity. The discarded
> approaches attempted to make world visibility manageable at runtime. The
> shipped design moved that work offline, with runtime rendering still
> resolving pixel visibility. [Next: surface caching and the cost of
> lighting](#sec-3).

## Defining the problem precisely

In [chapter 64, "Quake's Visible-Surface
Determination,"](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)
Abrash lays out the ideal target, and keeping this definition in mind is
crucial because every rejected approach failed to meet one of its requirements:

> The process of VSD would ideally work as follows: First, you would cull all
> polygons that are completely outside the view frustum (view pyramid), and
> would clip away the irrelevant portions of any polygons that are partially
> outside. Then, you would draw only those pixels of each polygon that are
> actually visible from the current viewpoint [...] Finally, in a perfect
> world, the tests to figure out what parts of which polygons are visible would
> be free, and the processing time would be the same for all possible
> viewpoints, giving the game a smooth visual flow.  — [Michael Abrash,
> *Graphics Programming Black Book*, ch.
> 64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)

Two aspects were straightforward. A BSP allows efficient coarse frustum
culling, as each *node* bounds a convex subspace, so rejecting a node rejects
all polygons beneath it. It also provides a front-to-back or back-to-front
traversal order. The difficult parts were the middle clause and, most
crucially, the last one.

The final clause is where the trouble lies. A painter's algorithm renderer
draws every polygon inside the frustum, hidden or not; Abrash estimates that in
a typical Quake level, worst-case overdraw could be "10 times or more"
([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)),
meaning each pixel is written an average of ten times. The issue is not just
the slowdown. It's that best-case and worst-case performance diverge
significantly, causing frame rate to fluctuate as the player's view changes. A
design that runs smoothly in corridors but crawls to a halt in large spaces has
not truly solved the problem.

> **Abrash, ch. 64.** In terms of graphics, Quake is to DOOM as DOOM was to its
> predecessor, Wolfenstein 3-D. [...] Already, a good-sized Quake level
> contains on the order of 10,000 polygons, about three times as many polygons
> as a comparable DOOM level. [Local
> copy](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)

## The prototype's lifespan

When Abrash arrived at id in March 1995, he expected to optimize an existing
design:

> When I arrived at id at the beginning of March 1995, John already had an
> engine prototyped and a plan in mind, and I assumed that our work was a
> simple matter of finishing and optimizing that engine. If I had been aware of
> id's history, however, I would have known better.  — [Michael Abrash,
> *Graphics Programming Black Book*, ch.
> 64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)

The correction is instructive. By Abrash's count, Carmack had by then written
"perhaps 20 distinct engines over a four-year period," including "four engines
in four weeks" on one occasion. Rewriting the renderer was the project's normal
state, not a crisis. Three months after Abrash joined, "only one element of the
original VSD design was anywhere in sight" ([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).

This context is essential for understanding Quake's source code. The code is
not a first draft that was optimized; it is the last survivor of a lengthy
process of elimination.

## The beam tree

The original design rendered front-to-back and maintained a second BSP tree, a
*beam tree*, to track which parts of the screen were still unpainted. This tree
was three-dimensional: a set of wedges bounded by planes radiating from the
viewpoint.

It begins as a single beam — the view frustum — with everything outside marked
solid and the inside empty. Traversing the world tree front-to-back, each
polygon is converted into a beam by running planes from its edges through the
viewpoint. Any part of that beam intersecting empty space in the beam tree is
visible and is added to the beam tree as solid. When the beam tree becomes
entirely solid, nothing further can be visible, and the traversal stops.
Drawing occurs afterwards: once the tree is complete, the visible portions of
the polygons that contributed to it are rasterized.

The reason for using 3-D beams instead of 2-D screen regions is arithmetic
efficiency. Since every beam plane passes through the viewpoint, testing a
vertex against one is just a dot product with the plane normal and a sign
check, and generating a beam from a polygon edge is a single cross product.
There is no projection or division in the inner test ([Michael Abrash,
*Graphics Programming Black Book*, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).
{quoted}

> The advantage to working with a 3-D beam tree, rather than a 2-D region, is
> that determining which side of a beam plane a polygon vertex is on involves
> only checking the sign of the dot product of the ray to the vertex and the
> plane normal, because all beam planes run through the origin (the viewpoint).
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 64, "The Beam
> Tree"](../../../historical/abrash_black_book/black-book.html#the-beam-tree).

::: plate ../../../historical/abrash_black_book/images/64-05.jpg Planes extend
from the viewpoint through a triangle's edges, enclosing a wedge in 3-D. |
**Figure 64.5 — the beam.** Each polygon edge and the viewpoint define a beam
plane. Michael Abrash, *Graphics Programming Black Book*, [chapter
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination),
figure 64.5; original image, unchanged. [Archive and reproduction
note](../../../historical/abrash_black_book/black-book.html#about-this-version).

The beam tree failed to meet the last requirement of the specification. While
early termination appeared to cap the worst case, a view across the top of a level
or out to the sky never filled the beam tree, so every polygon inside the
frustum was tested anyway. Numerical precision also left thin cracks that prevented
the tree from closing completely. Abrash concludes:

> in scenes with long view distances, such as views across the top of a level,
> the total cost of beam processing slowed Quake's frame rate to a crawl. So,
> in the end, the beam-tree approach proved to suffer from much the same malady
> as the painter's algorithm: The worst case was much worse than the average
> case, and it didn't scale well with increasing level complexity.  — [Michael
> Abrash, *Graphics Programming Black Book*, ch.
> 64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)

## Five approaches that did not ship

Abrash lists the alternatives that were prototyped "in overnight or
weekend-long bursts of coding" ([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination))
or considered and rejected. They are worth noting individually, as each one
fails differently, mapping out the design space.

**Subdividing raycast.** Cast rays on an 8×8 screen grid — inexpensive, as a
ray is just a clip into the BSP tree until it reaches a solid leaf. Where
adjacent rays hit different surfaces, cast another ray between them,
recursively, until neighbors agree or are adjacent pixels. This scales with
pixel count rather than polygon count and eliminates overdraw entirely: exactly
the right scaling behavior. It was rejected for correctness, not speed — small
polygons can fall between rays and disappear.

**Vertex-free surfaces.** Store the world as planes only, extracting polygons
from plane intersections just before drawing. Clipping becomes fast, and the
dataset shrinks considerably, as a plane is much more compact than a polygon.
Rejected because extracting polygons from planes is expensive at precisely the
wrong moment. The shipped [on-disk BSP](frame:on-disk-bsp-format) does pool and
share planes, but that is standard BSP optimization rather than a remnant of
this idea: the vertex-free proposal was to not store polygons at all.

**The draw-buffer.** An occlusion bitmap with one bit per pixel, recording only
whether that pixel has been written. This eliminates overdraw at the cost of a
test in the inner loop, extra writes, cache misses, and, in Abrash's summary,
"considerable complexity" ([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).
The variations considered illustrate how far the search went: test the buffer a
byte at a time and skip fully occluded bytes, or branch from each byte into one
of 256 unrolled loops for drawing 0–8 pixels, hoping to overlap the perspective
divide with pixel processing.

**Span-based drawing.** Rasterize polygons into spans, clipping each new span
against a global span list, keeping only the nearest at each pixel.
Front-to-back traversal means little sorting is needed — if there is overlap,
the span already in the list is nearer. No overdraw, but every polygon still
has to be turned into spans, and the span arithmetic is substantial. This is
the closest of the five to what shipped. The [edge list and span
sorting](frame:software-renderer-edge-based-visible-surface-determination) in
the final renderer belong to the same family, though Abrash arrives at edge
sorting separately in chapters 66 and 67 rather than by reviving this proposal.
The section below returns to it.

**Portals.** Track the holes in surfaces, as line-of-sight only extends through
them. Draw front-to-back; on reaching a portal, clip the polygons and portals
behind it to its limits, recursively, until nothing visible remains. This draws
only the visible parts of visible polygons — the ideal — but pays for it with
extensive portal clipping.

The portal approach is the one to keep in mind: the shipped PVS preserves its
connectivity insight but precomputes visibility per leaf instead of clipping
portals at runtime.

::: diagram discarded-renderers

## The breakthrough

Carmack next tried extracting visibility directly from the world BSP tree,
reasoning that the beam tree was a second-order structure holding information
the world tree already contained implicitly. A week of that produced, as a side
effect, a perfect zero-overdraw visibility algorithm for *two-dimensional* DOOM
trees — and, in three dimensions, mounting complexity and persistent glitches.
Abrash's account of the weekend that followed is the chapter's most-quoted
passage:

> When I came in on Monday, John had the look of a man who had broken through
> to the other side—and also the look of a man who hadn't had much sleep. [...]
> At 3:30 Monday morning, as he lay in bed, thinking about portals, he thought
> of precalculating and storing in each leaf a list of all leaves visible from
> that leaf, and then at runtime just drawing the visible leaves back-to-front
> for whatever leaf the viewpoint happens to be in, ignoring all other leaves
> entirely.  — [Michael Abrash, *Graphics Programming Black Book*, ch.
> 64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)

The shift was to stop computing world visibility at runtime and start looking
it up. The discarded approaches tried to make that calculation cheaper; the PVS
removes it from the frame loop entirely. Abrash draws the general lesson
through a colleague's aphorism — "almost all programming can be viewed as an
exercise in caching" ([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination))
— and credits the reframing as the inspired part, rather than the algorithm
itself.

The archive does not provide an exact date for this, but it can be bounded:
Abrash joined in March 1995; chapter 64, written "several months" into his time
there with "a few more months to go" ([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)),
describes the PVS prototype as already working and was published while Quake
was still unshipped; the game shipped in June 1996. That places the
breakthrough in 1995, most likely around the middle of the year and thus
roughly a year before release. The archive supports no tighter estimate than
that. {inferred}

Abrash records a key correction: Carmack did
not experience it as a eureka moment. Abrash reports him saying "precalculating
the PVS was a logical evolution of the approaches he had been considering, that
there was no moment when he said 'Eureka!'" ([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).
The dramatic version is Abrash's framing of a colleague's work; the
participant's version is that it was a logical next step. Note also what the
preceding week was actually spent on: extracting visibility directly from the
world BSP tree, not portals. Portals enter the picture at 3:30 Monday
morning, as the subject Carmack was pondering when the precomputation idea
emerged. Abrash reports both accounts within a few paragraphs of each other,
and the gap between them reveals something about how such designs come about.

Nor was the underlying concept unprecedented. Abrash's own reference list for
the chapter cites Seth Teller's *Visibility Preprocessing for Interactive
Walkthroughs* (SIGGRAPH 91) and his dissertation on visibility in densely
occluded polyhedral environments. The archive does not record whether that work
was an input; it does establish that precomputed visibility was known in the
literature, and that the achievement was making it fit in a 1996 consumer
product.

## Making it fit

Abrash reports that the first raw, uncompressed PVS was several megabytes. Four
changes brought it down to roughly 20 KB for a good-sized level ([Michael
Abrash, *Graphics Programming Black Book*, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)):
{quoted}

> Size was a concern; initially, a raw, uncompressed potentially visible set
> (PVS) was several megabytes in size. […] Those steps, along with changing the
> BSP heuristic to generate fewer leaves (choosing as the next splitter the
> polygon that splits the fewest other polygons appears to be the best
> heuristic) and sealing the outside of the levels so the BSPer can remove the
> outside surfaces, which can never be seen, eventually brought the PVS down to
> about 20 Kb for a good-size level.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 64,
> "Breakthrough!"](../../../historical/abrash_black_book/black-book.html#breakthrough).

1. Store the set as a bit vector, one bit per leaf, rather than a list.
2. Compress it with run-length encoding of zero bytes, which works extremely well because the rows are sparse. Life of a Frame covers [the decompressor](frame:mod-leafpvs-mod-decompressvis-rle-decompression).
3. Change the BSP splitter heuristic to produce fewer leaves. Abrash: "choosing as the next splitter the polygon that splits the fewest other polygons appears to be the best heuristic" ([Abrash, ch. 64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).
4. Seal the outside of levels, so the compiler can discard exterior surfaces that can never be seen.

The fourth point explains a rule every Quake mapper has encountered: a leak
prevents the normal sealed-world BSP/PVS build from producing valid visibility
data. That constraint is not arbitrary strictness — it is what makes the
surface count, and therefore the leaf count, and therefore the size of the
visibility data, manageable. The format allows up to a megabyte for it
(`MAX_MAP_VISIBILITY` at `WinQuake/bspfile.h:44`), while the cited good-sized
level used about a fiftieth of that.

## What it bought, and what it cost

The PVS is deliberately imprecise. It records what is visible from *anywhere*
in a leaf, not from the actual viewpoint, so it over-reports. Abrash gives the
resulting overdraw as "typically on the order of 50 percent but ranging up to
150 percent" ([Michael Abrash, *Graphics Programming Black Book*, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).
{quoted}

> the PVS for a leaf includes all leaves visible from anywhere in the leaf, so
> some overdraw, typically on the order of 50 percent but ranging up to 150
> percent, generally occurs
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 64,
> "Breakthrough!"](../../../historical/abrash_black_book/black-book.html#breakthrough).

::: plate ../../../historical/abrash_black_book/images/64-02.jpg Overhead map
rays from the viewpoint bound a viewing wedge; heavy wall segments mark only
the portions visible through gaps between solid blocks. | **Figure 64.2 — exact
visibility from one viewpoint.** The PVS is coarser: it admits leaves visible
from anywhere in the viewer's leaf. This is the chapter's exact-visibility
illustration, not a PVS diagram. Michael Abrash, *Graphics Programming Black
Book*, [chapter
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination),
figure 64.2; original image, unchanged. [Archive and reproduction
note](../../../historical/abrash_black_book/black-book.html#about-this-version).

That inaccuracy is the whole point. Every rejected approach bought precision
with runtime work that grew with scene complexity; the PVS accepts bounded
imprecision in exchange for a lookup. The payoff is in the third clause of the
original specification:

> precalculating the PVS results in a leveling of performance; worst case is no
> longer much worse than best case, because there's no longer extra VSD
> processing—just more polygons and perhaps some extra overdraw—associated with
> complex scenes. The first time John showed me his working prototype, I went
> to the most complex scene I knew of, a place where the frame rate used to
> grind down into the single digits, and spun around smoothly, with no
> perceptible slowdown.  — [Michael Abrash, *Graphics Programming Black Book*,
> ch.
> 64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)

The cost moved to the map toolchain, where it is paid once by the author rather
than on every frame by the player. That trade is why `vis` is slow enough
to have its own folklore. The archive does not quantify `vis` itself, but it
does show the stage becoming a prerequisite for the rest of the toolchain:
Carmack's [`.plan` of 27 August
1996](../../../historical/plans/carmack/by_day/johnc_plan_19960827.txt),
describing his new radiosity lighting tool, notes that "you MUST do a vis
before running qrad (otherwise it would take about 1000 times longer)." The
thousandfold increase and the tool's 100 MB working set are qrad's, not
`vis`'s. The same entry ends with him wanting "to look into" the algorithmic
order of full `vis` processing, "especially now that the vis stage is put
before production lighting." Life of a Frame covers [how the runtime consumes
the result](frame:r-markleaves-visframe-and-r-novis); the GL path keeps a
`r_novis` cvar (`WinQuake/gl_rmain.c:86`) that switches the whole mechanism
off, which is the fastest way to feel what it does.

## The PVS stops being a renderer feature

The clearest evidence that this was a structural decision rather than a
rendering optimization is what happened to it afterwards. Carmack's 1996
worklogs show subsystems that have nothing to do with drawing reaching for the
PVS. The entries are terse and follow a consistent shape, with `*` marking
completed work and `+` marking immediate next steps; a plain line is a backlog
item. Tracked across six weeks:

> **.plan.** `PVS for net update` — [15 March 1996,
> backlog](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt);
> then `* changed network update to client PVS specific` — [23 April 1996,
> done](../../../historical/plans/carmack/by_day/johnc_plan_19960423.txt).

That is the moment visibility became a bandwidth policy: the server stopped
telling each client about entities the client could not possibly see. The
mechanism is [`SV_FatPVS`](frame:how-the-server-also-uses-pvs-sv-fatpvs), and
the [shipping-constraints](#sec-5) chapter examines how dialup shaped it. The
same worklogs carry a one-line done-item, "fixed monster sighting PVS problem,"
on [11
March](../../../historical/plans/carmack/by_day/johnc_plan_19960311.txt). That
reads like gameplay-visible behavior depending on compiled visibility data, but
a single worklog line will not carry the claim on its own, and the archive says
nothing further about it. On [6
April](../../../historical/plans/carmack/by_day/johnc_plan_19960406.txt)
Carmack probes for further uses:

> **.plan.** `use PVS to speed line of sight checks? Is that any faster than
> doing the line check, because it involves two point checks?` — [Carmack, 6
> April 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960406.txt)

Note that this one is a question, and that it is asked on cost grounds rather
than accepted on principle. It is a useful corrective to the tidy version of
this story: by 1996 the PVS was infrastructure, but its applicability was still
being evaluated case by case.

## What the PVS did not solve

The PVS answers "which leaves might be visible." It does not answer "which
pixels are visible," and its deliberate over-reporting actively creates
overdraw. Something still has to resolve the remainder.

That is where span-based drawing, rejected on its own above, returns. Abrash
describes the shipped renderer at the end of the chapter as the PVS "together
with a still-in-development sorted-edge rasterizer that completely eliminates
overdraw" ([Abrash, ch.
64](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination)).
The two halves are complementary: the PVS discards most of the world for free,
and the edge list resolves what is left exactly. Neither would have been
sufficient alone, and the PVS's tolerance for imprecision is affordable
precisely because a zero-overdraw rasterizer sits behind it.

Quake still uses a depth buffer for [entities, particles and
sprites](frame:alias-models-sprites-particles-and-the-entity-list). The world
writes depth as it is rasterized, so dynamic geometry can be tested per pixel
without making the world depend on a general z-buffer. That is a separate
decision, reached in chapter 66, not the rejected draw-buffer coming back: the
draw-buffer was a one-bit occlusion mask for the *world*, and this is per-pixel
depth for everything drawn after it. What they share is the recognition that an
occlusion structure is affordable once it covers only the geometry that needs
one.

The implementation details belong in Life of a Frame. The design decision is
the cost split: the PVS discards most of the world cheaply, while the edge list
and depth buffer resolve what remains at runtime.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, ch. 64, "Quake's
  Visible-Surface Determination" — the primary source for this entire chapter:
  [local
  copy](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination);
  also https://www.jagregory.com/abrash-black-book/
- Michael Abrash, *Graphics Programming Black Book*, ch. 66, "Quake's
  Hidden-Surface Removal" — the edge list and the limited use of a z-buffer:
  [local
  copy](../../../historical/abrash_black_book/black-book.html#chapter-66-quakes-hidden-surface-removal)
- Michael Abrash, *Graphics Programming Black Book*, ch. 67, "Sorted Spans in
  Action" — the span-sorting decision benchmarked: [local
  copy](../../../historical/abrash_black_book/black-book.html#chapter-67-sorted-spans-in-action)
- John Carmack, `.plan` archive, March–August 1996 — the PVS in use as general
  infrastructure: [11
  Mar](../../../historical/plans/carmack/by_day/johnc_plan_19960311.txt), [15
  Mar](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt), [6
  Apr](../../../historical/plans/carmack/by_day/johnc_plan_19960406.txt), [23
  Apr](../../../historical/plans/carmack/by_day/johnc_plan_19960423.txt), [27
  Aug](../../../historical/plans/carmack/by_day/johnc_plan_19960827.txt)
- Seth Teller, *Visibility Preprocessing for Interactive Walkthroughs*,
  SIGGRAPH 91, pp. 61–69, and *Visibility Computations in Densely Occluded
  Polyhedral Environments* (dissertation) — prior art on precomputed
  visibility, cited in Abrash's own reference list
- Fabien Sanglard, "Quake Source Code Review" — the runtime side of the PVS:
  https://fabiensanglard.net/quakeSource/index.php
- **Visual explainers.** Secondary readings of the same code and archive — good
  for intuition, not evidence:
  - Matthew Earl (Matt's Ramblings), "Quake's PVS: A hidden gem of rendering
    optimization" — the portal graph and the leaf-to-leaf visibility bitmap,
    animated: https://www.youtube.com/watch?v=IfCRHSIg6zo
  - Matthew Earl (Matt's Ramblings), "How Quake's software renderer ELIMINATES
    overdraw" — the edge list and span sorting, visualised. Title carries a
    flashing-images warning: https://www.youtube.com/watch?v=zdXsHWHxeBY
  - Matt's Ramblings, channel index — further Quake engine explainers:
    https://www.youtube.com/@MattsRamblings
  - Matthew Earl (Matt's Ramblings), "I added portals into software Quake"
    (2023) — a modern experiment, useful for seeing what runtime portal
    rendering costs: https://www.youtube.com/watch?v=kF-7Jd37gYk
- ericw-tools — the maintained qbsp/vis/light toolchain the mapping community
  uses today; the practical counterpart to the compile-time costs described
  here: https://github.com/ericwa/ericw-tools (docs:
  https://ericw-tools.readthedocs.io/)
- Michael Abrash, *Ramblings in Realtime* (Blue's News, 2000) — the Quake
  articles as Abrash released them, with his own permission note and
  acknowledgements: https://www.bluesnews.com/abrash/ (archived:
  https://web.archive.org/web/20260603214111/https://www.bluesnews.com/abrash/).
  The host refuses scripted requests but serves browsers. Content matches
  *Black Book* ch. 64 and 66-70, held locally.
