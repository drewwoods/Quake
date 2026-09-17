# After ship: GLQuake and QuakeWorld

Quake shipped on June 22, 1996, but its architecture was immediately challenged by two forces it had not been built to accommodate: consumer dial-up latency and dedicated 3D graphics hardware. The "client-as-terminal" networking model and the CPU surface cache—the two foundational choices of the release engine—were both dismantled within six months. QuakeWorld (December 1996) broke the client/server purity to introduce client-side movement prediction, while GLQuake (January 1997) traded the software span rasterizer and surface cache for hardware fill rate and two-pass alpha blending.

> **First pass.** NetQuake treated the client as a display terminal, forcing every input to round-trip to the server before moving the player; QuakeWorld abandoned that model to predict movement locally and reconcile errors against incoming snapshots. In parallel, GLQuake bypassed the CPU surface cache entirely once 3dfx Voodoo hardware provided enough fill rate for multipass alpha lighting. Together, these post-ship projects established the architecture of modern 3D games.

## The reality of dialup: why NetQuake broke

On a local area network or over single-player loopback, NetQuake's "client-as-terminal" model was seamless. The client sampled input, packed it into a `usercmd_t`, sent it across the wire, and rendered the authoritative world returned by the server, using [entity interpolation](frame:entity-interpolation-entity-t-cl-mtime-cl-relinkentities) to smooth the 20 Hz simulation ticks into display frames. Critically, [the client performed zero local physics simulation](frame:no-client-side-prediction-netquake-vs-quakeworld): it did not move the local player until the server dictated that movement.

Over consumer telephone lines, this design collapsed. John Carmack addressed the miscalculation in his worklog on [2 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt): {quoted}

> My original design was targeted at <200ms connection latencies. People that have a digital connection to the internet through a good provider get a pretty good game experience. Unfortunately, 99% of the world gets on with a slip or ppp connection over a modem, often through a crappy overcrowded ISP. This gives 300+ ms latencies, minimum. Client. User's modem. ISP's modem. Server. ISP's modem. User's modem. Client. God, that sucks.
>
> Ok, I made a bad call. I have a T1 to my house, so I just wasn't familliar with PPP life. I'm adressing it now.
> — [John Carmack, .plan, 2 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt)

At 300 ms round-trip latency, pressing a movement key meant waiting nearly a third of a second before the viewport shifted. Because NetQuake's single-player and multiplayer engines were unified, this delay could not be patched with small tweaks: the client simply lacked the authority or physics machinery to move without server confirmation.

## QuakeWorld: client-side prediction and the packet loop

Developed in late 1996 as a separate codebase (`QW/`), QuakeWorld rebuilt the networking engine around high-latency, lossy connections. Carmack attacked the problem with three structural changes:

1. **The packet-driven server loop.** Instead of locking server execution to a rigid 20 Hz frame timer, the QuakeWorld server switched to an event-driven loop:
   > The proper way to address this is by changing the server model from a game style loop to a fileserver/database style loop. Instead of expecting everyone's messages to be dealt with at once, I now deal with each packet as it comes in. That player alone is moved forward in time, and a custom response is sent out in very short order. [...] The average time from a packet ariving at the system to the time a response is sent back is down to under 4ms, as opposed to over 50 with the old dedicated servers.
   > — [John Carmack, .plan, 2 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt)

2. **Pure unreliable datagram transport.** NetQuake's hybrid network layer—a reliable byte stream retrofitted with unreliable channels—was discarded. QuakeWorld based everything on stateless UDP datagrams containing sequence numbers and delta-compressed snapshots. Dropped packets were simply abandoned.

3. **Client-side movement prediction.** Carmack broke the "client-as-terminal" rule. The client was given a copy of the player physics routine (`pmove.c`, `cl_pred.c`) and allowed to simulate local input immediately:
   > The biggest difference is the addition of client side movement simulation. I am now allowing the client to guess at the results of the users movement until the authoritative response from the server comes through. This is a biiiig architectural change. The client now needs to know about solidity of objects, friction, gravity, etc. I am sad to see the elegent client-as-terminal setup go away, but I am practical above idealistic.
   > — [John Carmack, .plan, 2 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt)

```
NetQuake (Client-as-Terminal):
Input ──────► Network (150ms) ──────► Server Sim ──────► Network (150ms) ──────► Screen Moves
Total latency to action: ~300ms

QuakeWorld (Client-Side Prediction):
Input ──┬───► Local Client Sim (pmove) ────────────────────────────────────────► Screen Moves (0ms)
        └───► Network (150ms) ──────► Server Sim ──────► Network (150ms) ──► Reconcile / Snap
```

The server remained the authoritative referee. When the server's update for packet *N* arrived, the client compared the server's authoritative position against what it had predicted. If the positions matched, prediction had succeeded quietly. If they differed (due to collision with another player or packet loss), the client corrected its position and replayed all unacknowledged inputs on top of the corrected state.

This introduced new trade-offs that Carmack documented immediately:
- **Prediction errors ("pops"):** Mispredictions caused the viewport to snap suddenly when corrected.
- **Weapon discrepancies:** While local movement was predicted instantly, entity state and projectile spawning remained on the server. Rocket launches appeared to originate from behind a strafing player, and players had to lead moving opponents based on ping.
- **Single-player bifurcation:** Because prediction complexity was unnecessary on local loopback, NetQuake remained the engine for single-player Quake, while QuakeWorld became the dedicated multiplayer platform.

## GLQuake: the surface cache gives way to hardware

In December 1996, [VQuake](#sec-7) showed that software Quake's rendering architecture—edge list, span sorting, and surface caching—could run on programmable accelerator hardware (Rendition Vérité V1000). But VQuake was constrained by proprietary APIs and fill-rate limits.

The release of the 3dfx Voodoo Graphics chip in late 1996 fundamentally altered the arithmetic. The Voodoo offered 50 Mpix/s fill rate and dedicated bilinear texture filtering at consumer prices ($300). Carmack developed GLQuake against standard OpenGL, discarding the entire software surface cache:

1. **No edge lists or span sorting.** The hardware depth buffer (Z-buffer) handled hidden-surface removal directly. The CPU no longer sorted edges into spans.
2. **Texture chains.** As detailed in [GL renderer texture chains](frame:gl-renderer-texture-chains-lightmaps-and-hardware-rasterization), `R_RecursiveWorldNode` walked the BSP to mark PVS visibility, but rather than emitting spans, it linked visible surfaces into batches sorted by texture to minimize hardware state changes.
3. **Two-pass alpha blending for lighting.** Instead of dynamically rasterizing lightmaps into texture surfaces in system RAM, GLQuake packed lightmaps into dedicated texture atlases ([`lightmaps-and-multitexture`](frame:lightmaps-and-multitexture)). Surfaces were rendered in two passes: first the base texture, then the lightmap blended on top with multiplicative blending.

Carmack acknowledged the fill-rate cost on [23 November 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt): {quoted}

> Because of the very fill-rate intensive nature of the way I implemented this version of glquake (using a blend pass to do the light maps), performance is not likely to be very good on any current generation consumer level board except 3dfx. The next generation of most vendors cards should have sufficient fill rate, if claims are to be believed.
> — [John Carmack, .plan, 23 November 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt)

When subsequent hardware introduced single-pass multitexturing (`GL_ARB_multitexture`), the two-pass blend was collapsed into a single rasterization pass. The software surface cache—the centerpiece of Quake's 1995–1996 development—was officially obsolete.

## The codepath cost and the end of the software era

The rapid evolution of QuakeWorld and GLQuake exposed a maintenance ceiling. By early 1997, id Software was supporting an unsustainable matrix of diverging targets: DOS software rendering, WinQuake, VQuake, GLQuake, NetQuake, and QuakeWorld, each with distinct assembly routines and network drivers.

On [13 March 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970313.txt), Carmack drew the line for Quake II:
- DOS support was dropped in favor of Win32.
- Proprietary hardware interfaces were abandoned for standard OpenGL.
- QuakeC was replaced with compiled native DLLs to eliminate interpreter overhead.
- QuakeWorld's client-side prediction and packet networking became the unified core.

What persisted from Quake was the underlying spatial foundation: the 3D binary space partition, the precomputed visibility set (PVS), the pre-expanded collision hulls, and the authoritative client/server split. The software rasterizers and dumb-terminal networking were discarded, but the spatial and structural architecture id built between 1993 and 1996 endured for decades.

## Further reading

- John Carmack, [.plan, 2 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt) — the announcement of QuakeWorld, latency analysis, and client-side prediction
- John Carmack, [.plan, 23 November 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt) — GLQuake status, 3dfx fill rate requirements, and two-pass lightmap blending
- John Carmack, [.plan, 13 March 1997](../../../historical/plans/carmack/by_day/johnc_plan_19970313.txt) — dropping DOS and custom assembly to consolidate Quake II architecture
- Michael Abrash, *Graphics Programming Black Book*, [chapter 70, "QuakeWorld"](../../../historical/abrash_black_book/black-book.html#quakeworld) — detailed retrospective on packet loss, bandwidth constraints, and UDP networking
- [NetQuake vs. QuakeWorld prediction walkthrough](frame:no-client-side-prediction-netquake-vs-quakeworld) — Life of a Frame's technical analysis of local prediction mechanics
- [GL renderer: texture chains and hardware rasterization](frame:gl-renderer-texture-chains-lightmaps-and-hardware-rasterization) — how GLQuake bypassed the edge list
- [Lightmaps and multitexture in GLQuake](frame:lightmaps-and-multitexture) — texture atlases and multitexture combining
