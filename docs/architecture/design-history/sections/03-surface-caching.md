# Surface Caching: Making Light Affordable

The visibility work in chapter 2 reduced the world to the pixels worth drawing. Lighting posed a different problem: how to make shadows and highlights stay attached to that world without filling it with extra polygons. Michael Abrash's [chapter 68, “Quake's Lighting Model”](../../../historical/abrash_black_book/chapter-68.md), traces the change from vertex lighting to lightmaps and cached, already-lit textures. Its argument is about representation before speed: separate the detail of a wall's texture from the detail of its illumination, then reuse their combined result. Chapter 69 tests that choice against hardware with different costs.

> **First pass.** Quake's world lighting stopped depending on polygon vertices. A coarse lightmap and a detailed texture became a lit surface that the renderer could reuse across frames. That bought stable lighting and a simpler drawing loop, at the cost of memory and rebuilding when illumination changed. Next: the planned chapter on designing for one processor; the [assembly walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from) shows the resulting loops in the meantime.

## The wall that needed too many vertices

Abrash states the world renderer's goal explicitly in chapter 68's “The Lighting Conundrum”: geometry, textures, and lighting should remain fixed under changes of viewpoint. This was a stricter target than the engine applied to moving models, which had their own rendering code and a stronger emphasis on speed. The account concerns walls, floors, and ceilings; it is not a claim that Quake abandoned vertex lighting everywhere.

The initial engine used Gouraud shading. Lighting values lived at vertices and were interpolated across the polygon. That made the geometry carry two responsibilities: describe the wall's shape and supply enough samples to describe its illumination. A large, flat wall needed little geometry, but a spotlight or a shadow across it could need many lighting samples.

Carmack first tried adding a vertex directly beneath a spotlight and splitting the surrounding polygon. Abrash reports that this improved highlights while exposing the cost: more polygons to store, transform, and rasterize, without a corresponding increase in geometric detail. Shadows and overlapping lights demanded further subdivisions. The problem was the coupling, not simply an insufficient polygon budget. {quoted}

## Why smaller triangles were not enough

The decisive defect in Abrash's account was visible while turning over a floor. Screen-space interpolation across a Gouraud-shaded quad could change as its screen orientation changed. The lighting appeared to move across the texture. Triangles removed that particular rotational ambiguity, but did not by themselves make the lighting perspective-correct or independent of clipping.

A world built from sufficiently small triangles could hide much of this. It would also increase the database and rasterization work that the visibility effort had been trying to contain. Moving lights made geometry chosen for static illumination an especially poor fit: tomorrow's highlight might need a vertex somewhere else.

Abrash describes weeks of considering alternatives while continuing to use Gouraud shading. His account places the insight at a wall split for a spotlight, with a lighting discontinuity at a T-junction: Carmack wanted to treat it as one surface again. That is the recorded motivation. The chapter does not supply a calendar date for the decision, so this guide does not assign it one.

## Two resolutions, one stable surface

The replacement separated lighting samples from vertices. During map preprocessing, a lightmap stored illumination on a grid spaced every 16 texture texels in each direction. At runtime, the engine combined that grid with the repeated texture tile to build a lit rectangle. The perspective texture mapper then sampled that rectangle without calculating lighting for each screen pixel. Abrash describes this in [“Decoupling Lighting from Rasterization”](../../../historical/abrash_black_book/chapter-68.md). {quoted}

Texture could retain fine detail while illumination varied more slowly. A crack in a stone texture did not require a separate light sample; a shadow did not require another geometric edge. The lightmap was still sampled and filtered, so this was not unlimited lighting resolution. It provided the detail the designers needed without making polygon density determine shadow quality.

::: plate ../../../historical/abrash_black_book/images/68-03.jpg A lightmap grid and a texture tile feed a combined surface: the tile repeats while brightness varies across it. | **Figure 68.3 — separate inputs, combined surface.** Fine texture detail and coarser lighting are combined before perspective mapping. The black dots illustrate lightmap sample positions; they are not drawn pixels. Michael Abrash, *Graphics Programming Black Book*, [chapter 68](../../../historical/abrash_black_book/chapter-68.md), figure 68.3; original image, unchanged. [Archive and reproduction note](../../../historical/abrash_black_book/README.md#source--license).

Because illumination was attached to the texture before projection, both passed through the same perspective mapping. Turning or clipping the polygon no longer made its light slide relative to its texels. This solved the stability problem at the representation level. The companion guide covers the [lightmap data](frame:lightmaps-and-light-styles-r-light-c) and [surface-building mechanism](frame:surface-caching-d-surf-c).

## Cache the result, not just the ingredients

A lightmap saves lighting samples; a surface cache saves the work of combining them with texture. These are separate economies. Keeping only the small texture tile and lightmap would still require rebuilding their lit result each time it was needed.

Abrash says Carmack included caching in the design immediately because he expected surface construction to be expensive. If the same surface remained visible, its already-lit pixels could serve another frame. Moving the camera did not inherently change those pixels: perspective mapping selected a new view of them. The expensive work followed changes to the surface rather than every change to the viewpoint. {quoted}

Separating construction from drawing also made each inner loop easier to optimize. Chapter 68 reports 2.25 cycles per lit texel for surface construction and 7.5 cycles per screen pixel for perspective mapping on a Pentium. These are Abrash's inner-loop figures, not measured whole-frame costs. Texels built and pixels drawn are different quantities; a cache hit can avoid construction, while a partly hidden surface can require building texels that never reach the screen.

The reuse rule is visible in `D_CacheSurface`: the chosen mip level must have a cached result with the same texture and lightstyle values, and no conflicting dynamic-light state (`WinQuake/d_surf.c:264-291`). {code} The [runtime account](frame:surface-caching-d-surf-c) explains that check and the allocator. The historical point is what it rewards: illumination that stays unchanged across frames.

## Making the cache fit

Combining texture and light destroys the small tile's reuse across differently lit walls. Each cached surface needs its own lit texels. Abrash initially expected several megabytes of surface storage at 320×200, too much for the intended 8 MB machine. His discussion also distinguishes this application cache from the processor's cache: a repeated 64×64 texture tile had good locality; a collection of large, unique surfaces did not.

Two existing decisions made the footprint manageable. The edge-list renderer avoided building surfaces for completely hidden world polygons. Mipmapping reduced the resolution of distant surfaces, with each successive level containing one quarter as many texels. Visibility determined whether construction was necessary; mip selection reduced how much construction and storage it required.

The savings had limits. Seeing part of a surface could still require building its entire rectangle. Choosing one mip level for a very long floor could retain excessive detail in its distant portion. Abrash connects the maximum surface dimensions of 256×256 to this problem. Lighting no longer forced subdivision at every highlight, but storage and sampling still constrained surface size.

Chapter 68 reports that roughly 600 KB sufficed at 320×200 and a little over 1 MB at 640×480. Those are the author's reported budgets, not universal bounds. The worklogs show continued tuning: on [24 May 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960524.txt), Carmack listed larger caches for higher resolutions and checking cache-size performance among pending work. On 12 June he recorded completion:

> **.plan.** * increased surface cache size — [Carmack, 12 June 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960612.txt).

That entry establishes a change, not its size or measured benefit. Neither number should be inferred from the worklog.

## The case reuse could not help

Dynamic lighting exposed the bargain. When illumination changed, the cached combination was obsolete. Abrash's worst case was a frame in which every visible surface needed relighting: construction and texture mapping both had to run, and cross-frame reuse provided no benefit. He called the slowdown tolerable but noticeable, and advised limiting how many surfaces changed at once.

This was therefore more than an implementation detail. A scene with stable architectural lighting suited the cache; widespread, continuous relighting worked against it. That conclusion follows from both the stated limitation and the reuse conditions, rather than from a claim that the archive documents a particular level designer's intent. {inferred}

Abrash also proposed storing bullet marks, splatters, and other effects in surfaces so their compositing cost could be reused. These are possibilities discussed in chapter 68's closing section, not evidence that original Quake shipped all those effects. The distinction matters: the surface was a place to retain computed appearance, but its potential exceeded the game's implementation.

## What survived the move to hardware

[Chapter 69, “Surface Caching and Quake's Triangle Models”](../../../historical/abrash_black_book/chapter-69.md), revisits the choice after work on VQuake. Keeping surface caching meant building lit pixels on the CPU and transferring them into accelerator memory. The 16-bit surface format increased construction and transfer costs; larger framebuffers also competed with the cache for memory. A reuse strategy that suited software acquired an additional cost whenever it missed.

Abrash then describes drawing texture and lightmap in separate hardware passes. This retained lighting independent of vertices and consistent under perspective, while avoiding storage of the combined surfaces. Its cost was extra drawing work. The distinction carries into the planned VQuake and GLQuake chapters: lightmaps could survive even when the surface cache did not.

Chapter 3's decision was thus two decisions. Separating illumination from geometry solved a visual problem. Caching the combined surface made that solution economical on the target software renderer. Hardware could change the second answer without undoing the first.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, [chapter 68, “Quake's Lighting Model”](../../../historical/abrash_black_book/chapter-68.md) — the failed Gouraud approach, surface-based lighting, caching, mipmapping, and dynamic-lighting limits.
- Michael Abrash, *Graphics Programming Black Book*, [chapter 69, “Surface Caching and Quake's Triangle Models”](../../../historical/abrash_black_book/chapter-69.md), “Surface Caching with Hardware Assistance” — the changed costs and alternatives on accelerators.
- John Carmack, [24 May 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960524.txt) and [12 June 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960612.txt) — cache-size work before release; neither entry supplies a benchmark.
- [Life of a Frame: surface caching](frame:surface-caching-d-surf-c) — the reuse conditions and allocator; [the assembly walkthrough](frame:assembly-walkthrough-where-the-pentium-speedup-comes-from) follows the optimized loops.
