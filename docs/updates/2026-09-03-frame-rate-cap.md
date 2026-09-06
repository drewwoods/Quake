# 3–6 Sep — Frame pacing and interpolation on macOS

## Current state

The macOS software renderer separates simulation from rendering:

- `host_maxfps` controls the fixed simulation rate: default 72 Hz,
  clamped to 10–1000.
- Rendering follows a `CVDisplayLink` counter when the backend reports a
  positive refresh interval. Without a working counter, it falls back to a
  wall-clock gate at that interval.
- `host_interpolate 1` (default) interpolates visible entity transforms
  between snapshots. Local movement is displayed one simulation step behind
  the render clock: **13.9 ms at 72 Hz**, before presentation delay.
- `host_interpolate 0` displays the latest local snapshot. Its age varies
  within a step, causing uneven motion when simulation and display differ.
- Timedemo bypasses both rate gates. Headless and non-Apple backends render
  once per simulation step and skip this additional interpolation.

The pacing fixes were measured on a 60 Hz panel. Higher-refresh behavior
below follows from the code; it has not been validated on such a panel.
There are open correctness issues under **Remaining work**.

## Original problem and evidence

Before these changes, one host frame performed input, simulation, client
updates and rendering. `Host_FilterTime` capped that loop at 72 fps, except
in timedemo. It used actual elapsed time, clamped to 0.001–0.1 seconds;
this was a variable timestep with a rate ceiling, not fixed 72 Hz physics.

At 800×600:

| Historical measurement | Result |
|---|---|
| `timedemo demo1`, original presentation path | 129.3 fps |
| `timerefresh` | ~600 fps |
| Normal play, presented-frame probe | ~72 fps |
| Panel refresh | 60 Hz |

`timerefresh` loops over the renderer and video update with a static scene.
It omits the host loop, simulation, sound and demo parsing, so it is not a
whole-game benchmark.

Producing 72 frames for a 60 Hz panel creates an uneven 6:5 cadence.
Lowering the cap to 60 visibly improved motion. That established a rate
mismatch as one cause; subsequent phase tests found separate presentation
problems even after rendering was reduced to 60 fps.

A ~17-second demo sample on the original `drawRect` path also found a tail:

```text
mean 13.979 ms; sd 2.532; p50 13.877; p99 17.606; max 74.989
20 intervals >16.67 ms (1.73%)
```

The median matched the cap. The 75 ms stall was separate from the cadence
beat. This sample is not a baseline for the newer layer presentation path.

## Movement constraint

Changing the simulation rate changes movement. `SV_AirAccelerate` computes
`sv_accelerate * wishspeed * dt`, then clamps that acceleration to
`addspeed`. When the clamp binds, gain per step no longer scales with `dt`.
More steps can therefore produce more air acceleration.

With `wishspeed = 320` and acceleration 10, the unclamped increment is
44.4 at 72 Hz and 53.3 at 60 Hz. The often-quoted ~107 Hz threshold assumes
`addspeed = 30`; the clamp does not always bind for every velocity and angle.
In particular, negative velocity along the wish direction can make
`addspeed` exceed 30.

The earlier optimal-strafe model gave:

| Simulation rate | Speed after one airborne second | Gain from 320 u/s |
|---|---|---|
| 72 Hz | 405.3 u/s | 85.3 u/s |
| 60 Hz | 392.5 u/s | 72.5 u/s |

That is ~15% less gain, or ~3% less final speed. It is a model, not an
in-game measurement or a universal percentage. A normal jump lasts less
than one second. Jump-distance and strafe-speed comparisons remain pending.

Fixed steps also change hitch behavior: stock used one large step; the new
loop catches up through repeated fixed steps and abandons excessive backlog.
Preserving the nominal 72 Hz rate does not reproduce every stock trajectory.

## Implemented phases

### Phase 1 — configurable cap

Commits `9649e0d` and `8df3eab` introduced and clamped `host_maxfps`.
The bounds are the reciprocals of the original timestep limits. Zero is
clamped to 10, not interpreted as uncapped. Timedemo needs no cap override.

Historical checks: 5000 → 1000, 1 → 10, 0 → 10; valid values passed through,
with one warning per invalid assignment. Timedemo remained around its
then-current ~129 fps baseline. Before Phase 2, presented rate followed the
cvar; now it follows the display where supported.

The cvar is archived. Check the local `id1/config.cfg` before comparisons;
a saved value of 60 overrides the source default of 72.

### Phase 2 — separate simulation and render gates

Commits `07baa54` and `785eb14` added the refresh query and split the loop.
The current structure is:

```text
Host_Frame(elapsed)
  advance realtime
  if one simulation step is due:
    advance oldrealtime by dt
    process input, network, server and client
  if a display frame is due:
    interpolate visible transforms, if enabled
    render, present and update sound
```

`dt = 1 / host_maxfps`. Catch-up happens across outer-loop calls, one
simulation step per call, not in an inner loop that drains all pending steps
before rendering. After advancing a step, a backlog exceeding
`HOST_MAX_CATCHUP` steps resets `oldrealtime` to now and discards lost time.

Decoupling alone saves unused render work but still samples discrete
positions unevenly. Phase 3 provides intermediate positions.

### Phase 3 — interpolate visible state

Commits `0936340` and `712b3e2` added render interpolation and corrected its
handling of demo/network snapshot spacing.

The implementation keeps `cl.time` on its existing client-update path.
It does **not** remove the `sv.active` bypass in `CL_LerpPoint` or turn
`cl.time` into a render clock. Instead:

```text
alpha = clamp((realtime - oldrealtime) / dt, 0, 1)
target = cl.time - (1 - alpha) * host_frametime
frac = (target - cl.mtime[1]) / (cl.mtime[0] - cl.mtime[1])
```

`CL_LerpView` uses this fraction for entity origins, angles and client
velocity; demo view angles also interpolate. It does not extrapolate past
the newest snapshot. Local snapshots normally arrive once per simulation
step, making `frac = alpha`. Demos and remote servers have their own
snapshot spacing, so applying `alpha` directly would be wrong.

Live mouse angles are not delayed by this interpolation, but input is
still sampled in `Host_SimFrame`, at the simulation rate. Mouse look does
**not** gain 120/144 Hz input updates just because rendering does.
Particles, trails, lights and other effects are not all interpolated.

An earlier experiment removed only the local interpolation bypass while
keeping rendering tied to simulation. It printed `frac=1.000` every frame
and was reverted: there were no intermediate render moments to fill.

Historical Phase 2/3 measurements at 72 Hz simulation and 60 Hz rendering:

| Measurement | Result |
|---|---|
| Render rate | 60.2 fps |
| Fraction | 0.041, 0.241, 0.441, 0.641, 0.841 |
| Offset behind newest snapshot | mean ~7.8 ms, max ~13.3 ms |
| Timedemo | 130.3 fps |

The ~7.8 ms number is **not total content age**. It excludes the time since
the newest simulation step. See the latency calculation below.

### Above 72 Hz: multiple renders between simulation steps

Higher refresh does not require faster physics or future snapshots.
Each refresh samples a different position between the two available states.
The one-step delay ensures both endpoints already exist.

For a local game, let `S(n)` have simulation time `n * dt`. Between updates:

```text
render time:    n*dt + alpha*dt
shown time: (n-1)*dt + alpha*dt = render time - dt
position:      lerp(S(n-1), S(n), alpha)
```

At an ideally aligned 144 Hz, renders are 6.94 ms apart and simulation
steps are 13.89 ms apart. After startup:

| Render time | Available snapshots | alpha | Shown time |
|---|---|---|---|
| 13.89 ms | S(0), S(1) | 0 | 0 ms |
| 20.83 ms | S(0), S(1) | 0.5 | 6.94 ms |
| 27.78 ms | S(1), S(2) | 0 | 13.89 ms |
| 34.72 ms | S(1), S(2) | 0.5 | 20.83 ms |

When alpha resets, the snapshot pair advances, so the shown position
continues forward. Actual phase can shift those fractions. At 120 Hz,
there are five renders for every three simulation steps; the fractions
cycle differently, but constant-velocity motion still advances by 8.33 ms
per rendered frame. No integer ratio is required.

Interpolation off repeats the newest position between ticks: at aligned
144 Hz, each local position appears for two refreshes. Interpolation on
fills those intermediate positions while retaining 72 Hz simulation.
It adds no extra simulation-step delay merely because refresh is higher.

This assumes stable simulation, valid snapshots, a supported display cadence
and enough rendering capacity. Teleports and snapshot discontinuities snap;
input and unsmoothed effects retain their own update limits.

### Phase 5 — display cadence and layer handover

Phase numbering follows implementation history; Phase 4 remains pending.
Commits `9e64df6` and `553ef78` changed presentation to layer contents,
explicitly committed the transaction, and added display-link pacing.

The previous wall-clock gate ran at the correct average frequency but had
an arbitrary phase relative to the compositor. Launches measured at phases
15.89, 9.72 and 1.57 ms looked good, juddery and good respectively. Controlled
phase sweeps reproduced the difference on the same demo.

The layer path reduced measured frame cost from ~10.7 ms to ~1.37 ms
(1.02 ms rendering, 0.35 ms video update). However, implicit transaction
handover followed a later runloop turn, processed on the simulation grid.
Measured handover delays ranged from 0.18 to 12.15 ms.

Over a 12-second probe, counts classified by vsyncs advanced were:

| Vsyncs advanced | 0 | 1 | 2 |
|---|---|---|---|
| Before explicit commit | 143 | 432 | 143 |
| After explicit commit | 0 | 719 | 0 |

The callback now increments a counter; the main thread renders when it
changes. It never renders on the callback thread. After
`HOST_VSYNC_GRACE` refresh intervals without a counter change, the gate
falls back to wall-clock pacing. Five tested launches recorded no bad
frames. These observations do not guarantee no missed frames under load.

The phase harness lives on `judder-probe`, behind `QJPROBE`, not here.
Its controls are `QJ_PHASE=<ms>`, `QJ_SWEEP=<seconds>` and `QJ_LOG=<path>`.
Measurements in this section are recorded results, not rerun for this review.

## Latency: content age versus presentation delay

For steady local play, `dt = 13.89 ms`. Let `alpha` be the residual simulation
fraction at render, and `P` the actual delay from that render moment to display:

| Setting | Content age at render | Content age on display |
|---|---|---|
| Interpolation on | `dt` | `dt + P` |
| Interpolation off | `alpha * dt` | `alpha * dt + P` |

Turning interpolation off saves `(1-alpha)*dt` on that frame. For uniformly
distributed phases, the mean saving is 6.94 ms. Exact ratios and phase locking
can give a different mean; it is not a universal number. A recorded local
sample had mean alpha 0.500. The earlier mean 0.441 explains its ~7.8 ms offset.

These are ages of represented movement, not measured input-to-photon latency.
Input sampling, simulation response, render duration and scanout also matter.
The local formula does not describe remote-server buffering or demo timing.

A probe reported CoreVideo's predicted `outputTime - now` as mean 24.22 ms
(range 23.89–24.99 ms) on the tested 60 Hz setup. That is a prediction, not a
measurement of when this layer's pixels reach the panel. It establishes
neither a guaranteed upper bound nor a ~7.5 ms floor. Actual `P` remains
unmeasured and need not be constant or transfer to another refresh rate.

For illustration only, **if** `P = 24.22 ms`, content age would be 38.11 ms
with interpolation and 24.22–38.11 ms without. Do not quote those values as
measured end-to-end latency.

An experiment added the predicted presentation lead to interpolation time.
The ~24 ms lead exceeded a 72 Hz step and clamped every measured frame to
fraction 1, restoring snapping. It was reverted. Reducing presentation delay
requires measuring the actual pipeline first; extrapolation or a different
presentation backend would be separate work.

## Remaining work

### Correctness found during review

1. **Render-side time integration still assumes one render per step.**
   `R_DrawParticles` advances particles using `cl.time - cl.oldtime` on every
   render. Two renders without a simulation update consume the same delta
   twice. At steady 144/72 Hz, particle integration runs at twice its intended
   rate; at 60/72 it under-integrates. Console motion, center-message expiry
   and several view effects similarly consume `host_frametime` per render.
   Move simulation-owned mutations to the simulation path, and give visual
   timers an appropriate elapsed-time clock. Keeping `cl.time` unchanged did
   not by itself preserve these behaviors.
2. **A zero refresh-rate query bypasses a working display link.**
   `Host_FilterRender` returns `stepped` before reading the counter when
   `VID_RefreshInterval` is zero; `_Host_Frame` also disables interpolation.
   Displays reporting zero therefore fall back to 72 Hz rendering. Use the
   active display link independently of the nominal-rate query, with a
   fallback interval for its watchdog.
3. **The shared vsync counter is volatile, not atomic.** The callback writes
   it while the main thread reads it. Use atomic operations or synchronization;
   `volatile` does not make cross-thread access race-free.

The display link and cached refresh query also follow the main display,
not window moves or later mode changes. Higher-refresh mouse look would
require separating input sampling from simulation. These limits should be
resolved or explicitly accepted before declaring high-refresh support complete.

### Phase 4 — reduce busy-spin and investigate stalls

The non-dedicated main loop still spins between due events. Sleep or wait
until the next simulation/render deadline, then verify wake-up accuracy.
Re-measure the hitch tail on the current layer path first.

Thermal throttling is only a hypothesis for the historical 75 ms stall.
A 10–15 minute sample with CPU residency and thermal pressure could test it;
otherwise trace loading, I/O and sound work directly.

## Verification still needed

- Compare steady movement at 72 Hz against the pre-decoupling build using
  repeatable jump distances and strafe runs. Treat hitch differences separately.
- Test 60, 120 and 144 Hz with interpolation on/off, including particle
  progression, console speed, view effects and center-message duration.
- Test a zero nominal refresh query, display-link failure, display removal,
  window moves and refresh-mode changes.
- Repeat phase/cadence measurements across launches and under render load.
  Counter cadence alone does not prove each submitted image was displayed.
- Keep timedemo uncapped. The later layer-path result was 622.2 fps at
  800×600; it is not directly comparable to the old ~129 fps presentation path.
  Its reported 98% CPU busy does not identify compositor waiting: process CPU
  time includes other threads, and wall-minus-CPU is not a precise wait metric.
- Measure input-to-photon latency externally before selecting a new
  presentation backend on latency grounds.

Running the game can rewrite `id1/config.cfg`; inspect that diff before committing.
