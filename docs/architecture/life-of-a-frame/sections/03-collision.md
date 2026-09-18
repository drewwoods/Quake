# Collision: Hulls, Traces, and Hit Detection

Collision answers a question: if this object tries to move from A to B, how far can it get and what does it hit? The caller uses the answer to stop, slide, bounce or trigger game behavior.

> **First pass.** Start with **trace_t**, the result of a movement query. `SV_Move` checks the world and candidate solid entities; it does not decide whether a hit means damage or a bounce. **mins/maxs** is the mover's box relative to origin. A **hull** is a collision BSP of **clipnodes**; three pre-expanded world hulls turn common box sizes into a point trace. The **areanode** tree narrows which moving entities need testing. Source: `WinQuake/world.h:28-37`, `WinQuake/world.c:923-961`. [Next: BSP and visibility →](#sec-4)

::: diagram collision

## Where it sits in the frame

Collision has no stage of its own. It is a service called from inside the server stage (`Host_ServerFrame` → `SV_Physics`, `WinQuake/host.c:617`), and almost every interesting call chain in the previous section bottoms out here: `SV_FlyMove` (`WinQuake/sv_phys.c:260`), `SV_PushEntity` (`WinQuake/sv_phys.c:408`), `SV_UserFriction`'s edge probe (`WinQuake/sv_user.c:142`), `SV_CheckWater` via `SV_PointContents` (`WinQuake/sv_phys.c:822`), `SV_movestep` for monsters (`WinQuake/sv_move.c:138,163,171`), and the `traceline` builtin from QuakeC (`WinQuake/pr_cmds.c:621`). The client also calls the hull code directly for the chase camera (`WinQuake/chase.c:55`).

## `trace_t`: the universal result

Every query returns the same eight-field struct (`WinQuake/world.h:28-37`):

```c
typedef struct
{
	qboolean	allsolid;	// if true, plane is not valid
	qboolean	startsolid;	// if true, the initial point was in a solid area
	qboolean	inopen, inwater;
	float	fraction;		// time completed, 1.0 = didn't hit anything
	vec3_t	endpos;			// final position
	plane_t	plane;			// surface normal at impact
	edict_t	*ent;			// entity the surface is on
} trace_t;
```

The distinction between `allsolid` and `startsolid` is load-bearing and easy to get backwards. `startsolid` means the trace *began* inside a solid — the mover is embedded — but it may still have found open space along the way. `allsolid` means it never left solid at all. `allsolid` leaves `fraction` at 1 and `endpos` at the requested end (`WinQuake/world.c:729-733`); the plane is not valid. Callers must test `allsolid` before trusting those fields. The header comment on `SV_Move` (`WinQuake/world.h:72-75`) states the policy: "if the starting point is in a solid, it will be allowed to move out to an open area." A start-in-solid trace that later reaches empty clears `allsolid` and is allowed out; one that never does stays `allsolid`. `SV_FlyMove` turns `allsolid` into "kill velocity, return 3" (`WinQuake/sv_phys.c:262-266`) and does not move, but tolerates `startsolid` silently.

`inopen` / `inwater` record the content types the trace passed through; the QuakeC `traceline` builtin exposes them via `trace_inopen` / `trace_inwater` to distinguish a shot that crossed a water surface. `fraction` is parametric along the move, so callers can determine how much of the requested path was completed; the hit plane is then used to clip velocity.

## The three hulls

This is the central idea, and it is worth being precise about what "hull" means. Carmack later named the absence of exactly this as one of DOOM's bigger misses; [why the hulls are pre-expanded at compile time](design:the-bsp-used-only-for-drawing) is covered in the design history. A `hull_t` (`WinQuake/model.h:169-177`) is a self-contained BSP:

```c
typedef struct
{
	dclipnode_t	*clipnodes;
	mplane_t	*planes;
	int			firstclipnode;
	int			lastclipnode;
	vec3_t		clip_mins;
	vec3_t		clip_maxs;
} hull_t;
```

A `dclipnode_t` is far leaner than the rendering `mnode_t` — a plane index and two children, where a negative child is a `CONTENTS_*` value rather than a node index. There are no surfaces, no textures, no leaf visibility. The clipnode tree exists purely to answer "solid or not" along a line.

Hulls 1 and 2 are built at load time by `Mod_LoadClipnodes` (`WinQuake/model.c:944-981`), which points both at the *same* clipnode lump from the BSP file but records different box sizes:

`WinQuake/model.c:959-981`:

```c
	hull = &loadmodel->hulls[1];
	hull->clipnodes = out;
	hull->firstclipnode = 0;
	hull->lastclipnode = count-1;
	hull->planes = loadmodel->planes;
	hull->clip_mins[0] = -16;
	hull->clip_mins[1] = -16;
	hull->clip_mins[2] = -24;
	hull->clip_maxs[0] = 16;
	hull->clip_maxs[1] = 16;
	hull->clip_maxs[2] = 32;

	hull = &loadmodel->hulls[2];
	hull->clipnodes = out;
	hull->firstclipnode = 0;
	hull->lastclipnode = count-1;
	hull->planes = loadmodel->planes;
	hull->clip_mins[0] = -32;
	hull->clip_mins[1] = -32;
	hull->clip_mins[2] = -24;
	hull->clip_maxs[0] = 32;
	hull->clip_maxs[1] = 32;
	hull->clip_maxs[2] = 64;
```

The `firstclipnode = 0` values are overwritten. `Mod_LoadBrushModel` sets each hull's `firstclipnode` from the submodel's `headnode[]` (`WinQuake/model.c:1189-1198`, `dmodel_t.headnode` at `WinQuake/bspfile.h:86`). Hulls 1 and 2 share one clipnode array; the headnodes pick the roots, including for doors. `MAX_MAP_HULLS` is 4 (`WinQuake/bspfile.h:24`); slot 3 is unused by `SV_HullForEntity`. Hull 0's headnode indexes the transcribed render nodes, not this lump.

Hull 0 is different: it has no clipnodes of its own in the file. `Mod_MakeHull0` (`WinQuake/model.c:998-1028`) *transcribes the rendering BSP* into clipnode form so that point queries can use identical code:

```c
	hull = &loadmodel->hulls[0];	
	
	in = loadmodel->nodes;
	count = loadmodel->numnodes;
	out = Hunk_AllocName ( count*sizeof(*out), loadname);	

	hull->clipnodes = out;
	hull->firstclipnode = 0;
	hull->lastclipnode = count-1;
	hull->planes = loadmodel->planes;

	for (i=0 ; i<count ; i++, out++, in++)
	{
		out->planenum = in->plane - loadmodel->planes;
		for (j=0 ; j<2 ; j++)
		{
			child = in->children[j];
			if (child->contents < 0)
				out->children[j] = child->contents;
			else
				out->children[j] = child - loadmodel->nodes;
		}
	}
```

Note hull 0's `clip_mins`/`clip_maxs` stay zeroed — a point has no size, so no offset correction is needed. Point traces therefore see render geometry: clip-only brushes (`CONTENTS_CLIP`, `WinQuake/bspfile.h:144`) live in hulls 1 and 2, not hull 0.

**Why three?** Because dilating the world by the mover's size at *compile* time turns a swept-box test into a swept-point test at runtime. This is a Minkowski sum baked into the data. Expand each solid obstacle by the reflected mover box: the space where the box’s origin would cause an overlap becomes solid in the expanded world. For example, a box with a 16-unit horizontal half-width must stop its center 16 units before a vertical wall. `qbsp` does this expansion once, offline, so the inner trace only needs a point path after the runtime has selected a hull and applied its offset — `SV_RecursiveHullCheck` only ever traces a line.

The constraint applies to collision against BSP geometry: **there are only three pre-expanded mover sizes.** `SV_HullForEntity` chooses hull 0, 1, or 2 by the mover's X width, for players and monsters alike: under 3 is hull 0 (grenade, nail, rocket), at most 32 is hull 1 (32×32×56, players and most monsters), else hull 2 (64×64×88, large monsters). Against a non-BSP entity the engine fabricates a box hull instead — player vs player is two AABBs, not hull 1 vs hull 1. This is why a rocket can pass through a gap that its player cannot.

> **.plan.** “invisible brushes for clip hull” — [Carmack, 11 Mar 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960311.txt). The collision hull was also a mapper-facing contract: authors could add geometry that shaped movement without adding visible polygons.

Fabien Sanglard's review and Olivier Montanuy's *Unofficial Quake Specs* both cover the hull expansion from the BSP-format side; the specs document the clipnode lump and the per-model `headnode[]` array that selects which hull a submodel uses.

## `SV_HullForEntity`: picking or fabricating a hull

Everything funnels through this selector (`WinQuake/world.c:129-171`):

```c
hull_t *SV_HullForEntity (edict_t *ent, vec3_t mins, vec3_t maxs, vec3_t offset)
{
// decide which clipping hull to use, based on the size
	if (ent->v.solid == SOLID_BSP)
	{	// explicit hulls in the BSP model
		if (ent->v.movetype != MOVETYPE_PUSH)
			Sys_Error ("SOLID_BSP without MOVETYPE_PUSH");

		model = sv.models[ (int)ent->v.modelindex ];

		VectorSubtract (maxs, mins, size);
		if (size[0] < 3)
			hull = &model->hulls[0];
		else if (size[0] <= 32)
			hull = &model->hulls[1];
		else
			hull = &model->hulls[2];

// calculate an offset value to center the origin
		VectorSubtract (hull->clip_mins, mins, offset);
		VectorAdd (offset, ent->v.origin, offset);
	}
	else
	{	// create a temp hull from bounding box sizes

		VectorSubtract (ent->v.mins, maxs, hullmins);
		VectorSubtract (ent->v.maxs, mins, hullmaxs);
		hull = SV_HullForBox (hullmins, hullmaxs);
		
		VectorCopy (ent->v.origin, offset);
	}

	return hull;
}
```

Two paths. For `SOLID_BSP` — the world itself, and every door, platform, and train, which are BSP submodels — hull selection is a threshold decision on the moving object's *X size alone*: point-sized, at most 32 units, or larger. It does not inspect the largest dimension or choose the numerically nearest hull.

The `offset` output is the coordinate correction. Because the dilated hull was built assuming the mover's origin sits at a specific position within its box, the caller's world-space start/end must be shifted into the hull's frame — `VectorSubtract (hull->clip_mins, mins, offset)` computes exactly the discrepancy between the hull's assumed box and the actual box, then adds the entity's origin so a moving door's hull travels with it.

The `else` branch is the elegant part. A non-BSP entity — a monster, an item, another player — is *not* special-cased. Its axis-aligned box is expanded by the mover's box (`ent->v.mins - maxs` … `ent->v.maxs - mins`: again a Minkowski sum, this time computed at runtime) and handed to `SV_HullForBox`, which patches six plane distances into a permanently-allocated 6-node BSP:

`WinQuake/world.c:105-115`:

```c
hull_t	*SV_HullForBox (vec3_t mins, vec3_t maxs)
{
	box_planes[0].dist = maxs[0];
	box_planes[1].dist = mins[0];
	box_planes[2].dist = maxs[1];
	box_planes[3].dist = mins[1];
	box_planes[4].dist = maxs[2];
	box_planes[5].dist = mins[2];

	return &box_hull;
}
```

The topology was built once at level load by `SV_InitBoxHull` (`WinQuake/world.c:68-94`), which chains six clipnodes so that "inside all six planes" reaches `CONTENTS_SOLID` and falling outside any one reaches `CONTENTS_EMPTY`. Its own comment says it best: "To keep everything totally uniform, bounding boxes are turned into small BSP trees instead of being compared directly" (`WinQuake/world.c:101-102`). One trace routine, no branches for entity type. The obvious hazard — `box_hull` is a single `static` (`WinQuake/world.c:56-58`), so a second call clobbers the first — is safe only because the trace is completed before the next `SV_HullForBox`. It is not reentrant, and it does not need to be in a single-threaded engine.

## `SV_RecursiveHullCheck`: the trace

This is the hot function of the server, and its shape is a textbook recursive BSP line clip with two decades of hindsight visible in its epsilon handling (`WinQuake/world.c:581-711`).

The base case (`WinQuake/world.c:592-606`) is reaching a negative child, i.e. a contents value:

```c
// check for empty
	if (num < 0)
	{
		if (num != CONTENTS_SOLID)
		{
			trace->allsolid = false;
			if (num == CONTENTS_EMPTY)
				trace->inopen = true;
			else
				trace->inwater = true;
		}
		else
			trace->startsolid = true;
		return true;		// empty
	}
```

Note `trace->allsolid` starts `true` (set by the caller, `WinQuake/world.c:732`) and is cleared the first time any non-solid region is touched — that is the entire implementation of "the whole move was inside a solid."

The recursive case computes signed distances of both endpoints from the node plane and, if both are on the same side, descends without splitting:

`WinQuake/world.c:614-638`:

```c
	node = hull->clipnodes + num;
	plane = hull->planes + node->planenum;

	if (plane->type < 3)
	{
		t1 = p1[plane->type] - plane->dist;
		t2 = p2[plane->type] - plane->dist;
	}
	else
	{
		t1 = DotProduct (plane->normal, p1) - plane->dist;
		t2 = DotProduct (plane->normal, p2) - plane->dist;
	}
	
#if 1
	if (t1 >= 0 && t2 >= 0)
		return SV_RecursiveHullCheck (hull, node->children[0], p1f, p2f, p1, p2, trace);
	if (t1 < 0 && t2 < 0)
		return SV_RecursiveHullCheck (hull, node->children[1], p1f, p2f, p1, p2, trace);
#else
	if ( (t1 >= DIST_EPSILON && t2 >= DIST_EPSILON) || (t2 > t1 && t1 >= 0) )
		return SV_RecursiveHullCheck (hull, node->children[0], p1f, p2f, p1, p2, trace);
	if ( (t1 <= -DIST_EPSILON && t2 <= -DIST_EPSILON) || (t2 < t1 && t1 <= 0) )
		return SV_RecursiveHullCheck (hull, node->children[1], p1f, p2f, p1, p2, trace);
#endif
```

The `plane->type < 3` fast path is the same trick the renderer uses: axis-aligned planes (the overwhelming majority in a Quake map, and *all six* of a box hull) skip the dot product for a single array index and subtract. The `#if 1` / `#else` pair is a preserved experiment — a version with slack epsilons on the same-side test, disabled in the shipping build.

When the segment straddles the plane, it is split — with the crossing point deliberately pulled back:

`WinQuake/world.c:640-654`:

```c
// put the crosspoint DIST_EPSILON pixels on the near side
	if (t1 < 0)
		frac = (t1 + DIST_EPSILON)/(t1-t2);
	else
		frac = (t1 - DIST_EPSILON)/(t1-t2);
	if (frac < 0)
		frac = 0;
	if (frac > 1)
		frac = 1;
		
	midf = p1f + (p2f - p1f)*frac;
	for (i=0 ; i<3 ; i++)
		mid[i] = p1[i] + frac*(p2[i] - p1[i]);

	side = (t1 < 0);
```

`DIST_EPSILON` is `0.03125` — 1/32 — chosen, per the comment at `WinQuake/world.c:572-573`, "to keep floating point happy." The constant itself is exactly representable in binary, though arithmetic using it can still round. Backing every split point 1/32 unit toward the near side means an entity is never left mathematically *on* a surface, where the next frame's `SV_HullPointContents` could round it to the solid side and jam it in a wall. This one constant is why players stand 1/32 of a unit above the floor in Quake, and it is the same epsilon that `SV_WalkMove` tests against when deciding whether stepping up made progress (`WinQuake/sv_phys.c:1019-1020`).

The near half is recursed first; only if it reports clear does the far half get considered:

`WinQuake/world.c:656-675`:

```c
// move up to the node
	if (!SV_RecursiveHullCheck (hull, node->children[side], p1f, midf, p1, mid, trace) )
		return false;

	if (SV_HullPointContents (hull, node->children[side^1], mid)
	!= CONTENTS_SOLID)
// go past the node
		return SV_RecursiveHullCheck (hull, node->children[side^1], midf, p2f, mid, p2, trace);
	
	if (trace->allsolid)
		return false;		// never got out of the solid area
```

The return value is "keep going," so a `false` propagates all the way out the instant an impact is recorded — the trace is front-to-back and stops at the first hit without any distance comparison. This ordering is what makes the average trace cost a handful of nodes rather than a full tree walk.

Finally, the impact is recorded with the plane flipped if approached from behind, and — the tell-tale of production code — a retry loop:

`WinQuake/world.c:680-708`:

```c
	if (!side)
	{
		VectorCopy (plane->normal, trace->plane.normal);
		trace->plane.dist = plane->dist;
	}
	else
	{
		VectorSubtract (vec3_origin, plane->normal, trace->plane.normal);
		trace->plane.dist = -plane->dist;
	}

	while (SV_HullPointContents (hull, hull->firstclipnode, mid)
	== CONTENTS_SOLID)
	{ // shouldn't really happen, but does occasionally
		frac -= 0.1;
		if (frac < 0)
		{
			trace->fraction = midf;
			VectorCopy (mid, trace->endpos);
			Con_DPrintf ("backup past 0\n");
			return false;
		}
		midf = p1f + (p2f - p1f)*frac;
		for (i=0 ; i<3 ; i++)
			mid[i] = p1[i] + frac*(p2[i] - p1[i]);
	}
```

"Shouldn't really happen, but does occasionally": even with `DIST_EPSILON`, the impact point sometimes classifies as solid, so the code walks backward along the segment in 10% steps until it finds free space. A correctness fallback for accumulated float error, retained because it was cheaper than making the geometry exact.

`SV_HullPointContents` (`WinQuake/world.c:491-516`) is the iterative point-classification counterpart — descend until a negative child, return it. It is the single most-called function in the server, and it has a hand-written i386 assembly version (`WinQuake/worlda.s:47-48`) selected by `#if !id386` around the C one (`WinQuake/world.c:483`), with `asm_i386.h:37` warning that the struct layout is duplicated in the assembler.

## `SV_ClipMoveToEntity`: one entity, one trace

`SV_ClipMoveToEntity` (`WinQuake/world.c:722-803`) is the adapter between world-space queries and hull-space traces:

```c
// fill in a default trace
	memset (&trace, 0, sizeof(trace_t));
	trace.fraction = 1;
	trace.allsolid = true;
	VectorCopy (end, trace.endpos);

// get the clipping hull
	hull = SV_HullForEntity (ent, mins, maxs, offset);

	VectorSubtract (start, offset, start_l);
	VectorSubtract (end, offset, end_l);

// trace a line through the apropriate clipping hull
	SV_RecursiveHullCheck (hull, hull->firstclipnode, 0, 1, start_l, end_l, &trace);

// fix trace up by the offset
	if (trace.fraction != 1)
		VectorAdd (trace.endpos, offset, trace.endpos);

// did we clip the move?
	if (trace.fraction < 1 || trace.startsolid  )
		trace.ent = ent;
```

The pattern is: subtract the offset going in, add it back coming out. `p1f`/`p2f` start at `0`/`1` so `fraction` comes out parametric. The `#ifdef QUAKE2` blocks between these steps (`WinQuake/world.c:741-792`) rotate the endpoints into a rotating brush model's frame and the results back out — Quake II's rotating-door support, present but compiled out.

## `SV_Move` and the areanode tree

`SV_Move` (`WinQuake/world.c:923-961`) is the public entry point, and it is short because all it does is compose: trace the world (edict 0, BSP hulls), then trace whatever solid entities the move's bounding box could reach (box hull, or BSP hulls for doors).

```c
	memset ( &clip, 0, sizeof ( moveclip_t ) );

// clip to world
	clip.trace = SV_ClipMoveToEntity ( sv.edicts, start, mins, maxs, end );

	clip.start = start;   clip.end = end;
	clip.mins = mins;     clip.maxs = maxs;
	clip.type = type;     clip.passedict = passedict;

	if (type == MOVE_MISSILE)
	{
		for (i=0 ; i<3 ; i++)
		{
			clip.mins2[i] = -15;
			clip.maxs2[i] = 15;
		}
	}
	else
	{
		VectorCopy (mins, clip.mins2);
		VectorCopy (maxs, clip.maxs2);
	}
	
// create the bounding box of the entire move
	SV_MoveBounds ( start, clip.mins2, clip.maxs2, end, clip.boxmins, clip.boxmaxs );

// clip to entities
	SV_ClipToLinks ( sv_areanodes, &clip );
```

`MOVE_MISSILE` (`WinQuake/world.h:42`) expands only the entity search: a rocket stays a point against the world and against players, but `SV_ClipToLinks` uses a ±15 box (`mins2`/`maxs2`) against `FL_MONSTER` (`WinQuake/world.c:857-860`). Players are not `FL_MONSTER`, so deathmatch rocket hits are point-vs-AABB. Against monsters the larger box is why a near miss still hits. `MOVE_NOMONSTERS` (`WinQuake/world.h:41`) is the opposite lever, used for line-of-sight and edge tests.

`SV_MoveBounds` (`WinQuake/world.c:893-916`) computes the AABB swept by the whole move, padded by one unit on each side, and — as with the `#if 0` "test against everything" debug branch at `WinQuake/world.c:895-898` — the padding and the debug escape hatch tell you this code was tuned against real bugs.

### The areanode tree

Entity-vs-entity culling uses a second spatial structure, entirely separate from the BSP. `areanode_t` (`WinQuake/world.c:181-188`):

```c
typedef struct areanode_s
{
	int		axis;		// -1 = leaf node
	float	dist;
	struct areanode_s	*children[2];
	link_t	trigger_edicts;
	link_t	solid_edicts;
} areanode_t;

#define	AREA_DEPTH	4
#define	AREA_NODES	32
```

It is a depth-4 balanced 2D k-d tree over the map's X/Y extent — 31 nodes, statically allocated (`WinQuake/world.c:193`), built once by `SV_CreateAreaNode` (`WinQuake/world.c:202-239`) splitting the longer horizontal axis at each level:

```c
	VectorSubtract (maxs, mins, size);
	if (size[0] > size[1])
		anode->axis = 0;
	else
		anode->axis = 1;
	
	anode->dist = 0.5 * (maxs[anode->axis] + mins[anode->axis]);
```

No Z split at all — Quake maps are wide and comparatively flat, so a third axis wasn't worth the nodes. Each node holds two intrusive doubly-linked lists (`link_t`, `WinQuake/common.h`): triggers separately from solids, so `SV_ClipToLinks` never has to test-and-skip triggers and `SV_TouchLinks` never has to walk solids. That is why `SV_ClipToLinks` can `Sys_Error ("Trigger in clipping list")` (`WinQuake/world.c:830`) as a pure invariant assertion.

An entity is stored at the *highest* node whose split plane its box crosses — the classic loose k-d placement:

`WinQuake/world.c:447-466`:

```c
// find the first node that the ent's box crosses
	node = sv_areanodes;
	while (1)
	{
		if (node->axis == -1)
			break;
		if (ent->v.absmin[node->axis] > node->dist)
			node = node->children[0];
		else if (ent->v.absmax[node->axis] < node->dist)
			node = node->children[1];
		else
			break;		// crosses the node
	}
	
// link it in	
	if (ent->v.solid == SOLID_TRIGGER)
		InsertLinkBefore (&ent->area, &node->trigger_edicts);
	else
		InsertLinkBefore (&ent->area, &node->solid_edicts);
```

so a query can visit only the nodes its own box overlaps and be guaranteed to see every candidate. `SV_ClipToLinks` (`WinQuake/world.c:814-885`) does exactly that, testing the node's solid list then descending to whichever children the move's box straddles:

```c
// recurse down both sides
	if (node->axis == -1)
		return;

	if ( clip->boxmaxs[node->axis] > node->dist )
		SV_ClipToLinks ( node->children[0], clip );
	if ( clip->boxmins[node->axis] < node->dist )
		SV_ClipToLinks ( node->children[1], clip );
```

Before the expensive `SV_ClipMoveToEntity`, each candidate goes through a cheap filter chain (`WinQuake/world.c:825-855`): skip `SOLID_NOT`, skip `passedict` itself, skip non-BSP entities under `MOVE_NOMONSTERS`, reject by AABB overlap, skip point-vs-point pairs ("points never interact"), and — the two lines that make rocket jumping possible —

```c
		if (clip->passedict)
		{
		 	if (PROG_TO_EDICT(touch->v.owner) == clip->passedict)
				continue;	// don't clip against own missiles
			if (PROG_TO_EDICT(clip->passedict->v.owner) == touch)
				continue;	// don't clip against owner
		}
```

The `.owner` field is set by QuakeC when spawning a projectile; the engine then makes shooter and projectile mutually transparent. Without it every rocket would detonate on the barrel it left.

The merge step (`WinQuake/world.c:861-874`) keeps the nearest hit, with the special rule that a `startsolid` flag is sticky across candidates even when a later trace supersedes the trace record.

## `SV_LinkEdict`: keeping both structures current

`SV_LinkEdict` (`WinQuake/world.c:372-471`) is the write side of everything above, and it also feeds the PVS transmission described in the server section. Its contract (`WinQuake/world.h:53-57`) is that it must be called any time an entity's origin, mins, maxs, or solid changes — which is why `PF_setorigin` exists as a builtin at all rather than letting QuakeC assign `.origin` directly.

It does four things. It recomputes the world-space bounds:

```c
		VectorAdd (ent->v.origin, ent->v.mins, ent->v.absmin);	
		VectorAdd (ent->v.origin, ent->v.maxs, ent->v.absmax);
```

Then it fudges them (`WinQuake/world.c:417-437`):

```c
//
// to make items easier to pick up and allow them to be grabbed off
// of shelves, the abs sizes are expanded
//
	if ((int)ent->v.flags & FL_ITEM)
	{
		ent->v.absmin[0] -= 15;
		ent->v.absmin[1] -= 15;
		ent->v.absmax[0] += 15;
		ent->v.absmax[1] += 15;
	}
	else
	{	// because movement is clipped an epsilon away from an actual edge,
		// we must fully check even when bounding boxes don't quite touch
		ent->v.absmin[0] -= 1;
		ent->v.absmin[1] -= 1;
		...
	}
```

Two different epsilons for two different reasons: items get a 15-unit horizontal grab radius because feeling like you picked up the shotgun matters more than geometric truth, and everything else gets 1 unit because `DIST_EPSILON` stops movers 1/32 short of contact and a strict AABB test would then miss touches that should register. The second comment is a direct consequence of the trace epsilon three sections up.

Third, it refreshes the PVS leaf cache used by `SV_WriteEntitiesToClient`, via `SV_FindTouchedLeafs` (`WinQuake/world.c:328-364`) walking the rendering BSP with `BOX_ON_PLANE_SIDE` and recording up to `MAX_ENT_LEAFS` (16) leaf numbers. An entity straddling more than 16 leaves silently truncates (`WinQuake/world.c:342-343`); the send-side consequence is in [BSP and PVS](#sec-4). Note the guard `if (ent->v.modelindex)` at `WinQuake/world.c:441`: invisible logic entities skip this entirely.

Fourth, it links into the areanode tree (unless `SOLID_NOT`, `WinQuake/world.c:444-445`) and optionally fires triggers.

`SV_UnlinkEdict` (`WinQuake/world.c:263-269`) is four lines of intrusive-list removal, and `SV_LinkEdict` calls it first — relinking is unlink-then-link, always.

### `SV_TouchLinks`

Trigger dispatch (`WinQuake/world.c:277-319`) walks the *trigger* lists of every areanode the entity's box overlaps and calls QuakeC:

```c
	for (l = node->trigger_edicts.next ; l != &node->trigger_edicts ; l = next)
	{
		next = l->next;
		touch = EDICT_FROM_AREA(l);
		if (touch == ent)
			continue;
		if (!touch->v.touch || touch->v.solid != SOLID_TRIGGER)
			continue;
		if (ent->v.absmin[0] > touch->v.absmax[0]
		|| ... )
			continue;
		old_self = pr_global_struct->self;
		old_other = pr_global_struct->other;

		pr_global_struct->self = EDICT_TO_PROG(touch);
		pr_global_struct->other = EDICT_TO_PROG(ent);
		pr_global_struct->time = sv.time;
		PR_ExecuteProgram (touch->v.touch);

		pr_global_struct->self = old_self;
		pr_global_struct->other = old_other;
	}
```

Three details. `next = l->next` is captured *before* the QuakeC call, because a touch function can legally `remove()` the trigger and unlink it mid-iteration — the classic teleporter/pickup case. The `self`/`other` globals are saved and restored around the call because `SV_TouchLinks` can be re-entered: a touch function can invoke movement such as `walkmove`, which relinks with trigger touching enabled. `setorigin` itself passes `false` for trigger touching (`WinQuake/pr_cmds.c:120-129`). And the touch is a pure AABB overlap test — triggers are boxes, never hulls, so a trigger's shape is exactly its bounding box regardless of the brushes it was built from.

Trigger detection is thus decoupled from movement: `SV_FlyMove` handles blocking collisions and calls `SV_Impact`, while triggers fire from the post-move relink. That is why walking through a trigger never slows you down and why a very fast projectile can pass *through* a thin trigger between frames without firing it — the check is on the endpoint, not the swept volume.

## Point-in-solid checks

`SV_PointContents` (`WinQuake/world.c:527-535`) is the world-only, entity-free query, and it does one extra thing:

```c
	cont = SV_HullPointContents (&sv.worldmodel->hulls[0], 0, p);
	if (cont <= CONTENTS_CURRENT_0 && cont >= CONTENTS_CURRENT_DOWN)
		cont = CONTENTS_WATER;
	return cont;
```

Directional water currents (`CONTENTS_CURRENT_*`) are remapped to plain water so callers that only care "am I wet" need no knowledge of currents; `SV_TruePointContents` (`WinQuake/world.c:537-540`) skips the remap. This is what `SV_CheckWater` samples at three heights.

`SV_TestEntityPosition` (`WinQuake/world.c:551-561`) is the "am I embedded" test, and it is charmingly literal — a zero-length `SV_Move` from the entity's origin to the same origin, checking `startsolid`:

```c
edict_t	*SV_TestEntityPosition (edict_t *ent)
{
	trace_t	trace;

	trace = SV_Move (ent->v.origin, ent->v.mins, ent->v.maxs, ent->v.origin, 0, ent);
	
	if (trace.startsolid)
		return sv.edicts;
		
	return NULL;
}
```

The "This could be a lot more efficient..." comment (`WinQuake/world.c:548`) is id's own note that a dedicated point-classify would beat a degenerate trace. It is still used on the per-frame player path below, so its cost depends on how often those callers need to test a position.

Its main consumer is `SV_CheckStuck` (`WinQuake/sv_phys.c:762-800`), which runs for every walking player every frame and, if stuck, first tries `oldorigin` and then brute-forces a 3×3×18 grid of unit offsets looking for daylight:

```c
	for (z=0 ; z< 18 ; z++)
		for (i=-1 ; i <= 1 ; i++)
			for (j=-1 ; j <= 1 ; j++)
			{
				ent->v.origin[0] = org[0] + i;
				ent->v.origin[1] = org[1] + j;
				ent->v.origin[2] = org[2] + z;
				if (!SV_TestEntityPosition (ent))
				{
					Con_DPrintf ("Unstuck.\n");
					SV_LinkEdict (ent, true);
					return;
				}
			}
			
	VectorCopy (org, ent->v.origin);
	Con_DPrintf ("player is stuck.\n");
```

162 full `SV_Move` calls in the worst case, biased upward (z from 0 to 17) because pushing a player *up* is almost always the right escape. The function's own header calls it "a big hack to try and fix the rare case of getting stuck in the world clipping hull" (`WinQuake/sv_phys.c:758-759`). It is the frankest admission in the codebase that three precompiled hulls plus float arithmetic occasionally produce states the model says are impossible.

`SV_TryUnstick` (`WinQuake/sv_phys.c:901`) is the movement-time cousin, nudging in eight compass directions when a step-up made no progress.

## Monster movement: `sv_move.c`

Monsters do not use `SV_WalkMove`. `MOVETYPE_STEP` physics only handles falling (`WinQuake/sv_phys.c:1468-1496`); horizontal movement is driven explicitly from QuakeC through the `walkmove` and `movetogoal` builtins into `SV_movestep` (`WinQuake/sv_move.c:110-218`).

For ground monsters the move is done as a *drop from above*, not a slide:

`WinQuake/sv_move.c:158-189`:

```c
// push down from a step height above the wished position
	neworg[2] += STEPSIZE;
	VectorCopy (neworg, end);
	end[2] -= STEPSIZE*2;

	trace = SV_Move (neworg, ent->v.mins, ent->v.maxs, end, false, ent);

	if (trace.allsolid)
		return false;

	if (trace.startsolid)
	{
		neworg[2] -= STEPSIZE;
		trace = SV_Move (neworg, ent->v.mins, ent->v.maxs, end, false, ent);
		if (trace.allsolid || trace.startsolid)
			return false;
	}
	if (trace.fraction == 1)
	{
	// if monster had the ground pulled out, go ahead and fall
		if ( (int)ent->v.flags & FL_PARTIALGROUND )
		{
			...
		}
	
		return false;		// walked off an edge
	}
```

Lift 18 units, drop 36, and see where you land. One trace resolves stepping up onto a stair, stepping down off a ledge, and refusing to walk into a wall — `fraction == 1` means nothing was hit within 36 units, i.e. a cliff, and the move is rejected. Grounded monsters normally reject such a move. `FL_PARTIALGROUND` supplies exceptions for monsters that have already lost support (`WinQuake/sv_move.c:174-211`); flying and swimming monsters follow different rules.

Then the corner check. `SV_CheckBottom` (`WinQuake/sv_move.c:37-97`) verifies the monster isn't left balanced on a corner. It first tries the cheap path — four `SV_PointContents` probes one unit under the box corners, and if all four are solid world it returns immediately (`WinQuake/sv_move.c:47-61`, incrementing the `c_yes`/`c_no` counters at `WinQuake/sv_move.c:35` that exist purely to measure that fast path's hit rate). Only on failure does it do the expensive version: trace down from the midpoint, then from each corner, rejecting if any corner is more than `STEPSIZE` below the middle:

```c
			trace = SV_Move (start, vec3_origin, vec3_origin, stop, true, ent);
			
			if (trace.fraction != 1.0 && trace.endpos[2] > bottom)
				bottom = trace.endpos[2];
			if (trace.fraction == 1.0 || mid - trace.endpos[2] > STEPSIZE)
				return false;
```

Flying and swimming monsters take a different branch entirely (`WinQuake/sv_move.c:122-156`), with a nice touch: a flier tries its move twice, first with a vertical bias toward its enemy (±8 units depending on whether it is more than 40 above or less than 30 below), falling back to level flight if that fails. That is the whole of Scrag altitude-matching AI — nine lines.

`SV_StepDirection` (`WinQuake/sv_move.c:233-260`) is the layer above, turning a desired yaw into a move:

```c
	ent->v.ideal_yaw = yaw;
	PF_changeyaw();
	
	yaw = yaw*M_PI*2 / 360;
	move[0] = cos(yaw)*dist;
	move[1] = sin(yaw)*dist;
	move[2] = 0;

	VectorCopy (ent->v.origin, oldorigin);
	if (SV_movestep (ent, move, false))
	{
		delta = ent->v.angles[YAW] - ent->v.ideal_yaw;
		if (delta > 45 && delta < 315)
		{		// not turned far enough, so don't take the step
			VectorCopy (oldorigin, ent->v.origin);
		}
		SV_LinkEdict (ent, true);
		return true;
	}
```

It calls `PF_changeyaw` — a *builtin* — directly from C, turns first, and rolls the position back if the monster hasn't yet rotated within 45° of its intended heading. Monsters therefore pivot before they walk, which reads as deliberate rather than robotic. `SV_NewChaseDir` (`WinQuake/sv_move.c:284`) picks candidate yaws when the direct one fails, and `SV_MoveToGoal` (`WinQuake/sv_move.c:393`) is the builtin QuakeC actually calls each think.

`PF_walkmove` (`WinQuake/pr_cmds.c:1146-1180`) shows the VM/engine boundary being crossed carefully in both directions:

```c
// save program state, because SV_movestep may call other progs
	oldf = pr_xfunction;
	oldself = pr_global_struct->self;
	
	G_FLOAT(OFS_RETURN) = SV_movestep(ent, move, true);
	
// restore program state
	pr_xfunction = oldf;
	pr_global_struct->self = oldself;
```

QuakeC calls into C, which relinks the entity, which fires triggers, which calls back into QuakeC. The interpreter's current-function pointer and `self` must be saved by hand because these globals must survive the nested callback. The interpreter does have explicit call and local-save stacks; that does not automatically preserve every engine-visible VM global across a builtin.

## Hitscan vs. projectiles in progs

The two damage models in Quake differ entirely at the QuakeC level, using the same engine primitives.

**Hitscan** — shotgun, super shotgun, lightning, enemy soldiers — is `traceline` and instant resolution. `PF_traceline` (`WinQuake/pr_cmds.c:609-635`) is a thin wrapper over a zero-extent `SV_Move`:

```c
	v1 = G_VECTOR(OFS_PARM0);
	v2 = G_VECTOR(OFS_PARM1);
	nomonsters = G_FLOAT(OFS_PARM2);
	ent = G_EDICT(OFS_PARM3);

	trace = SV_Move (v1, vec3_origin, vec3_origin, v2, nomonsters, ent);

	pr_global_struct->trace_allsolid = trace.allsolid;
	pr_global_struct->trace_startsolid = trace.startsolid;
	pr_global_struct->trace_fraction = trace.fraction;
	pr_global_struct->trace_inwater = trace.inwater;
	pr_global_struct->trace_inopen = trace.inopen;
	VectorCopy (trace.endpos, pr_global_struct->trace_endpos);
	VectorCopy (trace.plane.normal, pr_global_struct->trace_plane_normal);
	pr_global_struct->trace_plane_dist =  trace.plane.dist;	
	if (trace.ent)
		pr_global_struct->trace_ent = EDICT_TO_PROG(trace.ent);
	else
		pr_global_struct->trace_ent = EDICT_TO_PROG(sv.edicts);
```

Results are returned through *globals*, not a return value, because the QuakeC ABI has one `OFS_RETURN` slot and a trace has eight fields. Note the `trace_ent` fallback: a miss reports the world (edict 0), so QuakeC can unconditionally read `trace_ent` and compare `.takedamage`. `nomonsters` maps straight onto `MOVE_NOMONSTERS`, and passing the shooter as `ent` reuses `SV_ClipToLinks`'s `passedict` exclusion so you cannot shoot yourself.

Because `mins`/`maxs` are `vec3_origin`, hitscan uses **hull 0** against the world and each target's own bounding box (via `SV_HullForBox`) against entities. Player hit detection in Quake is therefore box-vs-ray against a 32×32×56 AABB — no per-limb hitboxes, no model geometry, no head shots.

The QuakeC side is a loop of traces. NetQuake QC is not in the GPL engine tree; the official source is `qcc/v101qc/weapons.qc` in [Quake-Tools](https://github.com/id-Software/Quake-Tools/blob/master/qcc/v101qc/weapons.qc). `FireBullets` (`weapons.qc:253-275`):

```c
	ClearMultiDamage ();
	while (shotcount > 0)
	{
		direction = dir + crandom()*spread_x*v_right + crandom()*spread_y*v_up;

		traceline (src, src + direction*2048, FALSE, self);
		if (trace_fraction != 1.0)
			TraceAttack (4, direction);

		shotcount = shotcount - 1;
	}
	ApplyMultiDamage ();
```

Six traces for the shotgun (`weapons.qc:292`), fourteen for the super shotgun (`weapons.qc:317`), every shot — `2048` units is the hard-coded weapon range. `ClearMultiDamage`/`ApplyMultiDamage` coalesce pellets into one damage event so a target doesn't run its pain animation fourteen times. QuakeWorld's copy (`qw-qc/weapons.qc:290-315`) adds a sighting `traceline` for `puff_org` and a `Multi_Finish` after apply; those are not in NetQuake.

**Projectiles** are edicts. QuakeC spawns one, sets `.movetype` to `MOVETYPE_FLYMISSILE`, `.solid` to `SOLID_BBOX`, `.owner` to the shooter, and a `.touch` function; the engine then moves it each frame through `SV_Physics_Toss` → `SV_PushEntity` → `SV_Move`, and `SV_Impact` (`WinQuake/sv_phys.c:153`) invokes the touch function on contact. `MOVETYPE_FLYMISSILE` is what selects `MOVE_MISSILE` and the ±15 monster-clipping expansion described above.

So: hitscan is *N* traces resolved this instant with no entity created; projectiles are one entity traced once per frame until something touches it. Hitscan costs CPU at fire time and nothing thereafter; projectiles cost an edict slot, per-frame physics, and network bandwidth for as long as they fly. On a 1996 server with `MAX_EDICTS` 600 (`WinQuake/quakedef.h:107`), that mattered.

## Call graph

```
SV_Move (start, mins, maxs, end, type, passedict)      world.c:923
  SV_ClipMoveToEntity(sv.edicts, ...)   // the world   world.c:722
    SV_HullForEntity                                   world.c:129
      SV_HullForBox        [non-BSP entities]          world.c:105
        (topology from SV_InitBoxHull)                 world.c:68
      model->hulls[0|1|2]  [SOLID_BSP]                 model.c:998 / 944, 1189-1198
    SV_RecursiveHullCheck                              world.c:581
      SV_HullPointContents                             world.c:491 (asm: worlda.s:47)
      (recurse near side, then far side)               world.c:657, 672
  SV_MoveBounds                                        world.c:893
  SV_ClipToLinks (sv_areanodes, &clip)                 world.c:814
    (filters: SOLID_NOT, passedict, .owner, AABB)      world.c:825-855
    SV_ClipMoveToEntity(touch, ...)                    world.c:722
    (descend children the move box straddles)          world.c:881-884

SV_LinkEdict (ent, touch_triggers)                     world.c:372
  SV_UnlinkEdict                                       world.c:263
  absmin/absmax + FL_ITEM / 1-unit expansion           world.c:413-437
  SV_FindTouchedLeafs -> ent->leafnums[]               world.c:328
  insert into areanode trigger_edicts / solid_edicts   world.c:463-466
  SV_TouchLinks                                        world.c:277
    PR_ExecuteProgram (touch->v.touch)                 world.c:305

SV_PointContents                                       world.c:527
  SV_HullPointContents (worldmodel->hulls[0])          world.c:491
SV_TruePointContents                                   world.c:537
SV_TestEntityPosition -> SV_Move(origin -> origin)     world.c:551
  <- SV_CheckStuck                                     sv_phys.c:762
  <- SV_TryUnstick                                     sv_phys.c:901

SV_movestep (monsters)                                 sv_move.c:110
  SV_Move  [fly/swim branch]                           sv_move.c:138
  SV_Move  [lift STEPSIZE, drop 2*STEPSIZE]            sv_move.c:163, 171
  SV_CheckBottom                                       sv_move.c:37
    SV_PointContents  [4 corner fast path]             sv_move.c:56
    SV_Move           [midpoint + 4 corners]           sv_move.c:74, 87
  SV_LinkEdict                                         world.c:372
SV_StepDirection                                       sv_move.c:233
  PF_changeyaw                                         pr_cmds.c:1412
  SV_movestep                                          sv_move.c:110
SV_NewChaseDir / SV_MoveToGoal                         sv_move.c:284 / 393

PF_traceline  (QuakeC "traceline")                     pr_cmds.c:609
  SV_Move (v1, 0, 0, v2, nomonsters, ent)              world.c:923
PF_walkmove   (QuakeC "walkmove")                      pr_cmds.c:1146
  SV_movestep                                          sv_move.c:110
PF_droptofloor                                         pr_cmds.c:1189
PF_setorigin -> SV_LinkEdict                           pr_cmds.c:120
```

## Key data structures

- `trace_t` — `WinQuake/world.h:28-37` — the universal query result: `allsolid`, `startsolid`, `inopen`/`inwater`, `fraction`, `endpos`, `plane`, `ent`.
- `plane_t` — `WinQuake/world.h:22-26` — impact plane (normal + distance) reported in `trace_t`; distinct from the renderer's `mplane_t`.
- `hull_t` — `WinQuake/model.h:169-177` — a collision BSP: clipnodes, planes, node range, and the `clip_mins`/`clip_maxs` the hull was dilated for.
- `dclipnode_t` — `WinQuake/bspfile.h:165-169` — plane index + two children; negative child = `CONTENTS_*`. The whole collision tree is made of these.
- `model_t.hulls[MAX_MAP_HULLS]` — `WinQuake/model.h:355`, `MAX_MAP_HULLS` = 4 (`WinQuake/bspfile.h:24`) — hull 0 point (built by `Mod_MakeHull0`, `WinQuake/model.c:998`), hull 1 32×32×56, hull 2 64×64×88 (`WinQuake/model.c:959-981`); `firstclipnode` from `dmodel_t.headnode[]` (`WinQuake/model.c:1189-1198`); slot 3 unused by `SV_HullForEntity`.
- `box_hull` / `box_clipnodes[6]` / `box_planes[6]` — `WinQuake/world.c:56-58` — the single reusable six-plane BSP that makes an AABB traceable by the same code as the world.
- `areanode_t` — `WinQuake/world.c:181-188` — depth-4 X/Y k-d node holding two intrusive lists, `trigger_edicts` and `solid_edicts`; `AREA_DEPTH` 4, `AREA_NODES` 32 (`WinQuake/world.c:190-191`), storage at `WinQuake/world.c:193`.
- `link_t` / `edict_t.area` — `WinQuake/common.h:52-55`, `WinQuake/progs.h:38` — intrusive doubly-linked list node embedded in every edict; `EDICT_FROM_AREA` recovers the edict.
- `moveclip_t` — `WinQuake/world.c:33-42` — per-`SV_Move` scratch: swept `boxmins`/`boxmaxs`, the mover's `mins`/`maxs`, the monster-only `mins2`/`maxs2`, `type`, `passedict`, and the accumulating `trace`.
- `edict_t.leafnums[MAX_ENT_LEAFS]` / `num_leafs` — `WinQuake/progs.h:40-41`, `MAX_ENT_LEAFS` = 16 (`WinQuake/progs.h:34`) — BSP leaves the entity touches, filled by `SV_FindTouchedLeafs` during link; consumed by PVS transmission.
- `SOLID_*` — `WinQuake/server.h:132-136` — `NOT` (unlinked), `TRIGGER` (touch, don't block), `BBOX`, `SLIDEBOX`, `BSP` (use the model's hulls).
- `MOVE_NORMAL` / `MOVE_NOMONSTERS` / `MOVE_MISSILE` — `WinQuake/world.h:40-42` — the `type` argument to `SV_Move`; `MOVE_MISSILE` swaps in the ±15 monster-clip box.
- `DIST_EPSILON` (0.03125) — `WinQuake/world.c:573` — the 1/32-unit standoff that keeps traces from landing exactly on planes.
- `STEPSIZE` (18) — `WinQuake/sv_phys.c:957` and `WinQuake/sv_move.c:24` — duplicate `#define`s; maximum step height for `SV_WalkMove` and `SV_movestep`/`SV_CheckBottom`.

## Further reading

- Fabien Sanglard, "Quake Source Code Review" — the clearest external treatment of the three clipping hulls and why the BSP is expanded at compile time: https://fabiensanglard.net/quakeSource/index.php
- Olivier Montanuy et al., "Unofficial Quake Specs" — the BSP file format, the clipnode lump, and the per-model `headnode[]` array that selects hulls: https://www.gamers.org/dEngine/quake/spec/quake-spec34/ (archived: https://web.archive.org/web/20251206223630/https://www.gamers.org/dEngine/quake/spec/quake-spec34/)
- Quake BSP format specifics (nodes, clipnodes, planes, contents values): https://www.gamers.org/dEngine/quake/spec/quake-spec34/qkspec_4.htm (archived: https://web.archive.org/web/20250222033358/https://www.gamers.org/dEngine/quake/spec/quake-spec34/qkspec_4.htm)
- Michael Abrash, *Graphics Programming Black Book*, ch. 59–64 — BSP construction and traversal; the same tree the collision hulls are derived from: https://www.jagregory.com/abrash-black-book/
- QuakeC reference — `traceline`, `walkmove`, `movetogoal`, `droptofloor`, and the `trace_*` globals: https://www.gamers.org/dEngine/quake/spec/quake-spec34/qc-menu.htm (archived: https://web.archive.org/web/20251124162531/https://www.gamers.org/dEngine/quake/spec/quake-spec34/qc-menu.htm)
- id Software, NetQuake QuakeC (`qcc/v101qc`, GPL via Quake-Tools) — `FireBullets` and the weapon traces: https://github.com/id-Software/Quake-Tools/blob/master/qcc/v101qc/weapons.qc
- John Carmack .plan archive — contemporaneous notes on collision, stuck players, and hull limitations: https://github.com/ESWAT/john-carmack-plan-archive
- Matthew Earl (Matt's Ramblings), "Uncovering Quake's unseen collision hulls" (2025) — the expanded hulls visualised against the render geometry: https://www.youtube.com/watch?v=3KjMjHJ3WQg
- Matthew Earl (Matt's Ramblings), "BSP Trees: The Magic Behind Collision Detection in Quake" (2023) — the trace as a tree descent: https://www.youtube.com/watch?v=wLHXn8IlAiA
- Matthew Earl (Matt's Ramblings), "Shooting Through Walls: Unraveling the Code Behind Quake's Lightning Gun Bug" (2023) — a trace bug traced to its source: https://www.youtube.com/watch?v=4gNYTqn3qRc
