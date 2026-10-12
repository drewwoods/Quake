# QuakeWorld contrast: decoupled tics and client prediction

NetQuake renders the past: it holds displayed time between the last two server
snapshots and interpolates. QuakeWorld renders a predicted present: the client
simulates its own movement immediately, and the server runs on its own clock in
a separate process. Same game rules, opposite latency strategy.

> **First pass.** Think **simulate locally, correct from the server**.
> QuakeWorld's client stamps each input with milliseconds (`msec`), sends the
> last three commands redundantly, and replays unacked commands through the real
> player physics (`PlayerMove`) every frame — then blends the result toward
> server time. Remote players extrapolate their last command; packet entities
> have no interpolation (`f = 0; // FIXME: no interpolation right now`). The
> server is a standalone program with no client half at all. Sources:
> `QW/client/cl_pred.c:112-212`,
> `QW/client/cl_input.c:383-474`, `QW/client/cl_ents.c:867-886`,
> `QW/client/cl_ents.c:425-430`, `QW/server/sv_main.c:1230-1271`. [Return to
> the frame map →](#pipe)

> **Scope.** Everything else in this guide cites `WinQuake/` at commit
> `3ef8a7a`. This chapter only cites `QW/` (the QuakeWorld client and server
> trees) at the same commit, and only to contrast with NetQuake. QuakeWorld
> remains out of scope for the rest of the guide.

## Where it sits in the frame

There is no shared `_Host_Frame` anymore. The QuakeWorld server is its own
program: `main` in `QW/server/sys_unix.c` / `QW/server/sys_win.c` loops on
`select` over the network socket (and stdin) and calls `SV_Frame(time)` with the
measured delta (`QW/server/sys_unix.c:254-276`, `QW/server/sys_win.c:236-254`).
The client is a separate program whose `Host_Frame`
(`QW/client/cl_main.c:1302-1391`) has no server stage at all — no `sv.active`
branch, no `Host_ServerFrame`. Its per-frame order is: read packets, send input,
predict, emit entities, draw:

```c
// QW/client/cl_main.c:1340-1359 (abridged)
	CL_ReadPackets ();

	// send intentions now
	// resend a connection request if necessary
	if (cls.state == ca_disconnected) {
		CL_CheckForResend ();
	} else
		CL_SendCmd ();

	// Set up prediction for other players
	CL_SetUpPlayerPrediction(false);

	// do client side motion prediction
	CL_PredictMove ();

	// Set up prediction for other players
	CL_SetUpPlayerPrediction(true);

	// build a refresh entity list
	CL_EmitEntities ();
```

Compare with NetQuake's `_Host_Frame` ([frame overview](#sec-1)):
input-before-server versus packets-before-input, prediction where the server
stage used to be, entity emission split into prediction setup plus
`CL_EmitEntities`. The client's frame gate also differs: instead of a fixed 72
Hz cap it computes `fps` from `cl_maxfps` (defaulting from `rate/80`, bounded to
30–72) and returns early below `1.0/fps` unless timedemo
(`QW/client/cl_main.c:1317-1328`), and it clamps `host_frametime` at 0.2 s
rather than 0.1 s (`QW/client/cl_main.c:1327-1328`). Frame pacing follows the
player's bandwidth setting, not a compile-time constant — the client sends one
input packet per frame, so the send rate *is* the frame rate.

## Decoupled server tic

NetQuake's listen server ticks inside the host player's frame loop: one world
step per rendered frame, same `host_frametime` for client and server, and a slow
renderer slows the simulation for everyone connected. QuakeWorld deletes the
coupling by deleting the shared process. `SV_Frame`
(`QW/server/sv_main.c:1230-1271`) advances its own clocks (`realtime += time;
sv.time += time;`, `QW/server/sv_main.c:1242-1243`), runs physics, reads
packets, drains the console, executes commands, and sends updates — with no
client structures, no render call, and no `host_frametime` mediation:

```c
// QW/server/sv_main.c:1230-1271 (abridged)
void SV_Frame (float time)
{
	static double	start, end;
	
	start = Sys_DoubleTime ();
	svs.stats.idle += start - end;
	
// keep the random time dependent
	rand ();

// decide the simulation time
	if (!sv.paused) {
		realtime += time;
		sv.time += time;
	}

// check timeouts
	SV_CheckTimeouts ();

// toggle the log buffer if full
	SV_CheckLog ();

// move autonomous things around if enough time has passed
	if (!sv.paused)
		SV_Physics ();

// get packets
	SV_ReadPackets ();

// check for commands typed to the host
	SV_GetConsoleCommands ();

// process console commands
	Cbuf_Execute ();

	SV_CheckVars ();

// send messages back to the clients that had packets read this frame
	SV_SendClientMessages ();

// send a heartbeat to the master if needed
	Master_Heartbeat ();
```

Two orderings differ from NetQuake's `Host_ServerFrame` beyond the missing
client: autonomous entity physics runs before packet reception, and console
commands are drained mid-frame. Player movement runs during reception:
`SV_ReadPackets` calls `SV_ExecuteClientMessage`, which executes `SV_RunCmd`
before the reply (`QW/server/sv_main.c:1110-1116`,
`QW/server/sv_user.c:1640-1657`). Inputs do not wait for the next world step.
The server loop itself is event-driven — `select` on socket plus stdin with a
1 s (unix) or 100 µs (Windows) timeout —
so the tic rate floats with traffic instead of sleeping to a fixed
`sys_ticrate`. There is no listen-server mode and no loopback fast path: every
client, even on localhost, speaks the wire protocol. What NetQuake got from
`net_loop.c`'s `memcpy` (zero-latency local play), QuakeWorld must earn back
with prediction — which is exactly what the client does.

## Inputs with timestamps: `msec` and redundant sends

NetQuake's `usercmd_t` (`WinQuake/client.h:20-32`) carries intended velocities
and view angles — no duration, because command and server step share one
`host_frametime`. QuakeWorld's variant (`QW/client/protocol.h:274-281`) adds
time:

```c
// QW/client/protocol.h:274-281
typedef struct usercmd_s
{
	byte	msec;
	vec3_t	angles;
	short	forwardmove, sidemove, upmove;
	byte	buttons;
	byte	impulse;
} usercmd_t;
```

`msec` is filled in `CL_FinishMove` (`QW/client/cl_input.c:333-377`): `ms =
host_frametime * 1000`, clamped so an unreasonable stall sends 100 ms rather
than a huge step (`QW/client/cl_input.c:356-359`), with button bits and impulse
folded in alongside. The server then integrates each command for exactly its
stamped duration rather than for the server's own frame time — the decoupling
only works because the duration travels with the input.

`CL_SendCmd` (`QW/client/cl_input.c:383-474`) does three things NetQuake's never
did. First, it archives every outgoing command into `cl.frames[outgoing_sequence
& UPDATE_MASK].cmd` *before* sending (`QW/client/cl_input.c:397-400`) — the
replay buffer prediction consumes. Second, it sends not one command but three:
the two previous commands plus the current one, each delta-compressed against
its predecessor (`MSG_WriteDeltaUsercmd`, `QW/client/cl_input.c:435-447`),
covered by a checksum byte over the move block. A single dropped packet no
longer loses an input; the next packet re-carries it. Third, it piggybacks
delta-compression state for the *downstream* (`clc_delta` with
`cl.validsequence`, `QW/client/cl_input.c:455-467`), telling the server which
entity baseline the client can delta from — NetQuake's server sends full
baselines and bitmask deltas without client feedback (see [input and
networking](#sec-6)). During demo playback `CL_SendCmd` returns immediately
(`QW/client/cl_input.c:393-394`): commands come from the file, as in NetQuake.

## Predicting yourself: `CL_PredictMove`

This is the chapter's core. NetQuake never integrates the local player's input
client-side; until the server's reply arrives there is nothing newer to draw
than interpolation between old snapshots ([input and networking](#sec-6)).
`CL_PredictMove` (`QW/client/cl_pred.c:112-212`) instead re-simulates every
unacknowledged command each frame through the genuine shared physics
(`PlayerMove` in `QW/client/pmove.c`, operating on the `playermove_t` in
`QW/client/pmove.h:49-72` with world plus `physent_t` collision hulls).

The frame starts by deciding *when* the client is rendering at: `cl.time =
realtime - cls.latency - cl_pushlatency.value*0.001`
(`QW/client/cl_pred.c:125`), i.e. now minus the measured round trip, optionally
pushed further back by the `pushlatency` cvar (negative values predict further
ahead; positive values are forced back to 0, `QW/client/cl_pred.c:119-120`). It
bails while paused, in intermission, without a valid baseline sequence, or when
the send/receive gap exceeds the backup buffer (`QW/client/cl_pred.c:122-136`).
Then it replays: starting from the last server-acked frame
(`cl.frames[incoming_sequence & UPDATE_MASK]`), it runs `CL_PredictUsercmd` over
each buffered command in turn until the predicted time covers `cl.time`
(`QW/client/cl_pred.c:168-177`).

Each single step (`QW/client/cl_pred.c:64-103`) loads a `pmove` from the `from`
state, installs the command, calls `PlayerMove`, and writes the `to` state —
splitting commands longer than 50 ms into halves recursively
(`QW/client/cl_pred.c:67-78`) so a hitch never integrates one giant step.
For non-spectators, `PlayerMove` first calls `NudgePosition`
(`QW/client/pmove.c:869-875`), which tries 1/8-unit offsets to escape solid
geometry after network rounding (`QW/client/pmove.c:735-769`).

The result lands in `cl.simorg` / `cl.simvel` (`QW/client/client.h:247-248`),
with view rendering driven from `cl.simangles` — the client's render origin is
predicted state, not the last server snapshot. There is no explicit "reconcile"
or error-smoothing pass: correction happens implicitly because every frame
re-simulates from the newest acked server state, so a misprediction persists for
at most one round trip before the replay base snaps to authoritative data.
Setting `cl_nopred` skips simulation and copies the last server state straight
through (`QW/client/cl_pred.c:155-160`) — NetQuake behavior on demand, and the
standard way to feel what prediction buys. The `>128`-unit teleport guard
(`QW/client/cl_pred.c:197-203`) plays the same role as NetQuake's `>100`-unit
anti-lerp heuristic: never blend across a discontinuity.

## Everyone else: half-predicted, un-interpolated

The local player replays its buffered commands; remote players extrapolate their
last command. `CL_SetUpPlayerPrediction` (`QW/client/cl_ents.c:950-1009`) runs
twice per frame: `dopred=false` supplies snapshot positions for local player
collision, then `true` supplies extrapolated positions for remote player
collision. `CL_SetSolidPlayers` inserts those positions as `physent_t` boxes,
gated by `cl_solid_players` (`QW/client/cl_ents.c:1021-1053`).

Rendering has its own prediction in `CL_LinkPlayers`: it advances each remote
player by `500*(playertime - state->state_time)` milliseconds of their last
command, caps this at 255 ms, and copies the result into `ent->origin`
(`QW/client/cl_ents.c:867-886`). The factor 500 predicts only half the elapsed
time "to minimize overruns". If both `cl_predict_players` and
`cl_predict_players2` are off, it copies the latest snapshot instead.

Packet entities have no interpolation.
`CL_LinkPacketEntities` (`QW/client/cl_ents.c:408-...`) draws the newest packet
as-is:

```c
// QW/client/cl_ents.c:425-430
	f = 0;	// FIXME: no interpolation right now
	...
		s1 = &pack->entities[pnum];
		s2 = s1;	// FIXME: no interpolation right now
```

NetQuake blends `msg_origins[1]` → `msg_origins[0]` by `frac` over
`cl.mtime[1..0]`; QuakeWorld at this commit pins `f = 0` and points both sample
pointers at the latest state. The wire compensates differently: instead of
NetQuake's per-field bitmask against a level-load baseline, the server
delta-compresses whole `entity_state_t`s against a previous packet the client
acknowledges (`cl.validsequence`, `UPDATE_BACKUP` = 64 buffered frames,
`UPDATE_MASK` = 63, `QW/client/protocol.h:246-248`; `packet_entities_t` capped
at 64 entities per packet, `QW/client/protocol.h:267-271`). Bandwidth comes from
acknowledging shared history; smoothness for packet entities is simply deferred
— the era's tradeoff, favoring the shooter's own gunfeel over spectators' glide,
with the FIXME marking the known gap.

::: diagram qw-contrast

## Call graph

```
QW server: main (QW/server/sys_unix.c:254, QW/server/sys_win.c:236)
  select(socket + stdin) -> SV_Frame(time) (QW/server/sv_main.c:1230)
    SV_Physics (QW/server/sv_main.c:1254)
    SV_ReadPackets (QW/server/sv_main.c:1257)
      SV_ExecuteClientMessage (QW/server/sv_main.c:1116)
        SV_RunCmd (QW/server/sv_user.c:1655)
          PlayerMove (QW/server/sv_user.c:1467)
    SV_GetConsoleCommands (QW/server/sv_main.c:1260)
    Cbuf_Execute (QW/server/sv_main.c:1263)
    SV_SendClientMessages (QW/server/sv_main.c:1268)
    Master_Heartbeat (QW/server/sv_main.c:1271)

QW client: Host_Frame(time) (QW/client/cl_main.c:1302)
  fps gate from cl_maxfps/rate (QW/client/cl_main.c:1317-1328)
  CL_ReadPackets (QW/client/cl_main.c:935)
    Netchan_Process + CL_ParseServerMessage
  CL_SendCmd (QW/client/cl_input.c:383)
    archive cmd into cl.frames[outgoing & UPDATE_MASK] (QW/client/cl_input.c:397)
    CL_BaseMove (QW/client/cl_input.c:282) + IN_Move
    CL_FinishMove: msec = host_frametime*1000 (QW/client/cl_input.c:356-359)
    MSG_WriteDeltaUsercmd x3 + checksum (QW/client/cl_input.c:435-447)
    Netchan_Transmit (QW/client/cl_input.c:474)
  CL_SetUpPlayerPrediction(false) (QW/client/cl_ents.c:950)
  CL_PredictMove (QW/client/cl_pred.c:112)
    cl.time = realtime - latency - pushlatency (QW/client/cl_pred.c:125)
    CL_PredictUsercmd per buffered cmd (QW/client/cl_pred.c:64)
      PlayerMove on pmove (QW/client/cl_pred.c:92)
        NudgePosition (QW/client/pmove.c:875)
      split msec > 50 (QW/client/cl_pred.c:67-78)
    write cl.simorg/simvel (QW/client/cl_pred.c:205-211)
  CL_SetUpPlayerPrediction(true)
  CL_EmitEntities (QW/client/cl_ents.c:1065)
    CL_LinkPlayers (half-prediction) (QW/client/cl_ents.c:867-886)
    CL_LinkPacketEntities (f = 0, no lerp) (QW/client/cl_ents.c:408-430)
```

## Key data structures

- `usercmd_t` — `QW/client/protocol.h:274-281` — one input with `msec` duration, angles, moves, buttons, impulse; sent three-deep with delta compression.
- `playermove_t` (`pmove`) — `QW/client/pmove.h:49-72` — shared player physics state: origin/angles/velocity, `physents[MAX_PHYSENTS]` world snapshot, input `cmd`, touch results.
- `frame_t` / `cl.frames[UPDATE_BACKUP]` — `QW/client/client.h:229`, `QW/client/protocol.h:246-248` — 64-deep ring of sent commands, received player states, and delta bookkeeping indexed by `& UPDATE_MASK`.
- `cl.simorg` / `cl.simvel` / `cl.simangles` / `cl.time` — `QW/client/client.h:240-249` — the predicted render state; `time` trails `realtime` by measured latency.
- `cl.validsequence` / `cl.parsecount` — `QW/client/client.h:214-215` — last good entity baseline and server-message counter; prediction refuses to run at 0.
- `cls.latency` — `QW/client/client.h:199` — rolling-average round trip driving `cl.time`.
- `cl_nopred` / `cl_pushlatency` (cvars) — `QW/client/cl_pred.c:23-24` — prediction off-switch and render-time offset.
- `packet_entities_t` — `QW/client/protocol.h:267-271` — up to 64 delta-compressed `entity_state_t`s per server packet.

## Further reading

- Fabien Sanglard, "Quake Source Code Review":
  https://fabiensanglard.net/quakeSource/index.php — NetQuake baseline this
  chapter contrasts against.
- John Carmack .plan archive, 10 Aug 1996 entry:
  https://github.com/ESWAT/john-carmack-plan-archive — NetQuake holds display
  time between packets; QuakeWorld predicts from the newest (cited in [input and
  networking](#sec-6)).
- QuakeWorld official changelog/notes in-tree: `QW/qwchangelog.txt`,
  `QW/qwrlnote.txt` — contemporary release notes on prediction and delta
  compression (unverified for specific claims above; read alongside the code).
