# Quake design history — writer brief

## What this guide is

The companion to `../life-of-a-frame/`. That guide is ordered by **runtime
control flow**: what happens, in the order one frame does it. This guide is
ordered by **chronology and decision**: why each mechanism exists, what was
tried first, and what constraint forced the answer.

The split is strict, and it is the thing that keeps the two docs from
decaying into one bloated page and one stale page:

| | Life of a Frame | Design History |
|---|---|---|
| Question | What does the code do, in what order | Why does it exist, how did it get that way |
| Axis | Control flow through `_Host_Frame` | Chronology, 1993 → 1997 |
| Primary source | `WinQuake/*.c`, verified line refs | `docs/historical/` |
| Reading order | Dip in by subsystem | Front to back |

Neither guide restates the other beyond one sentence plus a link. If you find
yourself explaining *how* `SV_RecursiveHullCheck` walks the tree, stop: that
belongs in Life of a Frame, and you should link to it.

## Cross-references

Write them as `[label](frame:anchor)`, e.g.:

    the [expanded collision hulls](frame:the-three-hulls)

The builder resolves the `frame:` scheme to
`../life-of-a-frame/quake-life-of-a-frame.html#anchor`, styles the link as a
cross-doc link, and **verifies at build time that the anchor exists** in the
generated target. A rename on the other side shows up as a build warning
rather than a silently dead link, so read the build output.

Anchor slugs come from the other guide's heading text, lowercased with
non-alphanumerics collapsed to `-`. To list what is available:

    grep -o 'id="[a-z0-9-]*"' ../life-of-a-frame/quake-life-of-a-frame.html | sort -u

Life of a Frame can link back the same way with the `design:` scheme. Add a
back-link wherever a section there gestures at rationale — the existing
`> **.plan.**` blockquotes are the natural anchors for it.

## Sourcing rules

The point of this guide is that it is *evidence-bounded*. It is easy and
worthless to write confident design narrative from memory.

- Every claim about someone's intent must be traceable to a document in
  `docs/historical/`, linked, and preferably quoted. Attribute and date it.
- Distinguish three things explicitly, in the prose: what the code does
  (checkable), what a source says (quotable), and what you are inferring
  (say "this suggests", and say why).
- `.plan` files are daily worklogs written for a public `finger` query. They
  are terse, sometimes wrong, and record what was done rather than why. Do not
  inflate a one-line worklog entry into a design rationale.
- Abrash's chapters were written during and just after the work and are the
  closest thing to a design record. They are also a narrative written for
  publication — he is reconstructing, not transcribing.
- Where the record is thin, say so. "The archive does not record why" is a
  legitimate and useful sentence.
- Video explainers (Matt's Ramblings, Fabien Sanglard's write-ups) are
  secondary readings of the same code and archive. Cite them to help a reader
  build intuition, never as evidence for a claim about intent — chase the
  primary source they are reading and cite that instead.
- The local archive comes first. Where it is silent, the web is fair game:
  name the source and its date inline, prefer primary or well-sourced secondary
  work (Sanglard, vintage hardware archives with citations) over wikis, and say
  in the prose which claims rest on it. Mark anything you could not corroborate
  as unverified.
- Chapter titles: the table in `../../historical/abrash_black_book/README.md`
  has several titles that do not match the chapter files. Cite the heading
  inside the chapter file, not the README table.

## Format

Same markdown subset as Life of a Frame (see `../build_doc.py`). Per chapter:

    # <Chapter title>
    <one-paragraph summary>

    > **First pass.** <2–4 sentences: the claim of the chapter, and the
    > forward link to the next one.>

    ## <Subtopic>
    ...

    ## Further reading
    <bullet list, local archive links first, then external URLs>

`> **.plan.**` blockquotes render as a distinct "era" pull-quote — use them for
verbatim quotes from the archive. `## Further reading` renders as a link list.
`## Call graph` and `## Key data structures` trigger Life-of-a-Frame-specific
rendering and should not appear here.

`::: diagram name` on its own line includes `diagrams/name.html`. Diagrams need
text equivalents, must work in light and dark themes, and must stay usable on
narrow screens.

## Build

    python3 docs/architecture/design-history/build.py

The generated `quake-design-history.html` is checked in. Register each new
chapter in the `files` list in `build.py`, and move it off the `todo` roadmap
in `template.html`.

## Checking citations

External links rot. `build.py` deliberately does not touch the network, so
citations are checked separately:

    python3 docs/architecture/check-links.py                  # all guides
    python3 docs/architecture/check-links.py design-history   # one guide
    python3 docs/architecture/check-links.py --slow 2         # gentler on old hosts

It reports every cited URL's status and, for failures, the closest Wayback
snapshot, so a dead citation can be repaired rather than dropped. It exits
non-zero if anything failed. A 403 from a host known to block scripted requests
is reported but not treated as a failure.

When citing a host with no institutional backing — an old community site, a
personal page — pin it alongside the live URL:

    https://example.org/spec.htm (archived: https://web.archive.org/web/<ts>/https://example.org/spec.htm)

Durable hosts (GitHub, Wikipedia, YouTube, active projects) are left unpinned;
annotating everything costs more readability than it buys.

## Planned chapters

1. **Before Quake: what DOOM could not do** — the 1993 feature list as a
   ceiling; the 2-D BSP; what DOOM used the BSP for and what it did not;
   Quake announced in 1994 as a design with no engine.
2. **The year of discarded renderers** — the prototype Abrash arrived to find,
   beam trees, portal clipping, direct-BSP visibility, and the PVS.
3. **Surface caching** — separating high-frequency texture from low-frequency
   light; why this made lighting affordable at all. Primary sources: Abrash
   ch. 68 and 69. For intuition first, Matthew Earl's "Shedding light on Quake I
   and II lightmapping" (https://www.youtube.com/watch?v=bxientPsqRg).
4. **Designing for one processor** — the Pentium's paired pipes and FPU
   overlap as an architectural input, not an optimization pass.
5. **Shipping constraints** — dialup bandwidth, the surface cache budget,
   deadline compromises that are visible in the source.
6. **QuakeC: why a virtual machine** — the "open game" commitment traced from
   the 1993 DOOM announcement to `progs.dat`.
7. **VQuake: the surface cache on hardware** — the first accelerated Quake, and
   the one that kept the software architecture. Detailed plan below.
8. **After ship** — GLQuake as a concession, QuakeWorld as the networking
   decision NetQuake declined to make, and the codepath cost that ended the
   era of per-vendor ports.

## Chapter 7 in detail: VQuake

**The argument.** VQuake (2 December 1996, Rendition Vérité V1000) was the
first hardware-accelerated Quake, seven weeks ahead of GLQuake. It matters to
this guide for one reason: it is the counterfactual. The Vérité was
programmable, so the port did *not* have to discard the software renderer's
architecture — it kept the edge list, the span sorting and the surface cache,
and moved only span drawing onto the chip. GLQuake threw all of that out for
two-pass alpha lighting. Chapter 7 uses the pair to show that surface caching
was not a software-era hack but a real architectural choice with a hardware
future. Keep two reasons distinct rather than merging them into one thesis:
Abrash's stated reason two-pass alpha lighting won is **fill rate** — 3dfx had
enough of it and the Vérité did not — while **codepath cost** is why the native
Vérité port was later abandoned. The first is about the technique, the second
about maintaining a per-vendor port. Do not write "economics rather than merit"
as if it covered both.

**Where it sits.** After chapter 3 (surface caching) establishes the mechanism
and before chapter 8 explains why the mechanism was abandoned. Chapters 3, 7
and 8 are one argument in three parts.

**Beats.**

1. *What the Vérité was.* A 25 MHz programmable RISC core with 128 KiB of
   microcode and 4 MiB of unified memory, 25 Mpix/s fill (12.5 with z-test),
   and no hardware z-buffer. Not a fixed-function triangle engine. Contrast
   3dfx Voodoo at ~50 Mpix/s, which Carmack measured himself.
2. *Why a proprietary API.* Direct3D and OpenGL were ruled out on performance
   grounds; VQuake used Rendition's Speedy3D with custom Vérité code.
3. *The port that kept the architecture.* CPU builds the edge list and span
   lists exactly as in software Quake; the Vérité DMAs span descriptors and
   draws them. CPU builds lit, tiled surfaces in system RAM; the Vérité DMAs
   them into an onboard surface cache. Cross-link the mechanism to Life of a
   Frame rather than re-explaining it.
4. *Where it hurt.* The DMA step is pure overhead. Textures must be 16-bpp for
   hardware filtering, doubling the software version's 8-bpp footprint inside
   4 MiB shared with a z-buffer and two pages. Surface-cache thrash shows up as
   sluggishness "when coming around corners into complex scenes or when
   spinning" (Abrash) — the same failure mode as software Quake, but with a bus
   transfer in the loop.
5. *Why it ended.* Not quality: Carmack rated the image and the architecture
   well. Codepath cost. The 12 May 1997 `.plan` is the chapter's closing quote,
   and it is the general principle the whole guide has been building toward.

**Evidence note to preserve.** Abrash and Rendition give different primary
reasons for keeping span generation on the CPU: Abrash frames it as fill-rate
economy at high resolution, Walt Donovan frames it as working around the
absence of a hardware z-buffer. Both are consistent with the design; do not
collapse them into one motive. Say that the sources emphasise different halves.

**Sources, already located.**

- Abrash, *Black Book* ch. 70, section "Verite Quake" — the definitive
  technical account: `../../historical/abrash_black_book/chapter-70.md:662`.
  The adjacent "GLQuake" section gives the two-pass alpha lighting contrast.
- Carmack `.plan` 22 Aug 1996 — first impressions, and the surface-cache tell:
  "We do take a bit of a hit when we have to generate a lot of 16 bit surfaces,
  so occasionally the framerate gets a bit uneven."
  `../../historical/plans/carmack/by_day/johnc_plan_19960822.txt`
- Carmack `.plan` 13 Dec 1996 — the hardware survey with measured fill rates,
  and "the risc architecture allows a lot of room for optimization."
  `../../historical/plans/carmack/by_day/johnc_plan_19961213.txt`
- Carmack `.plan` 23 Feb 1997 — the unification plan that became Quake 2's
  renderer: `../../historical/plans/carmack/by_day/johnc_plan_19970223.txt`
- Carmack `.plan` 2 Apr 1997 — "A verite module will come later." It slipped.
  `../../historical/plans/carmack/by_day/johnc_plan_19970402.txt`
- Carmack `.plan` 12 May 1997 — the closing quote:
  "every codepath that gets added holds back future innovation... Just having
  software and gl is a lot of work, and I have allready commited to verite
  support." `../../historical/plans/carmack/by_day/johnc_plan_19970512.txt`
- Carmack `.plan` 12 Feb 1998 and 13 Mar 1998 — the Vérité V2100/V2200 assessed
  through an OpenGL ICD, i.e. the native-port era already over:
  `../../historical/plans/carmack/by_day/johnc_plan_19980212.txt`,
  `../../historical/plans/carmack/by_day/johnc_plan_19980313.txt`
- Brian Hook `.plan` 14 Dec 1997 — measured V2200 numbers, fill-limited:
  `../../historical/plans/brian_hook/1997-12-15.txt`
- Fabien Sanglard, "The story of the Rendition Vérité 1000",
  https://fabiensanglard.net/vquake/ — V1000 internals and interviews with Walt
  Donovan, including the 1-clock 32x32 multiply and the bilinear-load
  instruction. Authorship of the port (Walt Donovan and Stefan Podell of
  Rendition, with Abrash) comes from here, not from the local archive.
- GLQuake's release date is in the local archive, and must be cited from there:
  `../../historical/plans/carmack/by_day/johnc_plan_19970122.txt`, "A preliminary
  release of glquake and the 3dfx driver has been put on our ftp site in the
  idstuff/unsup directory."
- VQuake's 2 Dec 1996 date is *not* in the local archive. Sanglard is the source;
  https://quake.fandom.com/wiki/VQuake corroborates weakly. Say in the prose that
  this date rests on a secondary source, and prefer the archive if it surfaces.

**Gap.** The archive holds no id-side account of the VQuake porting work
itself — Abrash's chapter is written after the fact and Rendition did the
implementation. Anything about day-to-day decisions during the port is
unavailable; say so rather than inferring.
