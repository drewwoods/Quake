# Quake "Life of a Frame" documentation — researcher brief

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
