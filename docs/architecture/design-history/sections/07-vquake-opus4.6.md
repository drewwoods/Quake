# VQuake: the surface cache on hardware

Putting Quake on a graphics card did not immediately mean discarding its renderer. VQuake kept the CPU's edge sorting and surface building intact, handing only the finished spans to Rendition's Vérité chip for rasterisation. That division produced a faster, smoother-looking game, but it also placed a bus transfer and a small pool of video memory between every surface-cache miss and the pixels it needed to produce. The port demonstrates how much of an architecture can survive a change of execution target — and how the work it retains can eventually become the bottleneck.

> **First pass.** The Vérité was programmable enough to draw Quake's spans, so VQuake could preserve the software renderer's visibility pipeline and cached lighting. That saved pixel work on a chip with limited fill rate, at the cost of CPU cycles, bus bandwidth, and cache pressure. Faster hardware would shift that balance; maintaining a separate renderer would impose a cost of its own. Next: the planned final chapter, on GLQuake, QuakeWorld, and the decisions revisited after release.

## A graphics card that could follow Quake's plan

Abrash identifies VQuake as the first hardware-accelerated Quake in [chapter 70, "Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake). Fabien Sanglard's [2019 history of the V1000](https://fabiensanglard.net/vquake/) dates its release to 2 December 1996 and credits Rendition's Walt Donovan and Stefan Podell, working alongside Michael Abrash at id. The exact date and credits here come from that later account. GLQuake's preliminary release is recorded in [Carmack's 22 January 1997 worklog](../../../historical/plans/carmack/by_day/johnc_plan_19970122.txt), roughly seven weeks later.

The Vérité paired a programmable RISC processor with dedicated graphics operations. In Donovan's recollection, published by Sanglard, the V1000 ran at 25 MHz and included a bilinear-load instruction that could read and filter a 2×2 block of texels. It had no dedicated hardware for depth testing; the programmable processor had to perform the comparison itself. That does not mean VQuake had no depth buffer — it means depth testing consumed cycles on the general-purpose core rather than running in fixed-function silicon. See [Donovan's account](https://fabiensanglard.net/vquake/).

Programmability gave the port its opening. A conventional triangle interface asks the card to turn polygons into pixels on its own. But Quake already had code that determined exactly which horizontal runs of world pixels should survive occlusion. The Vérité could accept those runs directly, provided someone wrote the microcode to draw them.

Abrash says performance requirements ruled out the standard APIs for this port. It used Rendition's Speedy3D, extended with special calls and custom Vérité code. {quoted}

> The need to squeeze as much performance as possible out of Verite ruled out the use of a standard API such as Direct 3D or OpenGL
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 70, "Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake).

This is a claim about what this particular chip and this particular game needed at the time. It does not establish that a proprietary API was inherently faster, or that OpenGL could never have suited Rendition hardware.

## The polygon path that gave way to spans

Stefan Podell's [30 October 1997 account, reproduced on Vogons Wiki](https://www.vogonswiki.com/index.php/VQuake#Architecture), supplies a piece of the development sequence missing from the local archive. The first attempt at the port used Quake's polygon interface: the card received triangulated world geometry and rasterised it directly. Texture filtering looked good, but performance fell short.

Donovan and Abrash then proposed switching to the software renderer's span interface instead. Under that scheme the CPU would sort world visibility before anything crossed the bus, leaving the card fewer pixels to draw and allowing world surfaces to be rendered without depth comparisons. Depth values were still written for each span; comparisons were enabled only for entities such as monsters that could overlap the sorted world. New microcode on the Vérité handled Quake's span format natively. Podell describes the exchange directly. {quoted}

> we traded more CPU work in stage one for less Verite work in stage four
>
> — [Stefan Podell, 30 October 1997, preserved on Vogons Wiki](https://www.vogonswiki.com/index.php/VQuake#Architecture).

Abrash emphasises scarce fill rate at higher resolutions; Podell emphasises the V1000's poor throughput on depth-tested pixels. These accounts illuminate different facets of the same decision. Sorting spans on the CPU reduced both overdraw and the need to compare world depths on the card. The [software visibility walkthrough](frame:software-renderer-edge-based-visible-surface-determination) explains how Quake produces those spans.

## What crossed the bus

The CPU retained two substantial jobs. It built the edge and span lists describing which world pixels were visible, and it composited texture tiles with lighting to produce finished surfaces. The Vérité then transferred span descriptors and those completed surfaces into its onboard memory via DMA, and drew the spans with texture mapping. Abrash describes this division explicitly. {quoted}

> VQuake uses an edge list and builds span lists on the CPU, just as in software Quake, then Verite DMAs the span descriptors to onboard memory and draws them.
>
> — [Abrash, ch. 70, "Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake).

For ordinary cached world surfaces, the division of labour looked like this:

| Work | Software Quake | VQuake |
|---|---|---|
| Determine visible spans | CPU | CPU |
| Combine texture and lighting | CPU | CPU |
| Keep the completed surface | System-memory cache | Onboard cache, after transfer |
| Sample the surface and draw spans | CPU | Vérité |

DMA — direct memory access — lets a device move data without tying up the CPU to copy every byte. It still consumes bus bandwidth and competes for memory access. A surface already resident in the card's cache avoids both a rebuild and a download; a surface that is missing or has been evicted must be rebuilt on the CPU and transferred before the card can draw it. [Chapter 3](#sec-3) explains the caching decision, and the [runtime guide](frame:surface-caching-d-surf-c) covers the software implementation.

The edge list provided a secondary benefit beyond reducing pixel count. A world surface might appear in the potentially visible set yet be completely hidden behind other geometry from the current viewpoint. Span sorting could eliminate such a surface before the CPU ever built a lit version of it and sent it across the bus. VQuake inherited that advantage from the software renderer, carrying it cleanly across the hardware boundary.

## A cache miss became more expensive

Software Quake's cached surfaces stored 8-bit palette indices. VQuake needed 16-bit RGB surfaces so the Vérité could apply hardware filtering, doubling the bytes per texel. Abrash reports that building those wider surfaces took roughly twice as long, even before accounting for the DMA transfer. His [chapter 69 discussion](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance) therefore puts a cache miss at well over twice the software cost. {quoted}

> it takes about twice as long to build 16-bpp surfaces as 8-bpp surfaces, so the cost of missing the surface cache is well over twice as expensive in VQuake as in Quake.
>
> — [Abrash, ch. 69, "Surface Caching with Hardware Assistance"](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance).

The card had 4 MB of memory total, shared among cached surfaces, display pages, and the depth buffer. Raising resolution squeezed that budget from both directions: larger display buffers consumed more of it, while the finer mip levels needed at higher detail demanded more surface storage. A cache that served one view comfortably could buckle when a turn revealed a different set of walls.

This is why a good average frame rate did not guarantee an even response. Abrash singles out turning corners into complex scenes and spinning quickly as cases where VQuake could feel more sluggish than software Quake. Carmack had already noticed the rebuild cost in August 1996, before the public release. {quoted}

> **.plan.** We do take a bit of a hit when we have to generate a lot of 16 bit surfaces, so occasionally the framerate gets a bit uneven, but overall it is a very solid improvement.
>
> — [Carmack, 22 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960822.txt).

The same entry reports better image quality and nearly twice the software renderer's speed at 512×384. It does not name the test machine or the benchmark, so those figures should remain his observation rather than a general performance guarantee. The important connection is visible in both accounts: the faster the card could draw, the harder it became to hide the cost of preparing new surfaces for it.

## Why not draw the light separately?

The alternative was already well understood: draw the tiled texture in one pass, then draw the lightmap over it with alpha blending. That approach avoids storing and transferring a separate pre-lit version of every surface. Lighting stays aligned with the texture under perspective correction without depending on a composite-cache hit.

But the memory savings come at the expense of extra pixel work. Abrash says two-pass lighting required at least twice the fill rate, and the Vérité could not sustain that at higher resolutions. {quoted}

> However, this approach requires at least twice the fill rate of the surface cache approach, and Verite didn't have enough fill rate for that at higher resolutions.
>
> — [Abrash, ch. 70, "Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake).

GLQuake would take exactly that route, on hardware better suited to it. Abrash's adjacent ["GLQuake" section](../../../historical/abrash_black_book/black-book.html#glquake) reports good performance on fast 3dfx chips and poor performance on many contemporary accelerators. Carmack's [December hardware survey](../../../historical/plans/carmack/by_day/johnc_plan_19961213.txt) puts a number on the difference: he reported roughly 50 million textured pixels per second from 3dfx, with little sensitivity to which options were enabled. That is a fill-rate observation, not a Quake frame rate, but it explains why additional rendering passes could be affordable on that generation of hardware.

VQuake also preserved a possibility Abrash still valued: because the CPU built each surface as a bitmap before sending it to the card, it could composite procedural effects into that bitmap along the way. He suggested bumps, shimmers, and warps as potential future uses. These were possibilities inherent to the architecture, not a catalogue of effects VQuake shipped. Surface caching remained a defensible design choice, even as a different class of hardware was making two-pass lighting more attractive.

## Faster silicon did not remove the CPU work

The same division of labour that helped the V1000 could limit an upgrade. In his October 1997 account, Podell explains that VQuake still spent substantial CPU time sorting spans and building textures even on the faster V2x00 chips. A quicker pixel renderer could not eliminate those stages; they ran on the Pentium regardless of how fast the card could consume their output. See [his explanation](https://www.vogonswiki.com/index.php/VQuake#Architecture).

This is the longer-term consequence of the port's own success. VQuake had reduced the work sent to the graphics processor by doing more on the CPU. Once drawing itself became cheap, that remaining CPU work loomed as a larger share of each frame. Taking advantage of a new, faster chip would require renegotiating the division entirely — not simply running the existing renderer on quicker silicon. {inferred}

## The cost of keeping another renderer

By [23 February 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970223.txt), Carmack wanted a rendering architecture that could combine software Quake, GLQuake, and a Windows VQuake in a single executable. On [2 April](../../../historical/plans/carmack/by_day/johnc_plan_19970402.txt), he still described the Vérité module as work yet to come. These are plans; neither entry records a completed module or an abandonment date.

The maintenance problem becomes explicit in May, when Carmack explains why he would not add a native Glide renderer despite expecting a possible 10–15% gain over the OpenGL driver. He already had software and OpenGL paths to maintain and had committed to supporting the Vérité. {quoted}

> **.plan.** The big drawback is that every codepath that gets added holds back future innovation. Just having software and gl is a lot of work, and I have allready commited to verite support.
>
> — [Carmack, 12 May 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970512.txt).

This explains the pressure against adding vendor-specific rendering paths; it is not an announcement that VQuake was cancelled. It also answers a different question from the fill-rate comparison. Pixel throughput determined which lighting technique suited a given card. Engineering time determined how many distinct implementations id could afford to keep improving.

VQuake had demonstrated that Quake's surface cache could survive the transition to hardware acceleration. It had also revealed the price: custom microcode for the card, a carefully negotiated division of CPU and accelerator work, and yet another renderer to carry forward. The next chapter follows what happened when id chose to revisit those commitments.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, ch. 70, ["Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake) and ["GLQuake"](../../../historical/abrash_black_book/black-book.html#glquake) — the rendering split, cache pressure, and two-pass comparison.
- Abrash, ch. 69, ["Surface Caching with Hardware Assistance"](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance) — surface building and transfer costs.
- Carmack, [22 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960822.txt) and [13 December 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961213.txt) — early VQuake impressions and the hardware survey.
- Carmack, [22 January](../../../historical/plans/carmack/by_day/johnc_plan_19970122.txt), [23 February](../../../historical/plans/carmack/by_day/johnc_plan_19970223.txt), [2 April](../../../historical/plans/carmack/by_day/johnc_plan_19970402.txt), and [12 May 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970512.txt) — GLQuake's release, the unification plan, and the maintenance cost of another renderer.
- Stefan Podell, [30 October 1997 post, reproduced on Vogons Wiki](https://www.vogonswiki.com/index.php/VQuake#Architecture) — a participant's account of the polygon prototype, span port, and CPU bottlenecks.
- Fabien Sanglard, ["The story of the Rendition Vérité 1000," 1 April 2019](https://fabiensanglard.net/vquake/) — release chronology and credits; includes Walt Donovan's recollections of the hardware.
- Life of a Frame: [software visibility](frame:software-renderer-edge-based-visible-surface-determination), [surface caching](frame:surface-caching-d-surf-c), and the [GL renderer](frame:gl-renderer-texture-chains-lightmaps-and-hardware-rasterization) — the corresponding runtime mechanisms.
