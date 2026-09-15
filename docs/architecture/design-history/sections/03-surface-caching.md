# Surface caching: making light affordable

[Chapter 2](#sec-2) got Quake down to drawing only the pixels that are actually visible. Lighting posed the opposite kind of problem: how to keep shadows and highlights attached to the world without paying for them in polygons.

Michael Abrash's [chapter 68, "Quake's Lighting Model"](../../../historical/abrash_black_book/black-book.html#chapter-68-quakes-lighting-model) traces the route from vertex lighting to lightmaps to pre-lit cached surfaces. The idea was to separate a wall's fine texture detail from its coarser illumination, then reuse the combined result. [Chapter 69](../../../historical/abrash_black_book/black-book.html#chapter-69-surface-caching-and-quakes-triangle-models) asks how well that design holds up when a graphics card takes over the drawing.

> **First pass.** Moving world lighting off polygon vertices and onto a coarse lightmap, combined with the texture into a cached pre-lit surface, bought consistent lighting and a simpler pixel loop. It cost memory, and it made every change in illumination a rebuild. [Next: the processor those loops were written for](#sec-4).

## The problem with vertex lighting

Abrash opens chapter 68 with the goal for the world renderer: geometry, texture and lighting all stay fixed and consistent as the viewpoint moves. That is a higher bar than moving models had to clear, and they got their own faster code paths. Everything below is about static world geometry — walls, floors, ceilings.

Quake started with Gouraud shading: a lighting value per polygon vertex, interpolated across the face. That made the geometry do two jobs — describe the wall's shape, and supply enough sample points for its illumination. A large flat wall needs a handful of polygons for its shape; a spotlight on it, or a shadow across it, needs many more vertices to be represented at all.

Carmack's first fix was to add a vertex under each spotlight and split the surrounding polygon. Abrash reports better highlights — and the problem laid bare: more polygons to store, transform and rasterize, none of them adding geometric detail. Shadows and overlapping lights would each demand their own subdivision. The defect was the coupling itself. {quoted}

> A primary problem with Gouraud shading is that it requires the vertices used for world geometry to serve as lighting sample points as well, even though there isn't necessarily a close relationship between lighting and geometry. This artificial coupling often forces the subdivision of a single polygon into several polygons purely for lighting reasons
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 68, "Problems with Gouraud Shading"](../../../historical/abrash_black_book/black-book.html#problems-with-gouraud-shading).

## The limits of finer tessellation

The flaw showed itself on a lit floor viewed from different angles: because the lighting interpolation was not perspective-correct, illumination slid across the texture as the polygon's screen orientation changed. Rasterizing in triangles removed that rotational ambiguity, but left lighting tied to clipping and projection.

Finer tessellation could mask the artifacts, at the price of everything [chapter 2](#sec-2) had spent on getting the polygon count down: a bigger world database and more rasterization. It suits dynamic lighting worst of all, because a highlight that moves needs a sample point where the compiler did not put one.

Abrash describes weeks of considering alternatives while the Gouraud code stayed in. The turn came when Carmack looked at a wall split for a spotlight, with a lighting discontinuity along the resulting T-junction, and wanted the wall back as one surface. The chapter gives no date.

## Decoupling lighting from geometry

The answer was to store lighting samples in a separate grid per polygon — a lightmap — with no relation to the vertices. It is computed offline, one sample every 16 texels horizontally and vertically. At runtime the engine combines that coarse lighting with the tiled texture into a pre-lit surface, then draws the surface with perspective-correct texture mapping and no lighting in the pixel loop at all. {quoted}

> During off-line preprocessing, a grid, called a light map, is calculated for each polygon in the world, with a lighting value every 16 texels horizontally and vertically. […] Then the polygon is drawn with perspective texture mapping, with the surface serving as the input texture, and with no lighting performed during the texture mapping.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 68, "Decoupling Lighting from Rasterization"](../../../historical/abrash_black_book/black-book.html#decoupling-lighting-from-rasterization).

Lighting is now sampled and filtered on its own grid, independently of the texture detail. A sample every 16 texels cannot capture every fine shadow, but it lights the wall without adding polygons.

::: plate ../../../historical/abrash_black_book/images/68-03.jpg A lightmap grid and a texture tile combine to create a pre-lit surface. | **Figure 68.3 — separate inputs, combined surface.** Fine texture detail and coarser lighting are combined before perspective mapping. The black dots illustrate lightmap sample positions; they are not drawn pixels. Michael Abrash, *Graphics Programming Black Book*, [chapter 68](../../../historical/abrash_black_book/black-book.html#chapter-68-quakes-lighting-model), figure 68.3; original image, unchanged. [Archive and reproduction note](../../../historical/abrash_black_book/black-book.html#about-this-version).

Because lighting and texture are combined before perspective projection, they stay in registration through every transform and clip. The consistency problem is solved in the representation rather than patched in the rasterizer. Life of a Frame covers the [lightmap format](frame:lightmaps-and-light-styles-r-light-c) and the [runtime surface build](frame:surface-caching-d-surf-c).

## Caching combined surfaces

The lightmap is only half the design. The other half is caching the combined surfaces, on the expectation that most of what is visible this frame was visible last frame. If a surface is going to be reused, keeping its lit texels avoids rebuilding them.

Abrash reports that the cache was part of the idea from the start, because Carmack expected compositing to be expensive. {quoted}

> When he thought of surface-based lighting, John immediately realized that surface building would be relatively expensive. […] Consequently, his design included the concept of caching surfaces, so that if the same surface were visible in the next frame, it could be reused without having to be rebuilt.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 68, "Surface Caching"](../../../historical/abrash_black_book/black-book.html#surface-caching).

Splitting surface build from surface draw also left two short loops instead of one long one, each easy to optimize. Abrash gives 2.25 cycles per lit texel for the builder and 7.5 cycles per pixel for the perspective mapper on a Pentium. These are inner-loop timings in isolation, not per-frame costs, and texels built are not pixels drawn: a cache hit builds nothing, while a partially occluded surface builds texels that are never seen.

`D_CacheSurface` reuses a surface only when the requested mip level has cached pixels with the same texture animation frame and all four light-style values unchanged. No dynamic light may affect the surface this frame, and the cached pixels must contain no previous dynamic lighting (`WinQuake/d_surf.c:264-288`). {code} A surface must therefore be rebuilt when a dynamic light disappears, too. The [runtime caching section](frame:surface-caching-d-surf-c) covers reuse and allocation in detail.

## Balancing quality and memory

Combining texture and lighting requires separate storage for each cached surface. Surfaces can share a 64x64 source texture, but different lighting produces different sets of lit texels. Abrash's first estimate was several megabytes even at 320x200 — too much for the 8 MB target machine — and the composited texels have far worse CPU cache behaviour than a 64x64 tile referenced over and over.

Two existing mechanisms kept the cache small. The edge list prevents fully hidden surfaces from being built. Mipmapping quarters the texel count at each level, so distant surfaces need less storage.

Both have limits. A partially visible surface is still built in full. Mip level is chosen per surface, from the distance of its nearest vertex, so a floor spanning a large depth range is built at the near level throughout. That is what the 256x256 cap on surface dimensions is for: without it, floors would run to thousands of texels at their nearest vertex's resolution. Lighting quality is no longer a function of polygon density, but surface size is still capped to keep the cache affordable.

Chapter 68 reports that 600 KB proved to be plenty for the cache at 320x200, and a little over 1 MB at 640x480. Carmack kept adjusting the cache budget as release approached. Carmack's [24 May 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960524.txt) worklog carries two unstarred backlog lines — "need bigger surface cache in higher res modes" and "check surface cache size performance figures" — so the resolution-dependent sizing was a known open item three weeks before ship, not yet a measurement. It closes on 12 June:

> **.plan.** * increased surface cache size — [Carmack, 12 June 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960612.txt).

The log records neither the new size nor any performance figure.

## Limits of the caching approach

Combining lighting into the cached texels means any change in illumination invalidates them. Abrash's worst case is a frame in which every visible surface must be rebuilt: no reuse at all, and the full cost of building and drawing. He calls the slowdown tolerable but noticeable, and advises capping how many surfaces may be invalidated at once.

That is a constraint on level design, not just on code: static architectural lighting plays to the cache, and dynamic or animated lighting plays against it. The trade-off follows from the documented reuse behaviour. The archive does not connect it to any level designer's intent. {inferred}

Chapter 68 closes by floating a further use for the cache: compositing bullet holes, decals and other persistent marks into the surface. Shipped Quake does not do this. The idea is what the architecture allows, not what was built.

## What hardware changed

[Chapter 69](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance) revisits the trade-off from Abrash's work porting Quake to Rendition's Vérité. The architecture survives the move: the CPU still builds surfaces, but now downloads them into the card's memory, and they must be 16 bpp for the hardware's bilinear filter. That doubles the data and roughly doubles the build cost, so a cache miss costs well over twice what it costs in software — and a higher-resolution framebuffer both enlarges the working set and shrinks the memory left to hold it. {quoted}

> The surface-caching architecture of the Verite version of Quake (which we call VQuake) is essentially the same as in the software-only version of Quake: The CPU builds surfaces on demand, which are then downloaded to the accelerator's memory and cached there. […] it takes about twice as long to build 16-bpp surfaces as 8-bpp surfaces, so the cost of missing the surface cache is well over twice as expensive in VQuake as in Quake.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 69, "Surface Caching with Hardware Assistance"](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance).

The alternative Abrash sets against it is two-pass drawing: the unlit texture first, then the lightmap over it as an alpha texture. That keeps the decoupling and the perspective-correct registration with no composite storage and no dependence on a hit rate, and pays for it in fill rate — twice the rasterization. Which of the two wins is a property of the hardware, not of the technique.

The architecture is two separable techniques. Moving lighting into lightmaps is the representational change, and it is what buys the quality and the perspective consistency. Caching the composite on top of it is an optimization chosen for the cost structure of a software rasterizer. Hardware can overturn the second without touching the first — which is what GLQuake did, and what the [VQuake chapter](#sec-7) and planned GLQuake chapter take up.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, ch. 68, "Quake's Lighting Model" — the primary source for this chapter: Gouraud's failure modes, surface-based lighting, the cache, mipmapping, and the dynamic-lighting limit: [local copy](../../../historical/abrash_black_book/black-book.html#chapter-68-quakes-lighting-model); also https://www.jagregory.com/abrash-black-book/
- Michael Abrash, *Graphics Programming Black Book*, ch. 69, "Surface Caching with Hardware Assistance" — the same trade-off re-run on the Vérité, and the two-pass alternative: [local copy](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance)
- John Carmack, `.plan`, [24 May 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960524.txt) (cache sizing still on the backlog) and [12 June 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960612.txt) (`* increased surface cache size`) — the budget as a release-time tuning parameter, with no figures recorded
- Matthew Earl (Matt's Ramblings), "Shedding light on Quake I and II lightmapping" — a secondary reading of the same mechanism, good for intuition, not evidence: https://www.youtube.com/watch?v=bxientPsqRg
- Life of a Frame: the [runtime cache](frame:surface-caching-d-surf-c) and the [assembly walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from) — allocation policy and the loops these decisions produced
