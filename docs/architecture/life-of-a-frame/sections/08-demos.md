# Demos: recording, playback, timedemo, and the VCR

A demo is a recording of the raw server-to-client message stream, plus the
camera angles for each message. Recording appends to a file as messages arrive;
playback substitutes the file for the socket inside `CL_GetMessage`, so the
normal parser, relinker, and renderer run unchanged.

> **First pass.** Think **file instead of socket**. `CL_GetMessage` reads the
> next packet from `cls.demofile` when `cls.demoplayback` is set, and writes
> each received packet there when `cls.demorecording` is set. `timedemo` replays
> as fast as the machine can render to benchmark it. A separate, lower-level
> tool — the VCR (`-record`/`-playback`) — logs network-driver calls instead of
> game packets. Source: `WinQuake/cl_demo.c:90-156`,
> `WinQuake/cl_demo.c:347-366`, `WinQuake/host.c:772-828`. [Next: dedicated
> servers →](#sec-9)

## Where it sits in the frame

Demos interpose at exactly one choke point. `CL_ReadFromServer`
(`WinQuake/cl_main.c:634`) loops on `CL_GetMessage` (`WinQuake/cl_demo.c:90`),
which returns 1 for "message ready in `net_message`", 0 for "nothing new", and
-1 for "connection lost". When `cls.demoplayback` is set it serves bytes from
`cls.demofile`; otherwise it drains `NET_GetMessage` and, when
`cls.demorecording` is set, copies each accepted message to `cls.demofile`
(`WinQuake/cl_demo.c:152-153`). Everything downstream — `CL_ParseServerMessage`,
`CL_RelinkEntities`, screen update, sound mix — cannot tell playback from a live
game. Two frame counters pace the replay: `host_framecount`
(`WinQuake/host.c:726`, incremented last in `_Host_Frame`) meters timedemo to
one message per frame, and `Host_FilterTime` (`WinQuake/host.c:505`) skips its
72 Hz gate when `cls.timedemo` is set so the benchmark is never throttled.

## The file format: a text header, then length-tagged records

A `.dem` file has two layers. First comes one ASCII line: the forced CD track as
decimal text terminated by `\n` (`fprintf (cls.demofile, "%i\n",
cls.forcetrack)` on record, `WinQuake/cl_demo.c:255`; parsed back
character-by-character on play, `WinQuake/cl_demo.c:307-314`, including the `-`
sign handling). `-1` means "play whatever track the level requests". Then comes
a sequence of records, each written by `CL_WriteDemoMessage`
(`WinQuake/cl_demo.c:66-81`):

```c
// WinQuake/cl_demo.c:66-81
void CL_WriteDemoMessage (void)
{
	int		len;
	int		i;
	float	f;

	len = LittleLong (net_message.cursize);
	fwrite (&len, 4, 1, cls.demofile);
	for (i=0 ; i<3 ; i++)
	{
		f = LittleFloat (cl.viewangles[i]);
		fwrite (&f, 4, 1, cls.demofile);
	}
	fwrite (net_message.data, net_message.cursize, 1, cls.demofile);
	fflush (cls.demofile);
}
```

Each record is a 4-byte little-endian length, three little-endian floats of
camera angles, then the raw message bytes. Recording the camera matters because
the server stream carries entity positions but never the viewer's own look
direction — during playback the client must see what the recorder saw. The
`fflush` per message is deliberate: a crash mid-game still leaves a playable
prefix, at the cost of a syscall per packet. Note the format stores no
timestamps at all; pacing is reconstructed from message contents (see below),
which is why playback speed depends on the frame loop rather than the file.

::: diagram demo-record

## Recording: `record`, and the `stop` trailer

`CL_Record_f` (`WinQuake/cl_demo.c:196-258`) implements `record <demoname>
[<map> [cd track]]`. Three guards come first: the command must come from the
console (`cmd_source != src_command` returns, so QuakeC or aliases cannot start
recordings), pathnames containing `..` are rejected, and recording
mid-connection is refused — with two arguments while `cls.state == ca_connected`
it prints "Can not record - already connected to server" and returns
(`WinQuake/cl_demo.c:218-222`). Recording must start before connecting because
the demo needs the full signon handshake (serverinfo, baselines, precaches) from
message zero; joining mid-stream would produce a file missing everything the
client needs to decode later updates.

With three or more arguments the command first starts the map
(`Cmd_ExecuteString (va("map %s", ...))`, `WinQuake/cl_demo.c:239`), then opens
`<gamedir>/<name>.dem` for writing and stores the CD-track override as the text
header. From that point every accepted server message is tee'd to disk by the
tail of `CL_GetMessage`. The signon phase is recorded like any other traffic,
which is exactly what makes the file self-contained.

`CL_Stop_f` (`WinQuake/cl_demo.c:166-187`) ends a recording. Before closing it
synthesizes one last message into the file — a lone `svc_disconnect` byte
(`WinQuake/cl_demo.c:178-180`). On playback that byte runs through the ordinary
`svc_disconnect` parse path and tears the virtual connection down cleanly;
without it, hitting end-of-file would call `CL_StopPlayback` mid-frame instead.
`CL_Disconnect` (`WinQuake/cl_main.c:99-128`) also finalizes a recording
automatically when the user disconnects, so quitting normally never leaves a
truncated file.

## Playback: one choke point, three pacing rules

`CL_PlayDemo_f` (`WinQuake/cl_demo.c:268-317`, registered as `playdemo`,
`WinQuake/cl_main.c:754`) disconnects any live game first (`CL_Disconnect`,
`WinQuake/cl_demo.c:286`), opens the file through the search path
(`COM_FOpenFile`), then fakes a connection: `cls.demoplayback = true; cls.state
= ca_connected;` (`WinQuake/cl_demo.c:303-304`). No socket exists; `cls.netcon`
is never touched on this path. The signon counter advances from the recorded
`svc_signonnum` messages exactly as it would over the wire.

All pacing lives in `CL_GetMessage`:

```c
// WinQuake/cl_demo.c:95-114
	if	(cls.demoplayback)
	{
	// decide if it is time to grab the next message		
		if (cls.signon == SIGNONS)	// allways grab until fully connected
		{
			if (cls.timedemo)
			{
				if (host_framecount == cls.td_lastframe)
					return 0;	// allready read this frame's message
				cls.td_lastframe = host_framecount;
			// if this is the second frame, grab the real td_starttime
			// so the bogus time on the first frame doesn't count
				if (host_framecount == cls.td_startframe + 1)
					cls.td_starttime = realtime;
			}
			else if ( /* cl.time > 0 && */ cl.time <= cl.mtime[0])
			{
					return 0;	// don't need another message yet
			}
		}
```

Three rules, in priority order. Before signon completes (`cls.signon !=
SIGNONS`, where `SIGNONS` is 4, `WinQuake/client.h:69`), every call grabs the
next record — loading must never stall waiting for a clock. Once connected,
timedemo takes exactly one message per `host_framecount`, so each rendered frame
consumes one packet and the benchmark counts frames, not wall time. Normal
playback instead compares clocks: if `cl.time` (advanced by `host_frametime`
each `CL_ReadFromServer`) has not passed the last message's timestamp
`cl.mtime[0]`, return 0 and render another frame on the existing state. This
reuses the same "don't need another message yet" gate as live play, so demo
playback inherits live interpolation behavior for free — including the
`CL_LerpPoint` fast path that snaps `frac` to 1 when `cls.timedemo` is set
(`WinQuake/cl_main.c:397`).

The record reader itself is plain:

```c
// WinQuake/cl_demo.c:117-135
	// get the next message
		fread (&net_message.cursize, 4, 1, cls.demofile);
		VectorCopy (cl.mviewangles[0], cl.mviewangles[1]);
		for (i=0 ; i<3 ; i++)
		{
			r = fread (&f, 4, 1, cls.demofile);
			cl.mviewangles[0][i] = LittleFloat (f);
		}
		
		net_message.cursize = LittleLong (net_message.cursize);
		if (net_message.cursize > MAX_MSGLEN)
			Sys_Error ("Demo message > MAX_MSGLEN");
		r = fread (net_message.data, net_message.cursize, 1, cls.demofile);
		if (r != 1)
		{
			CL_StopPlayback ();
			return 0;
		}

		return 1;
```

Two details repay attention. First, the angle history shift (`mviewangles[0]` →
`[1]` before reading the new `[0]`) mirrors the entity snapshot shift in
`CL_ParseUpdate`; `CL_RelinkEntities` then lerps `cl.viewangles` between the two
recorded angles (`WinQuake/cl_main.c:464-477`) with the same `frac` used for
entities, so the camera and the world stay in sync. Second, a short read —
normal end of file — calls `CL_StopPlayback` (`WinQuake/cl_demo.c:45-57`), which
closes the file, clears `demoplayback`, drops to `ca_disconnected`, and, if this
was a timedemo, prints the benchmark. An oversized length is instead a hard
`Sys_Error`: corrupt lengths fail fast rather than allocating.

While playback runs, `CL_SendCmd` (`WinQuake/cl_main.c:670-706`) still builds
movement from local input but discards the reliable half: `if (cls.demoplayback)
{ SZ_Clear (&cls.message); return; }` (`WinQuake/cl_main.c:690-693`). Sending
would be meaningless with no peer, but building the command keeps
`IN_Move`/view-angle code exercised so the demo camera path stays live.

Attract mode chains demos through `cls.demonum` and `cls.demos`
(`WinQuake/client.h:120-121`). `CL_NextDemo` (`WinQuake/cl_main.c:219-242`)
inserts `playdemo <name>` at the front of the command buffer and advances the
index, wrapping to zero; `Host_EndGame` resumes the loop on level exit
(`WinQuake/host.c:106-107`) while `Host_Error` cancels it (`cls.demonum = -1`,
`WinQuake/host.c:145`). Starting a real connection also cancels it (`cls.demonum
= -1`, `WinQuake/cl_main.c:163`).

## Timedemo: a benchmark made of three counters

`CL_TimeDemo_f` (`WinQuake/cl_demo.c:347-366`, registered as `timedemo`,
`WinQuake/cl_main.c:755`) is four lines over `CL_PlayDemo_f`:

```c
// WinQuake/cl_demo.c:358-365
	CL_PlayDemo_f ();

	// cls.td_starttime will be grabbed at the second frame of the demo, so
	// all the loading time doesn't get counted

	cls.timedemo = true;
	cls.td_startframe = host_framecount;
	cls.td_lastframe = -1;		// get a new message this frame
```

`td_startframe`/`td_lastframe`/`td_starttime` live in `client_static_t`
(`WinQuake/client.h:130-132`). The start time is deliberately *not* taken here:
the first frame's `realtime` includes level loading, so `CL_GetMessage` re-grabs
`td_starttime = realtime` on the second benchmarked frame
(`WinQuake/cl_demo.c:107-108`). `CL_FinishTimeDemo`
(`WinQuake/cl_demo.c:325-338`) then reports:

```c
// WinQuake/cl_demo.c:325-338
void CL_FinishTimeDemo (void)
{
	int		frames;
	float	time;
	
	cls.timedemo = false;
	
	// the first frame didn't count
	frames = (host_framecount - cls.td_startframe) - 1;
	time = realtime - cls.td_starttime;
	if (!time)
		time = 1;
	Con_Printf ("%i frames %5.1f seconds %5.1f fps\n", frames, time, frames/time);
}
```

Frames minus one over wall seconds is the period fps figure (`demo1`/`demo2`
shipping demos exist precisely for this). Two engine behaviors make the number
meaningful: `Host_FilterTime` bypasses the 72 Hz cap under timedemo
(`WinQuake/host.c:505`), so fast machines are never gated, and `CL_LerpPoint`
snaps interpolation (`WinQuake/cl_main.c:397`), so rendering cost is measured
without blending artifacts changing the workload. `timedemo` is also cleared by
`CL_Disconnect` (`WinQuake/cl_main.c:127`), so disconnecting mid-benchmark
cannot leave the 72 Hz gate disabled.

## The VCR: deterministic replay below the network layer

The VCR (`-record` / `-playback` command-line flags, `Host_InitVCR`,
`WinQuake/host.c:772-828`) operates one layer down from demos: it logs
*network-driver calls*, not game packets. On `-record` it rewrites the argument
list (swapping `-record` for `-playback`) and writes it plus a `VCR_SIGNATURE`
(`0x56435231`, `"VCR1"`, `WinQuake/host.c:769`) into `quake.vcr`. On `-playback`
it refuses any other parameters (`WinQuake/host.c:779-780`), reads the recorded
argv back over the process's own, and VCR playback starts at driver slot 0
(`VCR_Init`, `WinQuake/net_vcr.c:39-54`).

Each logged call records `host_time`, an op code
(`VCR_OP_CONNECT/GETMESSAGE/SENDMESSAGE/CANSENDMESSAGE`,
`WinQuake/net_vcr.h:22-26`), and a session id. Playback asserts all three match:

```c
// WinQuake/net_vcr.c:78-98
int VCR_GetMessage (qsocket_t *sock)
{
	int	ret;
	
	if (host_time != next.time || next.op != VCR_OP_GETMESSAGE || next.session != *(long *)(&sock->driverdata))
		Sys_Error ("VCR missmatch");

	Sys_FileRead(vcrFile, &ret, sizeof(int));
	if (ret != 1)
	{
		VCR_ReadNext ();
		return ret;
	}

	Sys_FileRead(vcrFile, &net_message.cursize, sizeof(int));
	Sys_FileRead(vcrFile, net_message.data, net_message.cursize);

	VCR_ReadNext ();

	return 1;
}
```

Any divergence — a frame boundary at a different `host_time`, calls in a
different order — is a fatal `Sys_Error ("VCR missmatch")`, and end of log is a
fatal `"=== END OF PLAYBACK==="` (`WinQuake/net_vcr.c:61`). That strictness is
the point: the VCR is a debugging tool for reproducing exact network timing
(notably around the dialup-era serial drivers), and silent divergence would make
reproductions untrustworthy. The Linux dedicated loop even exempts VCR recording
from its ticrate sleep (`vcrFile == -1 || recording`,
`WinQuake/sys_linux.c:411`) so the log captures unthrottled timing. Demos record
*what the game said*; the VCR records *when the network said it* — use the
former to watch a game, the latter to replay a bug.

## Call graph

```
CL_Record_f (cl_demo.c:196)                  [console "record"]
  Cmd_ExecuteString("map ...") (cl_demo.c:239) [optional map start]
  fopen .dem, fprintf forcetrack (cl_demo.c:247-255)
  cls.demorecording = true (cl_demo.c:257)
CL_ReadFromServer (cl_main.c:634)
  CL_GetMessage (cl_demo.c:90)
    [playback] fread len/angles/payload (cl_demo.c:117-135)
      short read -> CL_StopPlayback (cl_demo.c:45)
        [timedemo] CL_FinishTimeDemo (cl_demo.c:325)
    [live] NET_GetMessage loop, drop svc_nop (cl_demo.c:138-150)
    [recording] CL_WriteDemoMessage (cl_demo.c:66)
CL_Stop_f (cl_demo.c:166)                    [console "stop"]
  MSG_WriteByte(svc_disconnect) -> CL_WriteDemoMessage (cl_demo.c:178-180)
CL_PlayDemo_f (cl_demo.c:268)                [console "playdemo"]
  CL_Disconnect (cl_main.c:99)
  cls.demoplayback = true, state = ca_connected (cl_demo.c:303-304)
CL_TimeDemo_f (cl_demo.c:347)                [console "timedemo"]
  CL_PlayDemo_f + timedemo=true, td_startframe=host_framecount (cl_demo.c:358-365)
Host_FilterTime (host.c:501)
  !cls.timedemo gate bypass (host.c:505)
CL_SendCmd (cl_main.c:670)
  [demoplayback] SZ_Clear, drop reliable (cl_main.c:690-693)
CL_NextDemo (cl_main.c:219)                  [attract loop via Host_EndGame host.c:106]
Host_InitVCR (host.c:772)                    [-record/-playback argv handling]
VCR_Init (net_vcr.c:39) -> VCR_GetMessage/SendMessage/CanSendMessage/CheckNewConnections
```

## Key data structures

- `cls.demofile` (`FILE *`) — `WinQuake/client.h:129` — open demo handle for whichever direction is active; `NULL` otherwise.
- `cls.demorecording` / `cls.demoplayback` / `cls.timedemo` (`qboolean`) — `WinQuake/client.h:125-127` — the three switches `CL_GetMessage` branches on.
- `cls.forcetrack` (int) — `WinQuake/client.h:128` — CD-track override stored as the file's text header line.
- `cls.td_lastframe` / `cls.td_startframe` / `cls.td_starttime` — `WinQuake/client.h:130-132` — timedemo metering: one message per `host_framecount`, benchmark window starting at the second frame.
- `cls.demonum` / `cls.demos[MAX_DEMOS]` — `WinQuake/client.h:120-121` — attract-mode playlist consumed by `CL_NextDemo`.
- `cl.mviewangles[2]` (`vec3_t`) — `WinQuake/client.h:169` — recorded camera history; `CL_RelinkEntities` lerps `cl.viewangles` between the slots during playback.
- `host_framecount` (int) — `WinQuake/host.c:44` — accepted-frames counter; timedemo's per-frame message meter.
- `vcrFile` (int) — `WinQuake/host.c:768` (extern) — VCR log handle; `-1` when inactive.
- VCR `next` (`{double time; int op; long session;}`) — `WinQuake/net_vcr.c:32-37` — lookahead record every playback call is checked against.

## Further reading

- Fabien Sanglard, "Quake Source Code Review":
  https://fabiensanglard.net/quakeSource/index.php — demo playback and the
  `CL_GetMessage` interposition point.
- Olivier Montanuy et al., "Unofficial Quake Specs":
  https://www.gamers.org/dEngine/quake/spec/quake-spec34/ (archived:
  https://web.archive.org/web/20251206223630/https://www.gamers.org/dEngine/quake/spec/quake-spec34/)
  — `svc_*` opcodes including the `svc_disconnect` trailer byte.
- John Carmack .plan archive: https://github.com/ESWAT/john-carmack-plan-archive
  — period notes on timedemo as the standard benchmark (browse for era context).
