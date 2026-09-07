# Plan: visual upgrades for the architecture guides

Both guides share `build_doc.py` and `assets/base.{css,js}`. Life of a Frame
has one interactive pipeline map and six concept diagrams. Design History has
none; `design-history/diagrams/` is empty. Fix that asymmetry first.

Constraints throughout: diagrams need text equivalents, must work in light
and dark themes, must survive narrow screens, and `build.py` must stay offline
and stdlib-only. Generated data lands in the checked-in HTML.

Label simplified simulations explicitly; reserve measured claims for actual
captures. Keep interactions local to the concept, without a browser port of
the engine.

Two decisions this plan makes implicitly, recorded so they are deliberate:

- **Single-file property is dropped.** The guides currently inline everything
  and open as one file. D2 and F5 introduce sibling assets, so a guide becomes
  a directory. Right call — data URIs for screenshots would bloat a 600 KB page
  into megabytes — but it is a property being given up, not an oversight.
- **Accessibility is roughly a third of each widget.** Keyboard operation plus
  a static fallback that still teaches the point is not a finishing pass; F1
  and F4 in particular are not done when the mouse path works.

## Priority

1. Discarded-renderer comparison figure (Design History)
2. e1m1 leaf/PVS explorer (Life of a Frame)
3. Timeline graphic (Design History)

The first two carry the most explanatory weight; the third is cheap.

Among the additions below, start with D6 (DOOM geometry), F6 (collision), and
D7 (historical decisions). They extend coverage beyond visibility and rendering.

## Design History

### D1. Discarded renderers, side by side

Chapter 2 names beam trees, portal clipping, direct-BSP visibility, PVS. One
figure: the same two-room scene under each scheme, with the failure case each
one hit (beam tree splitting on a complex scene, portal recursion cost).
Inline SVG in `diagrams/discarded-renderers.html`, included with
`::: diagram discarded-renderers` next to "Five that did not ship".

### D2. Black Book plates

Abrash granted permission (commit e2d40aa). `docs/historical/abrash_black_book/`
holds 197 chapter images. Embed chapter 64's beam-tree and PVS figures as
captioned plates. Needs a `::: plate path caption` directive in `build_doc.py`
that copies or references the image and emits `<figure class="plate">`.
Attribution line in the caption, every time.

### D3. Timeline graphic

Replace the `<dl class="timeline">` in `template.html` with a horizontal rail:
`.plan` entries as dots, chapters as bands beneath, hover or focus shows the
quote. Keep the `<dl>` as the text equivalent. Do not hide it on wide screens: that
leaves desktop screen-reader users with only the rail. Make the rail itself
focusable and labelled, and let the list stay in the document at every width
(collapsed behind a disclosure if it crowds the page).

### D4. Evidence badges

The brief promises three tiers: what the code does, what a source says, what
is inferred. Mark claims inline with a small tag. Markdown form: `{code}`,
`{quoted}`, `{inferred}` at the end of a sentence; builder turns them into
`<span class="ev ev-code">`. Cheap, and makes the evidence bound visible.

### D5. Finger chrome for `.plan` quotes

Render `> **.plan.**` blockquotes as a terminal panel: header line
`finger johnc@idsoftware.com`, the file date, monospace body. CSS only; the
builder already tags these blockquotes.

### D6. Can DOOM represent this room?

An interactive cutaway beside Chapter 1's dimensionality discussion. Toggle
a ramp, stacked rooms, and sloping ceilings; show which representation breaks
and why. Pair the floor plan with the 3D view so the limitation is concrete.
Use a small SVG scene with labelled controls and a static comparison fallback.

### D7. Choose before reading the history

At a historical turning point, present the requirements known then and a few
candidate approaches. Readers choose before revealing the actual decision,
its evidence, and its tradeoff. Explain why discarded approaches looked
promising; distinguish documented constraints from reconstructed reasoning.
Use disclosure cards, keeping the evidence available without JS.

## Life of a Frame

### F1. e1m1 leaf/PVS explorer

`id1/pak0.pak` is in the tree. A build-time parser reads e1m1's BSP: leaves,
planes, the vis lump. Emit a top-down SVG of leaf bounding boxes at one Z
slice. Click a leaf, its PVS lights up. Data embedded as JSON in the page.

Parser lives in `life-of-a-frame/bsp_slice.py`; `build.py` calls it and the
result goes through `::: diagram pvs-explorer`. Pak reading is ~40 lines
(directory at offset 4, entries of 64 bytes).

To keep the SVG under 200 KB, simplify geometry (round coordinates, merge
collinear edges) rather than dropping leaves. Omitting leaves understates the
leaf count and so misrepresents the exact thing the figure exists to show. If
any leaf is dropped, say so in the caption with the count.

Pak data is id's, not GPL. Embed derived geometry only, never textures or
raw lumps.

### F2. Measured stage costs in the pipeline map

`host_speeds 1` prints per-stage times. Run `timedemo demo1` on the baseline
build, average the numbers, store them in `life-of-a-frame/timings.json`.
Builder scales a bar inside each stage box to its share of the frame. Record
the machine and commit in the caption.

### F3. One packet, dissected

Parse a `.dem` at build time and show one frame's `svc_*` stream as a byte
strip with fields labelled: message id, entity number, delta bits, payload.
Goes beside `CL_ParseServerMessage`. Demo parsing is a small extension of the
pak reader; the message layout is in `protocol.h`.

### F4. Scanline animation

The edge list and span sort are the core of the software renderer. A stepping
SVG that sweeps one scanline down a three-polygon scene with "next edge" and
"next span" buttons. Pure JS, no build-time data. Place it in the software
renderer section next to `R_ScanEdges`.

### F5. Annotated screenshots

The game runs locally. Capture pairs: `r_novis 0/1`, `r_speeds 1` overlay,
`r_drawentities 0`, `r_lightmap 1`. Show as a before/after slider. Store under
`life-of-a-frame/shots/` as PNG, sized to 640 px wide.

`r_drawflat` is **not** available in the `glquake.cocoa` build in the tree: it
is registered in `WinQuake/r_main.c:199` and consumed in `WinQuake/d_edge.c:187`,
both software-renderer only, and `gl_rmain.c` never references it. Capture that
one from a software build or drop it.

Script the captures from a `.cfg` that plays `demo1`, pauses at fixed points and
toggles the cvar, so the pairs share a viewpoint exactly and can be regenerated.
Record the build commit in each caption: these are evidence, not decoration.

### F6. Collision playground

Extend the collision diagram: move a player box toward a wall, corner, or
doorway. Toggle the equivalent point moving through expanded collision
geometry; show the contact normal and remaining slide. Ask "Will this move
clear the doorway?" before stepping the trace. Provide keyboard controls and
a fixed worked example. Label the simplified geometry and link the trace and
slide steps to the relevant code.

### F7. Network delay lab

Extend the interpolation diagram with controls for packet interval, delay,
and loss. Show server position, received snapshots, and displayed position
together. Readers predict smooth movement, a pause, or a snap before the next
update. Follow the documented NetQuake behavior, including interpolation
limits; do not silently substitute QuakeWorld prediction. Include a stepped
timeline and a static example.

### F8. Memory allocator sandbox

Show Hunk, Zone, and Cache in a memory strip. Step through a scripted sequence:
load a map, load a sound, grow the hunk, change maps. Readers predict what
survives, moves, or gets evicted, then inspect the result and responsible
allocator. Use illustrative sizes and verified allocator rules; distinguish
the model/sound Cache from the software renderer's surface cache. Include the
sequence as a static table.

### F9. Hear spatialization

Move a synthetic sound source around a listener and rotate the listener.
Display left/right volume meters while playing the result, using the source
code's spatialization rules. Start audio only on request; provide mute and
keyboard controls. The meters and a static worked example must teach the
concept without audio. Place beside `S_Update` and spatialization.

## Both guides

- **Theme toggle.** Currently system-only. Button in the masthead, preference
  in `localStorage` via the existing `savePref`.
- **Print stylesheet.** Hide the rail, expand all code folds, show link URLs.
- **Xref hover preview.** Hovering a `frame:` or `design:` link shows the
  target chapter's First pass paragraph. Builder already resolves the anchor;
  it can also emit the paragraph into a `data-preview` attribute.
- **Mini pipeline map in the rail.** A shrunken copy of the pipeline SVG,
  pinned below the contents, highlighting the current stage from the existing
  scroll spy.
- **Self-test cards.** The guides explain but never check. Add predict-then-
  reveal cards at section ends: a question, then the answer behind a
  disclosure. "You push against a wall — which half decides where you stop?"
  Uses the `<details>` idiom already established for code folds and call
  graphs, so no new pattern and no JS. Life of a Frame's static "Check your
  understanding" paragraph in `template.html` is the prototype; the format
  generalises. Cheap, and a foundation for the decision and diagnosis cards.
- **"What broke?" cases.** Show a screenshot or short recording of a
  deliberately induced fault, then offer likely responsible stages. Reveal
  the relevant state and code path after the reader chooses. Use reproducible
  captures with the build commit and fault setup recorded, following F5.
  Pair recordings with stills and a text description. Place runtime cases in
  Life of a Frame; cross-link from relevant design tradeoffs in Design History.

## Order of work

1. D1, D3, D5: no new build machinery, Design History stops being text-only.
2. Theme toggle and print stylesheet: shared, small.
3. F1: the pak/BSP parser. Reusable by F3.
4. D2, D4: builder directives.
5. F2, F5: need a running baseline build.
6. F3, F4, xref preview, mini map.

Additional concept work, in priority order:

1. D6, F6, D7: geometry, collision, and historical decisions.
2. F7, F8, F9: networking, memory, and sound.
3. "What broke?" cases: after F5 establishes reproducible captures.

Self-test cards can slot in anywhere; they need no machinery and are the
cheapest item in the plan.

Accessibility is not a step of its own. Each item ships with its text
equivalent, keyboard path and both themes, or it is not done. A widget that
works only with a mouse is unfinished, not "phase two".

Rebuild both guides after each step and run `check-links.py`.
