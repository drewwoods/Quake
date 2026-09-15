# Shipping constraints: bandwidth, memory, deadline

Quake's fast renderer had to coexist with the realities of 1996: it needed to
run well on modest machines, work over unreliable dial-up connections, and ship
on a tight timeline. The traces of how id Software navigated those constraints
are scattered throughout the code and developer accounts. Carmack's retroactive
realization about modem latencies, logs tracking memory optimizations, and a
last-minute collision workaround all tell parts of this story. This chapter
examines the key technical tradeoffs id made to ship Quake under these
limitations, setting aside the rendering decisions covered earlier. The June
1996 .plan updates give a sense of the final sprint; later developer
commentaries fill in some of the rationale, without mythologizing every cut
feature as a deadline sacrifice.

> **First pass.** Quake's original networking targeted fast connections, its
> memory footprint shrank to fit small machines at the cost of sound quality,
> and rough edges remained for the sake of shipping. Recovery logic worked
> around physics failures, reduced precision freed up heap, and interpolation
> disguised latency. Next: [QuakeC](#sec-6), which made the game rules replaceable
> without rebuilding the engine.

## The connection the design expected

An illuminating admission comes from Carmack's [worklog on 2 August
1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt), a
month after launch, as he was developing QuakeWorld. He directly states the
latency expectation he had designed around and how reality differed. His
numbers describe the connections under discussion, not a comprehensive study of
the playerbase. {quoted}

> My original design was targeted at <200ms connection latencies. […] Ok, I
> made a bad call. I have a T1 to my house, so I just wasn't familliar with PPP
> life. I'm adressing it now.
>
> — [John Carmack, 2 August
> 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt).

Bandwidth and latency were separate but linked constraints. Sending updates
more often could reduce input-to-response delays. But sending them faster than
dial-up links could handle would congest the connection, delaying everything
queued behind them. Carmack describes Quake's release netcode as simulating at
20 fps by default. He cautions that raising this could easily saturate modem
bandwidth and cause punishing delays.

This reveals a tradeoff, but doesn't prove 20 Hz was empirically optimal for
1996 connections. Client and server frame rates could also vary. The key
historical point is that past some threshold, shorter server frames could
degrade responsiveness as the network became the bottleneck. The [runtime trace
of client-server
messaging](frame:server-round-trip-cl-readfromserver-cl-parseservermessage)
elaborates the flow involved.

## Replace stale state instead of waiting for it

Quake's netcode changed substantially prior to release. Carmack's August notes
describe the initial reliable-ordered foundation and the unreliable channel
grafted onto it later. Abrash's [QuakeWorld summary in the Graphics Programming
Black Book](../../../historical/abrash_black_book/black-book.html#quakeworld)
explains what necessitated this retrofit: waiting to retransmit dropped packets
produced unplayable hitching. Time-critical game state moved to unreliable
delivery. Reliable transport remained for data that couldn't simply be
overwritten by updates.

This worked because updates only sent relevant state. [Chapter 2](#sec-2)
covered how PVS became a network optimization as well as a rendering one. The
delta encoder (`WinQuake/sv_main.c:472-512`) further compresses by comparing
fields to fixed baselines, not just the last update. {code} The [discussion of
baseline deltas](frame:delta-against-baseline) details the format. A key
property emerges: unlike chains of incremental deltas, these snapshots stay
decodable when one is lost. There are still no guarantees that every entity
update fits in a single packet.

Unreliable delivery didn't eliminate latency entirely. Abrash describes how
Quake hid jitter by keeping the visible world a bit behind the latest server
time and interpolating. Carmack's [10
August](../../../historical/plans/carmack/by_day/johnc_plan_19960810.txt) entry
confirms that release Quake buffered to smooth inconsistent packet arrival.
[The interpolation code
itself](frame:entity-interpolation-entity-t-cl-mtime-cl-relinkentities) shows
the mechanism. At launch, fluidity and responsiveness remained in tension.
QuakeWorld's advancements are best left for chapter 8.

## Memory changed what the player received

Abrash's [Lighting
Model](../../../historical/abrash_black_book/black-book.html#surface-caching)
chapter identifies 8 MB PCs as Quake's baseline when discussing texture
caching. [Chapter 3](#sec-3) explored how mipmaps and PVS made that cache
viable. But memory pressures reached further.

On May 1st, Carmack logged an automatic sound quality fallback based on
available memory:

> **.plan.** * automatic sound decimation based on available memory — [Carmack,
> 1 May
> 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960501.txt).

The final sound setup code cuts samples to 8-bit when the heap given to Quake
is under 8 MB (`WinQuake/snd_dma.c:196-200`). {code} It's based on the
application heap size, not total system RAM. This reveals a concrete quality
dial: sound precision could drop to save space. The worklog's "decimation"
shouldn't be taken as a literal description of the final code's behavior
though.

Four days later, another memory-sensitive feature:

> **.plan.** * use all memory between the hunks as dynamic cache — [Carmack, 5
> May 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960505.txt).

This refers to Quake's general resource cache, separate from the surface cache.
The [overview of heap
allocation](frame:brief-hunk-zone-cache-allocators-zone-c) explains how the
cache resides in slack between the two hunk sentinels, reclaimable when either
needs to grow. Assets can stick around while memory is plentiful without
permanently reserving space.

Carmack also added an option to simulate a low-memory configuration. On [May
30th](../../../historical/plans/carmack/by_day/johnc_plan_19960530.txt) he
logged `-minmemory`, "for testing entry case." It caps Quake's heap on the
command line, regardless of physical RAM (`WinQuake/host.c:1035-1046`). {code}
Its presence strengthens the evidence: not just a stated memory target, but a
way to force even well-equipped developer machines to exercise it.

## The rewrite that did not happen before release

The networking transition changed a fundamental assumption without replacing
the architecture built around it. Carmack calls the old code a reliable-stream
design retrofitted for unreliable packets. Abrash's retrospective says
debugging the resulting system continued until shipping. {quoted}

> John did not rewrite the net code to reflect this new fundamental assumption,
> and wound up with 8,000 lines of messy code that took right up until Quake
> shipped to debug.
>
> — [Michael Abrash, *Graphics Programming Black Book*, ch. 70,
> "QuakeWorld"](../../../historical/abrash_black_book/black-book.html#quakeworld).

The line count is Abrash's report, not a count reproduced here. More
significantly, neither account establishes that a fixed deadline alone caused
the decision against rewriting. They establish an architectural retrofit and a
debugging cost that lasted through release. The June worklogs show that tail:
[14 June](../../../historical/plans/carmack/by_day/johnc_plan_19960614.txt)
records a fix for stuttering on dropped packets while still listing
reliable-message backlog and packet-overflow checks as concerns.

The distinction matters when reading the code. A mechanism can survive because
replacing it remains expensive even after its original assumption has changed.
Here that interpretation is supported by both developers' later accounts,
rather than inferred solely from complicated source.

## A release candidate with recovery code

On June 18th, Carmack describes a narrow bugfix:

> **.plan.** * big hack to catch rare stuck occasions — [Carmack, 18 June
> 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960618.txt).

`SV_CheckStuck` has a similar "big hack for rare failures" comment, attempting
recovery via the previous position and perturbation before declaring the player
stuck (`WinQuake/sv_phys.c:754-760,768-799`). {code} Together they strongly
imply the same breed of band-aid, but can't prove the function remains
unaltered since. {inferred}

It's a glimpse of the collision code's limits: last-resort attempts to unstick
the player could still fail. The log doesn't detail the error or indicate that
a replacement physics system was considered and rejected. Identifying it as a
workaround has support; extrapolating about roads not taken would not.

The following day, Carmack recorded creating the “0.9 SW RC distribution” while
the same entry still listed bugs and proposed rewrites ([19 June
1996](../../../historical/plans/carmack/by_day/johnc_plan_19960619.txt)). A
release candidate is evidence of release preparation, not the final public
release date. Together, these entries show what shipping meant in practice: a
working system with known limits, recent recovery fixes, and work still
deferred. The resulting source preserves those decisions alongside the more
deliberate architecture.

## Further reading

- John Carmack, [2 August
  1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt) and
  [10 August
  1996](../../../historical/plans/carmack/by_day/johnc_plan_19960810.txt) —
  hindsight on the initial netcode, latency aims and mitigations
- Michael Abrash, *Graphics Programming Black Book*, [chapter 70,
  "QuakeWorld"](../../../historical/abrash_black_book/black-book.html#quakeworld)
  — packet loss, interpolation, and unreliability retrofit pains
- Carmack, [1
  May](../../../historical/plans/carmack/by_day/johnc_plan_19960501.txt), [5
  May](../../../historical/plans/carmack/by_day/johnc_plan_19960505.txt), and
  [30 May
  1996](../../../historical/plans/carmack/by_day/johnc_plan_19960530.txt) —
  low-memory sound/caching policies and testing
- Carmack, [14
  June](../../../historical/plans/carmack/by_day/johnc_plan_19960614.txt), [18
  June](../../../historical/plans/carmack/by_day/johnc_plan_19960618.txt), and
  [19 June
  1996](../../../historical/plans/carmack/by_day/johnc_plan_19960619.txt) —
  late netcode churn, unstuck hack, and RC with unresolved issues
- [Lifecycle walkthroughs for
  networking](frame:net-layer-driver-abstraction-loopback-and-datagram-delivery),
  [entity
  interpolation](frame:entity-interpolation-entity-t-cl-mtime-cl-relinkentities),
  and [memory management](frame:brief-hunk-zone-cache-allocators-zone-c) — the
  shipping implementations
