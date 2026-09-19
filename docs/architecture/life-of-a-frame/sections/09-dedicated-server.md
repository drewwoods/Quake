# The dedicated server: the same frame without a client

A dedicated server runs the identical `_Host_Frame` with the client half
compiled in but switched off: no video, no sound device, no input, no local
player. What remains is the server stage, a stdin console, and a ~20 Hz pacing
loop. Everything the operator types goes through the same command buffer as a
local player's keystrokes.

> **First pass.** Think **server stage only**. `-dedicated` sets `cls.state =
> ca_dedicated`; every client call in the frame then hits an early return
> (`CL_SendCmd` no-ops, `CL_ReadFromServer` is skipped, `SCR_UpdateScreen`
> returns immediately). The platform loop sleeps until `sys_ticrate` (default
> 0.05 s) elapses, and stdin is polled into the command buffer each frame.
> Source: `WinQuake/host.c:157-201`, `WinQuake/sys_win.c:857-864`,
> `WinQuake/host.c:532-543`. [Next: QuakeWorld contrast →](#sec-10)

## Where it sits in the frame

Nowhere new — that is the point. `_Host_Frame` (`WinQuake/host.c:633-727`)
executes the same statement order as in a listen server; dedicated mode only
changes which branches are taken. `CL_SendCmd` appears twice but both calls
return immediately (`cls.state != ca_connected`, `WinQuake/cl_main.c:674`).
`Host_ServerFrame` runs (`sv.active` is true). `CL_ReadFromServer` is skipped
(`cls.state == ca_connected` is false, `WinQuake/host.c:691`).
`SCR_UpdateScreen` is still *called* (`WinQuake/host.c:700`) but returns at its
guard (`WinQuake/screen.c:831`). Audio still calls `S_Update` with null vectors
(`WinQuake/host.c:712`) — harmless, since no sound device was ever opened. The
frame counter still ticks (`WinQuake/host.c:726`).

::: diagram dedicated-compare

## Selecting dedicated: one flag, two state variables

`Host_FindMaxClients` (`WinQuake/host.c:157-201`) reads the command line once at
startup. `-dedicated [n]` sets `cls.state = ca_dedicated` with `svs.maxclients`
defaulting to 8; `-listen [n]` raises `svs.maxclients` without touching
`cls.state`; neither leaves a single-player setup. The two flags are mutually
exclusive (`Sys_Error`, `WinQuake/host.c:180-181`), the count is clamped to
`MAX_SCOREBOARD`, and anything above one player sets `deathmatch`
(`WinQuake/host.c:197-200`).

Two variables jointly describe the configuration, and both are read every frame.
`sv.active` (`WinQuake/server.h:37`) asks "is this process simulating a world";
`cls.state` (`WinQuake/client.h:102-104`: `ca_dedicated` / `ca_disconnected` /
`ca_connected`) asks "does this process have a usable client". A dedicated
server is `sv.active == true` with `cls.state == ca_dedicated` — server yes,
client nonexistent. (The full three-way table is in [the frame
overview](#sec-1); the same enum also decides `CL_EstablishConnection`'s
immediate return, `WinQuake/cl_main.c:150-151`.)

Client slots come from one hunk allocation sized by the command line:
`svs.clients = Hunk_AllocName (svs.maxclientslimit*sizeof(client_t), "clients")`
(`WinQuake/host.c:195`), where `maxclientslimit` is `maxclients` raised to a
floor of 4. Slot count is therefore fixed for the process lifetime — raising it
means restarting, not typing a command. The static side (`maxclients`,
`clients`, `serverflags`) lives in `server_static_t`
(`WinQuake/server.h:22-29`); the per-level mutable side (`active`, `paused`,
`time`, datagrams, edicts) lives in `server_t` (`WinQuake/server.h:35-72`).

## What doesn't run: the `ca_dedicated` guards

`Host_Init` (`WinQuake/host.c:835-921`) draws the line explicitly.
`R_InitTextures` runs unconditionally — "needed even for dedicated servers"
(`WinQuake/host.c:874`), because the server still needs texture metadata for
visibility and collision-adjacent queries — but the whole presentation block is
skipped:

```c
// WinQuake/host.c:876-911 (abridged)
	if (cls.state != ca_dedicated)
	{
		host_basepal = (byte *)COM_LoadHunkFile ("gfx/palette.lmp");
		...
		IN_Init ();
		...
		VID_Init (host_basepal);
		Draw_Init ();
		SCR_Init ();
		R_Init ();
		S_Init ();
		...
		CDAudio_Init ();
		Sbar_Init ();
		CL_Init ();
		IN_Init ();
	}
```

No framebuffer, no palette/colormap load, no sound or CD audio, no status bar,
no client module, no input drivers. `Host_Shutdown` mirrors the split (`if
(cls.state != ca_dedicated) VID_Shutdown();`, `WinQuake/host.c:953-956`). The
dedicated process never maps video memory or opens audio hardware, which is also
why it can run on a headless machine — or, in 1996 terms, on a spare box in a
closet with nothing but a network cable.

The per-frame guards complete the picture. `SCR_UpdateScreen` bails before
touching the renderer (`if (cls.state == ca_dedicated) return; // stdout only`,
`WinQuake/screen.c:831`) — the "stdout only" comment is literal: console text
goes to the terminal instead. `CL_SendCmd` returns before reading input
(`WinQuake/cl_main.c:674-675`). `Sys_SendKeyEvents` and `IN_Commands` still
execute in `_Host_Frame`, but with no window and no drivers they have nothing to
pump. The memory allocators, by contrast, are fully live: the Zone/Hunk/Cache
trio serves the server exactly as it serves single player (see [the allocator
reference](#sec-7) — Zone still holds cvar strings, the hunk still holds the
level and edicts, the Cache still holds models and sounds the server needs for
precache bookkeeping).

Two behaviors change subtly rather than switching off. `Host_WriteConfiguration`
skips writing `config.cfg` on dedicated servers (`if (host_initialized &
!isDedicated)`, `WinQuake/host.c:252`) — an unattended server must not persist
operator keystrokes or transient cvar state over its tuned config. And both
`Host_EndGame` and `Host_Error` escalate to `Sys_Error` under `ca_dedicated`
(`WinQuake/host.c:103-104`, `WinQuake/host.c:141-142`): with no player to drop
back to a menu, any game-fatal error is process-fatal, on the theory that a
corrupted public server should exit and be restarted rather than idle in an
unknown state.

## Pacing: `sys_ticrate` instead of the 72 Hz gate

An interactive client spins its platform loop as fast as possible and lets
`Host_FilterTime` rejectHz excess frames. A dedicated server inverts the
responsibility: the *platform loop* waits, so `Host_Frame` is simply called at
the right rate. On Windows:

```c
// WinQuake/sys_win.c:857-864
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
```

`sys_ticrate` (default `"0.05"`, `WinQuake/host.c:60`) is the target tick
period: 20 Hz. `Sys_Sleep` is a 1 ms `Sleep` (`WinQuake/sys_win.c:635-637`), so
the loop polls the clock at ~1 kHz granularity without burning the CPU the way a
tight spin would — coarse, but the error is ±1 ms on a 50 ms tick. `isDedicated`
itself is a separate platform flag (`WinQuake/sys_win.c:44`), set from the same
`-dedicated` argument before `Host_Init` runs (`WinQuake/sys_win.c:753`); the
engine-side `cls.state` and the platform-side `isDedicated` agree by
construction, and the console/input code reads whichever layer it belongs to.

The Linux loop (`WinQuake/sys_linux.c:402-424`) has the same shape with one
extra clause: while dedicated, frames short of `sys_ticrate` are skipped via
`usleep(1)` *unless a VCR recording is in progress* (`if (time <
sys_ticrate.value && (vcrFile == -1 || recording))`,
`WinQuake/sys_linux.c:411`), then the delta is replaced wholesale with `time =
sys_ticrate.value` (`WinQuake/sys_linux.c:416`). VCR capture (see
[demos](#sec-8)) needs unthrottled timing, so recording exempts the process from
pacing; playback instead drives timing from the log. Note the consequence for
simulation: `host_frametime` on a dedicated server is nearly constant at
`sys_ticrate`, so `SV_Physics` integrates fixed-size steps and QuakeC sees a
steady `frametime` — unlike a listen server, whose step varies with the host
player's render rate. The 72 Hz cap in `Host_FilterTime` still applies in
principle, but a 50 ms dedicated tick never trips a 13.9 ms minimum.

Fixed steps also change the pause story. `Host_ServerFrame` simulates unless
paused (`if (!sv.paused && (svs.maxclients > 1 || key_dest == key_game))`,
`WinQuake/host.c:616`): single player freezes when the console or menu opens,
but any multiplayer configuration — dedicated included — simulates until an
explicit `pause` command sets `sv.paused`. A dedicated server therefore has
exactly two time regimes: ticking at `sys_ticrate`, or frozen by operator
command. There is no focus loss, no minimization, no `SleepUntilInput` path; the
Windows branch that yields the CPU for unfocused clients never runs because
`isDedicated` takes the sleep-until-ticrate branch first. The cost of that
simplicity is latency quantization: client inputs arriving between ticks wait up
to a full 50 ms for the next `SV_RunClients`, which is part of why the default
tick felt sluggish next to loopback single player even before network delay.

## Operating it: stdin into the command buffer

A dedicated server has no key bindings and no console overlay; its entire
operator interface is stdin, drained once per frame by `Host_GetConsoleCommands`
(`WinQuake/host.c:532-543`):

```c
// WinQuake/host.c:532-543
void Host_GetConsoleCommands (void)
{
	char	*cmd;

	while (1)
	{
		cmd = Sys_ConsoleInput ();
		if (!cmd)
			break;
		Cbuf_AddText (cmd);
	}
}
```

Lines accumulate in the same `cmd_text` buffer as typed commands and `exec`
scripts (see [the Cbuf/Cmd/Cvar reference](#sec-7)), and execute at the next
`Cbuf_Execute` — i.e. next frame, before the server stage. Server administration
(`map`, `kick`, `fraglimit`, `timelimit`, `say`, ...) is therefore ordinary
console commands, not a separate remote-admin protocol; typing `map e1m1` into
the server terminal is byte-identical to typing it into a listen server's
console.

The two `Sys_ConsoleInput` implementations differ in flavor. Windows
(`WinQuake/sys_win.c:555-633`) returns `NULL` immediately when not dedicated
(`WinQuake/sys_win.c:564`), otherwise drains Win32 console input records one at
a time, acting only on key-up events: `\r` submits the 256-byte line buffer,
`\b` edits it with echo (`"\b \b"`), printable characters echo and append with
`len = (len + 1) & 0xff` wraparound. The console window itself is created with
`AllocConsole` at startup, failing fatally if unavailable
(`WinQuake/sys_win.c:812-816`). Linux (`WinQuake/sys_linux.c:319-343`) gates on
`cls.state == ca_dedicated` (`WinQuake/sys_linux.c:326`), polls stdin with a
zero-timeout `select`, and returns the whole `read` minus its trailing newline —
no line editing at all; that is the shell's job. Either way the contract is
identical: return one complete line, or `NULL` when there is none, and never
block the frame.

## Call graph

```
WinMain / main (sys_win.c:692, sys_linux.c:354)
  isDedicated = COM_CheckParm("-dedicated") (sys_win.c:753)
  [Windows] AllocConsole (sys_win.c:812)
  Host_Init (host.c:835)
    Host_FindMaxClients (host.c:157)          [-dedicated -> ca_dedicated, maxclients]
    Host_InitVCR (host.c:772)
    R_InitTextures (host.c:874)               [unconditional]
    [skipped if ca_dedicated] VID/Sound/SCR/Sbar/CL/IN init (host.c:876-911)
  while (1)
    [dedicated] sleep until sys_ticrate (sys_win.c:857-864, sys_linux.c:409-416)
    Host_Frame -> _Host_Frame (host.c:633)
      Sys_SendKeyEvents / IN_Commands          [nothing to pump]
      Cbuf_Execute
      CL_SendCmd                               [no-op: state != ca_connected, cl_main.c:674]
      Host_GetConsoleCommands (host.c:532)
        Sys_ConsoleInput (sys_win.c:555, sys_linux.c:319) -> Cbuf_AddText
      Host_ServerFrame (host.c:600)            [sv.active]
        SV_ClearDatagram / SV_CheckForNewClients / SV_RunClients
        SV_Physics (fixed ~sys_ticrate steps) / SV_SendClientMessages
      [skipped] CL_ReadFromServer (host.c:691) [state != ca_connected]
      SCR_UpdateScreen                         [early return, screen.c:831]
      S_Update (null vectors, host.c:712)      [no device open]
      host_framecount++ (host.c:726)
```

## Key data structures

- `cls.state` (`cactive_t`: `ca_dedicated` / `ca_disconnected` / `ca_connected`) — `WinQuake/client.h:102-104` — whether this process has a client; every client-stage guard reads it.
- `sv.active` (`qboolean`) — `WinQuake/server.h:37` — whether this process simulates a world this frame.
- `svs.maxclients` / `svs.maxclientslimit` / `svs.clients` (`server_static_t`) — `WinQuake/server.h:22-29`, sized `WinQuake/host.c:195` — fixed-lifetime client slots.
- `sys_ticrate` (cvar, `"0.05"`) — `WinQuake/host.c:60` — dedicated tick period; read by the platform sleep loops.
- `isDedicated` (`qboolean`) — `WinQuake/sys_win.c:44` — platform-side mirror of `-dedicated`, set before `Host_Init`.
- `host_frametime` (double) — `WinQuake/host.c:40` — ≈ `sys_ticrate` every dedicated frame; the QuakeC-visible step via `pr_global_struct->frametime`.
- `con_text` (`CON_TEXTSIZE` = 16384 bytes) — `WinQuake/console.c:35` — scrollback buffer; on dedicated servers its sink is stdout rather than the overlay (see [the console reference](#sec-7)).

## Further reading

- Fabien Sanglard, "Quake Source Code Review":
  https://fabiensanglard.net/quakeSource/index.php — `Host_Init` split and the
  client/server coexistence model.
- John Carmack .plan archive: https://github.com/ESWAT/john-carmack-plan-archive
  — the 2 Aug 1996 note on the 20 Hz default server rate and dialup bandwidth
  (cited in [the frame overview](#sec-1)).
