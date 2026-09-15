# VQuake: the surface cache on hardware

When id Software ported Quake to Rendition's Vérité graphics card, they didn't completely abandon the existing renderer. Instead, VQuake maintained the CPU's role in edge sorting and surface building, then passed the completed spans to the Vérité chip for final rendering. This division of labor enabled a smoother, faster gaming experience, but it also introduced potential bottlenecks, such as bus transfers and the limitations of the card's video memory. VQuake demonstrates how much of a software architecture can persist through a hardware transition — and how the work it retains can ultimately constrain performance.

> **First pass.** The Vérité's programmability allowed it to handle Quake's spans, enabling VQuake to preserve the software renderer's visibility calculations and cached lighting. This approach saved pixel work on a chip with restricted fill rate, but at the expense of CPU cycles, data transfers, and cache pressure. As hardware capabilities evolved, this balance would shift, and maintaining a separate renderer would incur additional costs. In the next chapter, we'll explore the decisions revisited in GLQuake, QuakeWorld, and after the game's release.

## A graphics card that could follow Quake's plan

In chapter 70 of his Graphics Programming Black Book, "Verite Quake," Michael Abrash identifies VQuake as the first hardware-accelerated Quake. Fabien Sanglard's 2019 history of the V1000 pinpoints its release to December 2, 1996, crediting Rendition's Walt Donovan and Stefan Podell, in collaboration with id's Michael Abrash. These specifics come from Sanglard's later account. Approximately seven weeks later, Carmack's January 22, 1997 worklog records the preliminary release of GLQuake.

According to Donovan's recollection in Sanglard's article, the V1000 combined a programmable 25 MHz RISC processor with graphics operations. It featured a bilinear-load instruction for reading and filtering 2×2 texel blocks but lacked dedicated hardware for depth testing, requiring the program to handle comparisons. This doesn't imply VQuake omitted a depth buffer; rather, depth testing consumed cycles on the programmable processor.

The Vérité's programmability provided an opportunity. Conventional triangle interfaces require the card to convert polygons into pixels. However, Quake already had code determining which horizontal runs of world pixels should be visible. Given the right programming, the Vérité could process these runs directly.

Abrash states that performance demands precluded using standard APIs for this port, which instead relied on Rendition's Speedy3D, augmented with custom calls and Vérité code. {quoted}

> The need to squeeze as much performance as possible out of Verite ruled out the use of a standard API such as Direct 3D or OpenGL
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 70, "Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake).

This claim pertains to the specific needs of this chip and game at the time, not a general assertion about proprietary APIs being inherently faster or OpenGL being universally unsuitable for Rendition hardware.

## The polygon path that gave way to spans

A piece of the development timeline absent from the local archive is filled in by Stefan Podell's October 30, 1997 account, preserved on Vogons Wiki. The initial port utilized Quake's polygon interface, which yielded good filtering but disappointing performance. Donovan and Abrash then suggested leveraging the software renderer's span interface.

By having the CPU handle world visibility sorting, the card would have fewer pixels to draw and could render the world without depth comparisons. Depth values were still written, with comparisons enabled for objects like monsters. Custom microcode was developed to process Quake's span format. Podell succinctly describes the tradeoff: {quoted}

> we traded more CPU work in stage one for less Verite work in stage four
>
> — [Stefan Podell, 30 October 1997, preserved on Vogons Wiki](https://www.vogonswiki.com/index.php/VQuake#Architecture).

Abrash emphasizes limited fill rate at higher resolutions, while Podell highlights the V1000's subpar performance on depth-tested pixels. These accounts shed light on different aspects of the same decision. Sorting spans reduced both overdraw and the need for world depth comparisons. The software visibility walkthrough explains how Quake generates these spans.

## What crossed the bus

The CPU retained two significant responsibilities: constructing the edge and span lists representing visible world pixels, and combining texture tiles with lighting to create surfaces. The Vérité transferred span descriptors and finished surfaces into onboard memory, then texture-mapped the spans. Abrash explicitly describes this division: {quoted}

> VQuake uses an edge list and builds span lists on the CPU, just as in software Quake, then Verite DMAs the span descriptors to onboard memory and draws them.
>
> — [Abrash, ch. 70, "Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake).

For standard cached world surfaces, the work was partitioned as follows:

| Work | Software Quake | VQuake |
|---|---|---|
| Determine visible spans | CPU | CPU |
| Combine texture and lighting | CPU | CPU |
| Keep the completed surface | System-memory cache | Onboard cache, after transfer |
| Sample the surface and draw spans | CPU | Vérité |

Direct Memory Access (DMA) allows a device to transfer data without burdening the CPU with copying every byte. However, it still consumes bus bandwidth and competes for memory access. A surface already in the card's cache avoids another build and download; a missing or invalidated surface must be provided before it can be drawn. Chapter 3 explores the caching decision, and the runtime guide covers the software implementation.

The edge list benefited the cache as well as the pixel count. A world surface in the potentially visible set might be completely hidden from the current viewpoint. By sorting spans, such surfaces could be eliminated before the CPU built a lit surface and sent it to the card. VQuake carried this benefit from the software renderer across the bus boundary.

## A cache miss became more expensive

Software Quake's cached surfaces stored 8-bit palette indices, while VQuake required 16-bit RGB surfaces for hardware filtering, doubling the bytes per texel. Abrash reports that building these surfaces took about twice as long, not including the download cost. In his chapter 69 discussion, he estimates a cache miss in VQuake to be well over twice as expensive as in software Quake. {quoted}

> it takes about twice as long to build 16-bpp surfaces as 8-bpp surfaces, so the cost of missing the surface cache is well over twice as expensive in VQuake as in Quake.
>
> — [Abrash, ch. 69, "Surface Caching with Hardware Assistance"](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance).

The card's 4 MB was shared among cached surfaces, display pages, and the depth buffer. Increasing resolution squeezed this budget from both ends: larger display buffers left less space, while more detailed surface mip levels demanded more of it. A cache sufficient for one view could struggle when a turn revealed a different set of walls.

This explains why a good average frame rate didn't guarantee a consistent response. Abrash identifies turning corners into complex scenes and spinning as situations where VQuake could feel more sluggish than software Quake. Carmack had already noticed the rebuild cost in August, before the public release. {quoted}

> **.plan.** We do take a bit of a hit when we have to generate a lot of 16 bit surfaces, so occasionally the framerate gets a bit uneven, but overall it is a very solid improvement.
>
> — [Carmack, 22 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960822.txt).

The same entry mentions better image quality and nearly double the software speed at 512×384, without specifying the test machine or benchmark. These figures should be considered his report, not a universal performance guarantee. Both accounts highlight the key relationship: faster drawing made the cost of preparing new surfaces harder to conceal.

## Why not draw the light separately?

The alternative was well understood: render the tiled texture, then overlay the lightmap with blending. This approach avoids storing and transferring separately lit versions of each surface. Lighting remains aligned with the texture under perspective without relying on a composite-cache hit.

However, the saved memory work becomes additional pixel work. Abrash states that two-pass lighting required at least twice the fill rate, which the Vérité couldn't afford at higher resolutions. {quoted}

> However, this approach requires at least twice the fill rate of the surface cache approach, and Verite didn't have enough fill rate for that at higher resolutions.
>
> — [Abrash, ch. 70, "Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake).

GLQuake pursued this path on hardware better suited to it. Abrash's adjacent "GLQuake" section reports good performance on fast 3dfx chips and poor performance on many contemporary accelerators. Carmack's December hardware survey provides context for the difference: he reported approximately 50 million textured pixels per second for 3dfx, with minimal sensitivity to enabled options. This fill-rate observation, not a Quake frame rate, explains why extra passes could be feasible there.

VQuake also preserved a possibility Abrash still valued: the CPU could composite procedural effects into surfaces before the card drew them. He proposed bumps, shimmers, and warps as potential future applications. These were architectural possibilities, not a list of shipped effects. Surface caching remained a justifiable choice, even as another hardware design made two-pass lighting more appealing.

## Faster silicon did not remove the CPU work

The same division that helped the V1000 could limit an upgrade. In his October 1997 account, Podell explains that VQuake still spent substantial CPU time sorting spans and building textures on the faster V2x00 chips. A quicker pixel renderer couldn't eliminate those stages.

This is the long-term consequence of the port's success. VQuake reduced the work sent to the graphics processor by doing more on the Pentium. Once drawing became cheaper, the remaining CPU work constituted a larger share of the frame. Taking advantage of a new chip could necessitate revisiting that division, rather than simply running the old renderer on it. {inferred}

## The cost of keeping another renderer

By February 23, 1997, Carmack wanted a rendering architecture that could combine software Quake, GLQuake, and a Windows VQuake in one executable. On April 2, he still described the Vérité module as work to come. These are plans; neither entry records a completed module or an abandonment date.

The maintenance problem becomes explicit in May, when Carmack explains why he would not add a native Glide renderer despite expecting a possible 10–15% gain over the OpenGL driver. He already had software and OpenGL paths to maintain and had committed to Vérité support. {quoted}

> **.plan.** The big drawback is that every codepath that gets added holds back future innovation. Just having software and gl is a lot of work, and I have allready commited to verite support.
>
> — [Carmack, 12 May 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970512.txt).

This explains the pressure against adding vendor-specific paths; it is not an announcement that VQuake was cancelled. It also answers a different question from the fill-rate comparison. Pixel throughput determined which lighting technique suited a card. Engineering time determined how many distinct implementations id could keep improving.

VQuake had shown that Quake's surface cache could survive hardware acceleration. It had also shown the price: custom card code, a carefully chosen division of CPU and accelerator work, and another renderer to carry forward. The next chapter follows what happened when id chose to revisit those commitments.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, ch. 70, ["Verite Quake"](../../../historical/abrash_black_book/black-book.html#verite-quake) and ["GLQuake"](../../../historical/abrash_black_book/black-book.html#glquake) — the rendering split, cache pressure, and two-pass comparison.
- Abrash, ch. 69, ["Surface Caching with Hardware Assistance"](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance) — surface building and transfer costs.
- Carmack, [22 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960822.txt) and [13 December 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961213.txt) — early VQuake impressions and the hardware survey.
- Carmack, [22 January](../../../historical/plans/carmack/by_day/johnc_plan_19970122.txt), [23 February](../../../historical/plans/carmack/by_day/johnc_plan_19970223.txt), [2 April](../../../historical/plans/carmack/by_day/johnc_plan_19970402.txt), and [12 May 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970512.txt) — GLQuake's release, the unification plan, and the maintenance cost of another renderer.
- Stefan Podell, [30 October 1997 post, reproduced on Vogons Wiki](https://www.vogonswiki.com/index.php/VQuake#Architecture) — a participant's account of the polygon prototype, span port, and CPU bottlenecks.
- Fabien Sanglard, ["The story of the Rendition Vérité 1000," 1 April 2019](https://fabiensanglard.net/vquake/) — release chronology and credits; includes Walt Donovan's recollections of the hardware.
- Life of a Frame: [software visibility](frame:software-renderer-edge-based-visible-surface-determination), [surface caching](frame:surface-caching-d-surf-c), and the [GL renderer](frame:gl-renderer-texture-chains-lightmaps-and-hardware-rasterization) — the corresponding runtime mechanisms.
