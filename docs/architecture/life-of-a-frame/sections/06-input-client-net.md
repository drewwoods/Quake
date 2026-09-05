# Input, client movement, and networking

This section traces a single control input from the physical keyboard/mouse
through to bytes on the wire, and traces the reply back through delta-decoded
entity updates to the interpolated positions the renderer draws. NetQuake
supports loopback, LAN, serial, modem, IPX, and UDP transports, but it has no
client prediction. QuakeWorld later added prediction to hide WAN latency.

## Where it sits in the frame

`_Host_Frame` (`WinQuake/host.c:633-693`) drives the whole pipeline once per
frame:

1. `Sys_SendKeyEvents()` — `WinQuake/host.c:650` — pumps the OS message queue,
   which synchronously calls back into `Key_Event`.
2. `IN_Commands()` — `WinQuake/host.c:653` — lets the mouse/joystick driver
   generate button events (Windows mouse buttons are polled here, not via
   window messages).
3. `Cbuf_Execute()` — `WinQuake/host.c:656` — executes any `+forward`-style
   commands the key events queued into the command buffer.
4. `NET_Poll()` — `WinQuake/host.c:659`.
5. `CL_SendCmd()` is called from **one of two places** depending on topology:
   `WinQuake/host.c:663` (`if (sv.active) CL_SendCmd();`, before the server
   simulates — a listen server samples input before running the world), or
   `WinQuake/host.c:686` (`if (!sv.active) CL_SendCmd();`) for a pure client,
   after the skipped server-frame block and immediately before the network
   read. The source comment says incoming messages have already been read,
   but the executable order is send, then read.
6. `CL_ReadFromServer()` — `WinQuake/host.c:693` — only when
   `cls.state == ca_connected`; this both drains the socket and calls
   `CL_ParseServerMessage`, `CL_RelinkEntities`, `CL_UpdateTEnts`.

## Input: Sys_SendKeyEvents and Key_Event

On Windows, `Sys_SendKeyEvents` (`WinQuake/sys_win.c:641-655`) is just a
`PeekMessage`/`GetMessage`/`DispatchMessage` pump; the actual key translation
happens in the window procedure, which eventually calls `Key_Event(int key,
qboolean down)` (`WinQuake/keys.c:599`). `Key_Event` is the single funnel for
every physical input source — keyboard, mouse buttons (`WinQuake/in_win.c:561,
567, 659, 665`), joystick buttons (`WinQuake/in_win.c:982, 988, 1015, 1020`)
all call it with a "key number" and up/down state.

The design problem `Key_Event` solves: keybindings map a keynum to a command
string, and "button" commands (leading `+`) need matching press/release pairs
even though two different physical keys can be bound to the same logical
action (e.g. mouse2 and space both bound to `+jump`). The fix is to pass the
keynum as a text argument to the queued command, so the release handler
(`KeyUp`, see below) knows which physical key came up:

```c
// WinQuake/keys.c:664-682
	if (!down)
	{
		kb = keybindings[key];
		if (kb && kb[0] == '+')
		{
			sprintf (cmd, "-%s %i\n", kb+1, key);
			Cbuf_AddText (cmd);
		}
		if (keyshift[key] != key)
		{
			kb = keybindings[keyshift[key]];
			if (kb && kb[0] == '+')
			{
				sprintf (cmd, "-%s %i\n", kb+1, key);
				Cbuf_AddText (cmd);
			}
		}
		return;
	}
```

On key-down, the same routing happens in the other direction, again appending
the keynum as a parameter for `+` commands:

```c
// WinQuake/keys.c:696-714
	if ( (key_dest == key_menu && menubound[key])
	|| (key_dest == key_console && !consolekeys[key])
	|| (key_dest == key_game && ( !con_forcedup || !consolekeys[key] ) ) )
	{
		kb = keybindings[key];
		if (kb)
		{
			if (kb[0] == '+')
			{	// button commands add keynum as a parm
				sprintf (cmd, "%s %i\n", kb, key);
				Cbuf_AddText (cmd);
			}
			else
			{
				Cbuf_AddText (kb);
				Cbuf_AddText ("\n");
			}
		}
		return;
	}
```

Note this never touches `usercmd_t` directly — it only appends text to the
console command buffer (`Cbuf_AddText`), which `Cbuf_Execute()` runs later in
the same frame (`WinQuake/host.c:656`). This is the same mechanism used for
ordinary console commands, which is why every movement key can also be bound
to an arbitrary console command string.

## +/- button commands: kbutton_t and cl_input.c

The `+forward`/`-forward` command pair (and `+left`, `+attack`, `+jump`, …)
are registered in `CL_InitInput` (`WinQuake/cl_input.c:409-444`):

```c
// WinQuake/cl_input.c:419-420
	Cmd_AddCommand ("+forward",IN_ForwardDown);
	Cmd_AddCommand ("-forward",IN_ForwardUp);
```

Each is backed by a `kbutton_t` (`WinQuake/client.h:313-317`):

```c
// WinQuake/client.h:313-317
typedef struct
{
	int		down[2];		// key nums holding it down
	int		state;			// low bit is down state
} kbutton_t;
```

`down[2]` is the two-physical-keys-one-logical-button design mentioned above.
`KeyDown`/`KeyUp` (`WinQuake/cl_input.c:58-84, 87-115`) update it from the
keynum argument that `Key_Event` embedded in the command string:

```c
// WinQuake/cl_input.c:58-84
void KeyDown (kbutton_t *b)
{
	int		k;
	char	*c;

	c = Cmd_Argv(1);
	if (c[0])
		k = atoi(c);
	else
		k = -1;		// typed manually at the console for continuous down

	if (k == b->down[0] || k == b->down[1])
		return;		// repeating key
	
	if (!b->down[0])
		b->down[0] = k;
	else if (!b->down[1])
		b->down[1] = k;
	else
	{
		Con_Printf ("Three keys down for a button!\n");
		return;
	}
	
	if (b->state & 1)
		return;		// still down
	b->state |= 1 + 2;	// down + impulse down
}
```

`state` bit 0 is "currently down", bits 1/2 are edge-triggered "went down" /
"went up" impulses *within this frame*. `CL_KeyState` (`WinQuake/cl_input.c:
171-201`) turns that bit state into an analog fraction the movement code can
scale a speed by, which matters because a key can be pressed and released
*within* a single frame at low framerate:

```c
// WinQuake/cl_input.c:171-201
float CL_KeyState (kbutton_t *key)
{
	float		val;
	qboolean	impulsedown, impulseup, down;
	
	impulsedown = key->state & 2;
	impulseup = key->state & 4;
	down = key->state & 1;
	val = 0;
	
	if (impulsedown && !impulseup)
		if (down)
			val = 0.5;	// pressed and held this frame
		else
			val = 0;	//	I_Error ();
	if (impulseup && !impulsedown)
		if (down)
			val = 0;	//	I_Error ();
		else
			val = 0;	// released this frame
	if (!impulsedown && !impulseup)
		if (down)
			val = 1.0;	// held the entire frame
		else
			val = 0;	// up the entire frame
	if (impulsedown && impulseup)
		if (down)
			val = 0.75;	// released and re-pressed this frame
		else
			val = 0.25;	// pressed and released this frame

	key->state &= 1;		// clear impulses
```

The 0.25/0.5/0.75/1.0 scale is a crude time-fraction estimate — it doesn't
know *when within the frame* the tap happened, only whether an edge occurred,
so it approximates. This matters more on old, low, variable framerates than
on modern hardware.

## Mouse input: IN_Move / IN_MouseMove

`IN_Move` is the platform-specific entry point called once per frame from
`CL_SendCmd` (see below); the Windows implementation
(`WinQuake/in_win.c:738-746`) just fans out to the mouse and joystick
handlers:

```c
// WinQuake/in_win.c:738-746
void IN_Move (usercmd_t *cmd)
{

	if (ActiveApp && !Minimized)
	{
		IN_MouseMove (cmd);
		IN_JoyMove (cmd);
	}
}
```

`IN_MouseMove` (`WinQuake/in_win.c:581-724`) reads either DirectInput device
deltas or (in the non-DirectInput path, further down the function) raw
`GetCursorPos` deltas, applies `m_filter` smoothing and `sensitivity`, then
converts pixel deltas directly into `usercmd_t` fields or view-angle deltas —
mouse input bypasses the `kbutton_t`/`CL_KeyState` machinery entirely because
it is naturally continuous, not edge-triggered:

```c
// WinQuake/in_win.c:700-723
// add mouse X/Y movement to cmd
	if ( (in_strafe.state & 1) || (lookstrafe.value && (in_mlook.state & 1) ))
		cmd->sidemove += m_side.value * mouse_x;
	else
		cl.viewangles[YAW] -= m_yaw.value * mouse_x;

	if (in_mlook.state & 1)
		V_StopPitchDrift ();
		
	if ( (in_mlook.state & 1) && !(in_strafe.state & 1))
	{
		cl.viewangles[PITCH] += m_pitch.value * mouse_y;
		if (cl.viewangles[PITCH] > 80)
			cl.viewangles[PITCH] = 80;
		if (cl.viewangles[PITCH] < -70)
			cl.viewangles[PITCH] = -70;
	}
	else
	{
		if ((in_strafe.state & 1) && noclip_anglehack)
			cmd->upmove -= m_forward.value * mouse_y;
		else
			cmd->forwardmove -= m_forward.value * mouse_y;
	}
```

Note this function writes `cl.viewangles` directly (a client-global, not part
of `usercmd_t`) as well as fields of `cmd`. `cl.viewangles` is what
`CL_SendMove` later serializes into the outgoing packet and what the renderer
uses for the camera — the view direction is authoritative on the client and
is *told* to the server, never predicted or corrected by it (see the
NetQuake-vs-QuakeWorld discussion below).

## Client movement: CL_AdjustAngles / CL_BaseMove / CL_SendMove

`CL_SendCmd` (`WinQuake/cl_main.c:670-706`) is the orchestrator, called from
`_Host_Frame` as shown above:

```c
// WinQuake/cl_main.c:679-687
	if (cls.signon == SIGNONS)
	{
	// get basic movement from keyboard
		CL_BaseMove (&cmd);
	
	// allow mice or other external controllers to add to the move
		IN_Move (&cmd);
	
	// send the unreliable message
		CL_SendMove (&cmd);
	
	}
```

`CL_BaseMove` (`WinQuake/cl_input.c:283-323`) first calls `CL_AdjustAngles`,
then zeroes and fills a fresh `usercmd_t` from the `kbutton_t` states via
`CL_KeyState`:

```c
// WinQuake/cl_input.c:283-296
void CL_BaseMove (usercmd_t *cmd)
{	
	if (cls.signon != SIGNONS)
		return;
			
	CL_AdjustAngles ();
	
	Q_memset (cmd, 0, sizeof(*cmd));
	
	if (in_strafe.state & 1)
	{
		cmd->sidemove += cl_sidespeed.value * CL_KeyState (&in_right);
		cmd->sidemove -= cl_sidespeed.value * CL_KeyState (&in_left);
	}
```

`CL_AdjustAngles` (`WinQuake/cl_input.c:232-253`) is where keyboard-driven
turning (as opposed to mouse look) updates `cl.viewangles`, scaled by
`host_frametime` so turn rate is framerate-independent:

```c
// WinQuake/cl_input.c:232-253
void CL_AdjustAngles (void)
{
	float	speed;
	float	up, down;
	
	if (in_speed.state & 1)
		speed = host_frametime * cl_anglespeedkey.value;
	else
		speed = host_frametime;

	if (!(in_strafe.state & 1))
	{
		cl.viewangles[YAW] -= speed*cl_yawspeed.value*CL_KeyState (&in_right);
		cl.viewangles[YAW] += speed*cl_yawspeed.value*CL_KeyState (&in_left);
		cl.viewangles[YAW] = anglemod(cl.viewangles[YAW]);
	}
	if (in_klook.state & 1)
	{
		V_StopPitchDrift ();
		cl.viewangles[PITCH] -= speed*cl_pitchspeed.value * CL_KeyState (&in_forward);
		cl.viewangles[PITCH] += speed*cl_pitchspeed.value * CL_KeyState (&in_back);
	}
```

`usercmd_t` itself (`WinQuake/client.h:20-32`) is tiny by design — three
floats for intended velocity plus the view angles, nothing else:

```c
// WinQuake/client.h:20-32
typedef struct
{
	vec3_t	viewangles;

// intended velocities
	float	forwardmove;
	float	sidemove;
	float	upmove;
#ifdef QUAKE2
	byte	lightlevel;
#endif
} usercmd_t;
```

Finally `CL_SendMove` (`WinQuake/cl_input.c:332-403`) serializes the command
into a `clc_move` (`WinQuake/protocol.h:139`, `#define clc_move 3
// [usercmd_t]`) network message and fires it unreliably:

```c
// WinQuake/cl_input.c:348-372
    MSG_WriteByte (&buf, clc_move);

	MSG_WriteFloat (&buf, cl.mtime[0]);	// so server can get ping times

	for (i=0 ; i<3 ; i++)
		MSG_WriteAngle (&buf, cl.viewangles[i]);
	
    MSG_WriteShort (&buf, cmd->forwardmove);
    MSG_WriteShort (&buf, cmd->sidemove);
    MSG_WriteShort (&buf, cmd->upmove);

//
// send button bits
//
	bits = 0;
	
	if ( in_attack.state & 3 )
		bits |= 1;
	in_attack.state &= ~2;
	
	if (in_jump.state & 3)
		bits |= 2;
	in_jump.state &= ~2;
	
    MSG_WriteByte (&buf, bits);
```

Piggybacking `cl.mtime[0]` (the timestamp of the last server update this
client has processed) into every move command is the ping mechanism. The
server subtracts it from `sv.time` and stores the sample in
`client->ping_times`; no separate ping response is needed. The move goes via
`NET_SendUnreliableMessage` (`WinQuake/cl_input.c:390`) rather than the
reliable stream: a lost movement packet is harmless because the *next* frame
sends a fresh, complete `usercmd_t` a fraction of a second later — retransmitting
a stale input would be actively wrong. This is a deliberate consequence of
1996-era 28.8k/33.6k modem links, where reliable retransmission delays later
reliable data. Inputs are cheap and perishable, so they ride the lossy channel;
state that must arrive (level changes, spawn events) rides the reliable one.

## Net layer: driver abstraction, loopback, and datagram delivery

`NET_SendMessage` / `NET_GetMessage` (`WinQuake/net_main.c:540-568,
625-649`) are thin wrappers that dispatch to a driver vtable (`sfunc`) chosen
per-socket — either the loopback driver (`net_loop.c`, used for single-player
and to talk to your own listen server) or a real datagram driver (`net_dgrm.c`,
UDP/IPX):

```c
// WinQuake/net_main.c:625-649 (NET_SendMessage)
int NET_SendMessage (qsocket_t *sock, sizebuf_t *data)
{
	int		r;
	
	if (!sock)
		return -1;

	if (sock->disconnected)
	{
		Con_Printf("NET_SendMessage: disconnected socket\n");
		return -1;
	}

	SetNetTime();
	r = sfunc.QSendMessage(sock, data);
	if (r == 1 && sock->driver)
		messagesSent++;
```

`net_loop.c` implements this vtable without touching a real socket at all:
`Loop_SendMessage` (`WinQuake/net_loop.c:154-183`) copies the serialized
message into the *other* endpoint's linear `receiveMessage` buffer,
and `Loop_GetMessage` (`WinQuake/net_loop.c:127-150`) reads it back out:

```c
// WinQuake/net_loop.c:127-150
int Loop_GetMessage (qsocket_t *sock)
{
	int		ret;
	int		length;

	if (sock->receiveMessageLength == 0)
		return 0;

	ret = sock->receiveMessage[0];
	length = sock->receiveMessage[1] + (sock->receiveMessage[2] << 8);
	// alignment byte skipped here
	SZ_Clear (&net_message);
	SZ_Write (&net_message, &sock->receiveMessage[4], length);

	length = IntAlign(length + 4);
	sock->receiveMessageLength -= length;

	if (sock->receiveMessageLength)
		Q_memcpy(sock->receiveMessage, &sock->receiveMessage[length], sock->receiveMessageLength);

	if (sock->driverdata && ret == 1)
		((qsocket_t *)sock->driverdata)->canSend = true;

	return ret;
}
```

This is why single-player and listen-server-hosted LAN play use the same
message format and parser as remote play. The client and server halves in one
process use two `qsocket_t`s pointed at each other through `driverdata`, and
the client still consumes messages through `CL_ParseServerMessage`.

`net_dgrm.c` is the real driver, and it implements two delivery models over
one UDP socket per connection:

- **Reliable stream** (used for the signon sequence, `svc_print`, level
  changes, etc. — anything that must arrive and arrive in order):
  `Datagram_SendMessage` (`WinQuake/net_dgrm.c:161-198`) fragments messages
  larger than `MAX_DATAGRAM` (1024 bytes, `WinQuake/quakedef.h:102`) into
  `NETFLAG_DATA`-tagged packets carrying a monotonically increasing
  `sendSequence`, sets `canSend = false`, and won't send the next fragment
  until the peer ACKs the current one. `Datagram_GetMessage`
  (`WinQuake/net_dgrm.c:315-463`) resends the unacked packet after a 1-second
  timeout (`ReSendMessage`, `WinQuake/net_dgrm.c:241-270`), and processes
  incoming ACKs like this:

```c
// WinQuake/net_dgrm.c:395-419
		if (flags & NETFLAG_ACK)
		{
			if (sequence != (sock->sendSequence - 1))
			{
				Con_DPrintf("Stale ACK received\n");
				continue;
			}
			if (sequence == sock->ackSequence)
			{
				sock->ackSequence++;
				if (sock->ackSequence != sock->sendSequence)
					Con_DPrintf("ack sequencing error\n");
			}
			else
			{
				Con_DPrintf("Duplicate ACK received\n");
				continue;
			}
			sock->sendMessageLength -= MAX_DATAGRAM;
			if (sock->sendMessageLength > 0)
			{
				Q_memcpy(sock->sendMessage, sock->sendMessage+MAX_DATAGRAM, sock->sendMessageLength);
				sock->sendNext = true;
			}
			else
			{
```

- **Unreliable datagrams** (used for `clc_move` and `svc_update` — anything
  perishable, sent every frame): `Datagram_SendUnreliableMessage`
  (`WinQuake/net_dgrm.c:289-307`) fires and forgets, tagging the packet
  `NETFLAG_UNRELIABLE` with its own independent sequence counter
  (`unreliableSendSequence`). On the receive side, out-of-order or dropped
  unreliable packets are simply detected and counted, never retransmitted
  (`WinQuake/net_dgrm.c:370-384`, tracking `droppedDatagrams`) — because the
  next frame's snapshot supersedes it anyway.

Only one reliable message may be in flight per connection at a time (`canSend`
gates it). Signon and control messages are low-volume compared with the
independent per-frame unreliable snapshot stream, so the protocol needs no
reliable sliding window.

`MSG_Write*`/`MSG_Read*` in `common.c` are the shared serialization
primitives both `cl_input.c`/`cl_parse.c` and the server side use.
Two are protocol-defining and bandwidth-driven: `MSG_WriteCoord` packs a
world coordinate into a 16-bit fixed-point value at 1/8-unit precision, and
`MSG_WriteAngle` packs a full 0-360° angle into a single byte:

```c
// WinQuake/common.c:584-592
void MSG_WriteCoord (sizebuf_t *sb, float f)
{
	MSG_WriteShort (sb, (int)(f*8));
}

void MSG_WriteAngle (sizebuf_t *sb, float f)
{
	MSG_WriteByte (sb, ((int)f*256/360) & 255);
}
```

1/8-unit position precision and ~1.4°-angle precision are both imperceptible
in-game but cut the per-axis cost from a 32-bit float to 16 or 8 bits — with
dozens of entities updated every frame over a 28.8k modem, this quantization
was not optional polish, it was the difference between a playable and
unplayable connection.

## Server round trip: CL_ReadFromServer / CL_ParseServerMessage

`CL_ReadFromServer` (`WinQuake/cl_main.c:634-660`) drains every waiting
message this frame (there can be more than one if the client is behind),
parses each, and only then relinks entities and updates temp-entity effects:

```c
// WinQuake/cl_main.c:634-655
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

`CL_GetMessage` (`WinQuake/cl_demo.c:90`) is the actual call site — it wraps
`NET_GetMessage` and transparently interposes demo record/playback (see
below).

`CL_ParseServerMessage` (`WinQuake/cl_parse.c:720-772+`) is a byte-code
interpreter over the message: it reads one opcode byte at a time and either
dispatches to `CL_ParseUpdate` for a "fast update" (top bit set — the packed
per-entity delta path) or into a big `switch` over `svc_*` opcodes for
everything else:

```c
// WinQuake/cl_parse.c:743-758
		cmd = MSG_ReadByte ();

		if (cmd == -1)
		{
			SHOWNET("END OF MESSAGE");
			return;		// end of message
		}

	// if the high bit of the command byte is set, it is a fast update
		if (cmd & 128)
		{
			SHOWNET("fast update");
			CL_ParseUpdate (cmd&127);
			continue;
		}

		SHOWNET(svc_strings[cmd]);
	
	// other commands
		switch (cmd)
```

The `svc_*` opcodes span everything from `svc_time`, `svc_print`,
`svc_serverinfo`, `svc_setangle`, `svc_sound`, `svc_spawnbaseline` to
`svc_intermission` (full list `WinQuake/cl_parse.c:769-957`); most simply
read a fixed set of fields and store them into `cl` or trigger a side effect
(e.g. `svc_sound` calls `S_StartSound`). The interesting one for this section
is the entity update path.

### CL_ParseUpdate and the delta bitmask

`CL_ParseUpdate(int bits)` (`WinQuake/cl_parse.c:330-483`) implements the
core bandwidth optimization of the whole protocol: rather than resending
every field of every visible entity every frame, the server sends only a
bitmask of *which* fields changed, and the client fills in anything absent
from its own cached baseline. The bitmask itself can be extended past the
initial byte via `U_MOREBITS` (`WinQuake/protocol.h:25`, plus `U_ANGLE1`
etc. defined up to `U_LONGENTITY` at `WinQuake/protocol.h:35-41`):

```c
// WinQuake/cl_parse.c:346-357
	if (bits & U_MOREBITS)
	{
		i = MSG_ReadByte ();
		bits |= (i<<8);
	}

	if (bits & U_LONGENTITY)	
		num = MSG_ReadShort ();
	else
		num = MSG_ReadByte ();

	ent = CL_EntityNum (num);
```

For each of position/angle per axis, the field is either read from the wire
(bit set) or copied from the entity's `baseline` (the state sent once at
level-load via `svc_spawnbaseline`/`CL_ParseBaseline`,
`WinQuake/cl_parse.c:491+`) — most entities are stationary or move
predictably, so most bits are usually clear (baseline itself is filled in by
`CL_ParseBaseline`, `WinQuake/cl_parse.c:491-...`, dispatched from
`svc_spawnbaseline`, `WinQuake/cl_parse.c:868`):

```c
// WinQuake/cl_parse.c:442-453
// shift the known values for interpolation
	VectorCopy (ent->msg_origins[0], ent->msg_origins[1]);
	VectorCopy (ent->msg_angles[0], ent->msg_angles[1]);

	if (bits & U_ORIGIN1)
		ent->msg_origins[0][0] = MSG_ReadCoord ();
	else
		ent->msg_origins[0][0] = ent->baseline.origin[0];
	if (bits & U_ANGLE1)
		ent->msg_angles[0][0] = MSG_ReadAngle();
	else
		ent->msg_angles[0][0] = ent->baseline.angles[0];
```

Note the shift-before-read: `msg_origins[1]` (the *previous* update) is set
from the outgoing `msg_origins[0]` *before* `msg_origins[0]` is overwritten
with the new value. `msg_origins[0]`/`msg_angles[0]` are "newest", `[1]` is
"one update ago" — this two-slot history is exactly what
`CL_RelinkEntities` interpolates between (next section). `U_NOLERP` lets the
server force a hard snap (e.g. teleporters) instead of a smooth blend.

## Entity interpolation: entity_t, cl.mtime, CL_RelinkEntities

`entity_t` (`WinQuake/render.h:39-70`) is the client-side render entity;
the fields relevant here are the two-deep history buffers:

```c
// WinQuake/render.h:39-51
typedef struct entity_s
{
	qboolean				forcelink;		// model changed

	int						update_type;

	entity_state_t			baseline;		// to fill in defaults in updates

	double					msgtime;		// time of last update
	vec3_t					msg_origins[2];	// last two updates (0 is newest)	
	vec3_t					origin;
	vec3_t					msg_angles[2];	// last two updates (0 is newest)
	vec3_t					angles;	
```

`origin`/`angles` are what the renderer actually draws; `msg_origins[2]` /
`msg_angles[2]` are raw server snapshots. `CL_RelinkEntities`
(`WinQuake/cl_main.c:442-...`) usually blends between the two most recent
snapshots using a fraction computed by
`CL_LerpPoint` (`WinQuake/cl_main.c:391-408`), based on where `cl.time`
(the client's local clock, advanced every frame in `CL_ReadFromServer`) sits
between the timestamps of the last two server messages, `cl.mtime[0]` and
`cl.mtime[1]` (`double mtime[2]`, `WinQuake/client.h:196`):

```c
// WinQuake/cl_main.c:391-408
float	CL_LerpPoint (void)
{
	float	f, frac;

	f = cl.mtime[0] - cl.mtime[1];
	
	if (!f || cl_nolerp.value || cls.timedemo || sv.active)
	{
		cl.time = cl.mtime[0];
		return 1;
	}
		
	if (f > 0.1)
	{	// dropped packet, or start of demo
		cl.mtime[1] = cl.mtime[0] - 0.1;
		f = 0.1;
	}
	frac = (cl.time - cl.mtime[1]) / f;
```

`sv.active` (running a local/listen server) forces `frac = 1` — snap
straight to the newest snapshot, no interpolation needed, because the local
server ticks in lockstep with the client's own frame loop so there's no
inter-packet gap to smooth over. For a remote connection, `frac` walks from
0 to 1 across the interval between the last two updates, and each entity is
blended:

```c
// WinQuake/cl_main.c:499-523
		if (ent->forcelink)
		{	// the entity was not updated in the last message
			// so move to the final spot
			VectorCopy (ent->msg_origins[0], ent->origin);
			VectorCopy (ent->msg_angles[0], ent->angles);
		}
		else
		{	// if the delta is large, assume a teleport and don't lerp
			f = frac;
			for (j=0 ; j<3 ; j++)
			{
				delta[j] = ent->msg_origins[0][j] - ent->msg_origins[1][j];
				if (delta[j] > 100 || delta[j] < -100)
					f = 1;		// assume a teleportation, not a motion
			}

		// interpolate the origin and angles
			for (j=0 ; j<3 ; j++)
			{
				ent->origin[j] = ent->msg_origins[1][j] + f*delta[j];

				d = ent->msg_angles[0][j] - ent->msg_angles[1][j];
				if (d > 180)
					d -= 360;
				else if (d < -180)
					d += 360;
```

The >100-unit heuristic distinguishes "the entity teleported" from "the
entity is just moving fast," since blending across a teleport would draw a
visible streak through the level geometry.

## Temp entities (cl_tent.c)

Transient, non-persistent effects — bullet impacts, explosions, lightning
bolts, the grapple beam — don't get full `entity_t` slots in the delta-update
system at all; they're one-shot events. `CL_ParseTEnt`
(`WinQuake/cl_tent.c:115-...`) is invoked from `svc_temp_entity`
(`WinQuake/cl_parse.c:876`), reads a `TE_*` type byte, and immediately
spawns a particle effect, sound, or (for beams like `TE_LIGHTNING1..3`,
`WinQuake/cl_tent.c:216-227`) a short-lived `beam_t` tracked outside the
normal entity list. `CL_UpdateTEnts` (`WinQuake/cl_tent.c:325-...`), called
every frame right after `CL_RelinkEntities` (`WinQuake/cl_main.c:657`),
advances/expires those beams and dynamic lights each frame independent of
any further server messages.

## Demo recording (cl_demo.c)

`cl_demo.c` lets `CL_GetMessage` transparently substitute file playback for
`NET_GetMessage`: during `cls.demoplayback`, message bytes and view angles
are read straight from `cls.demofile` instead of the socket
(`WinQuake/cl_demo.c:90-127`), and the same `CL_ParseServerMessage` path
handles them, since a demo records the raw server message stream. Playback
reuses the normal parser and interpolation path.

## No client-side prediction: NetQuake vs. QuakeWorld

Everything above adds up to a specific architectural choice: **NetQuake does
not simulate the local player's movement client-side at all.** `CL_SendCmd`
builds a `usercmd_t` and ships it off; the client then does nothing but wait
for the server's next `svc_update`/fast-update snapshot and interpolate
between the last two received positions (`CL_RelinkEntities`,
`CL_LerpPoint` above) — including for the local player's own entity (`client_state_t`, `WinQuake/client.h:148-235`,
holds `mtime[2]` and the entity array uniformly for local and remote
players). There
is no `CL_PredictMove` in this codebase, no rewind-and-replay reconciliation,
and no local physics integration of `usercmd_t` against the world. Movement
feels immediate over loopback and low-latency LAN play. On modem and WAN links,
the gap between sending input and receiving the resulting server state is
visible because the client cannot predict through it.

That assumption breaks down over the public internet, which is exactly the
problem QuakeWorld (`QW/`, a separate codebase in this repository — not
covered here, and not modified for this doc) was built to solve. QuakeWorld
introduces genuine client-side prediction: the client immediately, locally
simulates its own `usercmd_t` against a local copy of player physics
(`QW/client/cl_pred.c`), rendering the predicted result *before* the
server's authoritative reply arrives, then reconciles/corrects when the
server's snapshot (tagged with the input sequence it was computed from) comes
back — snapping or smoothly correcting for misprediction. That is a
fundamentally more complex model (it requires replaying buffered unacked
commands against corrected server state) that NetQuake's single-player/LAN
design goal never needed. The tradeoff is real: QuakeWorld's prediction can
mask 100+ms of internet latency at the cost of occasional visible
correction "pops"; NetQuake has zero prediction complexity but becomes
visibly laggy the moment round-trip time grows, which is why it was
effectively retired for competitive internet play once QuakeWorld shipped.

## Call graph

```
_Host_Frame (host.c:633)
├─ Sys_SendKeyEvents (sys_win.c:641)
│   └─ (Win32 message loop → WindowProc → Key_Event)
│       Key_Event (keys.c:599)
│       └─ Cbuf_AddText("+forward 79\n") etc.
├─ IN_Commands (in_win.c:963)
├─ Cbuf_Execute (host.c:656)
│   └─ IN_ForwardDown/IN_ForwardUp → KeyDown/KeyUp (cl_input.c:58,87)
├─ NET_Poll (net_main.c:927)
├─ CL_SendCmd (cl_main.c:670)                  [sv.active: host.c:663; else host.c:686]
│   ├─ CL_BaseMove (cl_input.c:283)
│   │   └─ CL_AdjustAngles (cl_input.c:232)
│   │       └─ CL_KeyState (cl_input.c:171)
│   ├─ IN_Move (in_win.c:738)
│   │   ├─ IN_MouseMove (in_win.c:581)
│   │   └─ IN_JoyMove (in_win.c:1068)
│   └─ CL_SendMove (cl_input.c:332)
│       └─ NET_SendUnreliableMessage (net_main.c)
│           └─ sfunc.SendUnreliableMessage
│               ├─ Loop_SendUnreliableMessage (net_loop.c:188)   [local]
│               └─ Datagram_SendUnreliableMessage (net_dgrm.c:289)  [UDP]
├─ Host_ServerFrame (sv.active only)
└─ CL_ReadFromServer (cl_main.c:634)             [cls.state == ca_connected]
    ├─ CL_GetMessage (cl_demo.c:90)
    │   └─ NET_GetMessage (net_main.c:540)
    │       └─ sfunc.QGetMessage
    │           ├─ Loop_GetMessage (net_loop.c:127)     [local]
    │           └─ Datagram_GetMessage (net_dgrm.c:315) [UDP; ACK/resend]
    ├─ CL_ParseServerMessage (cl_parse.c:720)
    │   ├─ CL_ParseUpdate (cl_parse.c:330)        [fast-update, high bit set]
    │   ├─ svc_* switch (cl_parse.c:769-957)
    │   │   ├─ svc_temp_entity → CL_ParseTEnt (cl_tent.c:115)
    │   │   ├─ svc_spawnbaseline → CL_ParseBaseline (cl_parse.c:491)
    │   │   └─ svc_clientdata → CL_ParseClientdata (cl_parse.c:514)
    │   └─ MSG_ReadByte/Short/Coord/Angle (common.c:623-724)
    ├─ CL_RelinkEntities (cl_main.c:442)
    │   └─ CL_LerpPoint (cl_main.c:391)
    └─ CL_UpdateTEnts (cl_tent.c:325)
```

## Key data structures

- `usercmd_t` — `WinQuake/client.h:20-32` — one frame's intended movement + view angles, built by `CL_BaseMove`/`IN_Move`, sent as `clc_move`.
- `kbutton_t` — `WinQuake/client.h:313-317` — tracks up to two physical keys driving one logical `+command`, plus edge-trigger state bits.
- `entity_t` — `WinQuake/render.h:39-70` — client render entity; `msg_origins[2]`/`msg_angles[2]` hold the last two server snapshots that `CL_RelinkEntities` interpolates between.
- `client_state_t` (`cl`) — `WinQuake/client.h:148-235` — client-global state; `mtime[2]` (`WinQuake/client.h:196`) holds the timestamps of the last two server messages used by `CL_LerpPoint`.
- `qsocket_t` — `WinQuake/net.h:119-149` — per-connection state: send/receive sequence numbers, `canSend`, buffered reliable message data, and the address.
- `sizebuf_t` (`net_message`, and per-call `buf` in `CL_SendMove`) — `WinQuake/common.h` — the growable byte buffer `MSG_Write*`/`MSG_Read*` operate on.
- `beam_t` — `WinQuake/cl_tent.c` (module-local) — tracks an active lightning-bolt/grapple beam's start/end entities and expiry time, independent of the normal entity list.

## Further reading

- Fabien Sanglard, "Quake Source Code Review" — network and client architecture chapters: https://fabiensanglard.net/quakeSource/index.php
- Olivier Montanuy et al., "Unofficial Quake Specs" — protocol opcode/bit-level reference for `svc_*`/`clc_*` and the `U_*` update bitmask: https://www.gamers.org/dEngine/quake/spec/quake-spec34/
- John Carmack .plan archive (design commentary from the era, including networking discussion around the QuakeWorld rewrite) — (unverified specific entries) https://github.com/ESWAT/john-carmack-plan-archive
