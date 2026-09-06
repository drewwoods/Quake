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
- Chapter titles: the table in `../../historical/abrash_quake_1995/README.md`
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

## Planned chapters

1. **Before Quake: what DOOM could not do** — the 1993 feature list as a
   ceiling; the 2-D BSP; what DOOM used the BSP for and what it did not;
   Quake announced in 1994 as a design with no engine.
2. **The year of discarded renderers** — the prototype Abrash arrived to find,
   beam trees, portal clipping, direct-BSP visibility, and the PVS.
3. **Surface caching** — separating high-frequency texture from low-frequency
   light; why this made lighting affordable at all.
4. **Designing for one processor** — the Pentium's paired pipes and FPU
   overlap as an architectural input, not an optimization pass.
5. **Shipping constraints** — dialup bandwidth, the surface cache budget,
   deadline compromises that are visible in the source.
6. **QuakeC: why a virtual machine** — the "open game" commitment traced from
   the 1993 DOOM announcement to `progs.dat`.
7. **After ship** — GLQuake as a concession, QuakeWorld as the networking
   decision NetQuake declined to make.
