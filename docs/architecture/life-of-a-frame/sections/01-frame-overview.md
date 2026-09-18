# The Top-Level Frame: `Sys_*` Main Loop and `Host_Frame`

The host loop is the spine of the engine: it gathers input, runs any local server, reads server results, then draws and mixes sound. Start with that order; the platform-specific clock code below can wait.

> **First pass.** Read the stage order, then follow the input. In the original listen loop, an accepted frame runs one server step (unless paused), followed by presentation. The 72 Hz gate is a maximum rate, not a promise of a fixed timestep. A remote server has its own clock. Source: `WinQuake/host.c:501-522`, `WinQuake/host.c:600-727`. [Next: input and the client →](#sec-6)

## Where it sits in the frame

This *is* the frame. Everything else in this document is a callee of `_Host_Frame` (`WinQuake/host.c:633-727`), which is called from `Host_Frame` (`WinQuake/host.c:729-763`), which is called from a platform `main`/`WinMain` loop: `WinQuake/sys_win.c:855-888`, `WinQuake/sys_linux.c:403-429`, `WinQuake/sys_dos.c:937-950`. Citations are `git show 3ef8a7a:WinQuake/...`, not this checkout. The current branch splits simulation from rendering and steps at a fixed `host_maxfps`; that loop is not this chapter.

## The platform loop: three ports, one shape

The platform layer's entire job at runtime is to answer "how much wall-clock time has passed since the last frame?" and to decide whether it is worth running a frame at all. Every port implements the same shape: sample a monotonic-ish clock, subtract, call `Host_Frame(delta)`, remember the new timestamp.

`WinQuake/sys_win.c:852-888`:

```c
	oldtime = Sys_FloatTime ();

    /* main window message loop */
	while (1)
	{
		if (isDedicated)
		{
			newtime = Sys_FloatTime ();
			time = newtime - oldtime;

			while (time < sys_ticrate.value )
			{
				Sys_Sleep();
				newtime = Sys_FloatTime ();
				time = newtime - oldtime;
			}
		}
		else
		{
		// yield the CPU for a little while when paused, minimized, or not the focus
			if ((cl.paused && (!ActiveApp && !DDActive)) || Minimized || block_drawing)
			{
				SleepUntilInput (PAUSE_SLEEP);
				scr_skipupdate = 1;		// no point in bothering to draw
			}
			else if (!ActiveApp && !DDActive)
			{
				SleepUntilInput (NOT_FOCUS_SLEEP);
			}

			newtime = Sys_FloatTime ();
			time = newtime - oldtime;
		}

		Host_Frame (time);
		oldtime = newtime;
	}
```

Two things are worth pulling out. First, the dedicated branch polls the clock with a 1 ms `Sleep` inside `Sys_Sleep()` (`WinQuake/sys_win.c:635-637`) until `sys_ticrate` seconds (default `0.05`, i.e. 20 Hz — `WinQuake/host.c:60`) have elapsed. Second, the interactive branch sleeps only while paused, minimized, or unfocused. `SleepUntilInput` blocks on `MsgWaitForMultipleObjects` (`WinQuake/sys_win.c:673-676`), waking on either a timeout or an input event. While active, the loop spins as fast as the machine allows and `Host_FilterTime` rejects calls that arrive too soon.

The Linux loop (`WinQuake/sys_linux.c:402-424`) differs on the dedicated path:

```c
    oldtime = Sys_FloatTime () - 0.1;
    while (1)
    {
// find time spent rendering last frame
        newtime = Sys_FloatTime ();
        time = newtime - oldtime;

        if (cls.state == ca_dedicated)
        {   // play vcrfiles at max speed
            if (time < sys_ticrate.value && (vcrFile == -1 || recording) )
            {
				usleep(1);
                continue;       // not time to run a server only tic yet
            }
            time = sys_ticrate.value;
        }

        if (time > sys_ticrate.value*2)
            oldtime = newtime;
        else
            oldtime += time;

        Host_Frame (time);
```

On the interactive path, `time` is the actual elapsed delta: `oldtime += time` and `oldtime = newtime` are equivalent unless the hitch is larger than `2 * sys_ticrate`, in which case `oldtime = newtime` drops the missed time. On the dedicated path, `time` has already been replaced with `sys_ticrate.value`, so that drop cannot run; `oldtime` advances by one tic per loop. A hitch is then drained by extra `Host_Frame(sys_ticrate)` calls as fast as the machine allows. Keep this platform behavior separate from `Host_FilterTime`, which gates calls and chooses the timestep used by the host.

The DOS loop (`WinQuake/sys_dos.c:937-950`) is the most primitive of the three: just a `continue` when a dedicated server has not reached its tic. Nothing in the loop sleeps or yields, so it polls the clock continuously. `Sys_FloatTime` there (`WinQuake/sys_dos.c:689-745`) reads the 8253 PIT counter at port 0x40 and the BIOS tick count at real-mode address `0x46c`, reconstructing a ~1.193 MHz timebase and defending against the two clocks disagreeing across a latch. It also carries a `sametimecount` hack that manufactures forward progress if the clock appears frozen for 100,000 consecutive calls.

## `Host_Frame` and the profiling wrapper

`Host_Frame` (`WinQuake/host.c:729-763`) is a thin shell. If the `serverprofile` cvar is zero it simply forwards to `_Host_Frame`; otherwise it brackets the call with `Sys_FloatTime()` and prints a rolling average of milliseconds-per-frame and active client count every 1000 frames. All the real work is in `_Host_Frame`.

The first statement in `_Host_Frame` is not work but a landing pad:

```c
	if (setjmp (host_abortserver) )
		return;			// something bad happened, or the server disconnected
```

`WinQuake/host.c:640-641`. `Host_Error` (`WinQuake/host.c:121`) and `Host_EndGame` (`WinQuake/host.c:90`) can abandon an interactive frame through `longjmp`, after shutdown/disconnection work. The stack does not unwind through cleanup handlers, and a dedicated server exits on these errors. `Host_ClearMemory` (`WinQuake/host.c:477`) later reclaims level allocations when preparing a new game or connection; returning to the frame loop is not by itself memory cleanup.

Then `rand ()` (`WinQuake/host.c:643-644`) is called once per attempted frame, before `Host_FilterTime` (`WinQuake/host.c:647-648`), with the comment "keep the random time dependent." Rejected frames advance the PRNG too, so otherwise identical runs can diverge when their platform loops call `Host_Frame` at different rates.

## `Host_FilterTime`: what `host_frametime` actually means

Everything downstream reads one global, `host_frametime` (`WinQuake/host.c:40`). `Host_FilterTime` produces it. DOOM ran on a fixed 35 Hz timebase; decoupling render rate from simulation rate is one of the deliberate breaks catalogued in [what Quake had to close](design:what-quake-had-to-close).

`WinQuake/host.c:501-522`:

```c
qboolean Host_FilterTime (float time)
{
	realtime += time;

	if (!cls.timedemo && realtime - oldrealtime < 1.0/72.0)
		return false;		// framerate is too high

	host_frametime = realtime - oldrealtime;
	oldrealtime = realtime;

	if (host_framerate.value > 0)
		host_frametime = host_framerate.value;
	else
	{	// don't allow really long or short frames
		if (host_frametime > 0.1)
			host_frametime = 0.1;
		if (host_frametime < 0.001)
			host_frametime = 0.001;
	}
	
	return true;
}
```

Four separate policies are packed into twenty lines.

**Accumulate, don't drop.** `realtime += time` happens on *every* call, including calls that then return `false`. A `false` return skips the rest of `_Host_Frame`: no input, server, or presentation. The platform loop still advances its own `oldtime`, so a rejected frame does not lose the elapsed time — it is banked in `realtime` and shows up in the next accepted frame's `host_frametime`. This is why the crude `oldtime = newtime` in the Windows and DOS loops is correct despite looking lossy.

**The 72 Hz cap.** `1.0/72.0` ≈ 13.9 ms is a hard ceiling on simulation rate, bypassed only for `timedemo`. The in-source justification is at the call site, `WinQuake/host.c:647-648`: `// don't run too fast, or packets will flood out`. Because a listen server's client sends one `clc_move` per frame (`CL_SendMove`, `WinQuake/cl_input.c:332`) and a server sends one update per client per frame, uncapped frames on a fast machine would multiply outbound packet rate without bound on a 28.8k modem. The cap is a network-bandwidth governor that happens to also bound how often the physics integrator runs. Dedicated servers use the other end of the same trade-off: `sys_ticrate` defaults to `0.05` (20 Hz).

> **.plan.** The default server framerate is 20 fps (50 ms). If you ask for more fps from the server, you may get less latency, but you would almost certainly overcommit the bandwidth of a dialup link. — [Carmack, 2 Aug 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt). [The connection the design expected](design:the-connection-the-design-expected).

**Slow motion.** `host_framerate` (`WinQuake/host.c:57`) overrides the measured simulation delta with a constant number of seconds. Despite its name, it is not a frames-per-second setting. For example, `host_framerate 0.001` advances very little game time per accepted frame; the ordinary 72 Hz gate still applies unless timedemo bypasses it.

**Clamping.** Normally `host_frametime` is limited to `[0.001, 0.1]` seconds. A three-second stall therefore becomes at most a 0.1-second simulation step. This limits the size of one integration step, but does not reproduce all the small steps that would have occurred without the stall. Collision already sweeps the movement path (`WinQuake/sv_phys.c:260`, `WinQuake/world.c:923-961`); the clamp is not what prevents an ordinary mover from skipping a wall between endpoints.

Note that the clamp is *not* applied when `host_framerate` is set, and that neither clamp nor cap bounds cumulative drift: after a stall the world is simply behind wall clock and never catches up. The original loop does not catch up with extra steps. The current branch's host loop does; that is not this frame model.

## The order of stages

`WinQuake/host.c:650-694` is the canonical ordering after `Host_FilterTime` accepts the frame (`WinQuake/host.c:647-648`). Reproduced with the comments intact, but note the misleading remote-send comment called out below:

```c
// get new key events
	Sys_SendKeyEvents ();

// allow mice or other external controllers to add commands
	IN_Commands ();

// process console commands
	Cbuf_Execute ();

	NET_Poll();

// if running the server locally, make intentions now
	if (sv.active)
		CL_SendCmd ();
	
//-------------------
//
// server operations
//
//-------------------

// check for commands typed to the host
	Host_GetConsoleCommands ();
	
	if (sv.active)
		Host_ServerFrame ();

//-------------------
//
// client operations
//
//-------------------

// if running the server remotely, send intentions now after
// the incoming messages have been read
	if (!sv.active)
		CL_SendCmd ();

	host_time += host_frametime;

// fetch results from server
	if (cls.state == ca_connected)
	{
		CL_ReadFromServer ();
	}
```

**`Sys_SendKeyEvents`** pumps the platform event queue. On Win32 (`WinQuake/sys_win.c:641-655`) it drains the message queue with `PeekMessage`/`GetMessage`/`DispatchMessage`; the window procedure turns `WM_KEYDOWN` etc. into `Key_Event` calls, and `Key_Event` for a bound key does not act directly — it `Cbuf_AddText`s the binding (`+forward`, `impulse 2`, …).

**`IN_Commands`** (`WinQuake/in_win.c:963`, `WinQuake/in_dos.c:197`, stub at `WinQuake/in_null.c:32`) synthesizes button events the same way. Win32 polls joystick buttons (`WinQuake/in_win.c:963-1024`); DOS also polls mouse buttons (`WinQuake/in_dos.c:201-223`).

**`Cbuf_Execute`** (`WinQuake/cmd.c:143`) then runs the accumulated command buffer. This is why the ordering matters so much: a key pressed *this* frame has already had its binding executed — setting `in_forward.state`, firing an impulse — before movement is built. An event collected here can affect this accepted frame’s command, avoiding an extra frame of buffering. Total input-to-display latency still depends on when the event arrives, networking and presentation.

**`NET_Poll`** (`WinQuake/net_main.c:927-955`) is *not* the game packet path. The first call can restore serial/modem config (`WinQuake/net_main.c:932-944`). Then it calls `SetNetTime()` (`WinQuake/net_main.c:946`) and runs a time-ordered list of poll procedures (`WinQuake/net_main.c:948-953`) — server-list broadcast/collect (`WinQuake/net_main.c:308-309`), ping tests (`WinQuake/net_dgrm.c:570,697`), the serial/modem hangup state machine (`WinQuake/net_comx.c:1262-1277`), IPX housekeeping (`WinQuake/net_ipx.c:192-195`). Actual game traffic is read on demand inside `SV_RunClients` and `CL_GetMessage`.

**`CL_SendCmd`** appears twice, guarded by opposite conditions. When `sv.active` — a listen server or single player — the client's intentions must be built *before* `Host_ServerFrame` runs, because the server consumes them in the same frame through the loopback socket. When the server is remote, the server stage is skipped and the second call runs immediately before `CL_ReadFromServer`. The nearby source comment says incoming messages have already been read, but the code does the opposite: it sends this frame's input first, then drains incoming packets.

**`Host_GetConsoleCommands`** (`WinQuake/host.c:532-543`) drains `Sys_ConsoleInput()` for the dedicated-server operator's stdin and injects it into the same command buffer.

**`Host_ServerFrame`** runs the world. Its build-time variants are covered below.

**`host_time += host_frametime`** (`WinQuake/host.c:688`) advances the host clock. Do not confuse it with `sv.time`, the simulation clock, or `cl.time`, used on the client. QuakeC thinks use `sv.time` / their scheduled think time (`WinQuake/sv_phys.c:126-144`), so the nearby historical comment about initializing `host_time` to 1 is not an explanation of the actual think scheduler.

**`CL_ReadFromServer`** (`WinQuake/cl_main.c:634-662`) advances `cl.time`, drains every pending server message, and rebuilds the client's renderable entity list (`CL_RelinkEntities`, `WinQuake/cl_main.c:656`):

```c
int CL_ReadFromServer (void)
{
	int		ret;

	cl.oldtime = cl.time;
	cl.time += host_frametime;
	
	do
	{
		ret = CL_GetMessage ();
		if (ret == -1)
			Host_Error ("CL_ReadFromServer: lost server connection");
		if (!ret)
			break;
		
		cl.last_received_message = realtime;
		CL_ParseServerMessage ();
	} while (ret && cls.state == ca_connected);
```

Note that the client keeps its *own* clock (`cl.time`) driven by the same `host_frametime`. The client interpolates entity positions between the last two server snapshots (`cl.mtime[0]`, `cl.mtime[1]`) in `CL_RelinkEntities`, which is why a 20 Hz server can drive a 72 Hz client smoothly.

**`SCR_UpdateScreen`** (`WinQuake/screen.c:808` software, `WinQuake/gl_screen.c:821` GL) renders. It is called unconditionally after server updates. Software returns immediately when `cls.state == ca_dedicated` (`WinQuake/screen.c:831-832`); GL returns if the screen was never initialized (`WinQuake/gl_screen.c:845-846`). `host_speeds` brackets it to report the classic `tot / server / gfx / snd` split (`WinQuake/host.c:716-724`).

**`S_Update`** (`WinQuake/snd_dma.c:721`) is handed the *renderer's* view vectors (`r_origin, vpn, vright, vup`) rather than the client's entity origin, so spatialization matches exactly what was just drawn — including in chase-cam mode. Before signon completes it is called with zero vectors (`WinQuake/host.c:711-712`). It returns immediately if sound never started (`WinQuake/snd_dma.c:728`). `CDAudio_Update` (`WinQuake/cd_win.c:398`, `WinQuake/cd_linux.c:328`) then services the redbook audio track state machine.

**`host_framecount++`** (`WinQuake/host.c:726`) is the last statement. Demo playback and `timedemo` use it to limit reads and count benchmarked frames. The renderer keeps separate `r_framecount` and `r_visframecount` counters.

## `Host_ServerFrame` and the `FPS_20` road not taken

The shipped server stage is compact (`WinQuake/host.c:600-621`):

```c
void Host_ServerFrame (void)
{
// run the world state	
	pr_global_struct->frametime = host_frametime;

// set the time and clear the general datagram
	SV_ClearDatagram ();
	
// check for new clients
	SV_CheckForNewClients ();

// read client messages
	SV_RunClients ();
	
// move things around and think
// always pause in single player if in console or menus
	if (!sv.paused && (svs.maxclients > 1 || key_dest == key_game) )
		SV_Physics ();

// send all messages to the clients
	SV_SendClientMessages ();
}
```

Read: publish the timestep to QuakeC, clear the per-frame unreliable datagram, accept pending connections, ingest client input, simulate, transmit. The pause condition is worth noting — in single player (`svs.maxclients == 1`) simply opening the console or the menu (`key_dest != key_game`) freezes the world, without any explicit pause command. In multiplayer that clause is bypassed and only an explicit `sv.paused` stops simulation.

There is a second, unshipped version guarded by `#ifdef FPS_20` (`WinQuake/host.c:552-596`). `FPS_20` is not defined by any makefile in the tree — the only other reference is `WinQuake/pr_exec.c:651` — so the `#else` branch above is what every build compiles. The dead variant is nevertheless instructive: it splits the frame into sub-steps of at most 0.05 s, running `_Host_ServerFrame` repeatedly while temporarily overwriting `host_frametime`, then restoring it:

```c
	temp_host_frametime = save_host_frametime = host_frametime;
	while(temp_host_frametime > (1.0/72.0))
	{
		if (temp_host_frametime > 0.05)
			host_frametime = 0.05;
		else
			host_frametime = temp_host_frametime;
		temp_host_frametime -= host_frametime;
		_Host_ServerFrame ();
	}
	host_frametime = save_host_frametime;
```

That is `WinQuake/host.c:582-592`. It subdivides a host delta into bounded steps, with a possibly shorter final step and a remainder ≤ 1/72 s that is not carried forward here. A host delta of 1/72 s or less runs no server step. It is not the ordinary build’s timing model and is not a persistent fixed-step accumulator. You can skip this disabled variant on a first read.

## Listen server, dedicated server, remote client

The three configurations are selected by a boolean (`sv.active`) and an enum (`cls.state`).

`Host_FindMaxClients` (`WinQuake/host.c:157-201`) reads the command line once at startup:

- `-dedicated [n]` sets `cls.state = ca_dedicated` and `svs.maxclients = n` (default 8).
- `-listen [n]` leaves `cls.state = ca_disconnected` but raises `svs.maxclients`.
- Neither: `svs.maxclients = 1`, `cls.state = ca_disconnected` — single player.

The two are mutually exclusive (`Sys_Error` at `WinQuake/host.c:180-181`). `svs.maxclients` < 1 becomes 8, and the value is capped at `MAX_SCOREBOARD` (`WinQuake/host.c:187-190`). `deathmatch` is auto-set whenever `maxclients > 1`.

`cls.state` is a three-value enum (`WinQuake/client.h:102-104`): `ca_dedicated` (server only, no client capability at all), `ca_disconnected` (client running, showing the full-screen console), `ca_connected` (client talking to *some* server). `sv.active` is the orthogonal question of whether *this process* is running a server.

From that, the frame behaviour falls out:

| Configuration | `sv.active` | `cls.state` | Frame behaviour |
|---|---|---|---|
| Single player / listen | true | `ca_connected` | `CL_SendCmd` before server stage; both server and client stages run; renders |
| Dedicated | true | `ca_dedicated` | Both `CL_SendCmd` calls no-op (`WinQuake/cl_main.c:674-675`); `CL_ReadFromServer` skipped; `SCR_UpdateScreen` short-circuits |
| Remote client | false | `ca_connected` | Server stage skipped; `CL_SendCmd` runs in the second position; `CL_ReadFromServer` drains the wire |

`Host_Init` (`WinQuake/host.c:835-921`) reinforces the split: `R_InitTextures` runs unconditionally ("needed even for dedicated servers", `WinQuake/host.c:874`), but the entire video/sound/input block — `VID_Init`, `Draw_Init`, `SCR_Init`, `R_Init`, `S_Init`, `CDAudio_Init`, `Sbar_Init`, `CL_Init`, `IN_Init` — is inside `if (cls.state != ca_dedicated)` (`WinQuake/host.c:876-911`). A dedicated server never allocates a framebuffer or opens a sound device.

## How client and server coexist in one process

Commands and replicated entity state cross a network-message interface, even in single player. That unification is a [design choice](design:leaving-lockstep-behind-the-client-server-split), not a local-play shortcut. Timing, cvars, allocators and the model registry are shared, and client code can check server state. For example, `CL_LerpPoint` checks `sv.active` to disable interpolation locally (`WinQuake/cl_main.c:391-402`); `Mod_ForName` reuses model records (`WinQuake/model.c:186-228`, `WinQuake/model.c:329-336`). The normal gameplay message path still uses `WinQuake/net_loop.c`.

`Loop_SendMessage` (`WinQuake/net_loop.c:154-185`) does not send anything — it copies the message into the *peer* qsocket's receive buffer with a 4-byte header (type byte, 16-bit length, one alignment pad byte), then clears `canSend`. A missing peer (`!sock->driverdata`, `WinQuake/net_loop.c:159-160`) returns -1; overflow calls `Sys_Error`:

```c
	bufferLength = &((qsocket_t *)sock->driverdata)->receiveMessageLength;

	if ((*bufferLength + data->cursize + 4) > NET_MAXMESSAGE)
		Sys_Error("Loop_SendMessage: overflow\n");

	buffer = ((qsocket_t *)sock->driverdata)->receiveMessage + *bufferLength;

	// message type
	*buffer++ = 1;

	// length
	*buffer++ = data->cursize & 0xff;
	*buffer++ = data->cursize >> 8;

	// align
	buffer++;

	// message
	Q_memcpy(buffer, data->data, data->cursize);
	*bufferLength = IntAlign(*bufferLength + data->cursize + 4);

	sock->canSend = false;
	return 1;
```

`Loop_GetMessage` (`WinQuake/net_loop.c:127-152`) pops one message off the front, memmoves the remainder down, and — crucially — re-arms the sender's `canSend` when it consumes a reliable message. Reliable-message flow control, the same "one in flight at a time" discipline the datagram driver enforces over a real socket, is faithfully reproduced over a `memcpy`.

Single-player Quake therefore uses the network protocol over an in-process transport. There is no separate local-play update path to keep in sync; QuakeC does not know whether its client is local; and `SV_WriteEntitiesToClient` builds and PVS-culls the same entity stream for loopback and datagram sockets.

The cost is that the two halves share a cadence. Both run from one `host_frametime` inside one `_Host_Frame`, so a listen server ticks only when the host player completes a frame: a slow renderer on the host lowers the simulation rate for everyone connected to it. Simulated time itself still tracks wall time, because `host_frametime` is variable — up to the 100 ms clamp, past which stall time is simply discarded. QuakeWorld later [decoupled the server tic](design:quakeworld-client-side-prediction-and-the-packet-loop) from the client's frame and added client-side prediction.

## Call graph

```
main / WinMain                                  sys_win.c:692, sys_linux.c:354, sys_dos.c:886
  Host_Init                                     host.c:835
  while (1)
    Sys_FloatTime                               sys_win.c:467, sys_linux.c:281, sys_dos.c:689
    Sys_Sleep / SleepUntilInput                 sys_win.c:635, 673
    Host_Frame(time)                            host.c:729
      _Host_Frame(time)                         host.c:633
        setjmp(host_abortserver)                host.c:640
        Host_FilterTime(time)  [false → return] host.c:501
        Sys_SendKeyEvents                       sys_win.c:641
        IN_Commands                             in_win.c:963 / in_dos.c:197 / in_null.c:32
        Cbuf_Execute                            cmd.c:143
        NET_Poll                                net_main.c:927
          SetNetTime                            net_main.c:95
          pollProcedureList->procedure          net_main.c:948-953
        CL_SendCmd            [if sv.active]    cl_main.c:670
          CL_BaseMove                           cl_input.c:283
          IN_Move                               in_win.c:738
          CL_SendMove                           cl_input.c:332
            NET_SendUnreliableMessage           net_main.c:656
        Host_GetConsoleCommands                 host.c:532
        Host_ServerFrame      [if sv.active]    host.c:600
          SV_ClearDatagram                      sv_main.c:348
          SV_CheckForNewClients                 sv_main.c:302
          SV_RunClients                         sv_user.c:600
          SV_Physics                            sv_phys.c:1507
          SV_SendClientMessages                 sv_main.c:819
        CL_SendCmd            [if !sv.active]   cl_main.c:670
        host_time += host_frametime             host.c:688
        CL_ReadFromServer  [if ca_connected]    cl_main.c:634
          CL_GetMessage                         cl_demo.c:90
          CL_ParseServerMessage                 cl_parse.c:720
          CL_RelinkEntities                     cl_main.c:442
          CL_UpdateTEnts                        cl_tent.c:325
        SCR_UpdateScreen                        screen.c:808 / gl_screen.c:821
        S_Update                                snd_dma.c:721
        CL_DecayLights                          cl_main.c:362
        CDAudio_Update                          cd_win.c:398 / cd_linux.c:328
        host_framecount++                       host.c:726
```

## Key data structures

- `quakeparms_t` — `WinQuake/quakedef.h:271-279` — basedir/cachedir/argc/argv/membase/memsize handed from `main` to `Host_Init`; the entire platform→engine configuration surface.
- `host_frametime` (double) — `WinQuake/host.c:40` — the simulation timestep for this frame; read by the server physics, the client clock, and QuakeC via `pr_global_struct->frametime`.
- `realtime` / `oldrealtime` (double) — `WinQuake/host.c:42-43` — unfiltered accumulated wall clock, and the timestamp of the last accepted frame; their difference is the raw delta before clamping.
- `host_time` (double) — `WinQuake/host.c:41` — host clock, initialized to `1.0` (`WinQuake/host.c:235`); used for menu animation and VCR timing, not QuakeC thinks.
- `host_framecount` (int) — `WinQuake/host.c:44` — accepted frames since startup; used by demo playback and `timedemo` accounting.
- `host_abortserver` (`jmp_buf`) — `WinQuake/host.c:52` — `longjmp` target for `Host_Error`/`Host_EndGame`; the only unwinding mechanism in the engine.
- `sys_ticrate` (cvar, "0.05") — `WinQuake/host.c:60` — dedicated-server tick period; also the drift threshold in the Linux loop.
- `host_framerate` (cvar, "0") — `WinQuake/host.c:57` — when nonzero, overrides the measured delta for slow motion.
- `cls.state` (`cactive_t`) — `WinQuake/client.h:101-105` — `ca_dedicated` / `ca_disconnected` / `ca_connected`; decides whether the client half of the frame exists.
- `sv.active` (`server_t`) — `WinQuake/server.h:37` — whether this process is running a server this frame; decides `CL_SendCmd` placement.
- `svs.maxclients` / `svs.clients` (`server_static_t`) — `WinQuake/server.h:24-26`, allocated `WinQuake/host.c:195` — client slot array of `svs.maxclientslimit` (at least 4), sized once by `Host_FindMaxClients`.
- `qsocket_t` — `WinQuake/net.h:119-149` — the network endpoint abstraction; the loopback driver fills its `receiveMessage` buffer with `memcpy` (`WinQuake/net_loop.c:154-185`) so local play is indistinguishable from networked play.

## Further reading

- Fabien Sanglard, "Quake Source Code Review" — the standard modern walkthrough of `Host_Frame` and the client/server split: https://fabiensanglard.net/quakeSource/index.php
- Michael Abrash, *Graphics Programming Black Book*, chapters 59–70 (the Quake chapters) — the renderer half of the frame, and the performance culture that produced this loop: https://www.jagregory.com/abrash-black-book/
- Olivier Montanuy et al., "Unofficial Quake Specs" — network protocol and progs interfaces: https://www.gamers.org/dEngine/quake/spec/quake-spec34/ (archived: https://web.archive.org/web/20251206223630/https://www.gamers.org/dEngine/quake/spec/quake-spec34/)
- QuakeC reference (the `frametime` global and `StartFrame`): https://www.gamers.org/dEngine/quake/spec/quake-spec34/qc-menu.htm (archived: https://web.archive.org/web/20251124162531/https://www.gamers.org/dEngine/quake/spec/quake-spec34/qc-menu.htm)
- John Carmack .plan archive — [2 Aug 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960802.txt): 20 Hz dedicated tick, dialup bandwidth, and ~100 ms of latency even in single player from a 15 Hz game loop. Year dump: [1996 .plan archive](../../../historical/plans/carmack/by_year/johnc_plan_1996.txt).
