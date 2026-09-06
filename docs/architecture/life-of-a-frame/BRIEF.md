# Quake "Life of a Frame" documentation — researcher brief

## Reader-facing guide (updated September 2026)

The reader wants a gentle introduction to Quake, and already knows programming
concepts such as linear interpolation. Diagrams should explain engine-specific
choices, data flow and failure cases rather than teach basic mathematics. Preserve the detailed reference below,
but lead each chapter with a short explanation and a **First pass.** blockquote.
These summaries form a linked reading route through the engine; explain state
ownership, call order and terminology before algorithms or historical rationale.

Edit `sections/*.md`, `template.html` and `diagrams/*.html`, then run
`python3 docs/architecture/life-of-a-frame/build.py` from the repository root.
That script is a thin config; the markdown-to-HTML engine is `../build_doc.py`
and the shared CSS and JS are `../assets/base.{css,js}`, also used by the
companion guide `../design-history/`. Editing either asset changes both guides.
The generated `quake-life-of-a-frame.html` is checked in. A standalone
`::: diagram name` line in Markdown includes `diagrams/name.html`; source
references in that fragment are linkified by the builder. Relative Markdown
links resolve from `sections/` and are adjusted for the generated page.

The guide describes the original NetQuake loop at local commit `3ef8a7a`.
The current branch has a different host loop; keep that distinction visible.
Verify baseline claims with `git show 3ef8a7a:WinQuake/<file>` and distinguish
code behavior from inferred design motives. Diagrams must have text equivalents,
work in light/dark themes and stay usable on narrow screens. Check the generated
page's links, controls and visual layout after rebuilding.

Design rationale and development history belong in the companion guide
`../design-history/`, not here. Where a section gestures at *why* a mechanism
exists, link across with `[label](design:anchor)` instead of expanding on it;
the builder resolves the `design:` scheme and warns at build time if the target
anchor no longer exists. The `> **.plan.**` blockquotes are the natural place
for those links.

The original research brief below describes the detailed reference layer, not
the expected difficulty of the first reading path.

## Original research brief

Repo: /Users/drew/src/Quake-worktree (id Software Quake 1 source, GPL release). Engine code is in WinQuake/ (software + GL renderer, server, client, progs VM). QW/ is QuakeWorld — ignore unless told.

Goal: an interactive HTML doc that walks the life of one frame (Host_Frame) — input, server/world simulation, networking, client, rendering, sound — and drills into subsystems. Your section is one drill-down. Another agent will assemble all sections into HTML, so write CLEAN MARKDOWN following the format below exactly.

## Rules
- Every claim about code must cite `WinQuake/<file>:<line>` (or a range `:start-end`). VERIFY every line number with `grep -n` / `sed -n` in the repo before writing it. Wrong line numbers are worse than none.
- Include short verbatim code excerpts (5–25 lines) for the key functions, in ```c fences, each preceded by its `WinQuake/file.c:start-end` reference.
- Explain the *why* (design rationale, constraints of 1996 hardware) not just the what.
- Cite authoritative external sources with URLs where relevant, e.g.:
  - Michael Abrash, *Graphics Programming Black Book* (chapters 59–70 on Quake): https://www.jagregory.com/abrash-black-book/
  - Fabien Sanglard, "Quake Source Code Review": https://fabiensanglard.net/quakeSource/index.php
  - Olivier Montanuy et al., "Unofficial Quake Specs": https://www.gamers.org/dEngine/quake/spec/quake-spec34/
  - Quake BSP format: https://www.gamers.org/dEngine/quake/spec/quake-spec34/qkspec_4.htm
  - Abrash's Dr. Dobb's / Blue's News Quake articles (e.g. "Quake's Lighting Model: Surface Caching", "Inside Quake: Visible-Surface Determination")
  - Carmack .plan archives (https://github.com/ESWAT/john-carmack-plan-archive)
  - QuakeC / progs: https://www.gamers.org/dEngine/quake/spec/quake-spec34/qc-menu.htm
  Only cite sources you are confident exist; mark any URL you could not verify with "(unverified)".
- Length: 1500–3500 words of prose plus excerpts. Dense and technical; the reader is an experienced engineer.

## Output format (write to the file named in your task)
```
# <Section title>
<one-paragraph summary>

## Where it sits in the frame
<which stage of Host_Frame calls into this, with refs>

## <Subtopic 1>
...prose, refs, excerpts...

## <Subtopic N>

## Call graph
<indented text tree of the main functions with file:line refs>

## Key data structures
<bullet list: struct name — file:line — one-line purpose>

## Further reading
<bullet list of external sources with URLs>
```
Do not write anything outside your assigned file. Report back with 3–5 lines summarizing what you covered and any gaps.
