# Plan: visual upgrades for the architecture guides

Both guides share `build_doc.py` and `assets/base.{css,js}`. Life of a Frame
has one interactive pipeline map and six concept diagrams. Design History has
none; `design-history/diagrams/` is empty. Fix that asymmetry first.

Constraints throughout: diagrams need text equivalents, must work in light
and dark themes, must survive narrow screens, and `build.py` must stay offline
and stdlib-only. Generated data lands in the checked-in HTML.

## Priority

1. Discarded-renderer comparison figure (Design History)
2. e1m1 leaf/PVS explorer (Life of a Frame)
3. Timeline graphic (Design History)

The first two carry the most explanatory weight; the third is cheap.

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
quote. Keep the `<dl>` as the text equivalent, visually hidden on wide screens
and shown on narrow ones.

### D4. Evidence badges

The brief promises three tiers: what the code does, what a source says, what
is inferred. Mark claims inline with a small tag. Markdown form: `{code}`,
`{quoted}`, `{inferred}` at the end of a sentence; builder turns them into
`<span class="ev ev-code">`. Cheap, and makes the evidence bound visible.

### D5. Finger chrome for `.plan` quotes

Render `> **.plan.**` blockquotes as a terminal panel: header line
`finger johnc@idsoftware.com`, the file date, monospace body. CSS only; the
builder already tags these blockquotes.

## Life of a Frame

### F1. e1m1 leaf/PVS explorer

`id1/pak0.pak` is in the tree. A build-time parser reads e1m1's BSP: leaves,
planes, the vis lump. Emit a top-down SVG of leaf bounding boxes at one Z
slice. Click a leaf, its PVS lights up. Data embedded as JSON in the page.

Parser lives in `life-of-a-frame/bsp_slice.py`; `build.py` calls it and the
result goes through `::: diagram pvs-explorer`. Pak reading is ~40 lines
(directory at offset 4, entries of 64 bytes). Keep the SVG under 200 KB by
dropping leaves smaller than a threshold.

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

The game runs locally. Capture pairs: `r_novis 0/1`, `r_drawflat 1`,
`r_speeds 1` overlay, `r_drawentities 0`. Show as a before/after slider.
Store under `life-of-a-frame/shots/` as PNG, sized to 640 px wide.

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

## Order of work

1. D1, D3, D5: no new build machinery, Design History stops being text-only.
2. Theme toggle and print stylesheet: shared, small.
3. F1: the pak/BSP parser. Reusable by F3.
4. D2, D4: builder directives.
5. F2, F5: need a running baseline build.
6. F3, F4, xref preview, mini map.

Rebuild both guides after each step and run `check-links.py`.
