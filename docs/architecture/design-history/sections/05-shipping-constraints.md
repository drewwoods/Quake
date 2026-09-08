# Shipping Constraints: Bandwidth, Memory, Deadline

A fast renderer was necessary, but Quake also had to fit a small machine, survive an unreliable connection, and reach a release candidate. Those constraints left different kinds of evidence: Carmack's account of a mistaken networking assumption, worklogs recording memory reductions, and a collision workaround still recognizable in the source. This chapter follows the limits that remained after the rendering decisions. The June worklogs establish what changed near release; later retrospectives explain some of the reasons, without turning every unfinished task into a deadline story.

> **First pass.** Quake spent bandwidth on replaceable world updates, memory on caches it could reclaim, and development time on making the existing system shippable. These choices left costs: modem latency, reduced sound precision on small heaps, and recovery code around collision failures. Next: the planned QuakeC chapter, tracing the separate decision to make game logic replaceable.

## The connection the design expected

Carmack's [2 August 1996 worklog](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt), written after release while developing QuakeWorld, identifies the original assumption directly. He had targeted connections below 200 ms latency; modem users were encountering substantially longer delays. His figures describe the connections he was discussing, not a measured distribution of all players. {quoted}

> My original design was targeted at <200ms connection latencies. […] Ok, I made a bad call. I have a T1 to my house, so I just wasn't familliar with PPP life. I'm adressing it now.
>
> — [John Carmack, 2 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt).

Bandwidth and latency were related but distinct. More frequent updates could reduce the time an input waited for server processing. Sending them faster than a modem link could carry them could instead build a queue and delay everything behind it. In the same entry, Carmack describes the existing server loop as collecting input, advancing the world, and sending updates, with a default 20 fps cadence. He explicitly warns that increasing it could overcommit dialup bandwidth and cause severe buffering delays.

That is evidence for a tradeoff, not proof that 20 Hz was an experimentally optimal modem setting. Nor was it a universal limit on every client and listen-server frame. The historical point is that shortening the simulation interval could worsen responsiveness once the connection became the bottleneck. The [runtime account of client and server communication](frame:server-round-trip-cl-readfromserver-cl-parseservermessage) supplies the control flow.

## Replace stale state instead of waiting for it

The network design changed before release. In the August entry, Carmack describes QTest's reliable-stream foundation and the later addition of an unreliable sideband. Abrash's [chapter 70, “QuakeWorld”](../../../historical/abrash_black_book/black-book.html#quakeworld), explains the failure that drove the change: waiting for retransmission produced hitches when packets disappeared. Ordinary gameplay state moved to unreliable delivery, with reliable delivery retained for information that could not simply be superseded.

The saving depended on sending only relevant state. As [chapter 2](#sec-2) established, the PVS had become a network filter as well as a rendering aid. The surviving encoder also compares entity fields against a fixed baseline, rather than requiring the preceding update packet to decode the next one (`WinQuake/sv_main.c:472-512`). {code} The [baseline account](frame:delta-against-baseline) explains the format. This gives replaceable updates a useful property: losing one does not break a chain of deltas against successive packets. It does not guarantee that every entity fits in every datagram.

Changing the transport did not remove all delay. Abrash describes keeping the displayed world slightly behind the latest server time so the client could interpolate between received states. Carmack confirms in his [10 August 1996 entry](../../../historical/plans/carmack/by_day/johnc_plan_19960810.txt) that the shipping version deliberately introduced latency to smooth variable packet arrival. The [interpolation mechanism](frame:entity-interpolation-entity-t-cl-mtime-cl-relinkentities) documents what that bought. QuakeWorld's later response belongs in chapter 8; at release, smoothing and responsiveness were still competing goals.

## Memory changed what the player received

Abrash's [chapter 68, “Quake's Lighting Model”](../../../historical/abrash_black_book/black-book.html#surface-caching), identifies an 8 MB machine as the intended target when discussing surface storage. [Chapter 3](#sec-3) covers how mipmapping and visibility made that cache fit. The remaining memory pressure reached beyond textures.

On 1 May, Carmack recorded an automatic sound reduction based on available memory:

> **.plan.** * automatic sound decimation based on available memory — [Carmack, 1 May 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960501.txt).

The surviving sound initialization selects `loadas8bit` when the engine heap is smaller than 8 MiB (`WinQuake/snd_dma.c:196-200`). {code} That test concerns memory supplied to the engine, not total installed RAM. It establishes a concrete quality trade: sound storage precision could be reduced to fit. The worklog's broader word “decimation” should not be treated as an exact description of this later source revision.

Four days later, the worklog records another memory decision:

> **.plan.** * use all memory between the hunks as dynamic cache — [Carmack, 5 May 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960505.txt).

This is the resource cache in the memory allocator, distinct from the renderer's cache of lit surfaces. The [hunk and cache account](frame:brief-hunk-zone-cache-allocators-zone-c) describes how cached resources occupy the free space between the hunk's two ends and can be reclaimed when allocations need that space. The policy lets spare memory retain useful assets without reserving that space permanently.

Low-memory behavior was also made testable. On [30 May](../../../historical/plans/carmack/by_day/johnc_plan_19960530.txt), Carmack recorded adding `-minmemory` “for testing entry case.” The option survives in `Host_Init`, where it caps the supplied heap size at the selected minimum (`WinQuake/host.c:1035-1046`). {code} That is stronger evidence than an advertised memory target alone: the program had a way to exercise its constrained configuration on a larger machine.

## The rewrite that did not happen before release

The networking transition changed a fundamental assumption without replacing the architecture built around it. Carmack calls the old code a reliable-stream design retrofitted for unreliable packets. Abrash's retrospective says debugging the resulting system continued until shipping. {quoted}

> John did not rewrite the net code to reflect this new fundamental assumption, and wound up with 8,000 lines of messy code that took right up until Quake shipped to debug.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 70, “QuakeWorld”](../../../historical/abrash_black_book/black-book.html#quakeworld).

The line count is Abrash's report, not a count reproduced here. More significantly, neither account establishes that a fixed deadline alone caused the decision against rewriting. They establish an architectural retrofit and a debugging cost that lasted through release. The June worklogs show that tail: [14 June](../../../historical/plans/carmack/by_day/johnc_plan_19960614.txt) records a fix for stuttering on dropped packets while still listing reliable-message backlog and packet-overflow checks as concerns.

The distinction matters when reading the code. A mechanism can survive because replacing it remains expensive even after its original assumption has changed. Here that interpretation is supported by both developers' later accounts, rather than inferred solely from complicated source.

## A release candidate with recovery code

On 18 June, the worklog records a narrowly described workaround:

> **.plan.** * big hack to catch rare stuck occasions — [Carmack, 18 June 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960618.txt).

`SV_CheckStuck` carries a matching description of a hack for rare failures in the world clipping hull (`WinQuake/sv_phys.c:754-760`). Its recovery attempts use a previous position, then nearby positions, before reporting that the player remains stuck (`WinQuake/sv_phys.c:768-799`). {code} The worklog and comment strongly suggest the same class of workaround, but do not prove that the surviving function is unchanged from that day's implementation. {inferred}

This is a visible limit of the collision system: recovery was added around a failure that could still occur. The archive entry does not identify its numerical cause or say that a complete collision rewrite was considered. Calling it a workaround is supported; inventing the rejected alternative would not be.

The following day, Carmack recorded creating the “0.9 SW RC distribution” while the same entry still listed bugs and proposed rewrites ([19 June 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960619.txt)). A release candidate is evidence of release preparation, not the final public release date. Together, these entries show what shipping meant in practice: a working system with known limits, recent recovery fixes, and work still deferred. The resulting source preserves those decisions alongside the more deliberate architecture.

## Further reading

- John Carmack, [2 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt) and [10 August 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960810.txt) — retrospective accounts of the shipping network model and its latency tradeoffs.
- Michael Abrash, *Graphics Programming Black Book*, [chapter 70, “QuakeWorld”](../../../historical/abrash_black_book/black-book.html#quakeworld) — packet loss, interpolation, and the cost of retrofitting unreliable delivery.
- Carmack, [1 May](../../../historical/plans/carmack/by_day/johnc_plan_19960501.txt), [5 May](../../../historical/plans/carmack/by_day/johnc_plan_19960505.txt), and [30 May 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960530.txt) — sound reduction, reclaimable cache space, and minimum-memory testing.
- Carmack, [14 June](../../../historical/plans/carmack/by_day/johnc_plan_19960614.txt), [18 June](../../../historical/plans/carmack/by_day/johnc_plan_19960618.txt), and [19 June 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960619.txt) — late networking fixes, stuck-player recovery, and release-candidate preparation.
- [Life of a Frame: network delivery](frame:net-layer-driver-abstraction-loopback-and-datagram-delivery), [entity interpolation](frame:entity-interpolation-entity-t-cl-mtime-cl-relinkentities), and [memory allocation](frame:brief-hunk-zone-cache-allocators-zone-c) — the surviving mechanisms.
