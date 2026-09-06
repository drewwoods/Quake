# The Server Stage: Physics, the QuakeC VM, and Entity Transmission

The server is where gameplay becomes real. It reads movement requests, runs C physics and QuakeC behavior on its entities, then sends each client the state it needs to see.

> **First pass.** Keep three jobs separate: read commands, simulate the world, send results. An **edict** is one server object; C and QuakeC both operate on its fields. Visibility filters the outgoing updates, not the main simulation loop. Source: `WinQuake/host.c:600-621`, `WinQuake/sv_phys.c:1507-1563`, `WinQuake/sv_main.c:427-470`. [Next: collision →](#sec-3)

::: diagram quakec

## Where it sits in the frame

`_Host_Frame` calls `Host_ServerFrame` (`WinQuake/host.c:674-675`) once per frame when `sv.active`, after the client has already deposited its intentions in the loopback socket (`CL_SendCmd`, `WinQuake/host.c:662-663`). `Host_ServerFrame` (`WinQuake/host.c:600-621`) runs six stages in order: publish `frametime` to QuakeC, `SV_ClearDatagram`, `SV_CheckForNewClients` (`WinQuake/sv_main.c:302`), `SV_RunClients` (`WinQuake/sv_user.c:600`), `SV_Physics` (`WinQuake/sv_phys.c:1507`), `SV_SendClientMessages` (`WinQuake/sv_main.c:819`).

## `SV_Physics`: one pass over every edict

The whole simulation is a single linear scan of the edict array, dispatching on one field:

`WinQuake/sv_phys.c:1507-1563`:

```c
void SV_Physics (void)
{
	int		i;
	edict_t	*ent;

// let the progs know that a new frame has started
	pr_global_struct->self = EDICT_TO_PROG(sv.edicts);
	pr_global_struct->other = EDICT_TO_PROG(sv.edicts);
	pr_global_struct->time = sv.time;
	PR_ExecuteProgram (pr_global_struct->StartFrame);

//
// treat each object in turn
//
	ent = sv.edicts;
	for (i=0 ; i<sv.num_edicts ; i++, ent = NEXT_EDICT(ent))
	{
		if (ent->free)
			continue;

		if (pr_global_struct->force_retouch)
		{
			SV_LinkEdict (ent, true);	// force retouch even for stationary
		}

		if (i > 0 && i <= svs.maxclients)
			SV_Physics_Client (ent, i);
		else if (ent->v.movetype == MOVETYPE_PUSH)
			SV_Physics_Pusher (ent);
```

Three structural facts fall out of this loop.

**Edict index encodes role.** Edict 0 is the world (`sv.edicts`), edicts `1..svs.maxclients` are the player slots — permanently, whether occupied or not — and everything above is a free pool. `ED_Alloc` (`WinQuake/pr_edict.c:87-112`) starts its search at `svs.maxclients+1` for exactly this reason, and refuses to reuse a slot freed less than 0.5 s ago (`WinQuake/pr_edict.c:97`) so that in-flight entity references and network entity numbers don't get recycled under a client that hasn't heard about the deletion yet. That comparison also relaxes the rule during the first two seconds of a level, when spawn functions churn through edicts freely.

**Player physics is chosen by index, not by movetype.** `if (i > 0 && i <= svs.maxclients)` routes to `SV_Physics_Client` before movetype is ever consulted; the movetype switch inside that function is a second, narrower dispatch. This is what makes `PlayerPreThink`/`PlayerPostThink` player-only hooks without any per-entity flag.

**There is no dependency scheduler and no second pass.** Entities are simulated in edict-array order, each one moving and colliding against whatever state the others are in when its turn arrives, so results can depend on edict index. This is about ordering, not about culling: collision itself still goes through the areanode broadphase described in the next section.

`sv.time += host_frametime` at the tail (`WinQuake/sv_phys.c:1563`) is the world clock. Note it advances *after* the pass, so every entity in a given frame sees the same `sv.time`.

The `force_retouch` global is a QuakeC-settable escape hatch: setting it forces `SV_LinkEdict(ent, true)` on every entity for a frame, re-running all trigger touches even for things that didn't move. It is decremented once per frame (`WinQuake/sv_phys.c:1560-1561`), so QuakeC sets it to 2 to guarantee a full retouch pass survives one frame boundary.

## The movetypes

`WinQuake/server.h:115-127` defines the taxonomy, and each one is a promise about what physics will do:

- `MOVETYPE_NONE` (0) — never moves; only thinks (`SV_Physics_None`, `WinQuake/sv_phys.c:1142-1146`). Doors' trigger fields, lights, most static geometry.
- `MOVETYPE_WALK` (3) — gravity plus step-climbing; players only.
- `MOVETYPE_STEP` (4) — "gravity, special edge handling"; monsters. Falls when unsupported, but does not slide — horizontal movement is driven explicitly by `SV_movestep`.
- `MOVETYPE_FLY` (5) / `MOVETYPE_FLYMISSILE` (9) — ballistic without gravity; the missile variant uses expanded hulls against monsters.
- `MOVETYPE_TOSS` (6) / `MOVETYPE_BOUNCE` (10) — gravity-driven projectiles; bounce restitution differs.
- `MOVETYPE_PUSH` (7) — doors, platforms, trains. "No clip to world, push and crush."
- `MOVETYPE_NOCLIP` (8) — integrate position, ignore everything.

`SV_Physics` collapses `TOSS`, `BOUNCE`, `FLY` and `FLYMISSILE` onto one handler, `SV_Physics_Toss` (`WinQuake/sv_phys.c:1245`), which branches internally on gravity.

## `SV_RunThink`: the QuakeC scheduler

Almost all game behavior in Quake is a chain of deferred `think` calls, and the entire scheduler is fourteen lines:

`WinQuake/sv_phys.c:126-144`:

```c
qboolean SV_RunThink (edict_t *ent)
{
	float	thinktime;

	thinktime = ent->v.nextthink;
	if (thinktime <= 0 || thinktime > sv.time + host_frametime)
		return true;
		
	if (thinktime < sv.time)
		thinktime = sv.time;	// don't let things stay in the past.
								// it is possible to start that way
								// by a trigger with a local time.
	ent->v.nextthink = 0;
	pr_global_struct->time = thinktime;
	pr_global_struct->self = EDICT_TO_PROG(ent);
	pr_global_struct->other = EDICT_TO_PROG(sv.edicts);
	PR_ExecuteProgram (ent->v.think);
	return !ent->free;
}
```

There is no priority queue, no timer wheel: every entity is polled every frame and the `nextthink <= sv.time + host_frametime` test is the whole scheduling policy. On a 200-edict level at 20 Hz that is 4,000 float comparisons per second — genuinely cheaper than maintaining a heap, and utterly predictable. Two details matter downstream. The QuakeC-visible `time` global is set to the *scheduled* think time, not the actual `sv.time`, so a think rescheduled with `self.nextthink = time + 0.1` can preserve its schedule when it is serviced on time. Overdue thinks are clamped forward to `sv.time`; this is not an unlimited catch-up scheduler. And the return value is `!ent->free` — a think function that calls `remove(self)` makes every caller bail out immediately, which is why `SV_Physics_Client` and `SV_Physics_Toss` are littered with `if (!SV_RunThink (ent)) return;`.

The function header's own comment (`WinQuake/sv_phys.c:120-122`) admits the imprecision: "There is some play in the exact time the think function will be called, because it is called before any movement is done in a frame. Not used for pushmove objects, because they must be exact." Pushers get the exact treatment in `SV_Physics_Pusher` (below), because a door that overshoots its think time by a frame ends up geometrically in the wrong place, whereas a rocket that thinks 8 ms late just moves 8 ms further.

## `SV_FlyMove`: the sliding-collision core

`SV_FlyMove` (`WinQuake/sv_phys.c:229-362`) handles sliding movement for players and falling step entities. Tossed and flying projectiles instead use `SV_Physics_Toss` → `SV_PushEntity` → `SV_Move` (`WinQuake/sv_phys.c:1245-1340`). It is an iterative trace-and-slide, capped at four bounces:

`WinQuake/sv_phys.c:252-296`:

```c
	for (bumpcount=0 ; bumpcount<numbumps ; bumpcount++)
	{
		if (!ent->v.velocity[0] && !ent->v.velocity[1] && !ent->v.velocity[2])
			break;

		for (i=0 ; i<3 ; i++)
			end[i] = ent->v.origin[i] + time_left * ent->v.velocity[i];

		trace = SV_Move (ent->v.origin, ent->v.mins, ent->v.maxs, end, false, ent);

		if (trace.allsolid)
		{	// entity is trapped in another solid
			VectorCopy (vec3_origin, ent->v.velocity);
			return 3;
		}

		if (trace.fraction > 0)
		{	// actually covered some distance
			VectorCopy (trace.endpos, ent->v.origin);
			VectorCopy (ent->v.velocity, original_velocity);
			numplanes = 0;
		}

		if (trace.fraction == 1)
			 break;		// moved the entire distance

		if (!trace.ent)
			Sys_Error ("SV_FlyMove: !trace.ent");

		if (trace.plane.normal[2] > 0.7)
		{
			blocked |= 1;		// floor
			if (trace.ent->v.solid == SOLID_BSP)
			{
				ent->v.flags =	(int)ent->v.flags | FL_ONGROUND;
				ent->v.groundentity = EDICT_TO_PROG(trace.ent);
			}
		}
```

The `0.7` threshold on `plane.normal[2]` — roughly 45.6° — is Quake's definition of "floor," and it appears verbatim in half a dozen places (`WinQuake/sv_phys.c:281`, `WinQuake/sv_phys.c:1033`, `WinQuake/sv_move.c`). Steeper than that and it's a wall you slide down; shallower and you stand on it. There is no separate slope-friction model.

The plane-accumulation logic (`WinQuake/sv_phys.c:308-348`) is the part that makes corners work. Each impact's normal is pushed onto a `planes[]` array of at most `MAX_CLIP_PLANES` (5). The code then searches for a single plane whose clipped velocity does not point *into* any other accumulated plane; failing that — the classic two-wall inside corner — it takes the cross product of the two planes and slides along the crease:

```c
		if (i != numplanes)
		{	// go along this plane
			VectorCopy (new_velocity, ent->v.velocity);
		}
		else
		{	// go along the crease
			if (numplanes != 2)
			{
				VectorCopy (vec3_origin, ent->v.velocity);
				return 7;
			}
			CrossProduct (planes[0], planes[1], dir);
			d = DotProduct (dir, ent->v.velocity);
			VectorScale (dir, d, ent->v.velocity);
		}
```

That is `WinQuake/sv_phys.c:333-348`. The final guard (`WinQuake/sv_phys.c:354-358`) kills velocity entirely if the clipped result opposes the original direction, "to avoid tiny occilations in sloping corners" — a heuristic that trades a little correctness for the absence of visible jitter, and one that every subsequent id engine inherited unchanged.

The `numbumps = 4` cap bounds the number of trace-and-slide attempts. Each `SV_Move` sweeps its segment, so this is continuous path testing against the current collision scene, but not a general solver for all moving bodies over time. Difficult corners can exhaust the budget before the desired movement is complete (`WinQuake/sv_phys.c:252-362`).

## Gravity, velocity bounds, and NaN defense

`SV_AddGravity` (`WinQuake/sv_phys.c:371-390`) is one line of physics wrapped in a per-entity gravity scale looked up by *name* through `GetEdictFieldValue(ent, "gravity")` — a reflective field lookup into the progs field table, so a mod can add a `.gravity` field without any engine change:

```c
	ent->v.velocity[2] -= ent_gravity * sv_gravity.value * host_frametime;
```

`sv_gravity` defaults to 800 (`WinQuake/sv_phys.c:44`) — 800 Quake units/s², with a unit conventionally read as about an inch, so ~20 m/s², about twice Earth gravity. Quake's world is deliberately heavier and snappier than reality.

`SV_CheckVelocity` (`WinQuake/sv_phys.c:90-114`) clamps each axis to `sv_maxvelocity` (2000, `WinQuake/sv_phys.c:45`) and — notably — explicitly tests for NaN in both velocity and origin, printing the offending entity's classname and zeroing the component. That check is defensive engineering born of experience: a single NaN propagating into `SV_Move` would poison the BSP hull traversal and crash the server, so the engine scrubs it every frame rather than trying to find the source.

Note that the clamp is **per axis**, not on the magnitude — a diagonal velocity can reach `2000√3` units/s.

## Water

Water is handled as a content type sampled at up to three points on the entity's bounding box. `SV_CheckWater` (`WinQuake/sv_phys.c:808-...`) probes at `mins[2]+1`, at the box midpoint, and at the view height, setting `waterlevel` to 0–3 and `watertype` to the BSP content value:

`WinQuake/sv_phys.c:816-830`:

```c
	point[0] = ent->v.origin[0];
	point[1] = ent->v.origin[1];
	point[2] = ent->v.origin[2] + ent->v.mins[2] + 1;	
	
	ent->v.waterlevel = 0;
	ent->v.watertype = CONTENTS_EMPTY;
	cont = SV_PointContents (point);
	if (cont <= CONTENTS_WATER)
	{
		ent->v.watertype = cont;
		ent->v.waterlevel = 1;
		point[2] = ent->v.origin[2] + (ent->v.mins[2] + ent->v.maxs[2])*0.5;
```

`waterlevel >= 2` (waist-deep) switches the player from `SV_AirMove` to `SV_WaterMove`; `waterlevel == 3` is the condition QuakeC uses for drowning. `SV_CheckWaterTransition` (`WinQuake/sv_phys.c:1198`) compares the new content against the old to update water state and emit splash sounds. It does not apply slime/lava damage; damage rules belong to game logic.

`MOVETYPE_WALK` skips gravity entirely when in water (`WinQuake/sv_phys.c:1089-1090`): `if (!SV_CheckWater (ent) && ! ((int)ent->v.flags & FL_WATERJUMP)) SV_AddGravity (ent);`. Buoyancy is not modeled; water simply turns gravity off and substitutes a different acceleration/friction model.

## `SV_Physics_Pusher`: exact-time movement for doors and platforms

Pushers get their own timebase. Every `MOVETYPE_PUSH` entity carries `ltime`, a private clock that is *not* `sv.time`, and `SV_Physics_Pusher` (`WinQuake/sv_phys.c:704-743`) shortens the frame's movement so the pusher lands exactly on its think time:

```c
	thinktime = ent->v.nextthink;
	if (thinktime < ent->v.ltime + host_frametime)
	{
		movetime = thinktime - ent->v.ltime;
		if (movetime < 0)
			movetime = 0;
	}
	else
		movetime = host_frametime;

	if (movetime)
	{
			SV_PushMove (ent, movetime);	// advances ent->v.ltime if not blocked
	}
		
	if (thinktime > oldltime && thinktime <= ent->v.ltime)
	{
		ent->v.nextthink = 0;
		pr_global_struct->time = sv.time;
		pr_global_struct->self = EDICT_TO_PROG(ent);
		pr_global_struct->other = EDICT_TO_PROG(sv.edicts);
		PR_ExecuteProgram (ent->v.think);
```

This is why a Quake door stops precisely at its open position rather than a frame's worth past it, at any framerate. The cost is that `ltime` can lag `sv.time` when a pusher is blocked, and `SV_PushMove` (`WinQuake/sv_phys.c:439-557`) explicitly rewinds it (`pusher->v.ltime -= movetime`, `WinQuake/sv_phys.c:535`) when it cannot complete.

`SV_PushMove` itself is the crush handler. It moves the pusher first, then scans every other edict for one now embedded in the pusher's new volume, tries to shove it along by the same delta, and if that fails restores *everything* it has moved so far and calls the pusher's QuakeC `blocked` function (`WinQuake/sv_phys.c:539-551`). The rollback arrays `moved_edict[MAX_EDICTS]` and `moved_from[MAX_EDICTS]` are stack-allocated per call (`WinQuake/sv_phys.c:446-447`), bounding rollback storage by the 600-edict limit. The corpse special case at `WinQuake/sv_phys.c:521-528` collapses a blocking non-solid entity's bounding box to a point rather than failing the move, so a dead body does not stop a door.

## `SV_Physics_Client` and player movement

Players are the only entities that get QuakeC hooks on both sides of their move:

`WinQuake/sv_phys.c:1059-1095`:

```c
void SV_Physics_Client (edict_t	*ent, int num)
{
	if ( ! svs.clients[num-1].active )
		return;		// unconnected slot

//
// call standard client pre-think
//	
	pr_global_struct->time = sv.time;
	pr_global_struct->self = EDICT_TO_PROG(ent);
	PR_ExecuteProgram (pr_global_struct->PlayerPreThink);
	
//
// do a move
//
	SV_CheckVelocity (ent);

	switch ((int)ent->v.movetype)
	{
	case MOVETYPE_WALK:
		if (!SV_RunThink (ent))
			return;
		if (!SV_CheckWater (ent) && ! ((int)ent->v.flags & FL_WATERJUMP) )
			SV_AddGravity (ent);
		SV_CheckStuck (ent);
		SV_WalkMove (ent);
		break;
```

and, at the end (`WinQuake/sv_phys.c:1126-1130`), `SV_LinkEdict (ent, true)` followed by `PlayerPostThink`. `PlayerPreThink` is where QuakeC applies weapon state and jump requests *before* the move; `PlayerPostThink` is where it reads the result — the classic use is fall-damage, which needs the pre-move velocity compared against the post-move ground contact.

Crucially, the *velocity* the move uses was already computed, earlier in the frame, by `SV_ClientThink` inside `SV_RunClients`. The split is: `SV_RunClients` turns network input into velocity; `SV_Physics_Client` turns velocity into position.

`SV_WalkMove` (`WinQuake/sv_phys.c:958-1049`) is stair-stepping, and it is delightfully brute-force. It runs the normal `SV_FlyMove`, and if the result was blocked by a wall (`clip & 2`), it *rewinds to the original position*, tries a swept upward move of `STEPSIZE` (18 units, `WinQuake/sv_phys.c:957`), re-runs the whole slide move, then pushes back down:

```c
	VectorCopy (oldorg, ent->v.origin);	// back to start pos

	upmove[2] = STEPSIZE;
	downmove[2] = -STEPSIZE + oldvel[2]*host_frametime;

// move up
	SV_PushEntity (ent, upmove);	// FIXME: don't link?

// move forward
	ent->v.velocity[0] = oldvel[0];
	ent->v. velocity[1] = oldvel[1];
	ent->v. velocity[2] = 0;
	clip = SV_FlyMove (ent, host_frametime, &steptrace);
```

(`WinQuake/sv_phys.c:999-1013`.) There are two main slide attempts, with further attempts possible inside `SV_TryUnstick`; the stepped result is discarded if the downward trace doesn't land on floor (`WinQuake/sv_phys.c:1041-1048`), reverting to the saved no-step result. The comment there is a good example of the empirical, bug-driven character of this code: "if the push down didn't end up on good ground, use the move without the step up. This happens near wall / slope combinations, and can cause the player to hop up higher on a slope too steep to climb."

There is even a sub-heuristic for float precision: if stepping up moved the player less than 1/32 of a unit, `SV_TryUnstick` (`WinQuake/sv_phys.c:901`) nudges the player in eight compass directions looking for one that frees them (`WinQuake/sv_phys.c:1017-1024`). The header comment on `SV_TryUnstick` names the cause outright — "float precision at some angle joins in the BSP hull" (`WinQuake/sv_phys.c:894`).

## The QuakeC VM

Quake's game logic is not C. It is compiled QuakeC, shipped as `progs.dat`, loaded by `PR_LoadProgs` (`WinQuake/pr_edict.c:985`) and interpreted by `PR_ExecuteProgram` (`WinQuake/pr_exec.c:361`). This is the design decision that made Quake moddable and is directly responsible for Team Fortress, Threewave CTF, and the entire mod culture that followed. id had committed to shipping an "open game" as early as the [1993 DOOM announcement](design:the-1993-feature-list-read-as-a-ceiling).

### The image

`progs.dat` is six lumps plus a header (`WinQuake/pr_edict.c:1010-1021`):

```c
	pr_functions = (dfunction_t *)((byte *)progs + progs->ofs_functions);
	pr_strings = (char *)progs + progs->ofs_strings;
	pr_globaldefs = (ddef_t *)((byte *)progs + progs->ofs_globaldefs);
	pr_fielddefs = (ddef_t *)((byte *)progs + progs->ofs_fielddefs);
	pr_statements = (dstatement_t *)((byte *)progs + progs->ofs_statements);

	pr_global_struct = (globalvars_t *)((byte *)progs + progs->ofs_globals);
	pr_globals = (float *)pr_global_struct;
	
	pr_edict_size = progs->entityfields * 4 + sizeof (edict_t) - sizeof(entvars_t);
```

The file is loaded onto the hunk and used *in place* — no relocation, no linking, just pointer arithmetic into the mapped image and a byte-swap pass for big-endian hosts. `pr_globals` and `pr_global_struct` are the same memory viewed two ways: the engine reads named fields through the C struct `globalvars_t` (`WinQuake/progdefs.q1:4-60`) while the interpreter indexes the same words as a flat `float[]`. That aliasing is validated by a CRC check against `PROGHEADER_CRC` (5927, `WinQuake/progdefs.q1:143`) at load time (`WinQuake/pr_edict.c:1009-1010`) — if a mod author changes the system globals or fields, the engine refuses to run rather than silently reading garbage.

`pr_edict_size` is the key line: an edict is a C `edict_t` header (`WinQuake/progs.h:35-49`) whose last member is an `entvars_t`, followed immediately by however many extra 4-byte fields the mod's progs declared. `NEXT_EDICT`, `EDICT_TO_PROG`, and `PROG_TO_EDICT` (`WinQuake/progs.h:94-97`) are byte-offset macros over that variable stride, and QuakeC's `entity` type is literally a byte offset from `sv.edicts`. Extra fields are reached reflectively via `GetEdictFieldValue` and the fielddef table — which is exactly how `SV_AddGravity` finds a mod-defined `.gravity`.

### The interpreter

`PR_ExecuteProgram` (`WinQuake/pr_exec.c:361-666`) is a straightforward switch-dispatch loop over a fixed-format three-address instruction:

`WinQuake/pr_exec.c:390-412`:

```c
while (1)
{
	s++;	// next statement

	st = &pr_statements[s];
	a = (eval_t *)&pr_globals[st->a];
	b = (eval_t *)&pr_globals[st->b];
	c = (eval_t *)&pr_globals[st->c];
	
	if (!--runaway)
		PR_RunError ("runaway loop error");
	
	pr_xfunction->profile++;
	pr_xstatement = s;
	
	if (pr_trace)
		PR_PrintStatement (st);
		
	switch (st->op)
	{
	case OP_ADD_F:
		c->_float = a->_float + b->_float;
		break;
```

Many operands address words in the flat `pr_globals` array; branch opcodes instead interpret their signed 16-bit operands as relative statement offsets — there are no registers and no stack machine. The compiler allocates temporaries as globals, which makes the interpreter trivially fast (three array indexes and a switch per instruction) at the cost of making QuakeC non-reentrant in an interesting way: recursion works only because `PR_EnterFunction` (`WinQuake/pr_exec.c:294-326`) *copies the callee's local slots onto a shadow stack* before overwriting them:

```c
// save off any locals that the new function steps on
	c = f->locals;
	if (localstack_used + c > LOCALSTACK_SIZE)
		PR_RunError ("PR_ExecuteProgram: locals stack overflow\n");

	for (i=0 ; i < c ; i++)
		localstack[localstack_used+i] = ((int *)pr_globals)[f->parm_start + i];
	localstack_used += c;

// copy parameters
	o = f->parm_start;
	for (i=0 ; i<f->numparms ; i++)
	{
		for (j=0 ; j<f->parm_size[i] ; j++)
		{
			((int *)pr_globals)[o] = ((int *)pr_globals)[OFS_PARM0+i*3+j];
			o++;
		}
	}
```

`PR_LeaveFunction` (`WinQuake/pr_exec.c:333-353`) copies them back. Locals are statically allocated globals with save/restore around calls — a callee-saves convention implemented in software.

> **.plan.** “made an execution stack for progs” — [Carmack, 15 Mar 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960315.txt). The shipping `localstack` is the concrete form of that terse worklog entry: QuakeC keeps its fast flat global array, then saves the callee’s locals around calls to make recursion possible.

The `runaway = 100000` counter (`WinQuake/pr_exec.c:382`, decremented at `:399`) bounds bytecode instruction execution for one invocation. Exhausting it raises `PR_RunError` with a QuakeC stack trace (`PR_StackTrace`, `WinQuake/pr_exec.c:190`). This is a runaway-loop guard, not a general safety sandbox or a time limit on C builtins. `Host_Error` abandons an interactive game; on a dedicated server it exits the process. `pr_xfunction->profile++` on every instruction is a free per-function instruction counter, dumped by the `profile` console command (`PR_Profile_f`, `WinQuake/pr_exec.c:222`) — the mod author's optimization tool, built into the shipping engine.

Two opcodes are not general computation at all. `OP_CALL0`–`OP_CALL8` (`WinQuake/pr_exec.c:620-636`) reuse a negative `first_statement` as a builtin index:

```c
		newf = &pr_functions[a->function];

		if (newf->first_statement < 0)
		{	// negative statements are built in functions
			i = -newf->first_statement;
			if (i >= pr_numbuiltins)
				PR_RunError ("Bad builtin call number");
			pr_builtins[i] ();
			break;
		}
```

And `OP_STATE` (`WinQuake/pr_exec.c:649-661`) hard-codes the animation frame convention — set `frame`, set `think`, and schedule `nextthink` exactly 0.1 s out — so that QuakeC's `$frame` state syntax compiles to a single instruction. That 0.1 is the origin of Quake's 10 Hz monster animation, and the `#ifdef FPS_20` alternative right beside it (0.05) is the same unshipped 20 Hz experiment seen in `host.c`.

### Builtins

The engine↔progs boundary is a flat function-pointer table, `pr_builtin[]` (`WinQuake/pr_cmds.c:1831-1931`), indexed by the negative first_statement above, with `pr_numbuiltins` computed by `sizeof` (`WinQuake/pr_cmds.c:1933`). Arguments arrive in fixed global slots `OFS_PARM0..7` and results go in `OFS_RETURN` — the same ABI the interpreter uses for QuakeC-to-QuakeC calls. There are about 80 of them and they supply operations beyond direct reads and writes of QuakeC globals and entity fields: `setorigin` (`WinQuake/pr_cmds.c:120`) because assigning `.origin` directly would skip `SV_LinkEdict`, `setmodel` (`WinQuake/pr_cmds.c:234`) because model indices must be interned in the precache table, `traceline` (`WinQuake/pr_cmds.c:609`) for hitscan, `spawn`/`remove` for edict lifetime, `sound`/`bprint`/`stuffcmd` for output.

The commented-out builtin numbers in the table (`// float(vector v1, vector v2, float tryents) traceline = #16;`) are the actual interface contract — QuakeC declares `traceline = #16` and the compiler emits a function whose `first_statement` is `-16`. Adding a builtin means appending to this array; the number is its position, forever.

## `SV_RunClients`: from packet to velocity

`SV_RunClients` (`WinQuake/sv_user.c:600-628`) walks the client array, and for each active client reads the wire, then thinks:

```c
	for (i=0, host_client = svs.clients ; i<svs.maxclients ; i++, host_client++)
	{
		if (!host_client->active)
			continue;
	
		sv_player = host_client->edict;

		if (!SV_ReadClientMessage ())
		{
			SV_DropClient (false);	// client misbehaved...
			continue;
		}

		if (!host_client->spawned)
		{
		// clear client movement until a new packet is received
			memset (&host_client->cmd, 0, sizeof(host_client->cmd));
			continue;
		}

// always pause in single player if in console or menus
		if (!sv.paused && (svs.maxclients > 1 || key_dest == key_game) )
			SV_ClientThink ();
	}
```

`host_client` and `sv_player` are file-scope globals set here and read throughout `sv_user.c`. This makes the active client implicit throughout the movement call chain. When reading a helper, trace back to the loop that set those globals; the helper is not independent of that calling context.

`SV_ReadClientMessage` (`WinQuake/sv_user.c:482-593`) drains all pending packets from that client's qsocket, dispatching on a leading command byte: `clc_nop`, `clc_disconnect`, `clc_stringcmd`, `clc_move`. The `clc_stringcmd` case (`WinQuake/sv_user.c:528-...`) is Quake's authorization model, and it is a hard-coded whitelist of command prefixes — `status`, `god`, `notarget`, `fly`, `name`, `noclip`, `say`, `say_team`, `tell`, `color`, `kill`, `pause`, `spawn`, `begin`, `prespawn`, `kick`, `ping`, `give`, `ban` — matched with `Q_strncasecmp` and executed through the normal console command path. Anything else is rejected unless `host_client->privileged`. Prefix matching plus a shared command buffer is exactly the kind of surface that produced remote-execution bugs in later derivatives.

`SV_ReadClientMove` (`WinQuake/sv_user.c:438-473`) unpacks the `clc_move` payload built by `CL_SendMove`:

```c
// read ping time
	host_client->ping_times[host_client->num_pings%NUM_PING_TIMES]
		= sv.time - MSG_ReadFloat ();
	host_client->num_pings++;

// read current angles	
	for (i=0 ; i<3 ; i++)
		angle[i] = MSG_ReadAngle ();

	VectorCopy (angle, host_client->edict->v.v_angle);
		
// read movement
	move->forwardmove = MSG_ReadShort ();
	move->sidemove = MSG_ReadShort ();
	move->upmove = MSG_ReadShort ();
	
// read buttons
	bits = MSG_ReadByte ();
	host_client->edict->v.button0 = bits & 1;
	host_client->edict->v.button2 = (bits & 2)>>1;
```

Notice what the client actually sends: a float echo of the last received server time (for RTT), three 8-bit-quantized angles, three 16-bit movement intentions, one byte of buttons, one byte of impulse. Including the one-byte `clc_move` opcode, that is 16 bytes. The client sends *intentions*, never positions — the server is fully authoritative over where the player ends up. Angles are the exception: `v_angle` is copied straight from the packet, because view direction has no server-side model and forcing it would fight the mouse.

Note also that there is no per-command timestamp and no command sequence. A `usercmd_t` is applied with *this frame's* `host_frametime`, whatever that is. If the client's framerate and the server's differ, the client's inputs are effectively resampled — the root of Quake 1's framerate-dependent movement quirks, and precisely what QuakeWorld's timestamped commands fixed.

`SV_ClientThink` (`WinQuake/sv_user.c:380-430`) then does the actual movement math, choosing between three models:

```c
	if ( (int)sv_player->v.flags & FL_WATERJUMP )
	{
		SV_WaterJump ();
		return;
	}
//
// walk
//
	if ( (sv_player->v.waterlevel >= 2)
	&& (sv_player->v.movetype != MOVETYPE_NOCLIP) )
	{
		SV_WaterMove ();
		return;
	}

	SV_AirMove ();	
```

It also derives the *rendered* body angles from the view angles at `WinQuake/sv_user.c:406-412`: pitch is divided by 3 (a player model that pitched fully would look absurd), roll comes from `V_CalcRoll` on lateral velocity — the strafe lean that reads as weight.

`SV_AirMove` (`WinQuake/sv_user.c:326-370`) is the famous one. It builds `wishvel` from the client's forward/side intentions rotated into world space, clamps its magnitude to `sv_maxspeed` (320, `WinQuake/sv_user.c:167`), and then branches:

```c
	VectorCopy (wishvel, wishdir);
	wishspeed = VectorNormalize(wishdir);
	if (wishspeed > sv_maxspeed.value)
	{
		VectorScale (wishvel, sv_maxspeed.value/wishspeed, wishvel);
		wishspeed = sv_maxspeed.value;
	}
	
	if ( sv_player->v.movetype == MOVETYPE_NOCLIP)
	{	// noclip
		VectorCopy (wishvel, velocity);
	}
	else if ( onground )
	{
		SV_UserFriction ();
		SV_Accelerate ();
	}
	else
	{	// not on ground, so little effect on velocity
		SV_AirAccelerate (wishvel);
	}		
```

Note the bug that made a genre. `wishspeed` is clamped, but `SV_AirAccelerate` (`WinQuake/sv_user.c:207-226`) separately clamps its *own* `wishspd` to 30 while computing `accelspeed` from the unclamped `wishspeed` global at `WinQuake/sv_user.c:220` (with the "correct" version commented out on the line above). The result: the projection test `addspeed = wishspd - currentspeed` uses a tiny target, so it stays positive whenever you're moving roughly perpendicular to your wish direction, while the acceleration applied is full-sized. With suitable steering, repeated air acceleration can increase total speed above `sv_maxspeed`, because that variable caps desired speed rather than the resulting velocity vector. `SV_CheckVelocity` still applies the separate per-axis `sv_maxvelocity` limit. That is strafe-jumping and bunny-hopping — an artifact of an inconsistent clamp, shipped, and load-bearing for two decades of movement shooters.

`SV_Accelerate` (`WinQuake/sv_user.c:190-205`) is the ground version, and it is the standard projection accelerator: only the component of `wishdir` you're not already moving along gets added.

`SV_UserFriction` (`WinQuake/sv_user.c:122-160`) applies drag — with an extra trace:

```c
// if the leading edge is over a dropoff, increase friction
	start[0] = stop[0] = origin[0] + vel[0]/speed*16;
	start[1] = stop[1] = origin[1] + vel[1]/speed*16;
	start[2] = origin[2] + sv_player->v.mins[2];
	stop[2] = start[2] - 34;

	trace = SV_Move (start, vec3_origin, vec3_origin, stop, true, sv_player);

	if (trace.fraction == 1.0)
		friction = sv_friction.value*sv_edgefriction.value;
	else
		friction = sv_friction.value;
```

A point trace 16 units ahead of the player's motion, 34 units down. If it hits nothing, you're about to run off a ledge and friction is multiplied by `sv_edgefriction` (2 by default). The whole feature — one extra trace per player per frame — exists so players don't skid off platforms, and it is the kind of tiny gameplay-driven hack that pervades this file.

The `control = speed < sv_stopspeed ? sv_stopspeed : speed` line (`WinQuake/sv_user.c:150`) gives constant deceleration below 100 units/s and proportional drag above it, so a stopping player comes to rest crisply instead of asymptotically.

## `SV_SendClientMessages`: PVS-gated delta compression

The last stage builds one packet per client. `SV_SendClientMessages` (`WinQuake/sv_main.c:819-887`) first flushes reliable state (`SV_UpdateToReliableMessages`, frag counts, name and color changes), then calls `SV_SendClientDatagram` per spawned client, then `SV_CleanupEnts` to clear muzzle-flash effect bits that should last exactly one frame.

`SV_SendClientDatagram` (`WinQuake/sv_main.c:720-749`) assembles a fixed-size unreliable packet:

```c
	byte		buf[MAX_DATAGRAM];
	sizebuf_t	msg;
	
	msg.data = buf;
	msg.maxsize = sizeof(buf);
	msg.cursize = 0;

	MSG_WriteByte (&msg, svc_time);
	MSG_WriteFloat (&msg, sv.time);

// add the client specific data to the datagram
	SV_WriteClientdataToMessage (client->edict, &msg);

	SV_WriteEntitiesToClient (client->edict, &msg);

// copy the server datagram if there is space
	if (msg.cursize + sv.datagram.cursize < msg.maxsize)
		SZ_Write (&msg, sv.datagram.data, sv.datagram.cursize);
```

The ordering is a priority ordering, and it is enforced by truncation rather than by a scheduler: timestamp first, then *this client's* own state (health, ammo, weapon, punch angles, velocity — `SV_WriteClientdataToMessage`, `WinQuake/sv_main.c:576`), then visible entities, then whatever broadcast events (`sv.datagram`: sounds, particles, temp entities) still fit. Run out of room and later data can be omitted. Unreliable packets are not retransmitted. A later baseline-relative entity update can restore current state without the lost packet, but one-shot sounds and effects in the lost datagram may never be seen.

### PVS gating

The visibility cut is the single biggest bandwidth lever, and it reuses the BSP's precomputed potentially-visible set.

`SV_FatPVS` (`WinQuake/sv_main.c:410-416`) does not take the PVS of the leaf containing the eye. It ORs together the PVS of every leaf within 8 units of the eye point:

```c
byte *SV_FatPVS (vec3_t org)
{
	fatbytes = (sv.worldmodel->numleafs+31)>>3;
	Q_memset (fatpvs, 0, fatbytes);
	SV_AddToFatPVS (org, sv.worldmodel->nodes);
	return fatpvs;
}
```

`SV_AddToFatPVS` (`WinQuake/sv_main.c:367-400`) walks the BSP from the root and, whenever the eye is within 8 units of a splitting plane (`if (d > 8) ... else if (d < -8) ... else` descend both children), takes *both* sides. The header comment (`WinQuake/sv_main.c:356-359`) explains why: without it, "an entity that should be visible [does] not show up, especially when the bob crosses a waterline" — view bob moves the eye a few units per frame, and a hard leaf lookup makes entities pop as the eye crosses a plane. Widening the query by 8 units in every direction costs a handful of extra leaf ORs and eliminates the flicker. Note the recursion is only on the near-plane case; the common path is an iterative descent.

`SV_WriteEntitiesToClient` (`WinQuake/sv_main.c:427-...`) then scans all edicts and drops anything not touching that set:

```c
// find the client's PVS
	VectorAdd (clent->v.origin, clent->v.view_ofs, org);
	pvs = SV_FatPVS (org);

// send over all entities (excpet the client) that touch the pvs
	ent = NEXT_EDICT(sv.edicts);
	for (e=1 ; e<sv.num_edicts ; e++, ent = NEXT_EDICT(ent))
	{
		if (ent != clent)	// clent is ALLWAYS sent
		{
// ignore ents without visible models
			if (!ent->v.modelindex || !pr_strings[ent->v.model])
				continue;

			for (i=0 ; i < ent->num_leafs ; i++)
				if (pvs[ent->leafnums[i] >> 3] & (1 << (ent->leafnums[i]&7) ))
					break;
				
			if (i == ent->num_leafs)
				continue;		// not visible
		}
```

The per-entity leaf list (`ent->leafnums[]`, up to `MAX_ENT_LEAFS` = 16, `WinQuake/progs.h:34`, `WinQuake/progs.h:40-41`) is maintained by `SV_LinkEdict` in `world.c` — the same call that keeps the areanode tree current for collision also records which BSP leaves the entity's bounding box straddles. So the visibility test is a 16-iteration bit test against a bitfield, per entity, per client. No frustum, no distance, no occlusion queries: a static precomputed cell-to-cell visibility matrix does all the work, at the cost of offline visibility computation and a conservative result that can include occluded entities. Missing a truly visible entity would be a culling/data limitation or bug, not the intended meaning of PVS.

Two consequences are worth naming. First, a client cannot inspect entities outside its fat PVS, although the conservative PVS still includes some occluded entities. Second, a non-client entity with no model (`!ent->v.modelindex`) is not transmitted, so QuakeC's invisible logic entities — triggers, spawn points, path corners — cost no entity-update bandwidth.

### Delta against baseline

Each surviving entity is compared not against the previous frame but against a per-entity *baseline* captured at level load by `SV_CreateBaseline` (`WinQuake/sv_main.c:925`) and sent once during signon. `SV_WriteEntitiesToClient` builds a bitmask of what differs (`WinQuake/sv_main.c:472-512`) and writes only those fields:

```c
		for (i=0 ; i<3 ; i++)
		{
			miss = ent->v.origin[i] - ent->baseline.origin[i];
			if ( miss < -0.1 || miss > 0.1 )
				bits |= U_ORIGIN1<<i;
		}

		if ( ent->v.angles[0] != ent->baseline.angles[0] )
			bits |= U_ANGLE1;
		...
		if (ent->v.movetype == MOVETYPE_STEP)
			bits |= U_NOLERP;	// don't mess up the step animation

		if (e >= 256)
			bits |= U_LONGENTITY;
			
		if (bits >= 256)
			bits |= U_MOREBITS;
```

Baseline-relative rather than previous-frame-relative delta is a deliberate simplification: the server keeps no per-client history, so it never has to track which frames a client actually received, and a dropped packet self-heals on the next one. The price is that a moving entity re-transmits its position every frame forever, which is why QuakeWorld switched to true per-client delta with acknowledged frames. The `U_MOREBITS` / `U_LONGENTITY` escape hatches (`WinQuake/sv_main.c:508-512`) keep the common case at one byte of bitmask and one byte of entity number — most updates are 4–8 bytes total.

`U_NOLERP` for `MOVETYPE_STEP` is the client-interpolation opt-out. Monsters animate at 10 Hz via `OP_STATE` and teleport between poses; interpolating their origins would smear the deliberate snap of the animation.

## Call graph

```
Host_ServerFrame                                host.c:600
  pr_global_struct->frametime = host_frametime  host.c:603
  SV_ClearDatagram                              sv_main.c:348
  SV_CheckForNewClients                         sv_main.c:302
  SV_RunClients                                 sv_user.c:600
    SV_ReadClientMessage                        sv_user.c:482
      NET_GetMessage                            net_main.c
      SV_ReadClientMove                         sv_user.c:438
      Cmd_ExecuteString  [clc_stringcmd]        cmd.c
    SV_ClientThink                              sv_user.c:380
      DropPunchAngle                            sv_user.c:229
      SV_WaterJump      [FL_WATERJUMP]          sv_user.c:307
      SV_WaterMove      [waterlevel >= 2]       sv_user.c:247
      SV_AirMove                                sv_user.c:326
        SV_UserFriction [onground]              sv_user.c:122
          SV_Move                               world.c
        SV_Accelerate   [onground]              sv_user.c:190
        SV_AirAccelerate[!onground]             sv_user.c:207
  SV_Physics                                    sv_phys.c:1507
    PR_ExecuteProgram(StartFrame)               pr_exec.c:361
    for each edict:
      SV_Physics_Client [1..maxclients]         sv_phys.c:1059
        PR_ExecuteProgram(PlayerPreThink)       sv_phys.c:1069
        SV_CheckVelocity                        sv_phys.c:90
        SV_RunThink                             sv_phys.c:126
        SV_CheckWater / SV_AddGravity           sv_phys.c:808 / 371
        SV_CheckStuck                           sv_phys.c:762
        SV_WalkMove                             sv_phys.c:958
          SV_FlyMove                            sv_phys.c:229
            SV_Move                             world.c
            SV_Impact -> PR_ExecuteProgram      sv_phys.c:153
          SV_PushEntity                         sv_phys.c:408
          SV_TryUnstick                         sv_phys.c:901
          SV_WallFriction                       sv_phys.c:867
        SV_LinkEdict                            world.c
        PR_ExecuteProgram(PlayerPostThink)      sv_phys.c:1130
      SV_Physics_Pusher [MOVETYPE_PUSH]         sv_phys.c:704
        SV_PushMove                             sv_phys.c:439
        PR_ExecuteProgram(think / blocked)      sv_phys.c:738 / 543
      SV_Physics_None   [MOVETYPE_NONE]         sv_phys.c:1142
      SV_Physics_Noclip [MOVETYPE_NOCLIP]       sv_phys.c:1172
      SV_Physics_Step   [MOVETYPE_STEP]         sv_phys.c:1468
      SV_Physics_Toss   [TOSS/BOUNCE/FLY/...]   sv_phys.c:1245
        SV_CheckWaterTransition                 sv_phys.c:1198
    sv.time += host_frametime                   sv_phys.c:1563
  SV_SendClientMessages                         sv_main.c:819
    SV_UpdateToReliableMessages                 sv_main.c:756
    SV_SendClientDatagram                       sv_main.c:720
      SV_WriteClientdataToMessage               sv_main.c:576
      SV_WriteEntitiesToClient                  sv_main.c:427
        SV_FatPVS                               sv_main.c:410
          SV_AddToFatPVS                        sv_main.c:367
            Mod_LeafPVS                         model.c
      NET_SendUnreliableMessage                 net_main.c
    SV_CleanupEnts                              sv_main.c:557

PR_ExecuteProgram                               pr_exec.c:361
  PR_EnterFunction                              pr_exec.c:294
  pr_builtins[i]()      [OP_CALL*]              pr_cmds.c:1831
  PR_LeaveFunction      [OP_RETURN/OP_DONE]     pr_exec.c:333
  PR_RunError                                   pr_exec.c:261
    PR_StackTrace                               pr_exec.c:190
```

## Key data structures

- `edict_t` — `WinQuake/progs.h:35-49` — one entity: `free` flag, `area` link into the collision areanode tree, `leafnums[]` PVS cache, network `baseline`, and the progs-visible `v` (`entvars_t`), with mod-declared extra fields trailing.
- `entvars_t` — `WinQuake/progdefs.q1:62-141` — the ~80 fields the engine and QuakeC both know by name (`origin`, `velocity`, `movetype`, `solid`, `nextthink`, `think`, `touch`, `flags`, `waterlevel`, …).
- `globalvars_t` — `WinQuake/progdefs.q1:4-60` — QuakeC globals the engine writes (`self`, `other`, `time`, `frametime`, `force_retouch`) and the function handles it calls (`StartFrame` `:51`, `PlayerPreThink` `:52`, `PlayerPostThink` `:53`).
- `dprograms_t` / `dfunction_t` / `dstatement_t` / `ddef_t` — `WinQuake/pr_comp.h` — the `progs.dat` on-disk format: header lump offsets, function descriptors (negative `first_statement` ⇒ builtin), three-address instructions, and the name/type/offset tables used for reflection.
- `pr_globals` (`float *`) — `WinQuake/pr_edict.c:31` — the flat global array; aliased as `pr_global_struct` so C and bytecode see the same words.
- `pr_edict_size` (int) — `WinQuake/pr_edict.c:32`, computed `WinQuake/pr_edict.c:1021` — runtime edict stride; makes `NEXT_EDICT` (`WinQuake/progs.h:94`) work over mod-extended entities.
- `localstack[]` / `pr_stack[]` — `WinQuake/pr_exec.c` — shadow save area for callee locals and the QuakeC return-address stack (`MAX_STACK_DEPTH`).
- `builtin_t pr_builtin[]` — `WinQuake/pr_cmds.c:1831-1931` — the engine ABI exposed to progs; index = QuakeC builtin number.
- `usercmd_t` — `WinQuake/common.h` / `WinQuake/client.h` — `forwardmove`/`sidemove`/`upmove` intentions; the only movement the client is trusted with.
- `client_t` — `WinQuake/server.h` — per-client slot: `edict`, `netconnection`, `message` (reliable sizebuf), `cmd`, `ping_times[]`, `spawned`/`active`/`privileged`.
- `server_t sv` — `WinQuake/server.h` — the world: `edicts`, `num_edicts`, `time`, `worldmodel`, `datagram` (per-frame broadcast events), `signon`.
- `trace_t` — `WinQuake/world.h` — result of `SV_Move`: `allsolid`, `startsolid`, `fraction`, `endpos`, `plane`, `ent`. See the collision section.
- `fatpvs[MAX_MAP_LEAFS/8]` — `WinQuake/sv_main.c:365` — scratch bitfield rebuilt per client per frame.

## Further reading

- Fabien Sanglard, "Quake Source Code Review" — the server and progs VM chapters: https://fabiensanglard.net/quakeSource/index.php
- Olivier Montanuy et al., "Unofficial Quake Specs" — the `progs.dat` file format, entity field tables, and network protocol message list: https://www.gamers.org/dEngine/quake/spec/quake-spec34/
- QuakeC reference (builtin numbers, `entvars_t` field semantics, `$frame`/`OP_STATE` conventions): https://www.gamers.org/dEngine/quake/spec/quake-spec34/qc-menu.htm
- Michael Abrash, *Graphics Programming Black Book*, ch. 64 ("Quake's Visible-Surface Determination") and ch. 70 — the PVS and BSP machinery that `SV_FatPVS` reuses: https://www.jagregory.com/abrash-black-book/
- John Carmack .plan archive — contemporaneous notes on QuakeC, progs performance, and the move to QuakeWorld's client-side prediction: https://github.com/ESWAT/john-carmack-plan-archive
