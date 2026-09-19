# Sound, plus misc engine plumbing

Sound is another client-side presentation of server events. The server names a sound and its location; the client chooses a mixer channel, computes left/right volume and mixes local sample data for the audio device.

> **First pass.** Think **sound event → local sample → stereo mix → device buffer**. The server sends a sound identifier, not recorded audio. The mixer fills ahead of the playback cursor so audio can continue between frames. The console and memory allocators below support many stages; they are not extra steps after sound. Source: `WinQuake/sv_main.c:118-171`, `WinQuake/cl_parse.c:101-136`, `WinQuake/snd_dma.c:856-902`. [Next: demos →](#sec-8)

## Where it sits in the frame

`_Host_Frame` (`WinQuake/host.c:633-727`) is the top-level per-frame driver. Sound is mixed near the very end, after the screen has been redrawn:

```c
// WinQuake/host.c:705-714
// update audio
if (cls.signon == SIGNONS)
{
    S_Update (r_origin, vpn, vright, vup);
    CL_DecayLights ();
}
else
    S_Update (vec3_origin, vec3_origin, vec3_origin, vec3_origin);

CDAudio_Update();
```

`S_Update` is called with the render view origin and axes (`r_origin`, `vpn`, `vright`, `vup`) when `cls.signon == SIGNONS`; otherwise with zeros, so mixing still fills the device buffer during load screens. `CDAudio_Update()` after it is not the mixer: it is a CD-ROM transport (`WinQuake/cd_win.c:398-417`; other ports in `cd_*.c`) and does not write the DMA buffer. On Windows it only pauses or resumes on `bgmvolume`. The sound box on the [frame map](#pipe) is this whole `host_speeds` bucket (mix + light decay + CD); integer milliseconds truncate a sub-millisecond mix to zero. `Cbuf_Execute` (`WinQuake/host.c:657`) runs once per accepted frame, before networking and simulation. `Host_GetConsoleCommands` (`WinQuake/host.c:672`) only queues stdin; those lines run on the next frame's `Cbuf_Execute`.

## Sound: S_Update and spatialization

`S_Update` (`WinQuake/snd_dma.c:721-808`) is `_Host_Frame`'s mixer entry. It stores the listener pose, refreshes the four ambient channels, re-spatializes every active dynamic/static channel, and calls `S_Update_` to paint into the DMA buffer. The renderer can also call `S_Update_` via `S_ExtraUpdate` during a slow draw, without re-spatializing.

```c
// WinQuake/snd_dma.c:721-748
void S_Update(vec3_t origin, vec3_t forward, vec3_t right, vec3_t up)
{
	int			i, j;
	int			total;
	channel_t	*ch;
	channel_t	*combine;

	if (!sound_started || (snd_blocked > 0))
		return;

	VectorCopy(origin, listener_origin);
	VectorCopy(forward, listener_forward);
	VectorCopy(right, listener_right);
	VectorCopy(up, listener_up);
	
// update general area ambient sound sources
	S_UpdateAmbientSounds ();

	combine = NULL;

// update spatialization for static and dynamic sounds	
	ch = channels+NUM_AMBIENTS;
	for (i=NUM_AMBIENTS ; i<total_channels; i++, ch++)
	{
		if (!ch->sfx)
			continue;
		SND_Spatialize(ch);         // respatialize channel
```

Channels are a flat array `channel_t channels[MAX_CHANNELS]` (`WinQuake/snd_dma.c:39`, `MAX_CHANNELS` = 128, `WinQuake/sound.h:130`). The running mixer uses three index ranges:

- `0 .. NUM_AMBIENTS-1` — four leaf ambients (water/sky/slime/lava, `WinQuake/bspfile.h:204-209`), written by `S_UpdateAmbientSounds` (`WinQuake/snd_dma.c:664`)
- `NUM_AMBIENTS .. NUM_AMBIENTS+MAX_DYNAMIC_CHANNELS-1` — eight dynamic voices; the only range `SND_PickChannel` walks (`WinQuake/snd_dma.c:363`)
- `NUM_AMBIENTS+MAX_DYNAMIC_CHANNELS .. total_channels` — static loops from `S_StaticSound` (`WinQuake/snd_dma.c:620`)

`NUM_AMBIENTS` is 4, `MAX_DYNAMIC_CHANNELS` is 8 (`WinQuake/sound.h:131`). Those eight dynamic slots are shared by every entity; they are not one mixer voice per `entnum/entchannel`. `sound.h:135-137` comments the regions in a different order (dynamic, then ambient, then static). `S_StopSound` (`WinQuake/snd_dma.c:519-532`) follows the comment: it walks `i = 0 .. MAX_DYNAMIC_CHANNELS-1` (slots 0–7). That can clear an ambient and never sees dynamic slots 8–11. `SND_PickChannel` uses the runtime map. Static origins never move after spawn. `S_Update` at `snd_dma.c:751-784` *combines* static channels that share an `sfx` into one volume sum ("so we don't mix five torches every frame"). Combined loops keep the selected channel's playback phase.

`SND_Spatialize` (`WinQuake/snd_dma.c:398-444`) computes per-channel left/right volume from 3D geometry:

```c
// WinQuake/snd_dma.c:398-444
void SND_Spatialize(channel_t *ch)
{
    vec_t dot;
    vec_t ldist, rdist, dist;
    vec_t lscale, rscale, scale;
    vec3_t source_vec;
	sfx_t *snd;

// anything coming from the view entity will allways be full volume
	if (ch->entnum == cl.viewentity)
	{
		ch->leftvol = ch->master_vol;
		ch->rightvol = ch->master_vol;
		return;
	}

// calculate stereo seperation and distance attenuation

	snd = ch->sfx;
	VectorSubtract(ch->origin, listener_origin, source_vec);
	
	dist = VectorNormalize(source_vec) * ch->dist_mult;
	
	dot = DotProduct(listener_right, source_vec);

	if (shm->channels == 1)
	{
		rscale = 1.0;
		lscale = 1.0;
	}
	else
	{
		rscale = 1.0 + dot;
		lscale = 1.0 - dot;
	}

// add in distance effect
	scale = (1.0 - dist) * rscale;
	ch->rightvol = (int) (ch->master_vol * scale);
	if (ch->rightvol < 0)
		ch->rightvol = 0;

	scale = (1.0 - dist) * lscale;
	ch->leftvol = (int) (ch->master_vol * scale);
	if (ch->leftvol < 0)
		ch->leftvol = 0;
}
```

This is the whole panning model: a dot of the source vector against `listener_right` is a `[-1,1]` pan, and linear falloff uses `dist_mult = attenuation / sound_nominal_clip_dist` (clip 1000, `WinQuake/snd_dma.c:54,478`). Volume is zero once `dist >= 1`. No HRTF. View-entity sounds (`cl.viewentity`: weapon fire, pain) skip both pan and distance and play at `master_vol` on both ears, so a gunshot at the listener origin cannot collapse to one side.

::: diagram spatialize

## Channels and the paint buffer mixer (snd_mix.c)

Once every channel's `leftvol`/`rightvol` are current, `S_Update_` (`WinQuake/snd_dma.c:856-902`) mixes `_snd_mixahead` seconds ahead of the DMA play cursor (default 0.1, clamped to the buffer, `WinQuake/snd_dma.c:82,875-878`), restores/resumes the Windows DirectSound buffer if needed, and calls `S_PaintChannels` (`WinQuake/snd_mix.c:261-332`):

```c
// WinQuake/snd_mix.c:269-291
	while (paintedtime < endtime)
	{
	// if paintbuffer is smaller than DMA buffer
		end = endtime;
		if (endtime - paintedtime > PAINTBUFFER_SIZE)
			end = paintedtime + PAINTBUFFER_SIZE;

	// clear the paint buffer
		Q_memset(paintbuffer, 0, (end - paintedtime) * sizeof(portable_samplepair_t));

	// paint in the channels.
		ch = channels;
		for (i=0; i<total_channels ; i++, ch++)
		{
			if (!ch->sfx)
				continue;
			if (!ch->leftvol && !ch->rightvol)
				continue;
			sc = S_LoadSound (ch->sfx);
			if (!sc)
				continue;

			ltime = paintedtime;
```

`paintbuffer` is a fixed global array of `portable_samplepair_t` (int left/right accumulators, `WinQuake/snd_mix.c:31`), `PAINTBUFFER_SIZE` = 512 samples — never the full DMA buffer, which is why the outer `while` chunks the work. `SND_PaintChannelFrom8`/`SND_PaintChannelFrom16` (`WinQuake/snd_mix.c:346-370`, `375-397`) add into `paintbuffer[i].left/right`. The 8-bit path uses a scale table (`SND_InitScaletable`, `WinQuake/snd_mix.c:334-341`): 32 volume buckets × 256 signed sample values, a lookup instead of a multiply. If the hunk is under 8 MB, `loadas8bit` is forced (`WinQuake/snd_dma.c:196-200`); see [memory changed what the player received](design:memory-changed-what-the-player-received). Mixing stays in a wide accumulator so many overlapping voices can sum; clamp and format conversion happen once at the edge (`S_TransferPaintBuffer`, `WinQuake/snd_mix.c:139`).

Sounds loop by rewriting `ch->pos`/`ch->end` from `sfxcache_t.loopstart` (`WinQuake/snd_mix.c:310-323`). If `loopstart < 0` when the cursor hits `ch->end`, the channel is cleared (`ch->sfx = NULL`) and drops out of the mix.

The DMA buffer is not on the hunk except `-simsound` fakedma (`WinQuake/snd_dma.c:215-227`). `SNDDMA_Init` (`WinQuake/snd_win.c:557`, `WinQuake/snd_linux.c:37`) owns a looping device buffer: DirectSound `pDSBuf` or waveOut on Windows (`WinQuake/snd_win.c:65,317,406,477-540`), OSS `mmap` on Linux (`WinQuake/snd_linux.c:132`). `shm` (`WinQuake/snd_dma.c:47`) is the engine's view; `S_TransferPaintBuffer` writes it. The device advances the play cursor between frames. `SNDDMA_Submit` is empty for DirectSound and OSS mmap; the waveOut path submits blocks (`WinQuake/snd_win.c:667-715`, `WinQuake/snd_linux.c:266-268`). `S_ExtraUpdate` (`WinQuake/snd_dma.c:844-853`) calls `S_Update_` from the renderer (`WinQuake/r_main.c:937`) so a slow draw still fills ahead of that cursor.

> **.plan.** “limit sound buffers to 4k, add extra mix points and mix full buffer” — [Carmack, 12 Jun 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960612.txt). The fixed paint buffer and ahead-of-DMA fill are the shape of a live buffer-management problem on 1996 sound hardware, not abstract audio middleware.

## How sound events reach the client: svc_sound

The server never streams PCM — it only ever tells clients *what* to play. `SV_StartSound` (`WinQuake/sv_main.c:118-171`) packs an `svc_sound` message into the shared unreliable `sv.datagram`:

```c
// WinQuake/sv_main.c:150-171
	ent = NUM_FOR_EDICT(entity);

	channel = (ent<<3) | channel;

	field_mask = 0;
	if (volume != DEFAULT_SOUND_PACKET_VOLUME)
		field_mask |= SND_VOLUME;
	if (attenuation != DEFAULT_SOUND_PACKET_ATTENUATION)
		field_mask |= SND_ATTENUATION;

// directed messages go only to the entity the are targeted on
	MSG_WriteByte (&sv.datagram, svc_sound);
	MSG_WriteByte (&sv.datagram, field_mask);
	if (field_mask & SND_VOLUME)
		MSG_WriteByte (&sv.datagram, volume);
	if (field_mask & SND_ATTENUATION)
		MSG_WriteByte (&sv.datagram, attenuation*64);
	MSG_WriteShort (&sv.datagram, channel);
	MSG_WriteByte (&sv.datagram, sound_num);
	for (i=0 ; i<3 ; i++)
		MSG_WriteCoord (&sv.datagram, entity->v.origin[i]+0.5*(entity->v.mins[i]+entity->v.maxs[i]));
```

The entity number and the 0-7 channel slot are packed into a single short (`(ent<<3) | channel`, mirrored by the unpack `ent = channel >> 3; channel &= 7;` on the client), and volume/attenuation are only written at all if they differ from the server's compiled-in defaults (`field_mask`), keeping the common case down to a handful of bytes. `sound_num` is an index into the level's precached sound list (`sv.sound_precache`, looked up by linear scan at `sv_main.c:139-142`) rather than a filename, so the wire format never carries a string. Note the guard `if (sv.datagram.cursize > MAX_DATAGRAM-16) return;` (`sv_main.c:135-136`) — under packet pressure the server silently drops sound events rather than growing the datagram or blocking; a missed footstep sound is an acceptable loss, a dropped player-state update is not.

On the client, `CL_ParseServerMessage`'s dispatch table hits `case svc_sound: CL_ParseStartSoundPacket();` (`WinQuake/cl_parse.c:830-832`), and `CL_ParseStartSoundPacket` (`WinQuake/cl_parse.c:101-136`) does the mirror-image unpack and calls straight into `S_StartSound`:

```c
// WinQuake/cl_parse.c:123-136
	channel = MSG_ReadShort ();
	sound_num = MSG_ReadByte ();

	ent = channel >> 3;
	channel &= 7;

	if (ent > MAX_EDICTS)
		Host_Error ("CL_ParseStartSoundPacket: ent = %i", ent);
	
	for (i=0 ; i<3 ; i++)
		pos[i] = MSG_ReadCoord ();
 
    S_StartSound (ent, channel, cl.sound_precache[sound_num], pos, volume/255.0, attenuation);
}
```

`S_StartSound` (`WinQuake/snd_dma.c:451`) calls `SND_PickChannel` for that `(entnum, entchannel)` pair. The server comment at `sv_main.c:107-111` is the rule: each entity has eight logical sources (voice, weapon, feet, …); channel 0 never overrides, 1–7 replace the same entity/channel pair. The eight dynamic mixer slots are still shared. With no override match, `SND_PickChannel` replaces the slot with the least remaining life, except it will not replace a `cl.viewentity` sound with a non-viewentity one — then it returns NULL and `S_StartSound` drops the event (`WinQuake/snd_dma.c:365-385,471-473`). It spatializes immediately so `S_ExtraUpdate` can mix the voice before the next `S_Update` (`snd_dma.c:482`). If both volumes are 0, it returns after clearing the stolen slot.

Looping map props use a different message: `svc_spawnstaticsound` → `CL_ParseStaticSound` → `S_StaticSound` (`WinQuake/cl_parse.c:697-709`, `WinQuake/snd_dma.c:620`). Those take static slots and must have `loopstart >= 0` (`WinQuake/snd_dma.c:641-644`). Static `dist_mult` uses `attenuation/64` because the signon byte is already `atten*64` (`WinQuake/pr_cmds.c:539`, `WinQuake/snd_dma.c:650`). If `total_channels == MAX_CHANNELS`, the static is printed and dropped (`WinQuake/snd_dma.c:628-631`).

## Brief: Sbar_Draw (status bar)

`Sbar_Draw` (`WinQuake/sbar.c:926-1044`) is called from `SCR_UpdateScreen` in both renderers (`WinQuake/screen.c:901/909/931`, `WinQuake/gl_screen.c:885/893/914`) once per drawn frame. It's a straightforward immediate-mode HUD painter: health, armor, ammo, weapon icons, and the frags/scoreboard overlay, blitted via `Sbar_DrawPic`/`Sbar_DrawNum` (`sbar.c:260`, `sbar.c:350`) from cached `qpic_t`s. Two details worth noting: it bails out early if the console is fullscreen (`if (scr_con_current == vid.height) return;`, `sbar.c:928`) or if it's already been redrawn for every visible page this frame (`sb_updates >= vid.numpages`, `sbar.c:931`) — `sb_updates`/`Sbar_Changed()` form a simple dirty-flag scheme so the status bar isn't recomposited when nothing in it changed, which mattered on page-flipped/paletted software rendering where blitting the sbar region was not free.

## Brief: the console

The console keeps its scrollback in a single flat ring-style char buffer, `con_text`, sized `CON_TEXTSIZE` = 16384 bytes (`WinQuake/console.c:35`), allocated once off the hunk at startup: `con_text = Hunk_AllocName (CON_TEXTSIZE, "context");` (`WinQuake/console.c:229`). `Con_Printf` (`WinQuake/console.c:377`) is the sink every subsystem funnels diagnostic and gameplay text through (`Con_Printf: %s not precacheed`, `Unknown command`, etc., seen throughout this doc), and `Con_DrawConsole` (`WinQuake/console.c:580`) paints the visible slice of that buffer plus the input line when the console is pulled down. Resizing the video mode reflows the buffer's line width and re-wraps existing text in place (`Con_CheckResize`, `WinQuake/console.c:153-204`) rather than dropping scrollback — a small but deliberate UX choice given how often players resized/changed video modes mid-session on 90s hardware.

## Brief: Cbuf/Cmd/Cvar plumbing

Every typed command, config-file `exec`, alias expansion, and `+`/`-` command-line argument funnels through one text pipeline. `Cbuf_AddText` (`WinQuake/cmd.c:86-99`) appends raw text to a single global `sizebuf_t cmd_text` (8192 bytes, allocated in `Cbuf_Init`, `cmd.c:73-76`); `Cbuf_InsertText` (`cmd.c:111-136`) instead splices text at the *front* of the buffer (used by `exec`/alias expansion so a config file's commands run before whatever was already queued after it). Once per accepted frame, `Cbuf_Execute` (`WinQuake/host.c:657`, `WinQuake/cmd.c:143-193`) pulls lines up to the next `\n` or unquoted `;` and hands each to `Cmd_ExecuteString`. That is the only execute in the frame. `Host_GetConsoleCommands` (`WinQuake/host.c:532`) later `Cbuf_AddText`s stdin; those lines wait until the next frame. `wait` (`WinQuake/cmd.c:53-56,186-190`) stops the drain with text still queued.

```c
// WinQuake/cmd.c:614-650
void	Cmd_ExecuteString (char *text, cmd_source_t src)
{	
	cmd_function_t	*cmd;
	cmdalias_t		*a;

	cmd_source = src;
	Cmd_TokenizeString (text);
			
// execute the command line
	if (!Cmd_Argc())
		return;		// no tokens

// check functions
	for (cmd=cmd_functions ; cmd ; cmd=cmd->next)
	{
		if (!Q_strcasecmp (cmd_argv[0],cmd->name))
		{
			cmd->function ();
			return;
		}
	}

// check alias
	for (a=cmd_alias ; a ; a=a->next)
	{
		if (!Q_strcasecmp (cmd_argv[0], a->name))
		{
			Cbuf_InsertText (a->value);
			return;
		}
	}
	
// check cvars
	if (!Cvar_Command ())
		Con_Printf ("Unknown command \"%s\"\n", Cmd_Argv(0));
	
}
```

The lookup order is fixed and significant: registered engine commands (a linked list, `cmd_functions`) win first, then user aliases, and only then cvars — so a command can never be shadowed by a same-named cvar, but a cvar *can* be shadowed by a command (`Cvar_RegisterVariable` refuses to register a cvar whose name collides with an existing command, `WinQuake/cvar.c:163-167`). `Cvar_Command` (`WinQuake/cvar.c:187-205`) is what makes typing a bare cvar name print its value and typing `name value` set it — it's just one more fallback tried by `Cmd_ExecuteString`, not a separate parser. `Cvar_Set` (`cvar.c:104-128`) always re-`Z_Malloc`s the string storage (freeing the old one), so cvar values live on the Zone heap, not the hunk — they're small, and they can be freed/reallocated at arbitrary times, which the hunk's stack-discipline allocator cannot do (see below).

## Brief: Hunk/Zone/Cache allocators (zone.c)

Quake takes one large allocation from the OS at startup and layers three allocators over it, each matched to a different lifetime: the engine gets explicit control over when memory is reclaimed, plus an asset cache it can evict from under pressure.

- **Zone** (`Z_Malloc`, `WinQuake/zone.c:142`) is a rover-based first-fit free-list allocator over a fixed-size arena (`DYNAMIC_SIZE` = 0xc000, `zone.c:24`) with block headers carrying a size/tag/id and a trash-detection sentinel (`ZONEID`, `zone.c:26`) checked by `Z_CheckHeap` (`zone.c:247-262`). It's for small, short-lived, arbitrarily-freed allocations — strings, cvar values — the doc comment says as much: "The zone calls are pretty much only used for small strings and structures, all big things are allocated on the hunk" (`zone.c:59-60`).
- **Hunk** (`Hunk_AllocName`, `WinQuake/zone.c:399-427`) is a two-ended bump/stack allocator over one huge arena (`hunk_base`/`hunk_size`) — permanent, load-time data (server/client game state, the current level's BSP) grows up from `hunk_low_used`, and short-lived per-frame/per-scope temp allocations grow down from the top via `hunk_high_used` (`Hunk_HighMark`/`Hunk_FreeToHighMark`, `zone.c:452-474`). There is no per-block free; you only ever roll the mark back to a previous low/high watermark, which avoids holes between live hunk blocks (rollback also zeroes the released bytes) — the tradeoff is that anything on the hunk must be freed in strict LIFO order relative to what was allocated after it.
- **Cache** (`Cache_Alloc`, `WinQuake/zone.c:871-903`) sits *inside* the hunk's free middle region (between the low and high marks) and is the one allocator in the trio that's allowed to evict its own contents on demand. This is the piece that makes a fixed-size hunk workable at all on a machine with a few dozen megabytes of RAM: it lets the engine hold onto expensive-to-regenerate resources (decompressed alias models, decoded sound effects) as long as there's room, and reclaim them transparently the moment the hunk needs to grow.

::: diagram memory

### Reading the allocator state

The strip models **block extents**, not returned pointers. `Hunk_AllocName`
adds `sizeof(hunk_t)` after rounding the payload to 16 bytes; `Cache_Alloc`
rounds payload plus `sizeof(cache_system_t)` to 16 bytes. Both return the address
past their header (`WinQuake/zone.c:399-427`, `WinQuake/zone.c:871-903`).
The sandbox uses already-sized abstract blocks; its units do not imply a C ABI
or real asset footprint.

**Zone is nested inside the low hunk.** `Memory_Init` allocates the arena with
`Hunk_AllocName(zonesize, "zone")`, then initializes its free list
(`WinQuake/zone.c:913-935`). The default is 48 KiB; `-zone` overrides it.
`Z_TagMalloc` includes a header and four-byte sentinel, aligns to eight bytes,
and splits only when the remainder exceeds `MINFRAGMENT` (64 bytes).
`Z_Free` merges adjacent free blocks and repairs the rover
(`WinQuake/zone.c:99-137`, `WinQuake/zone.c:156-220`). Freeing a cvar string
returns space to Zone, not to the Cache middle. Zone never relocates live
strings or automatically evicts them; `Z_Malloc` fails fatally if no block fits.
The sandbox holds Zone's contents fixed to isolate the competing hunk/Cache lifetimes.

**Address order and recency are different lists.** `Cache_FreeLow` visits the
lowest-address block; `Cache_FreeHigh` visits the highest. Neither chooses an
LRU victim. `Cache_Move` allocates a replacement while the old block still
exists, using `Cache_TryAlloc(size, true)` to skip the bottom gap. It copies
the payload, unlinks the old block and updates the same `cache_user_t.data`.
The replacement enters the MRU end, even though relocation is not an asset
access. Failure evicts that block; it does not evict some other LRU entry to
make relocation succeed (`WinQuake/zone.c:575-750`). A recent hit therefore
protects an asset only against ordinary LRU allocation pressure, not hunk growth.

**Free total is not the largest gap.** Step 6 has 32 free units split around A;
C needs 32 contiguous units. `Cache_Alloc` removes the LRU entry and retries.
`Cache_Compact` is empty (`WinQuake/zone.c:799-801`): this is not a general
compacting heap. A raw payload pointer retained across an allocating call can
become stale; callers reacquire through the handle. `Cache_Free` clears it,
`Cache_Check` returns NULL on a miss, and `S_LoadSound` reloads sound data
(`WinQuake/zone.c:826-863`, `WinQuake/snd_mem.c:108-139`).

**A level reset is not a Cache flush.** Startup records `host_hunklevel` after
initialization (`WinQuake/host.c:915-916`). `Host_ClearMemory` flushes the software
renderer surface cache, marks model records unreferenced through `Mod_ClearAll`,
and rewinds the low hunk (`WinQuake/host.c:477-488`, `WinQuake/model.c:167-180`).
The `zone.c` model/sound Cache can survive until subsequent loading displaces
it. `D_FlushCaches` concerns lit texture surfaces in the independent
`d_surf.c` allocator, not decoded sounds or alias-model payloads.

**High temp storage is a single active scratch allocation.** A new
`Hunk_TempAlloc` releases the previous temp; `Hunk_HighMark` also releases it
before returning the persistent high usage. Rolling back either hunk end
zeroes the released range, so freeing is proportional to released bytes,
not merely a pointer subtraction (`WinQuake/zone.c:444-548`). Hunk growth
first checks low/high capacity: low exhaustion is fatal; high allocation
returns NULL. Cache eviction cannot rescue overlapping low/high allocations.

`Cache_Alloc` walks a doubly linked list of `cache_system_t` blocks threaded through the hunk's middle, and also keeps a second, orthogonal doubly linked list — `lru_prev`/`lru_next` — purely for recency:

```c
// WinQuake/zone.c:871-903
void *Cache_Alloc (cache_user_t *c, int size, char *name)
{
	cache_system_t	*cs;

	if (c->data)
		Sys_Error ("Cache_Alloc: allready allocated");
	
	if (size <= 0)
		Sys_Error ("Cache_Alloc: size %i", size);

	size = (size + sizeof(cache_system_t) + 15) & ~15;

// find memory for it	
	while (1)
	{
		cs = Cache_TryAlloc (size, false);
		if (cs)
		{
			strncpy (cs->name, name, sizeof(cs->name)-1);
			c->data = (void *)(cs+1);
			cs->user = c;
			break;
		}
	
	// free the least recently used cahedat
		if (cache_head.lru_prev == &cache_head)
			Sys_Error ("Cache_Alloc: out of memory");
													// not enough memory at all
		Cache_Free ( cache_head.lru_prev->user );
	} 
	
	return Cache_Check (c);
}
```

When `Cache_TryAlloc` (`zone.c:680-750`) can't find a big-enough free gap between existing cache blocks (searched bottom-up, `zone.c:702-731`), `Cache_Alloc` frees the block at `cache_head.lru_prev` — the least-recently-touched entry — and retries; a textbook LRU eviction loop. Every successful lookup moves its block to the front of the LRU list: `Cache_Check` (`zone.c:849-863`) runs both after a fresh alloc and on every cache hit, unconditionally re-linking via `Cache_UnlinkLRU`/`Cache_MakeLRU` (`zone.c:858-860`) — merely *reading* a cached asset protects it from the next eviction pass. When the hunk's low or high mark needs to grow past where cached data sits, `Cache_FreeLow` (`zone.c:606-619`) / `Cache_FreeHigh` (`zone.c:628-648`) relocate the block out of the way (`Cache_Move`, `zone.c:575-597`) or, if there's nowhere to move it, evict it outright — eviction is forced by hunk growth pressure, not just by running out of cache space.

This is exactly the pattern used for alias-model data: `Mod_LoadAliasModel` builds the model into scratch hunk space, then copies the finished, relocatable blob into the cache (`Cache_Alloc (&mod->cache, total, loadname);`, `WinQuake/model.c:1654`, mirrored in `WinQuake/gl_model.c:1640`) and frees the scratch hunk space back (`Hunk_FreeToLowMark`, `model.c:1659`). Every later access goes through `Mod_Extradata` (`WinQuake/model.c:64-77`), which calls `Cache_Check` first and, only on a miss (the model got evicted under memory pressure), reloads it from disk via `Mod_LoadModel`:

```c
// WinQuake/model.c:64-75
void *Mod_Extradata (model_t *mod)
{
	void	*r;
	
	r = Cache_Check (&mod->cache);
	if (r)
		return r;

	Mod_LoadModel (mod, true);
	
	if (!mod->cache.data)
		Sys_Error ("Mod_Extradata: caching failed");
```

Precached sound effects go through the identical pattern via `snd_mem.c` (`Cache_Alloc ( &s->cache, len + sizeof(sfxcache_t), s->name);`, `WinQuake/snd_mem.c:139`). `S_LoadSound` hits `Cache_Check (&s->cache)` first (`WinQuake/snd_mem.c:108-110`) on every mix of that sfx, including from `S_PaintChannels`.

Worth being precise that the *software renderer's texture surface cache* — the lightmapped, mip-scaled wall/floor textures rasterized by `R_DrawSurface` in `WinQuake/r_surf.c:248-331` and fetched via `D_CacheSurface` — is **not** built on `zone.c`'s `Cache_Alloc`. It's a separate, purpose-built allocator in `WinQuake/d_surf.c`: a fixed-size ring buffer (`sc_base`/`sc_size`/`sc_rover`, `d_surf.c:29-30`) of `surfcache_t` blocks (`WinQuake/d_local.h:37-49`) sized at startup by `D_SurfaceCacheForRes` (`d_surf.c:35-53`, larger at higher resolutions since more distinct texture/lightmap combinations are visible per frame). `D_SCAlloc` (`d_surf.c:130-209`) evicts by walking forward from a rover pointer and coalescing/overwriting whatever it finds in its way — a FIFO/wrap eviction, not a true LRU — nulling each victim's owner pointer (`*sc_rover->owner = NULL`) so the next lookup treats it as a cache miss and regenerates the blit. The two systems are architectural siblings — both trade a fixed memory budget for on-demand regeneration — but separate implementations: `zone.c`'s Cache holds whole assets (models, sounds) inside the shared hunk, while `d_surf.c`'s surface cache is a renderer-private heap tuned for the volume and churn of on-screen texture surfaces every frame.

## Brief: Host_Error and the setjmp/longjmp recovery path

C has no exceptions, and Quake needs a way to unwind an arbitrary number of call frames — out of the middle of BSP traversal, physics, or a QuakeC opcode handler — back to the top of the frame loop when something recoverable-but-serious goes wrong (a corrupt server message, a QuakeC runtime fault, a missing model). The mechanism is `setjmp`/`longjmp` with one global jump buffer:

```c
// WinQuake/host.c:52
jmp_buf 	host_abortserver;
```

`_Host_Frame` establishes the recovery point at the very top of every single frame:

```c
// WinQuake/host.c:633-642
void _Host_Frame (float time)
{
	static double		time1 = 0;
	static double		time2 = 0;
	static double		time3 = 0;
	int			pass1, pass2, pass3;

	if (setjmp (host_abortserver) )
		return;			// something bad happened, or the server disconnected

// keep the random time dependent
	rand ();
```

`Host_Error` (`WinQuake/host.c:121-149`) is the landing pad every subsystem calls when it hits a non-fatal-to-the-process-but-fatal-to-this-game error. It re-entrancy-guards itself (`static qboolean inerror`, escalating to a hard `Sys_Error` if `Host_Error` is somehow called while already unwinding, `host.c:127-128`), shuts the local server down if one is running (`Host_ShutdownServer`, `host.c:138-139`), disconnects the client (`CL_Disconnect`, `host.c:144`), and then calls `longjmp (host_abortserver, 1)` (`host.c:149`) — controlled unwind straight back to the `setjmp` at the top of `_Host_Frame`, skipping the rest of whatever frame-processing code was on the stack, no matter how deep. Dedicated servers opt out of recovery (`if (cls.state == ca_dedicated) Sys_Error (...)`, `host.c:141-142`): there is no menu to return to, so the process exits. `Sys_Error` (`WinQuake/sys_win.c:346-423`) is the non-recoverable path — print, `Host_Shutdown`, `exit(1)` — used for allocator failure, recursive `Host_Error`, and dedicated `Host_Error`/`Host_EndGame`. It does not `longjmp`.

The alternative — plumbing an error return code through every function on the call path from QuakeC opcode dispatch up through `Host_Frame` — would have meant touching essentially the entire codebase and manually unwinding partially-initialized state at every level. `setjmp`/`longjmp` gets the same "abandon this frame, get back to a known-good top-level loop" behavior in two lines, at the cost of not running any C++-style destructors/cleanup along the way — acceptable here because the state being abandoned (partially loaded level, partially processed network packet) is precisely the state `Host_ShutdownServer`/`CL_Disconnect` are about to reset wholesale anyway.

## Call graph

```
_Host_Frame (host.c:633)
  setjmp(host_abortserver) (host.c:640)         <- Host_Error/Host_EndGame longjmp lands here
  Cbuf_Execute (cmd.c:143)                       <- once/frame command dispatch
    Cmd_ExecuteString (cmd.c:614)
      Cmd_Argv[0] match -> cmd_functions list
      else -> cmd_alias list -> Cbuf_InsertText (cmd.c:111)
      else -> Cvar_Command (cvar.c:187) -> Cvar_Set (cvar.c:104)
  Host_GetConsoleCommands (host.c:532)           <- stdin into cmd_text; runs next frame
  CL_ReadFromServer (cls.state == ca_connected)
    CL_ParseServerMessage
      case svc_sound (cl_parse.c:830)
        CL_ParseStartSoundPacket (cl_parse.c:101)
          S_StartSound (snd_dma.c:451)
            SND_PickChannel (snd_dma.c:354)      <- NULL: drop
            SND_Spatialize (snd_dma.c:398)
      case svc_spawnstaticsound (cl_parse.c:924)
        CL_ParseStaticSound (cl_parse.c:697)
          S_StaticSound (snd_dma.c:620)          <- drop if MAX_CHANNELS
  SCR_UpdateScreen (screen.c / gl_screen.c)
    Sbar_Draw (sbar.c:926)
    Con_DrawConsole (console.c:580)
    S_ExtraUpdate (snd_dma.c:844)                <- from r_main.c during draw
  S_Update (snd_dma.c:721)                       <- host.c:708/712
    S_UpdateAmbientSounds (snd_dma.c:664)
    SND_Spatialize (snd_dma.c:398)  [per active channel]
    S_Update_ (snd_dma.c:856)
      GetSoundtime (snd_dma.c:810)
      S_PaintChannels (snd_mix.c:261)
        SND_PaintChannelFrom8 / From16 (snd_mix.c:346 / 375)
        S_TransferPaintBuffer (snd_mix.c:139)
      SNDDMA_Submit
  CDAudio_Update (cd_win.c:398)                  <- CD transport, not DMA mix

SV_StartSound (sv_main.c:118)                    <- called from game/QuakeC side on the server
  MSG_WriteByte(svc_sound) -> sv.datagram
S_StopSound (snd_dma.c:519)                      <- walks slots 0–7, not 4–11

Host_Error (host.c:121)                          <- called from anywhere on error
  Host_ShutdownServer / CL_Disconnect
  longjmp(host_abortserver, 1)  ------------------> back to _Host_Frame's setjmp
Sys_Error (sys_win.c:346)                        <- process exit; no longjmp

Cache_Alloc (zone.c:871)                         <- called from Mod_LoadAliasModel, snd_mem.c S_LoadSound
  Cache_TryAlloc (zone.c:680)
  Cache_Free(cache_head.lru_prev->user) on failure  <- LRU eviction loop
Mod_Extradata (model.c:64) -> Cache_Check (zone.c:849) -> Mod_LoadModel on miss
```

## Key data structures

- `channel_t` — `WinQuake/sound.h:67-80` — one mixer voice: sfx pointer, computed left/right volume, playback position/loop end, owning entity/channel, world origin, distance multiplier, master volume.
- `channels[MAX_CHANNELS]` — `WinQuake/snd_dma.c:39` — the flat 128-slot channel array: ambient 0–3, dynamic 4–11, static from 12 (`WinQuake/snd_dma.c:363,620,664`; header comment at `WinQuake/sound.h:135-137` lists a different order).
- `dma_t` / `shm` — `WinQuake/sound.h:52-64`, `WinQuake/snd_dma.c:47` — engine view of the platform-owned looping playback buffer.
- `portable_samplepair_t paintbuffer[PAINTBUFFER_SIZE]` — `WinQuake/snd_mix.c:30-31` — 512-sample wide (unclamped) stereo accumulation buffer the mixer paints into before format conversion.
- `sfxcache_t` — `WinQuake/sound.h:42-50` — decoded PCM sample data (length, loop point, rate, width) for one sound effect, itself stored inside the `zone.c` Cache system.
- `cvar_t` — `WinQuake/cvar.h:56-64` — name/string/value plus `archive`/`server` flags and an intrusive `next` pointer for the global cvar linked list.
- `cmd_function_t` / `cmdalias_t` — `WinQuake/cmd.c:403-408`, `WinQuake/cmd.c:28-33` — intrusive linked lists of registered console commands and user aliases consulted in order by `Cmd_ExecuteString`.
- `sizebuf_t cmd_text` — `WinQuake/cmd.c:66` — the linear command buffer that `Cbuf_AddText` appends to and `Cbuf_Execute` compacts from the front.
- `memblock_t` / `memzone_t` — `WinQuake/zone.c:29-43` — Zone allocator's free-list block header and arena descriptor.
- `hunk_t` — `WinQuake/zone.c:268-273` — Hunk allocator's per-block header (sentinel, size, 8-byte debug name), used only for consistency checking since the hunk has no per-block free.
- `cache_system_t` / `cache_head` — `WinQuake/zone.c:557-568` — Cache allocator's block header (dual-linked into both an address-order list and an LRU list) and its sentinel head node.
- `cache_user_t` — `WinQuake/zone.h:111-114` — the opaque, one-`void*` handle callers (models, sfx) hold instead of a raw pointer, since the Cache system is free to move/evict the backing memory at any time.
- `surfcache_t` — `WinQuake/d_local.h:37-49` — the software renderer's independent surface-cache block header (ring-buffer allocator in `d_surf.c`, not the `zone.c` Cache).
- `jmp_buf host_abortserver` — `WinQuake/host.c:52` — the single global recovery point `Host_Error`/`Host_EndGame` `longjmp` back into from `_Host_Frame`'s `setjmp`.

## Further reading

- Fabien Sanglard, "Quake Source Code Review": https://fabiensanglard.net/quakeSource/index.php — covers the Zone/Hunk/Cache memory model and the sound mixer in more depth than fits here.
- Michael Abrash, Graphics Programming Black Book: https://www.jagregory.com/abrash-black-book/ — background on the era's memory-constrained, fixed-budget allocation strategies that motivated Quake's custom allocators.
- Olivier Montanuy et al., "Unofficial Quake Specs": https://www.gamers.org/dEngine/quake/spec/quake-spec34/ (archived: https://web.archive.org/web/20251206223630/https://www.gamers.org/dEngine/quake/spec/quake-spec34/) — documents the `svc_sound` network message format and field masks referenced above.
- Carmack .plan archives: https://github.com/ESWAT/john-carmack-plan-archive — period commentary on engine architecture decisions (unverified for specific sound/memory-allocator commentary; browse for era context).
