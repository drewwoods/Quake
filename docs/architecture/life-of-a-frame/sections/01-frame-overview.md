# The Top-Level Frame: `Sys_*` Main Loop and `Host_Frame`

Quake has no engine "framework," no scheduler, no threads, and no event loop in the modern sense. It has a `while (1)` in a platform file that computes a wall-clock delta and hands it to one function, `Host_Frame`, which runs *everything* — input, console, network, the QuakeC world simulation, the client's view of that world, the software or GL rasterizer, and mixing sound — in a fixed, straight-line order, then returns. There is exactly one place where the game advances in time and exactly one ordering of stages, and both the dedicated server and the single-player game are the same code with different flags. This section is the spine that the rest of the document hangs from: it establishes what `host_frametime` is, why the ordering of stages in `_Host_Frame` is what it is, and how the client and server manage to be two logically independent programs that happen to share an address space.

## Where it sits in the frame

This *is* the frame. Everything else in this document is a callee of `_Host_Frame` (`WinQuake/host.c:633-727`), which is called from `Host_Frame` (`WinQuake/host.c:729`), which is called from a platform `main`/`WinMain` loop: `WinQuake/sys_win.c:855-888`, `WinQuake/sys_linux.c:403-429`, `WinQuake/sys_dos.c:937-950`.

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

Two things are worth pulling out. First, the dedicated branch busy-waits on `Sys_Sleep()` until `sys_ticrate` seconds (default `0.05`, i.e. 20 Hz — `WinQuake/host.c:60`) have elapsed. A dedicated server has no reason to run faster than its network tick, and burning a Pentium on empty frames would have been actively hostile on the shared machines people ran servers on. Second, the interactive branch never sleeps *for a fixed period* — it blocks on `MsgWaitForMultipleObjects` (`WinQuake/sys_win.c:673-676`), waking on either a timeout or any input event. When the window is not focused it yields; when it is, the loop spins as fast as the machine allows and the rate limiting happens later, inside `Host_FilterTime`.

The Linux loop (`WinQuake/sys_linux.c:402-429`) differs in one interesting way — it *clamps the accumulator rather than the delta*:

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

`oldtime += time` is the same as `oldtime = newtime` here, but the `time > sys_ticrate.value*2` branch exists to keep the two from drifting apart after a hitch. On the dedicated path the delta handed to `Host_Frame` is *forced* to exactly `sys_ticrate.value` rather than the true elapsed time — a dedicated server therefore simulates in perfectly uniform 50 ms steps regardless of how badly the host machine hiccuped, which makes server-side physics deterministic and demo/VCR playback reproducible.

The DOS loop (`WinQuake/sys_dos.c:937-950`) is the most primitive of the three: no sleeping at all, just a `continue` when a dedicated server hasn't reached its tic. Under DOS there was no OS to yield to, so spinning cost nothing. `Sys_FloatTime` there (`WinQuake/sys_dos.c:689-745`) reads the 8253 PIT counter at port 0x40 and the BIOS tick count at real-mode address `0x46c`, reconstructing a ~1.193 MHz timebase and defending against the two clocks disagreeing across a latch. It also carries a `sametimecount` hack that manufactures forward progress if the clock appears frozen for 100,000 consecutive calls — a symptom of just how unreliable the 1996 PC timebase was.

## `Host_Frame` and the profiling wrapper

`Host_Frame` (`WinQuake/host.c:729-770`) is a thin shell. If the `serverprofile` cvar is zero it simply forwards to `_Host_Frame`; otherwise it brackets the call with `Sys_FloatTime()` and prints a rolling average of milliseconds-per-frame and active client count every 1000 frames. All the real work is in `_Host_Frame`.

The first statement in `_Host_Frame` is not work but a landing pad:

```c
	if (setjmp (host_abortserver) )
		return;			// something bad happened, or the server disconnected
```

`WinQuake/host.c:640-641`. `Host_Error` (`WinQuake/host.c:121`) and `Host_EndGame` (`WinQuake/host.c:90`) `longjmp` to this buffer (`host_abortserver`, declared `WinQuake/host.c:52`). This is Quake's entire error-recovery strategy: any subsystem, arbitrarily deep — a bad BSP node, a QuakeC runtime error, a dropped server connection — can abandon the frame from wherever it is and the engine resumes at the top of the next one, having torn down the server or disconnected the client on the way out. No unwinding, no cleanup handlers; the hunk allocator is reset to `host_hunklevel` by `Host_ClearMemory` (`WinQuake/host.c:477`) when the level is torn down and that is the whole memory-safety story.

Then `rand ()` is called once per frame, unconditionally (`WinQuake/host.c:643-644`), with the comment "keep the random time dependent." Advancing the PRNG by wall-clock frame count rather than by simulation events deliberately decouples random outcomes from the deterministic simulation, so two runs at different framerates diverge.

## `Host_FilterTime`: what `host_frametime` actually means

Everything downstream reads one global, `host_frametime` (`WinQuake/host.c:40`). It is produced here, and it is the single most consequential function in the engine's timing model:

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

**Accumulate, don't drop.** `realtime += time` happens on *every* call, including calls that then return `false`. The platform loop always advances its own `oldtime`, so a rejected frame does not lose the elapsed time — it is banked in `realtime` and shows up in the next accepted frame's `host_frametime`. This is why the crude `oldtime = newtime` in the platform loops is correct despite looking lossy.

**The 72 Hz cap.** `1.0/72.0` ≈ 13.9 ms is a hard ceiling on simulation rate, bypassed only for `timedemo`. The in-source justification is at the call site, `WinQuake/host.c:647-648`: `// don't run too fast, or packets will flood out`. Because a listen server's client sends one `clc_move` per frame (see `CL_SendMove`, below) and a server sends one update per client per frame, uncapped frames on a fast machine would multiply outbound packet rate without bound on a 28.8k modem. The cap is a network-bandwidth governor that happens to also bound how often the physics integrator runs.

**Slow motion.** `host_framerate` (`WinQuake/host.c:57`) overrides the measured delta with a constant. Setting `host_framerate 0.001` makes the world crawl while the renderer runs flat out — the developer tool that made the "bullet time" screenshots of the era possible, and the mechanism `_Host_ServerFrame` in the `FPS_20` variant leans on.

**Clamping.** `host_frametime` is pinned to `[0.001, 0.1]`. The upper clamp is the important one: a 3-second stall (disk thrash while paging in a level, an alt-tab) must not be handed to `SV_Physics` as a single 3-second integration step, because Quake's collision code moves entities by `velocity * frametime` in one shot and would tunnel every moving object straight through the world. Clamping trades time fidelity for the invariant that no entity moves more than ~0.1 s worth of distance per physics step. The lower clamp prevents division blow-ups in friction and acceleration code on absurdly fast frames.

Note that the clamp is *not* applied when `host_framerate` is set, and that neither clamp nor cap bounds cumulative drift: after a stall the world is simply behind wall clock and never catches up. Quake makes no attempt at the fixed-timestep-with-accumulator pattern that later engines adopted.

## The order of stages

`WinQuake/host.c:650-694` is the canonical ordering. Reproduced with the comments intact, because the comments are the design document:

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
	
// check for commands typed to the host
	Host_GetConsoleCommands ();
	
	if (sv.active)
		Host_ServerFrame ();

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

**`Sys_SendKeyEvents`** pumps the platform event queue. On Win32 (`WinQuake/sys_win.c:640-655`) it drains the message queue with `PeekMessage`/`GetMessage`/`DispatchMessage`; the window procedure turns `WM_KEYDOWN` etc. into `Key_Event` calls, and `Key_Event` for a bound key does not act directly — it `Cbuf_AddText`s the binding (`+forward`, `impulse 2`, …).

**`IN_Commands`** (`WinQuake/in_win.c:963`, `WinQuake/in_dos.c:197`, stub at `WinQuake/in_null.c:32`) lets the joystick driver synthesize button events the same way, since joystick buttons are polled rather than delivered as messages.

**`Cbuf_Execute`** (`WinQuake/cmd.c:143`) then runs the accumulated command buffer. This is why the ordering matters so much: a key pressed *this* frame has already had its binding executed — setting `in_forward.state`, firing an impulse — before movement is built. Input latency for a bound key is therefore sub-frame, not one frame, which on a 15 fps 486 was the difference between the game feeling responsive and feeling broken.

**`NET_Poll`** (`WinQuake/net_main.c:927-953`) is *not* the game packet path. It calls `SetNetTime()` and runs a time-ordered list of poll procedures — server-list broadcast/collect (`WinQuake/net_main.c:308-309`), ping tests (`WinQuake/net_dgrm.c:570,697`), the serial/modem dialing state machine (`WinQuake/net_comx.c:1262-1277`), IPX housekeeping (`WinQuake/net_ipx.c:195`). Actual game traffic is read on demand inside `SV_RunClients` and `CL_GetMessage`. `NET_Poll` sits here because it is cheap out-of-band bookkeeping that wants to run once per frame with a fresh timestamp.

**`CL_SendCmd`** appears twice, guarded by opposite conditions, and this is the single most deliberate ordering decision in the function. When `sv.active` — a listen server or single player — the client's intentions must be built *before* `Host_ServerFrame` runs, because the server will consume them in the same frame through the loopback socket. When the server is remote, intentions are built *after* the server stage (which is skipped) and just before `CL_ReadFromServer`, so the outgoing packet reflects the newest input and goes out as late as possible in the frame — minimizing the input-to-wire latency that dominates on a modem link.

**`Host_GetConsoleCommands`** (`WinQuake/host.c:532-543`) drains `Sys_ConsoleInput()` for the dedicated-server operator's stdin and injects it into the same command buffer.

**`Host_ServerFrame`** runs the world. Its build-time variants are covered below.

**`host_time += host_frametime`** (`WinQuake/host.c:688`) advances the host's own clock, initialized to `1.0` in `Host_InitLocal` (`WinQuake/host.c:235`) with the comment "so a think at time 0 won't get called" — a QuakeC entity with `nextthink` left at its zeroed default must not appear to be due immediately.

**`CL_ReadFromServer`** (`WinQuake/cl_main.c:634-661`) advances `cl.time`, drains every pending server message, and rebuilds the client's renderable entity list:

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

**`SCR_UpdateScreen`** (`WinQuake/screen.c:808` software, `WinQuake/gl_screen.c:821` GL) renders. It is called unconditionally, even for a dedicated server — where `cls.state == ca_dedicated` short-circuits it — and even between the frame's other work, which is why `host_speeds` brackets it to report the classic `tot / server / gfx / snd` split (`WinQuake/host.c:716-724`).

**`S_Update`** (`WinQuake/snd_dma.c:721`) is handed the *renderer's* view vectors (`r_origin, vpn, vright, vup`) rather than the client's entity origin, so spatialization matches exactly what was just drawn — including in chase-cam mode. Before signon completes it is called with zero vectors so ambient sounds don't pan wildly during connection. `CDAudio_Update` (`WinQuake/cd_win.c:398`, `WinQuake/cd_linux.c:328`) then services the redbook audio track state machine.

**`host_framecount++`** (`WinQuake/host.c:726`) is the last statement. It is a frame *counter*, not a time source; the renderer uses it to mark which BSP nodes and surfaces have already been visited this frame (the standard "visframe" trick), so per-frame visited-flags never need clearing.

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

That is `WinQuake/host.c:580-591` — a decoupled fixed-ish server tick, the pattern QuakeWorld and every later id engine adopted. It is in the shipped source, disabled, which is a nice fossil of the transition from Quake's fused client/server frame to QuakeWorld's split one.

## Listen server, dedicated server, remote client

The three configurations are not three code paths; they are three settings of two booleans.

`Host_FindMaxClients` (`WinQuake/host.c:157-200`) reads the command line once at startup:

- `-dedicated [n]` sets `cls.state = ca_dedicated` and `svs.maxclients = n` (default 8).
- `-listen [n]` leaves `cls.state = ca_disconnected` but raises `svs.maxclients`.
- Neither: `svs.maxclients = 1`, `cls.state = ca_disconnected` — single player.

The two are mutually exclusive (`Sys_Error` at `WinQuake/host.c:180`), `svs.maxclients` is clamped to `MAX_SCOREBOARD`, and `deathmatch` is auto-set whenever `maxclients > 1`.

`cls.state` is a three-value enum (`WinQuake/client.h:102-104`): `ca_dedicated` (server only, no client capability at all), `ca_disconnected` (client running, showing the full-screen console), `ca_connected` (client talking to *some* server). `sv.active` is the orthogonal question of whether *this process* is running a server.

From that, the frame behaviour falls out:

| Configuration | `sv.active` | `cls.state` | Frame behaviour |
|---|---|---|---|
| Single player / listen | true | `ca_connected` | `CL_SendCmd` before server stage; both server and client stages run; renders |
| Dedicated | true | `ca_dedicated` | Both `CL_SendCmd` calls no-op (`WinQuake/cl_main.c:674-675`); `CL_ReadFromServer` skipped; `SCR_UpdateScreen` short-circuits |
| Remote client | false | `ca_connected` | Server stage skipped; `CL_SendCmd` runs in the second position; `CL_ReadFromServer` drains the wire |

`Host_Init` (`WinQuake/host.c:835-921`) reinforces the split: `R_InitTextures` runs unconditionally ("needed even for dedicated servers", `WinQuake/host.c:874`), but the entire video/sound/input block — `VID_Init`, `Draw_Init`, `SCR_Init`, `R_Init`, `S_Init`, `CDAudio_Init`, `Sbar_Init`, `CL_Init`, `IN_Init` — is inside `if (cls.state != ca_dedicated)` (`WinQuake/host.c:876-911`). A dedicated server never allocates a framebuffer or opens a sound device.

## How client and server coexist in one process

They do not share state; they share a process and communicate exclusively by messages, exactly as if they were on opposite ends of a modem. The mechanism is the loopback network driver, `WinQuake/net_loop.c`.

`Loop_SendMessage` (`WinQuake/net_loop.c:154-186`) does not send anything — it copies the message into the *peer* qsocket's receive buffer with a 4-byte header (type byte, 16-bit length, one alignment pad byte), then clears `canSend`:

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

The payoff is enormous relative to its cost. Single-player Quake is a network game with a zero-latency link. There is no "local play" code path to keep in sync with the networked one; QuakeC never knows whether the client it is talking to is on the same machine; a bug that only manifests over the wire will usually also manifest in single player if the message sizes get large enough. `SV_WriteEntitiesToClient` builds and PVS-culls the same delta-compressed entity stream whether the destination is a loopback buffer or a 28.8k modem. Carmack made the same architectural choice in every engine after this one, and the loopback driver is where it starts.

The cost is the coupling this section opened with: because both halves are driven by one `host_frametime` inside one `_Host_Frame`, a listen server's simulation rate is the host player's framerate — capped at 72 Hz, but also *floored* by whatever the host machine manages. A host player with a slow video card slows the world down for everyone connected to them. That defect is precisely what QuakeWorld was built to fix, by moving the server to a fixed tick and letting the client predict.

## Call graph

```
main / WinMain                                  sys_win.c:692, sys_linux.c:354, sys_dos.c:885
  Host_Init                                     host.c:835
  while (1)
    Sys_FloatTime                               sys_win.c:467, sys_dos.c:689
    Sys_Sleep / SleepUntilInput                 sys_win.c:673
    Host_Frame(time)                            host.c:729
      _Host_Frame(time)                         host.c:633
        setjmp(host_abortserver)                host.c:640
        Host_FilterTime(time)                   host.c:501
        Sys_SendKeyEvents                       sys_win.c:640
        IN_Commands                             in_win.c:963 / in_dos.c:197 / in_null.c:32
        Cbuf_Execute                            cmd.c:143
        NET_Poll                                net_main.c:927
          SetNetTime                            net_main.c:95
          pollProcedureList->procedure          net_main.c:944-949
        CL_SendCmd            [if sv.active]    cl_main.c:670
          CL_BaseMove                           cl_input.c:283
          IN_Move                               in_win.c
          CL_SendMove                           cl_input.c:332
            NET_SendUnreliableMessage           net_main.c
        Host_GetConsoleCommands                 host.c:532
        Host_ServerFrame      [if sv.active]    host.c:600
          SV_ClearDatagram                      sv_main.c
          SV_CheckForNewClients                 sv_main.c
          SV_RunClients                         sv_user.c
          SV_Physics                            sv_phys.c
          SV_SendClientMessages                 sv_main.c
        CL_SendCmd            [if !sv.active]   cl_main.c:670
        host_time += host_frametime             host.c:688
        CL_ReadFromServer  [if ca_connected]    cl_main.c:634
          CL_GetMessage                         cl_demo.c
          CL_ParseServerMessage                 cl_parse.c
          CL_RelinkEntities                     cl_main.c
          CL_UpdateTEnts                        cl_tent.c
        SCR_UpdateScreen                        screen.c:808 / gl_screen.c:821
        S_Update                                snd_dma.c:721
        CL_DecayLights                          cl_main.c
        CDAudio_Update                          cd_win.c:398 / cd_linux.c:328
        host_framecount++                       host.c:726
```

## Key data structures

- `quakeparms_t` — `WinQuake/quakedef.h` — basedir/cachedir/argc/argv/membase/memsize handed from `main` to `Host_Init`; the entire platform→engine configuration surface.
- `host_frametime` (double) — `WinQuake/host.c:40` — the simulation timestep for this frame; read by the server physics, the client clock, and QuakeC via `pr_global_struct->frametime`.
- `realtime` / `oldrealtime` (double) — `WinQuake/host.c:42-43` — unfiltered accumulated wall clock, and the timestamp of the last accepted frame; their difference is the raw delta before clamping.
- `host_time` (double) — `WinQuake/host.c:41` — host clock, initialized to `1.0` (`WinQuake/host.c:235`) so zero-valued `nextthink` fields never fire.
- `host_framecount` (int) — `WinQuake/host.c:44` — frames since startup; used as the renderer's per-frame visited marker.
- `host_abortserver` (`jmp_buf`) — `WinQuake/host.c:52` — `longjmp` target for `Host_Error`/`Host_EndGame`; the only unwinding mechanism in the engine.
- `sys_ticrate` (cvar, "0.05") — `WinQuake/host.c:60` — dedicated-server tick period; also the drift threshold in the Linux loop.
- `host_framerate` (cvar, "0") — `WinQuake/host.c:57` — when nonzero, overrides the measured delta for slow motion.
- `cls.state` (`cactive_t`) — `WinQuake/client.h:101-105` — `ca_dedicated` / `ca_disconnected` / `ca_connected`; decides whether the client half of the frame exists.
- `sv.active` (`server_t`) — `WinQuake/server.h:37` — whether this process is running a server this frame; decides `CL_SendCmd` placement.
- `svs.maxclients` / `svs.clients` (`server_static_t`) — `WinQuake/server.h:24-26`, allocated `WinQuake/host.c:195` — client slot array, sized once at startup by `Host_FindMaxClients`.
- `qsocket_t` — `WinQuake/net.h` — the network endpoint abstraction; the loopback driver fills its `receiveMessage` buffer with `memcpy` (`WinQuake/net_loop.c:154-186`) so local play is indistinguishable from networked play.

## Further reading

- Fabien Sanglard, "Quake Source Code Review" — the standard modern walkthrough of `Host_Frame` and the client/server split: https://fabiensanglard.net/quakeSource/index.php
- Michael Abrash, *Graphics Programming Black Book*, chapters 59–70 (the Quake chapters) — the renderer half of the frame, and the performance culture that produced this loop: https://www.jagregory.com/abrash-black-book/
- Olivier Montanuy et al., "Unofficial Quake Specs" — network protocol and progs interfaces: https://www.gamers.org/dEngine/quake/spec/quake-spec34/
- QuakeC reference (the `frametime` global and `StartFrame`): https://www.gamers.org/dEngine/quake/spec/quake-spec34/qc-menu.htm
- John Carmack .plan archive — contemporaneous notes on the QuakeWorld client/server split that this frame structure motivated: https://github.com/ESWAT/john-carmack-plan-archive
