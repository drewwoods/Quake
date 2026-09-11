# VQuake: the surface cache on hardware

Putting Quake on a graphics card did not immediately mean throwing its renderer away. VQuake kept the CPU's edge sorting and surface building, then handed the finished spans to Rendition's Vérité chip. That division made a faster, smoother-looking game possible, but it also put a bus transfer and a small pool of video memory in the path of every surface-cache miss. The port shows how much of an architecture can survive a change of hardware — and how the work it keeps can eventually hold it back.

> **First pass.** The Vérité was programmable enough to draw Quake's spans, so VQuake could keep the software renderer's visibility work and cached lighting. That saved pixel work on a chip with limited fill rate, at the cost of CPU work, transfers, and cache pressure. Faster hardware would change that balance; maintaining a separate renderer would impose another cost. Next: the planned final chapter, on GLQuake, QuakeWorld, and the decisions revisited after release.

## A graphics card that could follow Quake's plan

Abrash identifies VQuake as the first hardware-accelerated Quake in [chapter 70, “Verite Quake”](../../../historical/abrash_black_book/black-book.html#verite-quake). Fabien Sanglard's [2019 history of the V1000](https://fabiensanglard.net/vquake/) dates its release to 2 December 1996 and credits Rendition's Walt Donovan and Stefan Podell, working with Michael Abrash at id. The exact date and credits here come from that later account. GLQuake's preliminary release is recorded in [Carmack's 22 January 1997 worklog](../../../historical/plans/carmack/by_day/johnc_plan_19970122.txt), about seven weeks later.

The Vérité combined a programmable RISC processor with graphics operations. In Donovan's recollection, published by Sanglard, the V1000 ran at 25 MHz and included a bilinear-load instruction that read and filtered a 2×2 block of texels. It had no dedicated hardware depth-test support; its program had to perform the comparison. That does not mean VQuake had no depth buffer. It means depth testing consumed work on the programmable processor. See [Donovan's account](https://fabiensanglard.net/vquake/).

Programmability gave the port an opening. A conventional triangle interface asks the card to turn polygons into pixels. Quake already had code that determined which horizontal runs of world pixels should survive. The Vérité could accept those runs directly, provided someone wrote the code to draw them.

Abrash says performance requirements ruled out the standard APIs for this port. It used Rendition's Speedy3D, extended with special calls and custom Vérité code. {quoted}

> The need to squeeze as much performance as possible out of Verite ruled out the use of a standard API such as Direct 3D or OpenGL
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 70, “Verite Quake”](../../../historical/abrash_black_book/black-book.html#verite-quake).

This is a claim about what this chip and this game needed at the time. It does not establish that a proprietary API was inherently faster, or that OpenGL could never suit Rendition hardware.

## The polygon path that gave way to spans

Stefan Podell's [30 October 1997 account, reproduced on Vogons Wiki](https://www.vogonswiki.com/index.php/VQuake#Architecture), supplies a piece of the development sequence missing from the local archive. The first port used Quake's polygon interface. Filtering looked good, but performance disappointed. Donovan and Abrash then proposed using the software renderer's span interface.

The CPU would sort world visibility, leaving the card fewer pixels to draw and allowing world drawing without depth comparisons. Depth values were still written; comparisons were enabled for objects such as monsters. New microcode handled Quake's span format. Podell describes the exchange directly. {quoted}

> we traded more CPU work in stage one for less Verite work in stage four
>
> — [Stefan Podell, 30 October 1997, preserved on Vogons Wiki](https://www.vogonswiki.com/index.php/VQuake#Architecture).

Abrash emphasises scarce fill rate at higher resolutions; Podell emphasises the V1000's poor performance on depth-tested pixels. These accounts explain different parts of the same decision. Sorting spans reduced both overdraw and the need to compare world depths. The [software visibility walkthrough](frame:software-renderer-edge-based-visible-surface-determination) explains how Quake produces those spans.

## What crossed the bus

The CPU retained two substantial jobs. It built the edge and span lists that described visible world pixels, and it combined texture tiles with lighting to build surfaces. The Vérité transferred span descriptors and completed surfaces into onboard memory, then texture-mapped the spans. Abrash describes this division explicitly. {quoted}

> VQuake uses an edge list and builds span lists on the CPU, just as in software Quake, then Verite DMAs the span descriptors to onboard memory and draws them.
>
> — [Abrash, ch. 70, “Verite Quake”](../../../historical/abrash_black_book/black-book.html#verite-quake).

For ordinary cached world surfaces, the work was divided like this:

| Work | Software Quake | VQuake |
|---|---|---|
| Determine visible spans | CPU | CPU |
| Combine texture and lighting | CPU | CPU |
| Keep the completed surface | System-memory cache | Onboard cache, after transfer |
| Sample the surface and draw spans | CPU | Vérité |

DMA — direct memory access — lets a device transfer data without asking the CPU to copy every byte. It still consumes bus bandwidth and competes for memory access. A surface already in the card's cache avoids another build and download; a missing or invalidated surface must be supplied before it can be drawn. [Chapter 3](#sec-3) explains the caching decision, and the [runtime guide](frame:surface-caching-d-surf-c) covers the software implementation.

The edge list helped the cache as well as the pixel count. A world surface might lie in the potentially visible set yet be completely hidden from the current viewpoint. Sorting spans could eliminate it before the CPU built a lit surface and sent it to the card. VQuake carried that benefit from the software renderer across the bus boundary.

## A cache miss became more expensive

Software Quake's cached surfaces held 8-bit palette indices. VQuake needed 16-bit RGB surfaces for hardware filtering, doubling the bytes per texel. Abrash reports that building those surfaces took about twice as long, before adding the cost of downloading them. His [chapter 69 discussion](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance) therefore puts a cache miss at well over twice the software cost. {quoted}

> it takes about twice as long to build 16-bpp surfaces as 8-bpp surfaces, so the cost of missing the surface cache is well over twice as expensive in VQuake as in Quake.
>
> — [Abrash, ch. 69, “Surface Caching with Hardware Assistance”](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance).

The card had 4 MB total, shared by cached surfaces, display pages, and the depth buffer. Raising resolution squeezed that budget from both directions: larger display buffers left less space, while more detailed surface mip levels needed more of it. The cache that worked for one view could struggle when a turn revealed a different set of walls.

That is why a good average frame rate did not guarantee an even response. Abrash singles out turning corners into complex scenes and spinning as cases where VQuake could feel more sluggish than software Quake. Carmack had already noticed the rebuild cost in August, before the public release. {quoted}

> **.plan.** We do take a bit of a hit when we have to generate a lot of 16 bit surfaces, so occasionally the framerate gets a bit uneven, but overall it is a very solid improvement.
>
> — [Carmack, 22 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960822.txt).

The same entry reports better image quality and nearly twice the software speed at 512×384. It does not name the test machine or benchmark, so those figures should remain his report, not a general performance guarantee. The important connection is visible in both accounts: faster drawing made the cost of preparing new surfaces harder to hide.

## Why not draw the light separately?

The alternative was already understood: draw the tiled texture, then draw the lightmap over it with blending. That avoids storing and transferring a separate lit version of every surface. Lighting can stay aligned with the texture under perspective without depending on a composite-cache hit.

But the saved memory work becomes extra pixel work. Abrash says two-pass lighting needed at least twice the fill rate, and the Vérité could not afford that at higher resolutions. {quoted}

> However, this approach requires at least twice the fill rate of the surface cache approach, and Verite didn't have enough fill rate for that at higher resolutions.
>
> — [Abrash, ch. 70, “Verite Quake”](../../../historical/abrash_black_book/black-book.html#verite-quake).

GLQuake took that route on hardware better suited to it. Abrash's adjacent [“GLQuake” section](../../../historical/abrash_black_book/black-book.html#glquake) reports good performance on fast 3dfx chips and poor performance on many contemporary accelerators. Carmack's [December hardware survey](../../../historical/plans/carmack/by_day/johnc_plan_19961213.txt) gives the scale of the difference: he reported roughly 50 million textured pixels per second for 3dfx, with little sensitivity to enabled options. That is a fill-rate observation, not a Quake frame rate; it explains why extra passes could be affordable there.

VQuake also preserved a possibility Abrash still valued: the CPU could composite procedural effects into surfaces before the card drew them. He suggested bumps, shimmers, and warps as future uses. These were possibilities of the architecture, not a list of effects VQuake shipped. Surface caching remained a defensible choice, even as another hardware design made two-pass lighting more attractive.

## Faster silicon did not remove the CPU work

The same division that helped the V1000 could limit an upgrade. In his October 1997 account, Podell explains that VQuake still spent substantial CPU time sorting spans and building textures on the faster V2x00 chips. A quicker pixel renderer could not eliminate those stages. See [his explanation](https://www.vogonswiki.com/index.php/VQuake#Architecture).

That is the longer-term consequence of the port's success. VQuake reduced the work sent to the graphics processor by doing more on the Pentium. Once drawing became cheaper, the remaining CPU work became a larger share of the frame. Taking advantage of a new chip could require changing that division again, rather than simply running the old renderer on it. {inferred}

## The cost of keeping another renderer

By [23 February 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970223.txt), Carmack wanted a rendering architecture that could combine software Quake, GLQuake, and a Windows VQuake in one executable. On [2 April](../../../historical/plans/carmack/by_day/johnc_plan_19970402.txt), he still described the Vérité module as work to come. These are plans; neither entry records a completed module or an abandonment date.

The maintenance problem becomes explicit in May, when Carmack explains why he would not add a native Glide renderer despite expecting a possible 10–15% gain over the OpenGL driver. He already had software and OpenGL paths to maintain and had committed to Vérité support. {quoted}

> **.plan.** The big drawback is that every codepath that gets added holds back future innovation. Just having software and gl is a lot of work, and I have allready commited to verite support.
>
> — [Carmack, 12 May 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970512.txt).

This explains the pressure against adding vendor-specific paths; it is not an announcement that VQuake was cancelled. It also answers a different question from the fill-rate comparison. Pixel throughput determined which lighting technique suited a card. Engineering time determined how many distinct implementations id could keep improving.

VQuake had shown that Quake's surface cache could survive hardware acceleration. It had also shown the price: custom card code, a carefully chosen division of CPU and accelerator work, and another renderer to carry forward. The next chapter follows what happened when id chose to revisit those commitments.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, ch. 70, [“Verite Quake”](../../../historical/abrash_black_book/black-book.html#verite-quake) and [“GLQuake”](../../../historical/abrash_black_book/black-book.html#glquake) — the rendering split, cache pressure, and two-pass comparison.
- Abrash, ch. 69, [“Surface Caching with Hardware Assistance”](../../../historical/abrash_black_book/black-book.html#surface-caching-with-hardware-assistance) — surface building and transfer costs.
- Carmack, [22 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960822.txt) and [13 December 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961213.txt) — early VQuake impressions and the hardware survey.
- Carmack, [22 January](../../../historical/plans/carmack/by_day/johnc_plan_19970122.txt), [23 February](../../../historical/plans/carmack/by_day/johnc_plan_19970223.txt), [2 April](../../../historical/plans/carmack/by_day/johnc_plan_19970402.txt), and [12 May 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970512.txt) — GLQuake's release, the unification plan, and the maintenance cost of another renderer.
- Stefan Podell, [30 October 1997 post, reproduced on Vogons Wiki](https://www.vogonswiki.com/index.php/VQuake#Architecture) — a participant's account of the polygon prototype, span port, and CPU bottlenecks.
- Fabien Sanglard, [“The story of the Rendition Vérité 1000,” 1 April 2019](https://fabiensanglard.net/vquake/) — release chronology and credits; includes Walt Donovan's recollections of the hardware.
- Life of a Frame: [software visibility](frame:software-renderer-edge-based-visible-surface-determination), [surface caching](frame:surface-caching-d-surf-c), and the [GL renderer](frame:gl-renderer-texture-chains-lightmaps-and-hardware-rasterization) — the corresponding runtime mechanisms.
