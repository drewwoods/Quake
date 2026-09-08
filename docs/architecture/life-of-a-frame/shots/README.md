# Runtime evidence

These are unedited GLQuake screenshots, converted from TGA to PNG with `sips`.
Captions supply annotations; the pixels contain only engine output.

## Revision

Captures use native macOS revision `7a74a7c6d901e39f907b39bec94819476bb7b845`.
The guide’s baseline, `3ef8a7a9e53e226c831467f1b200bc77239e2e0d`, predates that
backend. `host.c`, `gl_rmain.c`, `gl_rsurf.c`, and `gl_screen.c` are identical
between these revisions. Platform, audio, and demo instrumentation differ.

## Regenerate

From the repository root, on macOS with an active graphical session,
Python 3.12+, Xcode command-line tools, and `sips`:

```sh
python3 docs/architecture/life-of-a-frame/capture.py
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

All shots use windowed 640×480, `-nomtex`, `gl_texsort 1`, `viewsize 100`, and
`volume 0`. Disabling multitexture makes `r_lightmap` effective. The variants
change only the named diagnostic and, for `r_speeds`, notification visibility.
The `r_speeds` text is the engine’s console notification output.

## Timings

[Timing data](../timings.json) comes from [the retained log](../timings.log):
969 pre-summary `host_speeds` rows after discarding the initial stale timestamp.
Their means reproduce the JSON exactly. The demo reports 970 frames, 8.2 seconds,
and 118.5 fps; that summary uses a different timing boundary. Logged rows include
end-of-demo work and are not individual CPU profiles.

The printed `server` bucket includes other host work, scheduling, and prior
printing; demo playback runs no local server. `gfx` includes presentation.
`snd` includes sound, light decay, and CD audio. Integer millisecond truncation
puts every sound sample below resolution; zero does not mean free work.

The retained run reports signal 11 **after** the completed summary. The native
signal handler can exit with status zero, so the script checks the log too.
Only pre-summary measurements contribute to the data. This is one instrumented
run on an Apple M2, not a historical benchmark or a claim about every stage.
