# 3 Sep — Frame rate cap on the macOS software renderer

## Symptom

`make -C WinQuake -f Makefile.macos` builds and runs fine, but at
`-width 800 -height 600` the game does not feel as smooth as the numbers
suggest:

| Measurement | Reported |
|---|---|
| `timedemo demo1` | 129.3 fps (969 frames / 7.5 s) |
| `timerefresh` | ~600 fps |
| Actual play | *feels* far slower |

## Findings

### 1. The host loop is capped — 72 fps, now the `host_maxfps` default

Before Phase 1 landed, `Host_FilterTime` held a literal:

```c
/* pre-Phase-1; host.c:507-509 is now the host_maxfps test */
if (!cls.timedemo && realtime - oldrealtime < 1.0/72.0)
    return false;		// framerate is too high
```

Returning false makes `_Host_Frame` bail at `host.c:650`, *before*
`SCR_UpdateScreen`. Note the `!cls.timedemo` term: timedemo is the one
path explicitly exempted. That is why timedemo reports 129 fps and normal
play cannot.

Measured, not assumed. A dyld interpose on `CGDataProviderCreateWithData`
— which `drawRect` calls once per presented frame (`vid_macos.m:163`,
provider at `:175`) — counts screen updates without instrumenting the
loop:

```
t=3136411.441  delta=72
t=3136412.441  delta=72
t=3136413.443  delta=72
t=3136414.448  delta=73
t=3136415.451  delta=72
```

Locked to the cap, ticks 1.000 s apart. The rasterizer has ~57 fps of
headroom it is never allowed to spend.

### 2. `timerefresh` is not a comparable number

`R_TimeRefresh_f` (`r_misc.c:69`) loops `R_RenderView` + `VID_Update`
directly and never enters `Host_Frame`: no `Host_FilterTime`, no server
tick, no sound mixing, no demo parsing, and a static scene with no entity
relinking. ~600 fps is the raw rasterizer ceiling, not an achievable game
rate, and not a target.

### 3. 72 fps into a 60 Hz panel is the reported judder

`CGDisplayModeGetRefreshRate` on the built-in display returns **60.00 Hz**.
`VID_Update` (`vid_macos.m:413`) presents with `setNeedsDisplay:` +
`displayIfNeeded` (`:435-436`) and no vsync, so 72 frames/sec are
composited by a 60 Hz WindowServer: 12 frames every second are drawn and
discarded, on an uneven 6:5 cadence.

**This is the cause of the reported symptom** — confirmed later by test,
see Phase 1.

### 4. Minor: the main loop busy-spins

`sys_linux.c` calls `Host_Frame` every iteration with no sleep on the
non-dedicated path (the `usleep(1)` is inside the `ca_dedicated` branch
only). Since rejected calls return before `SCR_UpdateScreen`, the loop
spins far faster than the render-limited ~129 fps, so the overwhelming
majority of `Host_Frame` calls are rejects — not the "~40%" an earlier
draft of this note claimed. (That 40% was 72/129, a different quantity:
the share of *render-capable* frames the cap discards.)

Costs power and thermal headroom. Does not limit fps.

### 5. A second, separate defect: a hitch tail

Distinct from Finding 3 — the beat is what was reported; this is an
additional problem found while measuring. Frame-interval distribution
over ~17 s of `+playdemo demo1`, loading excluded:

```
mean=13.979ms  sd=2.532ms  min=4.155  p50=13.877  p99=17.606  max=74.989
intervals >16.67ms (a missed 60Hz vsync): 20 (1.73%)
```

`p50` of 13.877 ms sits on `1/72 = 13.888 ms`. **The existing gate is
already well paced** — there is no systemic jitter to correct.

Read the tail carefully: with `p99 = 17.6 ms`, most of that 1.73% is
one-frame slop, not visible hitching. The one genuinely visible event is
the 75 ms stall. These are frames the game failed to *produce* in time,
not frames delivered at the wrong moment.

---

## The constraint that governs everything below

**The cap is not a video setting. It sets the rate at which movement is
integrated, and changing it changes how the game plays.**

Be precise about the mechanism, because an earlier draft of this note
got it wrong. `FPS_20` is undefined (`host.c:555`), so `host.c:603`
selects the plain `Host_ServerFrame`: one server tick per host frame,
with `host_frametime` set to **actual elapsed time**, clamped to
[0.001, 0.1]:

```c
host_frametime = realtime - oldrealtime;
```

So the loop is **variable-dt with a maximum rate**, *not* a fixed
timestep. Happy-path frames sit on 1/72 — hence `p50 = 13.877 ms` — but
a slow frame is one large `host_frametime` step, not N small ticks. The
75 ms stall in Finding 5 was a single ~75 ms integration step.

The sharpest consequence is air control. `SV_AirAccelerate`
(`sv_user.c:207-226`):

```c
wishspd = VectorNormalize (wishveloc);
if (wishspd > 30)
    wishspd = 30;
currentspeed = DotProduct (velocity, wishveloc);
addspeed = wishspd - currentspeed;
if (addspeed <= 0)
    return;
accelspeed = sv_accelerate.value*wishspeed * host_frametime;
if (accelspeed > addspeed)
    accelspeed = addspeed;			// trips at any rate below ~107 fps
```

`accelspeed` is `10 * 320 * dt` = 44.4 per frame at 72 fps, 53.3 at 60,
while `addspeed` can never exceed 30. **The clamp therefore always
trips**, and the per-frame gain becomes `addspeed`, independent of
`host_frametime`. Airborne acceleration is proportional to *frame count*,
not elapsed time.

That equivalence has an upper bound: the clamp only always trips while
`3200*dt > 30`, i.e. below ~107 fps. Above that the mechanism changes
character, which matters for anyone raising the cap.

Modelled over one airborne second, starting at 320 u/s at an optimal
strafe angle:

| Rate | Speed after 1.0 s | Gain |
|---|---|---|
| 72 fps | 405.3 u/s | 85.3 |
| 60 fps | 392.5 u/s | 72.5 |

Quote both numbers, because "15%" alone overstates it: that is **~15%
less speed *gain*, but only ~3% less speed**. And one airborne second is
longer than a real jump — a 270 u/s jump against `sv_gravity 800` hangs
for ~0.675 s — so a single jump sees less than the table shows. The
*direction* of the effect is certain; the magnitude in casual play is
modest.

Ground friction shifts far less: `SV_UserFriction` (`sv_user.c:151`)
subtracts linearly per frame, so one second of decay retains 0.01632 of
speed at 72 fps versus 0.01593 at 60 — about 2%. Ground `SV_Accelerate`
(`sv_user.c:199`) saturates within a few frames at either rate and is
effectively unaffected.

**Correction to an earlier draft**, which called `host_maxfps` "safe to
lower". It is not: lowering the cap is a gameplay change. 72 is the rate
vanilla Quake shipped with and the rate its movement was tuned at.

---

## Goal

Originally: preserve the 72 Hz rate exactly, and treat any smoothness
work that touches it as off the table.

Where it landed. A 72 Hz simulation cannot be displayed evenly on a
60 Hz panel; no arrangement of the render path removes the 6:5 beat while
leaving both the rate and the latency alone. Three levers:

| Lever | Cost | Status |
|---|---|---|
| Lower the rate (`host_maxfps 60`) | ~15% less air *gain* (~3% less speed) | implemented, confirmed smooth |
| Interpolate (Phases 2+3, together) | ~7.8 ms mean movement latency | **implemented** |
| Neither | the beat stays | Option zero |

One measurement that should not be confused with the above: Finding 5
shows the **pre-Phase-2** 72 Hz gate was already well paced. It says
nothing about the decoupled loop, which is a different mechanism.

The latency cost came in below the prediction. This note long argued
Phase 3 would cost "one full step, ~13.9 ms". Measured, the render lands
mid-step far more often than at its start, so the mean is **~7.8 ms** and
only the worst case approaches ~13.3 ms.

Both levers are also smaller than they look next to a cost this note had
never counted: the compositor holds a finished frame ~24 ms before it is
on the panel (Finding 8). No lever here touches that.

## Plan

### Phase 1 — `host_maxfps` — **IMPLEMENTED** (commit 2e99166)

The cap is a cvar instead of a literal, defaulting to 72 so stock
behaviour is unchanged.

- `host.c` — `cvar_t host_maxfps = {"host_maxfps","72",true};`
- `host.c` — registered in `Host_InitLocal`
- `host.c` — `Host_FilterTime` clamps the value to 10..1000, then divides by it
- `quakedef.h` — `extern cvar_t host_maxfps;`

**Confirmed by testing:** `host_maxfps 60` makes motion visibly smooth,
which confirms Finding 3's diagnosis — the beat was the reported judder.

Be careful how strongly that is stated. 60 removes the 6:5 beat, but
production is still a wall-clock cap with no vsync, so phase relative to
the WindowServer can drift and occasional doubled or dropped frames
remain. It is far better than 12 discards a second; it is not a hard
lock.

**Superseded by Phase 5.** The render clock is now locked to vsync, so
the phase no longer drifts and the doubled and dropped frames are gone.

**Range clamp — implemented.** `Host_FilterTime` clamps to 10..1000 with
a write-back, following the vanilla `Cvar_Set` idiom used for `viewsize`
(`screen.c:234`):

```c
if (host_maxfps.value < 10 || host_maxfps.value > 1000)
{
    Con_Printf ("host_maxfps %g out of range, clamping to 10..1000\n",
        host_maxfps.value);
    if (host_maxfps.value < 10)
        Cvar_Set ("host_maxfps", "10");
    else
        Cvar_Set ("host_maxfps", "1000");
}
```

The bounds are not arbitrary — they are the reciprocals of the
`host_frametime` clamps a few lines below in the same function. Outside
10..1000 those clamps make simulated time diverge from wall time: above
1000 the 0.001 s floor makes the game **run fast**, below 10 the 0.1 s
ceiling makes it run slow. `timedemo` ignores the cap entirely, so
benchmarking never needs it unset — which is why 0 is no longer accepted
as "uncapped".

**Remaining caveats, not guarded:**

- Above ~107 fps the air-accel clamp stops always tripping (see above),
  so raising the cap within the legal range still changes the mechanism,
  not just the frame count.
- The cvar is archived, and `id1/config.cfg` now carries
  `host_maxfps "60"`. **A launch with that config is not stock.** Check it
  before any comparison against reference behaviour.

---

## Phases 2 and 3 — **IMPLEMENTED**

Both were previously written up as verdicts without the mechanism.
Setting that right — and noting they are not independent options, but one
change in two halves.

### The thing they both address

Simulation and rendering are welded together. `_Host_Frame` runs one
server tick and immediately renders the state it produced:

```
_Host_Frame(time):
    if (!Host_FilterTime(time)) return;      // rate ceiling
    ...
    Host_ServerFrame();                      // one variable-dt step
    CL_ReadFromServer();                     // cl.time += host_frametime
    SCR_UpdateScreen();                      // render + present
```

Render happens once per step, 1:1, at the instant that step finishes. The
display composites on its own 60 Hz cadence that nothing here knows about.

### Phase 2 — decouple the two clocks (commit 5444c7d)

Split the single gate in two:

- **Simulation gate:** a fixed-timestep accumulator.
- **Render gate:** `SCR_UpdateScreen` driven by the display's cadence.

```
while (1) {
    accumulate += elapsed;
    while (accumulate >= dt) {               // dt = 1/host_maxfps
        Host_ServerFrame();
        accumulate -= dt;
    }
    if (display_wants_a_frame)
        SCR_UpdateScreen();
}
```

The accumulator should read `host_maxfps`, not a hardcoded 72, now that
Phase 1 exists.

**This is a behaviour change, not a neutral refactor** — the previous
draft wrongly called it "unchanged in feel". Today's loop takes one large
variable step through a stall; an accumulator takes several fixed steps
instead. That is arguably *more* correct air accel during hitches, but it
is different, and it needs a maximum-steps-per-frame cap or a long stall
spirals (each catch-up step costing more time than it simulates).

**On its own it does not smooth anything.** You would still draw the
newest discrete state, still sampling a staircase at 60 Hz, so the beat
survives. It buys ~17% less wasted render work and a fixed rather than
free-running phase.

**On the render gate specifically:** the safe design is to read the
refresh rate once via `CGDisplayModeGetRefreshRate` and gate the *main
thread*. A `CVDisplayLink` callback runs on its own thread and nothing in
this renderer is thread-safe, so if a display link is used at all it must
only set a flag the main loop reads. Also handle
`CGDisplayModeGetRefreshRate` returning 0, which it does on some displays.

Phase 5 built exactly that, and found the refresh *rate* is not enough on
its own: the rate was already right, and the phase was what was wrong.

### Phase 3 — interpolate to the render moment (commit d10a398)

Once a render lands *between* steps, draw the world as it was at that
moment, interpolating between the two states bracketing it.

For render time `T` to be bracketed, both `S(n-1)` and `S(n)` must
already exist, so `T <= t(n)`. You are always drawing up to one step in
the past — **~13.9 ms** at 72. That is the unavoidable cost and the whole
argument against it.

In this codebase Phase 3 is mostly *un-bypassing machinery that already
works*:

- `CL_RelinkEntities` already lerps `msg_origins[1]` → `[0]` — proven
  every time a demo plays.
- `cl.time` becomes a deliberately lagged render clock instead of being
  pinned to `cl.mtime[0]`.
- `CL_LerpPoint` computes `frac` from that clock; the `sv.active` bypass
  comes out.
- The view origin is copied from `cl_entities[cl.viewentity]` in
  `V_CalcRefdef` (`view.c:892`) and so interpolates with everything else.

**Important nuance:** view *angles* come from the mouse (`cl.viewangles`)
and are sampled per host frame, so they would not be delayed. Mouse look
stays crisp; only world and camera *position* lag. The 13.9 ms is a
movement latency, not an aim latency.

### Why they are one change and not two

- **Phase 2 without 3** — renders land between steps but you draw the
  newest state anyway. Beat survives.
- **Phase 3 without 2** — render is 1:1 with the step, so `T` always *is*
  a step boundary, `frac` is always 1.0, and `lerp(a,b,1.0) == b`.
- **Together** — render on the display's cadence, each frame interpolated
  to its own moment: even motion at an unchanged rate, for ~13.9 ms.

**Phase 3 alone was built and is confirmed inert.** Removing `sv.active`
from `CL_LerpPoint` and running a local game printed, every frame:

```
lerp: frac=1.000 f=0.0139 lag=0.0ms
```

`f = 0.0139` is 1/72: the local server emits a state every host frame and
`cl.time` advances by `host_frametime`, so the clocks track exactly and
`frac` pins to 1.000. Motion was unchanged. Reverted.

### What building it actually took

- Restructure `_Host_Frame` into a sim step and a render step. This is
  the core loop; it is the risky part.
- Cap catch-up steps per frame to avoid a stall spiral.
- Two client snapshots: largely present already as `msg_origins[0]/[1]`,
  `mvelocity[0]/[1]`, `mtime[0]/[1]`.
- Decide where `S_Update` belongs — per step or per render.
- **`cl.time` was left alone.** The original sketch made it a lagged
  render clock, but it feeds `CL_DecayLights`, particles, water warp,
  alias skin cycling, view bob, idle sway and face animation. Rather than
  shift all of them, the interpolation fraction is passed explicitly to
  `CL_LerpView` and `cl.time` keeps its simulation meaning. This removed
  the largest source of risk in the change.
- Entity culling compares `ent->msgtime != cl.mtime[0]`; a lagged clock
  needs that revisited.
- The accumulator must stay pinned to `host_maxfps`. If it drifts with
  the render rate the feel changes and the exercise defeats itself.

### Result

Built and measured. With simulation at 72 and the panel at 60:

| | before | after |
|---|---|---|
| presented rate | 72.0 fps (13.882 ms) | 60.2 fps (16.607 ms) |
| interpolation fraction | pinned 1.000 | sweeps 0.041..0.841, mean 0.441 |
| movement latency | 0 | ~7.8 ms mean, ~13.3 ms worst |
| timedemo | ~129 fps | 130.3 fps (unaffected) |

The fraction lands on exactly five values — 0.041, 0.241, 0.441, 0.641,
0.841 — which is the 5:6 beat of 60 into 72. Those are the same five
phases that used to be *snapped* to and produced the judder; they are now
interpolated across.

There is still a real cost, and it is a movement-feel cost, so it is
toggleable: `host_interpolate 0` restores stock snapping. The honest
comparison against `host_maxfps 60` is ~7.8 ms of movement latency versus
~15% less air gain. Neither is free.

---

## Phase 5 — pace on the display, hand the frame over at once — **IMPLEMENTED** (5-6 Sep)

Phases 2 and 3 fixed *what* each frame depicts. They left *when* it reaches
the screen to luck, and two separate defects there put the beat back on the
panel. Neither is in frame production: the game produced a flawless 60.00 fps
throughout both.

Reported as "smooth on some launches, juddery on others, and it stays that way
for the whole session". Easiest to see in the console sliding shut, which
advances a fixed amount per *rendered frame* and so reads presentation cadence
directly, with no interpolation in the path.

### The panel is not the variable

| | |
|---|---|
| refresh | 60.0005 Hz |
| vsync interval sd | **0.0000 ms** |
| game render clock | `1/CGDisplayModeGetRefreshRate()` = 16.66667 ms |
| frequency error | 0.00017 ms/frame — one slip per ~27 min |

Not a 120 Hz compositor, and not a rate mismatch. The rate was already right.

### Finding 6: the render phase is a lottery, drawn once per launch

`Host_FilterRender` advanced `host_lastrender` by the refresh interval and
never consulted vsync, so its phase against the compositor was undefined.
This line set it:

```c
host_lastrender += interval;
if (realtime - host_lastrender > interval)
    host_lastrender = realtime;   // fell behind; resync rather than burst
```

Every stall longer than one interval reseeds the clock to whatever instant the
game recovered at. Loading is full of them, so the last one before gameplay
picks the phase and the session keeps it. Measured across launches, each
stable to sd 0.25 ms for its whole run:

| launch | a | b | c |
|---|---|---|---|
| phase | 15.89 ms | 9.72 ms | 1.57 ms |
| verdict by eye | good | **juddery** | good |

**Reproduction.** `-DQJPROBE` replaces the free-running gate with one locked
to a real vsync at a chosen offset, so phase becomes an input rather than
whatever a stall left behind:

```
QJ_PHASE=<ms>       pin one phase for the whole run
QJ_SWEEP=<seconds>  walk all eleven, holding each that long
QJ_LOG=<path>       where to write the trace
```

`QJ_PHASE=0` juddered for its whole life and `QJ_PHASE=9.1` was clean for its
whole life, on the same demo — which separates phase from content. Sweeping
all eleven against the eye, with the frame costing 10.7 ms of the 16.67 ms
budget on the `drawRect` path:

| frame finishes at | 10.8 ms | 12.3 | 13.8 | 15.0 | 16.5 | 1.4 – 6.4 | 7.8 | 9.2 |
|---|---|---|---|---|---|---|---|---|
| verdict | worst | bad | poor | mild | slight | **clean** | slight | mild |

That is a compositor deadline, roughly 6 ms before the vsync a frame is for.
Land clear of it and every frame makes its vsync; land on it and render-time
jitter makes frames alternately make and miss — one shown twice, one dropped.

### Finding 7: the handover rode the wrong runloop turn

On the layer-present path (commit 9e64df6) a frame costs only 1.37 ms — 1.02
rasterising, 0.35 in `VID_Update` — so the safe window is wide and phase
should barely matter. It juddered anyway, and worse.

Assigning `layer.contents` starts an *implicit* CATransaction, which commits
on the next runloop turn. The only runloop turn in this loop is inside
`Sys_SendKeyEvents`, called from `Host_SimFrame` — the simulation's 72 Hz
grid, not the render's 60 Hz one. So a frame finished at a rock-steady phase
(sd 0.21 ms) reached the compositor 0.18 to 12.15 ms later, at five discrete
delays beating 6:5. Vsyncs advanced per presented frame, over 12 s:

| vsyncs advanced | 0 | 1 | 2 |
|---|---|---|---|
| frames | **143** | 432 | **143** |

20% of frames overwritten before they were ever shown, 20% shown twice — about
12 stutters a second, with no wall clock anywhere in the mechanism.

### The fix (commit 6fa5f69)

**Commit the transaction where the frame is finished.** `[CATransaction
begin]` / `commit` around the `setContents:`, costing 0.22 ms. Handover
becomes as steady as the frame: `0:143 1:432 2:143` becomes **`1:719`**.

**Take the cadence from the display.** A `CVDisplayLink` callback bumps a
counter and does nothing else — the design Phase 2 called for.
`VID_VsyncSerial` reports it and `Host_FilterRender` renders when it changes,
so the frame is drawn immediately after a vsync with a full interval of slack
and the phase is the same every launch.

`HOST_VSYNC_GRACE` intervals of silence fall back to the wall clock: a display
link stops when its display goes away, and a game rendering only on vsync
would then stop drawing. Platforms that cannot count refreshes return 0 and
keep the old path.

**Both were needed.** With the commit fixed but the clock still free-running,
a phase sweep found ten of eleven positions perfect and one losing 20% of
frames — a ~6% chance per launch of a session that stutters end to end.

| launch | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| gate phase | 9.14 | 9.15 | 9.09 | 9.13 | 9.12 ms |
| bad frames | 0 | 0 | 0 | 0 | 0 |

against 0.05 / 5.87 / 7.79 / 12.11 ms before. The commit now lands 5.9 ms
clear of the boundary that failed.

### Finding 8: aiming the interpolation at presentation time does not work

`Host_LerpFrac` targets the render moment, so a frame depicts when it was
drawn rather than when it is seen. Correcting that reads like a free win. It
is not. `CVDisplayLink` reports the predicted presentation time, and the lead
is larger than a simulation step:

```
outputTime - now: mean 24.2222 ms  min 23.8947  max 24.9921
                  = 1.45 refresh periods = 1.74 simulation steps at 72
```

`CL_LerpView` interpolates between the last two snapshots and returns early at
`frac >= 1.0`; it never extrapolates. Aiming 1.74 steps past the newest state
therefore pins every frame:

| | aimed at render moment | aimed at presentation |
|---|---|---|
| lerp fraction, demo | mean 0.458, sweeps 0.001..0.997 | **1.000, on 100% of frames** |
| lerp fraction, local game | mean 0.500, sweeps 0.036..0.912 | **1.000, on 100% of frames** |
| `CL_LerpView` pins, local game | 0% | **100%** |

Pinned at 1.0 is stock snapping — precisely what Phase 3 was built to remove.
Built, measured, reverted.

Closing that 24 ms needs *extrapolation* across nearly two simulation steps,
which overshoots on every collision and direction change. That is a
movement-feel change of the kind Phase 3 deliberately refused, and a separate
piece of work — not a tweak to the lerp fraction.

**What it does settle** is the size of the latency argument. Phase 3 was
weighed at ~7.8 ms mean movement latency against `host_maxfps 60`'s ~15% less
air gain. The compositor adds ~24 ms of display latency underneath both, which
this note had never counted and no lever here touches.

---

### Phase 4 — stop the busy-spin, and chase the hitch tail

Independent of everything above, and worth doing whichever lever is
chosen.

Sleeping to the next scheduled frame instead of spinning is a clear power
and thermal win on its own terms.

**Hypothesis, not a finding:** on a fanless Air, sustained 100% core
occupancy invites thermal throttling, a plausible contributor to the
75 ms stall in Finding 5. Not demonstrated — 17 s is far too short to
show throttling.

To test before writing code: run a 10-15 minute sample and check whether
the hitch rate climbs; sample `powermetrics` for CPU residency and
thermal pressure alongside. If the rate is flat, throttling is not the
cause and the stalls should be traced instead (disk I/O on demo and model
loading, and the sound mixer, are the obvious candidates).

Risk in the fix: replacing a spin with a sleep trades precise wake-ups
for OS timer granularity. `p50` currently sits on the cap; re-run the
jitter probe after and treat any widening of `sd` as a regression.

## Option zero — change nothing to the render path

72 Hz on a 60 Hz panel is what vanilla Quake has always done on 60 Hz
hardware, and what the feel was calibrated against. It is the only option
costing neither feel nor latency.

No longer the automatic recommendation. Both other levers now exist and
both work, so the choice is a real one:

- **Authentic movement above all** → `host_interpolate 0` at
  `host_maxfps 72`. Stock feel, and the beat comes back.
- **Smooth, and latency matters more than air control** →
  `host_maxfps 60`, interpolation off. ~15% less air gain, zero added
  latency.
- **Smooth, and air control matters more than latency** → the default:
  72 with interpolation. Stock movement rate, ~7.8 ms mean latency.

Phase 4 is worth doing regardless.

## Verification

Results below are from the build at the Phase 1 clamp commit.

1. `make -C WinQuake -f Makefile.macos` — exit 0. The `host.c:453`
   `-Wpointer-sign` warning is pre-existing and unrelated.
2. **Timedemo is unmoved by the cvar**, as it must be — it bypasses the
   cap:

   | `host_maxfps` | timedemo |
   |---|---|
   | 72 | 123.9 fps |
   | 60 | 129.4 fps |

   Both sit on the ~129 fps baseline within run-to-run noise. If this
   ever tracks `host_maxfps`, a change has leaked into the wrong path.
3. **Presented rate follows the cvar** (interpose probe, `+playdemo demo1`,
   800x600):

   | `host_maxfps` | p50 interval | rate |
   |---|---|---|
   | 72 | 13.882 ms | 72.0 fps |
   | 60 | 16.649 ms | 60.06 fps |

4. **Clamp behaves.** 5000 → 1000, 1 → 10, 0 → 10; 60 and 72 pass
   through untouched. The warning prints exactly **once**, not per frame,
   confirming the write-back sticks, and the value reads back as a clean
   `"1000"` rather than `1000.000000`.
5. **Do not read the ">16.67 ms" column at 60.** That threshold was
   chosen to catch missed vsyncs against a 13.9 ms production period. At
   `host_maxfps 60` the target period *is* 16.67 ms, so roughly half the
   intervals land just above it (42% observed) — an artifact of the
   metric, not a regression. Compare `p50` and `sd` instead.
6. **Movement check, still outstanding.** With `host_maxfps 72`,
   movement should be unchanged from pre-Phase-1 — same jump distances on
   a known gap, same strafe-jump top speed over a fixed run — and should
   measurably shift at 60. Not yet measured in-game; the ~15% figure
   remains modelled.
7. **Phases 2 and 3.** Presented rate must follow the *display*, not
   `host_maxfps`: at `host_maxfps 72` on a 60 Hz panel expect p50
   ~16.6 ms, not 13.9 ms. `host_interpolate 0` must restore stock
   snapping, and timedemo must stay ~129 fps in both cases.
8. **Still unverified: that the simulation rate is untouched by Phases
   2/3.** The whole design rests on movement being unchanged at
   `host_maxfps 72`, and that has been argued from the code, not
   measured. Same jump distances and strafe-jump top speed as
   pre-Phase-2 is the check that matters most and has not been run.
9. **Phase 2's fixed timestep changes hitch behaviour by design.** A
   stall that used to be one long integration step is now several steps
   of equal length. Do not treat a difference in stall behaviour as a
   regression; do treat a difference in steady-state movement as one.

10. **Phase 5: one frame per vsync, and the same phase every launch.**
    The probe's `V` lines count frames produced between vsyncs and its `P`
    lines stamp each stage. Every interval must read `1`, and the gate phase
    must match across launches to a few hundredths of a millisecond. Spread
    in gate phase between launches means the display link is not driving the
    gate and the wall clock has taken back over.
11. **Timedemo must still bypass the render gate.** 622.2 fps, 98% busy,
    0.03 s blocked at 800x600. If it ever tracks 60, the vsync gate has
    leaked into the benchmark path. The busy figure is the check that
    matters: it is the share of wall time not spent queueing behind the
    compositor.
12. **Headless and non-Apple are untouched.** `VID_RefreshInterval` returns
    0 there, so `Host_FilterRender` returns `stepped` and never reaches the
    serial. `host.c` compiles clean under GCC 14 on gracemont; the display
    link is behind `#ifdef __APPLE__` and `Host_VsyncSerial` returns 0.
13. **Do not read Finding 5's hitch tail against Phase 5.** That
    distribution was measured on the `drawRect` present, where a frame cost
    10.7 ms. It costs 1.37 ms now, so the tail must be re-measured before
    Phase 4 uses it as a baseline.

Note: running the game rewrites `id1/config.cfg`, which now carries
`host_maxfps`. Check that diff before committing.
