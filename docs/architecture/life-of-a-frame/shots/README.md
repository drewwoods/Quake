# Runtime evidence

These are unedited GLQuake and Software Quake screenshots. GLQuake TGAs are
converted with `sips`; Software Quake PCXs are converted with Python's `zlib`
and `struct`. Captions supply annotations; the pixels contain only engine output.

## Revision

Captures use native macOS revision `78216afaad7ece08e98b0bff0b835a7628b699ee`
(branch `capture-base`: the first native build plus `NSOpenGLPFABackingStore`,
see below). The guide’s baseline, `3ef8a7a9e53e226c831467f1b200bc77239e2e0d`,
predates that backend. `host.c`, `screen.c`, `r_main.c`, `r_surf.c`,
`gl_rmain.c`, and `gl_rsurf.c` are identical between these revisions.
Platform, audio, and demo instrumentation differ.

## Regenerate

From the repository root, on macOS with an active graphical session,
Python 3.12+, Xcode command-line tools, and `sips`:

```sh
python3 docs/architecture/life-of-a-frame/capture.py [--renderer gl|software|both]
python3 docs/architecture/life-of-a-frame/build.py
```

The script exports and builds the pinned revision in a temporary directory.
Its tracked `id1/pak0.pak` supplies the shareware demo. It replaces the PNGs,
companion configs, capture metadata, timing config, log, and timing metadata.
The documentation build itself stays offline and never launches Quake.

Each screenshot runs `timedemo demo1`, uses `host_framerate 0.05`, and executes
200 `wait` commands before `screenshot`. Timedemo consumes at most one demo
message per host frame after signon. Separate runs therefore select the same
viewpoint without relying on `pause`, which does not freeze demo playback.
Timing counters can vary across runs; this is not a promise of identical pixels.

All shots use 640×480, `viewsize 100`, and `volume 0`. GLQuake uses `-window`,
`-nomtex`, and `gl_texsort 1`; disabling multitexture makes `r_lightmap`
effective. Software Quake runs in its standard windowed 8-bit paletted pipeline.
The variants change only the named diagnostic and, for `r_speeds`, notification
visibility. The `r_speeds` text is the engine’s console notification output.
Each variant has a companion `.cfg` in this directory.

## Alignment

Both renderers consume the demo identically: signon drains in the frame that
runs `timedemo`, then one message per host frame. After 200 `wait` commands,
`screenshot` runs in `Cbuf_Execute` at the start of frame 200 and saves the
buffer rendered in frame 199. Software reads `vid.buffer`, the single render
target. GL reads the back buffer with `glReadPixels`, which after a double-buffer
flip held frame 198. The pinned revision adds `NSOpenGLPFABackingStore` so the
swapped-out frame survives, and both renderers now capture frame 199 (demo
message 204). Verified by stamping `host_framecount` into the framebuffer of
an instrumented build.

## Timings

[Timing data](../timings.json) comes from [the retained log](../timings.log):
969 pre-summary `host_speeds` rows after discarding the initial stale timestamp.
Their means reproduce the JSON exactly. The demo reports 970 frames, 8.1 seconds,
and 119.3 fps; that summary uses a different timing boundary. Logged rows include
end-of-demo work and are not individual CPU profiles.

The printed `server` bucket includes other host work, scheduling, and prior
printing; demo playback runs no local server. `gfx` includes presentation.
`snd` includes sound, light decay, and CD audio. Integer millisecond truncation
puts every sound sample below resolution; zero does not mean free work.

The retained run reports signal 11 **after** the completed summary. The native
signal handler can exit with status zero, so the script checks the log too.
Only pre-summary measurements contribute to the data. This is one instrumented
run on an Apple M2, not a historical benchmark or a claim about every stage.
