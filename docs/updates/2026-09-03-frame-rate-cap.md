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
There are open correctness issues under **Remaining work**. The largest is
that render-side effects consume simulation deltas per render. At 72 Hz
simulation on a 60 Hz panel, simple linear timers run about 17% slow; at
144 Hz they run twice as fast. Integer rounding, conditional updates and
particle dynamics make other effects differ from this ratio. See **Phase 6**.

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
   `SCR_UpdateScreen` runs once per render, and its call tree consumes
   simulation-owned deltas: `host_frametime` in the console, view and sound
   timers, `cl.time - cl.oldtime` in particles and stair smoothing. Before
   Phase 2 a render coincided with a step and these were the same quantity.
   They are not now. Simple linear timers under-integrate by 1/6 at 60/72
   and run twice as fast at 144/72. Other effects also depend on rounding,
   snapshot timing and integration. This affects the default configuration,
   not only high refresh. Design in **Phase 6** below.
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

### Phase 6 — separate render-elapsed time from simulation time — **PLANNED**

Scope `host_frametime` for render-side timers, preserve fractional timer
progress, and move particle updates to simulation steps. The consumers need
different clocks; changing the global alone is insufficient.

#### What happens without it

The rate mismatch affects the macOS decoupled render path. Headless,
non-Apple backends and timedemo still render per simulation step. The
watchdog fallback remains display-interval paced and needs the same fix as
the display-link path.

For a linear timer consuming one fixed step per rendered frame, with no
rounding, pauses or stalls:

```text
rate multiplier = rendered frames per second / host_maxfps
```

| Display / `host_maxfps` | Linear timer rate | Duration multiplier |
|---|---|---|
| 60 / 72 — default | 0.833× | 1.20× |
| 60 / 36 | 1.667× | 0.60× |
| 120 / 72 | 1.667× | 0.60× |
| 144 / 72 | 2.0× | 0.50× |

At 800×600, these give approximate durations, rounded to render frames:

| Effect | Nominal | At 60/72 | At 144/72 |
|---|---|---|---|
| Console half-screen slide (`scr_conspeed 300`) | 1.00 s | 1.20 s | 0.50 s |
| Centerprint (`scr_centertime 2`) | 2.00 s | 2.40 s | 1.00 s |
| Damage view kick (`v_kicktime 0.5`), unpaused | 0.50 s | 0.60 s | 0.25 s |

Do not apply this table universally. Palette percentages and ambient volume
are integers, so fractional updates are discarded each render. Pitch drift
integrates velocity as well as angle. Stair smoothing depends on the moving,
interpolated target and clamps its lag to 12 units. These effects require
measurements, not exact duration predictions from the rate ratio.

Particle integration consumes the client delta per render. Timestamp expiry
checks `p->die < cl.time`, but fire and explosion ramps can also set
`p->die = -1`. Refresh therefore affects motion, colour progression and
potentially lifetime. Acceleration and damping mean neither travel distance
nor lifetime follows a universal multiplier.

The consequence is visible at the default 60/72 configuration: effects vary
with refresh and with `host_maxfps`, even though rendering and simulation
are intended to be independent. Pitch drift also changes aim state. The
server physics timestep and the Phase 5 pacing mechanism are separate from
these render-side defects.

#### Simulation and movement: audited separately

The effects above are render-side. The simulation was checked independently,
because "the renderer is wrong" does not by itself say the game is right.

Correct as it stands:

- **Fixed timestep.** `oldrealtime += dt` exactly, one step per call, so the
  simulation clock advances at precisely `1 / host_maxfps` with no drift.
- **All server physics.** `sv_phys.c` and `sv_user.c` run on the simulation
  path with `host_frametime = dt`. Air acceleration, friction, gravity and
  entity movement are untouched by Phases 2, 3 and 5.
- **Keyboard turning.** `CL_AdjustAngles` (`cl_input.c:238,240`) is reached
  through `CL_SendCmd`, on the simulation path.
- **Mouse input.** Deltas accumulate in the event pump and are drained once
  per simulation step through `CL_SendCmd` → `IN_Move`. Nothing is lost; the
  sampling rate is 72 Hz, which is a limit, not an error.
- **Demo playback.** `host_framecount` stays on the simulation step, so
  `cl_demo.c` still reads at most one message per step.
- **Beams anchored to the player.** `CL_UpdateTEnts` (`cl_tent.c:346`) reads
  `cl_entities[cl.viewentity].origin`, but runs immediately after
  `CL_RelinkEntities` inside `CL_ReadFromServer`, so it sees the snapshot
  origin rather than an interpolated leftover.

`CL_LerpView` writes shared client state, so the Phase 3 commit's claim that
it is "deliberately free of side effects" is imprecise. What it writes, and
who can observe it:

| Written | Restored by | Read on the simulation path? |
|---|---|---|
| `cl_entities[].origin`, `.angles` | `CL_RelinkEntities`, every step | No — recomputed before any consumer |
| `cl.velocity` (`cl_main.c:677`) | `CL_RelinkEntities` (`cl_main.c:461`) | No — only `V_CalcBob` (`view.c:127`) and `V_CalcRoll` (`view.c:812`), both render-side |
| `cl.viewangles` (demo playback only) | — | Demos issue no meaningful commands |

So interpolation does not leak into the simulation. The writes are confined to
render-side consumers.

**The exception is `V_DriftPitch`, and it is a movement defect, not a cosmetic
one.** It runs on the render path and writes `cl.viewangles[PITCH]`, which
`CL_SendCmd` reads on the next simulation step and transmits. Pitch recentring
— `lookspring`, `centerview`, releasing `+mlook` — is therefore scaled by the
same display/simulation ratio as the cosmetic timers: 17% slow at 60/72, twice
as fast at 144/72, with the wrong angle sent to the server.
`cl.driftmove += host_frametime` is scaled identically, so drift also *starts*
at the wrong time.

This is not pre-existing. Before Phase 2 a render accompanied each step, so
`V_DriftPitch` ran exactly once per step and was correct. Phase 2 introduced
it, and an earlier draft of this note wrongly filed it as a long-standing
limitation.

#### Group A — render-elapsed time

Wall-clock UI, view and audio timers. `Host_FilterRender` records whether
the render was display-paced; `_Host_Frame` replaces `host_frametime` with
the interval since the previous display-paced render, then restores it:

```text
CL_LerpView (...)             /* still needs the simulation step */
save = host_frametime
host_frametime = render-elapsed
SCR_UpdateScreen / S_Update / CDAudio_Update
host_frametime = save
```

The swap goes *after* `CL_LerpView` because `cl_main.c:668`
(`t = cl.time - (1 - alpha) * host_frametime`) is the one render-path reader
that needs the simulation step. Every other render-path reader is inside the
scoped region. Scoping `host_frametime` around a block is already an idiom
in this source: `sv_phys.c:1579-1614` does it inside `SV_Trace_Toss`.

| Site | Effect |
|---|---|
| `screen.c:468,475` | console slide |
| `screen.c:178` | centerprint expiry |
| `screen.c:369` | `SCR_DrawTurtle` threshold (debug cvar, default off) |
| `view.c:557,562,643,648` | damage and bonus palette decay |
| `view.c:724` | gun angle slew |
| `view.c:819` | `v_dmg_time` view kick |
| `view.c:199,216,217` | `V_DriftPitch` — **affects aim, not appearance** |
| `view.c:961-979` | stair smoothing |
| `snd_dma.c:704,710` | ambient volume fade |

Preserve existing pause gates. Explicit `cl.paused` skips `V_CalcRefdef`,
freezing pitch drift, view kick and stair smoothing; UI and audio have their
own gates. Single-player console/menu physics suspension is different: it
can stop the server while view calculation continues.

**Preserve fractional progress on the decoupled path.** Palette `percent`
and ambient `master_vol` are integers. A smaller timestep alone can round
ambient increases to zero and distort palette decay. Retain fractional
remainders in the fade routines, while leaving their integer outputs intact.
Reset remainders when an effect or channel resets, its target is reached,
or pacing mode changes; account for externally replaced values and fade
reversals. Keep legacy arithmetic on coupled paths. This requires changes
in `view.c` and `snd_dma.c`, beyond the scoped override.

**Stair smoothing belongs here, not on the simulation path.** `oldz`
(`view.c:871`) chases `cl_entities[cl.viewentity]`, which `CL_LerpView`
rewrites — it is the *interpolated* origin — and the result is applied as
`r_refdef.vieworg[2] += oldz - ent->origin[2]`. Advancing `oldz` on the
simulation path would chase the simulation Z while subtracting the
interpolated Z; the residual is the interpolation offset itself, which would
put a term oscillating at the interpolation fraction into eye height. It
uses `steptime = host_frametime` on the decoupled path, with no timestamp.
Keep the existing delta on coupled paths. During explicit pause,
`V_CalcRefdef` is skipped and `oldz` holds. If only server physics stops while
view calculation continues, `oldz` may converge toward the frozen target;
this is a deliberate change from consuming a zero client-time delta.

**`V_DriftPitch` is listed deliberately, and it is the one Group A site that
affects aim rather than appearance.** It mutates `cl.pitchvel` and
`cl.viewangles`, which `CL_SendCmd` reads on the simulation path and sends to
the server. Render-elapsed time removes the wrong timestep multiplier, but
numerical integration still depends on render cadence, so aim state remains
advanced on the render clock. Phase 2 introduced this; it is not a
long-standing limitation. Moving `V_DriftPitch` onto the simulation path would
close it, and is deliberately not part of Phase 6. See the simulation audit
above.

Render-elapsed interval, defined explicitly:

- initialised at the first display-paced render, so that frame's delta is 0
  rather than the interval since process start;
- reset when switching from coupled to display-paced rendering; watchdog
  fallback and link recovery remain display-paced, so keep the timestamp
  across those transitions and apply the stall clamp;
- clamped to `[0, 0.1]`, matching the pre-existing `host_frametime` ceiling.
  The ceiling **discards** elapsed time: past 100 ms in one frame these
  timers deliberately fall behind rather than catching up, so "advances by
  real time" holds only below the clamp;
- `double`, matching `cl.time` and `cl.oldtime` (`client.h:198,201`).
  `view.c:965` currently declares `float steptime`.

#### Group B — simulation time

Particles only. Split `R_DrawParticles` into `R_UpdateParticles` (expiry and
integration) and a draw-only pass, and call the former once per simulation
step from `Host_SimFrame`, beside `CL_DecayLights` and under the same
`cls.signon == SIGNONS` guard.

`R_UpdateParticles` computes `cl.time - cl.oldtime` after
`CL_ReadFromServer`. Integration, timestamp expiry and ramp-driven death
therefore follow client time, including local pause and `host_framerate`
overrides. Snapshot corrections can change this delta; retaining the
expression does not make it identical to `host_frametime`.

**Draw ordering changes.** Today each particle is drawn before its position,
velocity and ramp advance. The split updates before drawing, so even coupled
paths display the advanced position and colour. Accept this as an explicit
part of the plan, not a no-op: test first-frame appearance, ramp-driven death
and timedemo output. Particles also advance on simulation steps when drawing
is skipped. Timestamp expiry remains checked before integration, as today;
keep ramp-driven removal ordering explicit in the split.

No accumulator: particles integrate gravity and velocity damping, so one
step of `N*dt` does not equal `N` steps of `dt`, and a particle spawned
between renders would otherwise receive time from before it existed.

No new state, so no lifecycle to manage — `R_ClearParticles` already runs on
map load.

#### Group C — coupled paths

Timedemo and any render gated by `stepped` keep the existing timestep,
including the timedemo 1 ms floor. Group A also retains legacy fade
arithmetic and the original stair delta on these paths. Group B retains its
client-time delta but changes draw/update ordering as described above.
Timedemo stays uncapped; identical particle images or benchmark results are
not promised. Compare output and performance against the current build.

An earlier draft claimed the fix was a no-op wherever rendering is 1:1 with
simulation. That was wrong. On a coupled path a render accompanies each
step, so catch-up steps run back to back and a render-elapsed delta would be
near zero while `host_frametime` stays `dt` — motion would stall through a
hitch instead of advancing.

#### Rejected alternatives

- **A `cl.time`-based timestamp per consumer.** Needs explicit
  initialisation and reset on map and demo changes and on skipped rendering;
  clamping negative deltas does not prevent large positive jumps; and in
  stair smoothing the timestamp must advance outside the ascent condition or
  flat walking accumulates and the next step consumes the whole interval.
- **Substituting `host_frametime` for `cl.time - cl.oldtime` in particles.**
  Not equivalent even on coupled paths: `CL_LerpPoint` (`cl_main.c:399,415,425`)
  can reassign `cl.time` after `CL_ReadFromServer` increments it. The
  `steptime < 0` guard already in `view.c:965` records that the original
  authors knew this.

#### Scope

Expected edits:

- `host.c`: pacing mode, render timestamp, scoped swap and particle-update call.
- `r_part.c`: particle update/draw split.
- `view.c`: conditional stair delta and fractional palette decay.
- `snd_dma.c`: fractional ambient fade.
- Shared headers: declare `R_UpdateParticles` and expose the pacing mode needed
  by conditional consumers. Keep timestamp and fractional state private.

`screen.c` timers receive the scoped delta without call-site changes.
The particle update is a new cross-file function; this is not a three-file,
no-new-symbol change.

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
- Phase 6, render-domain effects — compare console retract, centerprint,
  palette decay and ambient fade at `host_maxfps` 36 / 72 / 144 on the 60 Hz
  panel. Expect matching duration within render-frame and rounding tolerance.
  Use fixed starting values and targets. Test fractional fades separately at
  high render rates, including increments below one integer unit: changing
  simulation rate on a 60 Hz panel does not exercise that case.
- Phase 6, controlled fixtures — use a stationary scripted explosion for
  particle travel, a fixed approach to one stair, and fixed initial pitch for
  `centerview`. Compare with tolerances: physics, numerical integration and
  frame quantization prevent exact equality across simulation rates.
  Check both timestamp-expiring and ramp-killed particles; lifetime need not
  be identical across rates, but must no longer scale with render frequency.
- Phase 6, clock consistency — explicit pause/resume should freeze local
  particles and `oldz` while the console can slide. Separately test console/menu
  physics suspension and stair convergence. Check `host_framerate 0.05`, map
  changes, effect resets, fade reversals and pacing-mode transitions.
- Phase 6, coupled paths — verify legacy timer/stair arithmetic, and compare
  particle spawn, colour and death frames after the intentional update-order
  change. Timedemo must remain uncapped; record performance differences rather
  than assuming the split is neutral.
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
