# BSP and PVS

Quake does expensive preparation before a level is played. The resulting BSP
file gives the engine spatial partitions, collision data, potentially visible
regions and baked lighting that it can reuse each frame.

> **First pass.** BSP is the spatial tree. A **leaf** is a convex cell at the
> end of a walk of that tree. **PVS** is a conservative per-leaf bitset of other
> leaves that might be visible from it — not a line-of-sight test. The client
> stamps **visframe** on those leaves so the world walk can skip the rest. The
> server uses the same vis lump as **fat PVS**, the union of leaves within 8
> units of the eye, to drop entity updates. An omitted entity still thinks.
> Source: `WinQuake/model.c:84-160`, `WinQuake/r_main.c:491-519`,
> `WinQuake/sv_main.c:427-470`, `WinQuake/sv_phys.c:1507-1563`. [Next: rendering
> →](#sec-5)

::: diagram visibility

## Where it sits in the frame

On the client, `SCR_UpdateScreen` (`WinQuake/screen.c:808`) calls `V_RenderView`
(`WinQuake/screen.c:893` invocation, defined `WinQuake/view.c:995`).
`V_RenderView` calls `R_PushDlights` (`WinQuake/view.c:1018`, defined
`WinQuake/r_light.c:115`) to re-mark which surfaces are touched by dynamic
lights this frame, then calls `R_RenderView`. Both renderers run `R_SetupFrame`
first (`WinQuake/r_misc.c:367` software, `WinQuake/gl_rmain.c:810` GL), which
sets `r_viewleaf` with `Mod_PointInLeaf`. In the GL renderer that leads into
`R_RenderScene` (`WinQuake/gl_rmain.c:949`), which calls `R_MarkLeaves`
(`WinQuake/gl_rmain.c:957`) — the PVS walk that flags which BSP nodes are
potentially visible from that leaf — immediately before `R_DrawWorld` walks the
tree and emits surfaces. The software path is `R_RenderView_`
(`WinQuake/r_main.c:953`) calling `R_MarkLeaves` at `WinQuake/r_main.c:967`.

On the server side, PVS is consulted once per client per frame inside
`SV_WriteEntitiesToClient` (`WinQuake/sv_main.c:427`), called from
`SV_SendClientMessages` (`WinQuake/sv_main.c:819`) during `Host_ServerFrame`
(`WinQuake/host.c:620`). This is a separate PVS computation (`SV_FatPVS`) from
the client's rendering PVS (`Mod_LeafPVS`/`R_MarkLeaves`) even though both
ultimately call the same `Mod_DecompressVis` on the same vis lump.

> **.plan.** “changed network update to client PVS specific” — [Carmack, 23 Apr
> 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960423.txt). The
> archive captures the architectural hinge: PVS stopped being only a renderer
> accelerator and became a per-client bandwidth policy.

## On-disk BSP format

The format is three-dimensional throughout, which is the break from DOOM's
plan-view tree; see [a binary tree in two
dimensions](design:a-binary-tree-in-two-dimensions).

The map file begins with a `dheader_t` (`WinQuake/bspfile.h:91-95`) containing a
version and 15 `lump_t` `{fileofs, filelen}` directory entries (`lump_t` at
`WinQuake/bspfile.h:59-62`, `HEADER_LUMPS` at `WinQuake/bspfile.h:80`),
version-locked to `BSPVERSION` 29 (`WinQuake/bspfile.h:56`). Each lump is
addressed by byte offset. `Mod_LoadModel` reads the file into a temporary
buffer; the lump loaders then copy or convert its contents into hunk
allocations.

The key on-disk structures:

- `dplane_t` (`WinQuake/bspfile.h:128-133`): a normal + distance + `type`
  (whether the plane is axis-aligned, used to fast-path dot products).
- `dnode_t` (`WinQuake/bspfile.h:155-163`): a render-tree node — `planenum`, two
  `children[]` (a non-negative index is another node, negative is `-(leaf+1)`),
  a 16-bit bounding box for frustum culling, and `firstface`/`numfaces` into the
  face list. Note `children` are `short` — capped at `MAX_MAP_NODES` 32767
  (`WinQuake/bspfile.h:32`) specifically because negative shorts double as leaf
  indices.
- `dclipnode_t` (`WinQuake/bspfile.h:165-169`): the *collision* tree node — just
  `planenum` and two `children[]`, where negative values are literal
  `CONTENTS_*` constants, not leaf indices. This is a much thinner structure
  than `dnode_t` because clipping only needs to answer "solid or not," not
  "which surfaces are here."
- `dleaf_t` (`WinQuake/bspfile.h:213-225`): `contents` (a `CONTENTS_*` enum,
  always negative — `WinQuake/bspfile.h:137-151`), `visofs` (byte offset into
  the RLE-compressed visibility lump, or -1), a 16-bit bbox, a marksurface
  range, and four `ambient_level` bytes used for ambient sound.
- `dface_t` (`WinQuake/bspfile.h:188-200`): `planenum`/`side`, an edge range
  (`firstedge`/`numedges` into the surfedges indirection list), `texinfo`, up to
  `MAXLIGHTMAPS` (4) light `styles` bytes, and `lightofs` — offset into the
  lighting lump where this face's lightmap samples begin.
- The visibility lump (`LUMP_VISIBILITY`, `WinQuake/bspfile.h:68`) is one big
  RLE-compressed bit matrix — see below.

`CONTENTS_EMPTY`/`CONTENTS_SOLID`/`CONTENTS_WATER`/`CONTENTS_SLIME`/`CONTENTS_LAVA`/`CONTENTS_SKY`,
plus the internal-only `CONTENTS_ORIGIN`/`CONTENTS_CLIP`/`CONTENTS_CURRENT_*`
(`WinQuake/bspfile.h:137-151`) are small negative ints. They live on
`dleaf_t.contents` in the render tree. Render-node `children[]` use a different
encoding: a negative short is `-(leaf+1)`, not a contents value
(`WinQuake/bspfile.h:158`). Clipnode `children[]` store contents directly when
negative (`WinQuake/bspfile.h:168`). Leaf 0 is the generic solid leaf, shared by
every solid volume and excluded from the vis leaf count
(`WinQuake/bspfile.h:211-212`, and `dmodel_t.visleafs` at
`WinQuake/bspfile.h:87`).

## Loading in model.c: from disk lumps to the mnode_t/mleaf_t graph

`Mod_LoadBrushModel` (`WinQuake/model.c:1143-1220`) is the top-level entry,
called from `Mod_LoadModel` when a `.bsp` is first referenced. It byte-swaps the
header for endianness (`WinQuake/model.c:1160-1161`, a legacy of the original
SGI/Mac ports), then loads every lump in a fixed order into hunk memory:

```c
// WinQuake/model.c:1163-1181
// load into heap
	
	Mod_LoadVertexes (&header->lumps[LUMP_VERTEXES]);
	Mod_LoadEdges (&header->lumps[LUMP_EDGES]);
	Mod_LoadSurfedges (&header->lumps[LUMP_SURFEDGES]);
	Mod_LoadTextures (&header->lumps[LUMP_TEXTURES]);
	Mod_LoadLighting (&header->lumps[LUMP_LIGHTING]);
	Mod_LoadPlanes (&header->lumps[LUMP_PLANES]);
	Mod_LoadTexinfo (&header->lumps[LUMP_TEXINFO]);
	Mod_LoadFaces (&header->lumps[LUMP_FACES]);
	Mod_LoadMarksurfaces (&header->lumps[LUMP_MARKSURFACES]);
	Mod_LoadVisibility (&header->lumps[LUMP_VISIBILITY]);
	Mod_LoadLeafs (&header->lumps[LUMP_LEAFS]);
	Mod_LoadNodes (&header->lumps[LUMP_NODES]);
	Mod_LoadClipnodes (&header->lumps[LUMP_CLIPNODES]);
	Mod_LoadEntities (&header->lumps[LUMP_ENTITIES]);
	Mod_LoadSubmodels (&header->lumps[LUMP_MODELS]);

	Mod_MakeHull0 ();
```

This order matters: leafs must load before nodes because `Mod_LoadNodes`
resolves a node's negative child index directly into a `loadmodel->leafs`
pointer (`WinQuake/model.c:884-886`), and planes and visibility data must exist
before structures point into them. Most `Mod_Load*` functions validate the lump
size, allocate a runtime array, byte-swap fields, and convert disk indices into
resident pointers. Later tree walks can therefore follow pointers without
repeated endian conversion or index resolution.

`Mod_LoadVisibility` and `Mod_LoadLighting` are trivial raw copies — the vis and
light lumps are opaque blobs at this stage, decoded lazily per-leaf/per-surface:

```c
// WinQuake/model.c:521-530
void Mod_LoadVisibility (lump_t *l)
{
	if (!l->filelen)
	{
		loadmodel->visdata = NULL;
		return;
	}
	loadmodel->visdata = Hunk_AllocName ( l->filelen, loadname);	
	memcpy (loadmodel->visdata, mod_base + l->fileofs, l->filelen);
}
```

`Mod_LoadNodes` (`WinQuake/model.c:850-890`) converts `dnode_t` into `mnode_t`,
resolving `planenum` to a pointer and each child index to either another
`mnode_t*` or, if negative, a `mleaf_t*` cast to `mnode_t*` (safe because
`mnode_t` and `mleaf_t` share an identical layout for their first fields —
`contents`, `visframe`, `minmaxs`, `parent`, see `WinQuake/model.h:128-166`):

```c
// WinQuake/model.c:865-889
	for ( i=0 ; i<count ; i++, in++, out++)
	{
		for (j=0 ; j<3 ; j++)
		{
			out->minmaxs[j] = LittleShort (in->mins[j]);
			out->minmaxs[3+j] = LittleShort (in->maxs[j]);
		}
	
		p = LittleLong(in->planenum);
		out->plane = loadmodel->planes + p;

		out->firstsurface = LittleShort (in->firstface);
		out->numsurfaces = LittleShort (in->numfaces);
		
		for (j=0 ; j<2 ; j++)
		{
			p = LittleShort (in->children[j]);
			if (p >= 0)
				out->children[j] = loadmodel->nodes + p;
			else
				out->children[j] = (mnode_t *)(loadmodel->leafs + (-1 - p));
		}
	}
	
	Mod_SetParent (loadmodel->nodes, NULL);	// sets nodes and leafs
```

`Mod_SetParent` (`WinQuake/model.c:836-843`) then recursively stamps a `parent`
back-pointer on every node and leaf — needed later purely so `R_MarkLeaves` can
walk *up* from a visible leaf to mark every ancestor node as visible, without
re-descending the tree.

`Mod_LoadLeafs` (`WinQuake/model.c:897-937`) converts `dleaf_t` into `mleaf_t`:
`visofs` becomes a resident `compressed_vis` pointer into `loadmodel->visdata`
(or `NULL` if -1), and `firstmarksurface` becomes a pointer into the
already-loaded `marksurfaces` array. It first sets `loadmodel->numleafs` to the
full leaf count including 0 (`WinQuake/model.c:910`). `Mod_LoadBrushModel` then
overwrites that with `bm->visleafs` (`WinQuake/model.c:1207`), matching the
`model.h` comment "number of visible leafs, not counting 0"
(`WinQuake/model.h:328`). PVS row length and `R_MarkLeaves`'s loop both use that
visleaf count.

## Mod_PointInLeaf

`Mod_PointInLeaf` (`WinQuake/model.c:84-107`) is the primitive both the renderer
(to find the camera's leaf) and general game code use to answer "what
leaf/contents is at this point":

```c
// WinQuake/model.c:84-107
mleaf_t *Mod_PointInLeaf (vec3_t p, model_t *model)
{
	mnode_t		*node;
	float		d;
	mplane_t	*plane;
	
	if (!model || !model->nodes)
		Sys_Error ("Mod_PointInLeaf: bad model");

	node = model->nodes;
	while (1)
	{
		if (node->contents < 0)
			return (mleaf_t *)node;
		plane = node->plane;
		d = DotProduct (p,plane->normal) - plane->dist;
		if (d > 0)
			node = node->children[0];
		else
			node = node->children[1];
	}
	
	return NULL;	// never reached
}
```

This is the render-tree (`dnode_t`-derived) walk, not the collision hulls — it's
O(log n) in practice because a well-formed qbsp tree is roughly balanced, and it
terminates the instant `contents < 0`, i.e., a leaf (all leaves have negative
`contents`; internal nodes always have `contents == 0`, per the comment at
`WinQuake/model.h:131`).

## Mod_LeafPVS / Mod_DecompressVis: RLE decompression

The PVS lump stores, per leaf, a bitset over all other leaves that are
potentially visible from it — a full N×N matrix would be too large and too
redundant (long runs of zero bits for far-away leaves), so it's run-length
encoded: a non-zero byte is copied literally, a zero byte is followed by a
repeat count.

```c
// WinQuake/model.c:115-160
byte *Mod_DecompressVis (byte *in, model_t *model)
{
	static byte	decompressed[MAX_MAP_LEAFS/8];
	int		c;
	byte	*out;
	int		row;

	row = (model->numleafs+7)>>3;	
	out = decompressed;

	if (!in)
	{	// no vis info, so make all visible
		while (row)
		{
			*out++ = 0xff;
			row--;
		}
		return decompressed;		
	}

	do
	{
		if (*in)
		{
			*out++ = *in++;
			continue;
		}
	
		c = in[1];
		in += 2;
		while (c)
		{
			*out++ = 0;
			c--;
		}
	} while (out - decompressed < row);
	
	return decompressed;
}

byte *Mod_LeafPVS (mleaf_t *leaf, model_t *model)
{
	if (leaf == model->leafs)
		return mod_novis;
	return Mod_DecompressVis (leaf->compressed_vis, model);
}
```

`decompressed` is `static` — a single shared scratch buffer, which is fine
because it is fully consumed (copied out or bit-tested) before the next call,
and keeps the engine from allocating/freeing a `MAX_MAP_LEAFS/8` = 1024-byte
buffer every leaf-crossing. If `leaf->compressed_vis` is `NULL` (no vis data
compiled, `visofs == -1` in the leaf), the function fills the whole row with
`0xff` — "everything visible" — matching a level whose vis pass was skipped.
`Mod_LeafPVS` special-cases leaf 0 (the shared solid leaf, `leaf ==
model->leafs`) by returning `mod_novis` (`WinQuake/model.c:36`, all-`0xff`,
initialized in `Mod_Init` at `WinQuake/model.c:53-54`) rather than trying to
decompress a vis row for a leaf that was never assigned one — the camera should
never actually be inside leaf 0, but this keeps the function total.

The RLE scheme is cheap at runtime because vis rows are sparse: a long zero run
compresses to two bytes. How that set is built, and which runtime visibility
schemes were discarded, is in [the PVS breakthrough](design:the-breakthrough).

::: diagram pvs-explorer

## R_MarkLeaves, visframe, and r_novis

`R_MarkLeaves` walks the decompressed PVS bitset for `r_viewleaf` and stamps a
monotonically increasing `r_visframecount` (`WinQuake/r_main.c:89` software,
`WinQuake/gl_rmain.c:31` GL) onto every node on the path from each visible leaf
up to the root:

```c
// WinQuake/gl_rsurf.c:1352-1389 (GL renderer; software is the same walk, WinQuake/r_main.c:491-519, minus r_novis and the mirror early-out)
void R_MarkLeaves (void)
{
	byte	*vis;
	mnode_t	*node;
	int		i;
	byte	solid[4096];

	if (r_oldviewleaf == r_viewleaf && !r_novis.value)
		return;
	
	if (mirror)
		return;

	r_visframecount++;
	r_oldviewleaf = r_viewleaf;

	if (r_novis.value)
	{
		vis = solid;
		memset (solid, 0xff, (cl.worldmodel->numleafs+7)>>3);
	}
	else
		vis = Mod_LeafPVS (r_viewleaf, cl.worldmodel);
		
	for (i=0 ; i<cl.worldmodel->numleafs ; i++)
	{
		if (vis[i>>3] & (1<<(i&7)))
		{
			node = (mnode_t *)&cl.worldmodel->leafs[i+1];
			do
			{
				if (node->visframe == r_visframecount)
					break;
				node->visframe = r_visframecount;
				node = node->parent;
			} while (node);
		}
	}
```

Two things worth noting. First, the early-out `r_oldviewleaf == r_viewleaf`
means the entire PVS walk is skipped whenever the camera hasn't crossed into a
new leaf since last frame — in a typical frame where the player is standing
still or moving within one room, this function does nothing at all, which
matters a great deal at 1996 frame budgets. Second, `leafs[i+1]` — vis bit `i`
corresponds to leaf `i+1`, because leaf 0 (the shared solid leaf) is never
included in the PVS matrix (`dmodel_t.visleafs` explicitly excludes it,
`WinQuake/bspfile.h:87`). The `do { ... node = node->parent; }` loop stops early
if it finds a node already marked for this `r_visframecount` — since an ancestor
being already marked means everything further up is too, this turns what could
be a full-tree-height walk per leaf into an amortized near-constant cost once
the upper tree is marked.

`r_novis` (`WinQuake/gl_rmain.c:86`, registered `WinQuake/gl_rmisc.c:189`) is a
debug/benchmarking cvar: when set, `R_MarkLeaves` fabricates an all-`0xff` vis
buffer instead of decompressing the real PVS, forcing every leaf to be
considered potentially visible (the `!r_novis.value` in the early-out means
enabling it re-marks even from a stationary viewpoint). It does not change the
server's fat PVS. The software `R_MarkLeaves` (`WinQuake/r_main.c:491-519`) has
no `r_novis` check — that cvar and the `mirror` early-out are GL-only. A map
with no vis lump (`compressed_vis == NULL`) already fills the row with `0xff` in
`Mod_DecompressVis`, which is the software equivalent.

Only nodes/leaves marked for the current `r_visframecount` are recursed into by
the surface-walking code (`R_DrawWorld`/`R_RecursiveWorldNode`), so PVS culling
composes with frustum culling and the `dnode_t` bounding boxes to minimize the
amount of BSP tree actually traversed and rasterized each frame.

## How the server also uses PVS: SV_FatPVS

The server needs a conceptually different query than the renderer: not "what's
visible from a single point right now" but "what's visible from anywhere a
bobbing, moving player might be this frame," used to decide which edicts to
include in each client's unreliable update. `SV_AddToFatPVS`/`SV_FatPVS`
(`WinQuake/sv_main.c:367-416`) compute the union (bitwise OR) of the PVS of
every leaf within a small box around the client's eye point, by recursively
descending the render tree and only pruning a subtree once the split plane is
farther than 8 units from the point:

```c
// WinQuake/sv_main.c:364-416
int		fatbytes;
byte	fatpvs[MAX_MAP_LEAFS/8];

void SV_AddToFatPVS (vec3_t org, mnode_t *node)
{
	int		i;
	byte	*pvs;
	mplane_t	*plane;
	float	d;

	while (1)
	{
	// if this is a leaf, accumulate the pvs bits
		if (node->contents < 0)
		{
			if (node->contents != CONTENTS_SOLID)
			{
				pvs = Mod_LeafPVS ( (mleaf_t *)node, sv.worldmodel);
				for (i=0 ; i<fatbytes ; i++)
					fatpvs[i] |= pvs[i];
			}
			return;
		}
	
		plane = node->plane;
		d = DotProduct (org, plane->normal) - plane->dist;
		if (d > 8)
			node = node->children[0];
		else if (d < -8)
			node = node->children[1];
		else
		{	// go down both
			SV_AddToFatPVS (org, node->children[0]);
			node = node->children[1];
		}
	}
}

byte *SV_FatPVS (vec3_t org)
{
	fatbytes = (sv.worldmodel->numleafs+31)>>3;
	Q_memset (fatpvs, 0, fatbytes);
	SV_AddToFatPVS (org, sv.worldmodel->nodes);
	return fatpvs;
}
```

The comment block right above this code in `sv_main.c` explains the "why"
directly: "The PVS must include a small area around the client to allow head
bobbing or other small motion on the client side. Otherwise, a bob might cause
an entity that should be visible to not show up, especially when the bob crosses
a waterline" (`WinQuake/sv_main.c:355-359`). Reusing
`Mod_LeafPVS`/`Mod_DecompressVis` here means the server pays the same
RLE-decompression cost as the client, but on `sv.worldmodel`. In local play this
can refer to the same loaded model as `cl.worldmodel`, through the shared
`Mod_ForName` registry (`WinQuake/model.c:186-243`, `WinQuake/model.c:329-336`);
a remote server has its own copy in its process.

`SV_WriteEntitiesToClient` (`WinQuake/sv_main.c:427`) calls `SV_FatPVS` once per
client per frame (`WinQuake/sv_main.c:438`) and then, for each edict, tests the
leaves that entity currently touches (`ent->leafnums[]`, filled from
`SV_LinkEdict` at `WinQuake/world.c:439-442`) against the fat PVS bitset:

```c
// WinQuake/sv_main.c:457-462
			for (i=0 ; i < ent->num_leafs ; i++)
				if (pvs[ent->leafnums[i] >> 3] & (1 << (ent->leafnums[i]&7) ))
					break;
				
			if (i == ent->num_leafs)
				continue;		// not visible
```

This is coarse server-side visibility culling: the server omits an entity when
none of the leaves it touches intersects the client's fat PVS. It is not an
anti-cheat boundary. PVS is leaf-to-leaf for the world; entities are not in the
bitset.

`SV_FindTouchedLeafs` (`WinQuake/world.c:328-364`) is a DFS of the *render* BSP,
called from `SV_LinkEdict` (`WinQuake/world.c:439-442`). At a leaf it records
`leaf - sv.worldmodel->leafs - 1` and returns. At a node it tests
`BOX_ON_PLANE_SIDE` on the edict's abs box and recurses `children[0]` then
`children[1]`. If `ent->num_leafs == MAX_ENT_LEAFS` (16, `WinQuake/progs.h:34`)
it returns without recording (`WinQuake/world.c:342-343`). The stored 16 are the
first leaves in that walk, not the 16 most relevant to any client.
`SV_WriteEntitiesToClient` tests only that list. The entity is omitted when none
of those 16 bits is set in the fat PVS, even if an unrecorded leaf would have
been. Typical case: a large bmodel (plat, train, door) that straddles many
leaves, mostly outside the client's PVS, with the overlapping leaf among the
dropped ones. Physics still runs (`WinQuake/sv_phys.c:1507-1563`). Linking
itself is in [collision](#sec-3).

Water and air are different leaves with different vis rows, which is why fat PVS
exists. `r_novis` affects only the GL world walk.

## Contents types: collision hulls vs. render nodes

Quake keeps two entirely separate trees per `.bsp`: the render tree
(`dnode_t`/`mnode_t`, walked by `Mod_PointInLeaf`, `R_MarkLeaves`,
`R_LightPoint`, `R_MarkLights`) and up to `MAX_MAP_HULLS` (4,
`WinQuake/bspfile.h:24`) collision hulls (`dclipnode_t`/`hull_t`, walked by
`SV_HullPointContents`/`SV_RecursiveHullCheck` in `world.c`). The render tree
carries surfaces (for drawing) and fine-grained leaf boundaries (for PVS/ambient
sound); the clip hulls carry none of that — just a leaner `planenum` + two
`children[]` per node, where a negative child is read directly as a `CONTENTS_*`
value:

```c
// WinQuake/world.c:491-516
int SV_HullPointContents (hull_t *hull, int num, vec3_t p)
{
	float		d;
	dclipnode_t	*node;
	mplane_t	*plane;

	while (num >= 0)
	{
		if (num < hull->firstclipnode || num > hull->lastclipnode)
			Sys_Error ("SV_HullPointContents: bad node number");
	
		node = hull->clipnodes + num;
		plane = hull->planes + node->planenum;
		
		if (plane->type < 3)
			d = p[plane->type] - plane->dist;
		else
			d = DotProduct (plane->normal, p) - plane->dist;
		if (d < 0)
			num = node->children[1];
		else
			num = node->children[0];
	}
	
	return num;
}
```

Hulls 1 and 2 are the on-disk clipnode lump with two box sizes recorded
(`Mod_LoadClipnodes`, `WinQuake/model.c:944-989`): hull 1
`clip_mins`/`clip_maxs` (-16,-16,-24)/(16,16,32) (`WinQuake/model.c:964-969`),
hull 2 (-32,-32,-24)/(32,32,64) (`WinQuake/model.c:976-981`). `MAX_MAP_HULLS` is
4 (`WinQuake/bspfile.h:24`); slot 3 is unused. Collision traces and hull
selection are in [collision](#sec-3). Hull 0 does not exist on disk as clipnodes
— `Mod_MakeHull0` (`WinQuake/model.c:998-1028`) transcribes the render tree into
clipnode form so point queries (hitscan, `SV_PointContents` at
`WinQuake/world.c:527-534`) share the clipnode walker. Camera leaf lookup still
uses the render tree (`Mod_PointInLeaf`), not hull 0:

```c
// WinQuake/model.c:998-1028
void Mod_MakeHull0 (void)
{
	mnode_t		*in, *child;
	dclipnode_t *out;
	int			i, j, count;
	hull_t		*hull;
	
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
}
```

Those `firstclipnode = 0` assignments, and the matching ones in
`Mod_LoadClipnodes`, are overwritten from each submodel's `headnode[]`
(`WinQuake/model.c:1189-1198`). Hull selection and that overwrite are in
[collision](#sec-3).

This split is a memory/precision trade characteristic of the whole engine: the
render tree needs surface lists and tight leaf bounding boxes for drawing and
PVS, but none of that is useful for collision, so the clip hulls strip it down
to the two fields collision actually needs, and reuse (rather than duplicate)
the plane array (`hull->planes = loadmodel->planes`, both here and in
`Mod_LoadClipnodes` at `WinQuake/model.c:963`/`975`).

## Lightmaps and light styles: r_light.c

`light.exe` writes the lighting lump. The engine copies it (`Mod_LoadLighting`)
and points each face at its samples (`Mod_LoadFaces`,
`WinQuake/model.c:801-807`). It never recomputes those samples. Runtime work is
scaling by light styles and adding dlights; compositing onto textures is [the
renderer](#sec-5). `RecursiveLightPoint`/`R_LightPoint`
(`WinQuake/r_light.c:141-259`) trace a vertical segment through the *render* BSP
tree (the same tree `Mod_PointInLeaf` walks) to find which surface is below a
point, then sample that surface's lightmap:

```c
// WinQuake/r_light.c:238-259
int R_LightPoint (vec3_t p)
{
	vec3_t		end;
	int			r;
	
	if (!cl.worldmodel->lightdata)
		return 255;
	
	end[0] = p[0];
	end[1] = p[1];
	end[2] = p[2] - 2048;
	
	r = RecursiveLightPoint (cl.worldmodel->nodes, p, end);
	
	if (r == -1)
		r = 0;

	if (r < r_refdef.ambientlight)
		r = r_refdef.ambientlight;

	return r;
}
```

This is what shades dynamic models (players, monsters, projectiles) to match the
static lighting of the floor/wall beneath them, without those movable objects
having their own lightmaps. Inside `RecursiveLightPoint`, once a hit surface is
found, the sample is scaled by `d_lightstylevalue[surf->styles[maps]]`
(`WinQuake/r_light.c:222`) — an 8.8 fixed-point brightness value per light
*style* (0–63, `MAX_LIGHTSTYLES`, `WinQuake/quakedef.h:108`). `R_SetupFrame`
calls `R_AnimateLight` (`WinQuake/r_light.c:33-53`; software
`WinQuake/r_misc.c:412`, GL `WinQuake/gl_rmain.c:820`) to recompute those values
each frame by indexing an ASCII brightness string (`cl_lightstyle[j].map`) with
the current time. The server owns the strings (`sv.lightstyles`,
`WinQuake/server.h:56`) and sends `svc_lightstyle`
(`WinQuake/pr_cmds.c:1231-1243`); it does not sample lightmaps. The client
stores them in `cl_lightstyle` (`WinQuake/cl_parse.c:822-827`). Styles are
flicker/pulse/switchable lights (torches, strobes, triggered switches), driven
by re-scaling precomputed texels rather than recomputing lighting. Why the
samples exist as a separate grid is in [decoupling lighting from
geometry](design:decoupling-lighting-from-geometry).

Dynamic lights (rockets, explosions, the muzzle flash) work the opposite
direction: instead of sampling a point, `R_PushDlights`
(`WinQuake/r_light.c:115-130`, called once per `V_RenderView`,
`WinQuake/view.c:1018`) walks the render tree from each active `dlight_t`
outward via `R_MarkLights` (`WinQuake/r_light.c:69-107`), setting a `dlightbits`
bitmask on every surface within the light's radius:

```c
// WinQuake/r_light.c:69-107
void R_MarkLights (dlight_t *light, int bit, mnode_t *node)
{
	mplane_t	*splitplane;
	float		dist;
	msurface_t	*surf;
	int			i;
	
	if (node->contents < 0)
		return;

	splitplane = node->plane;
	dist = DotProduct (light->origin, splitplane->normal) - splitplane->dist;
	
	if (dist > light->radius)
	{
		R_MarkLights (light, bit, node->children[0]);
		return;
	}
	if (dist < -light->radius)
	{
		R_MarkLights (light, bit, node->children[1]);
		return;
	}
		
// mark the polygons
	surf = cl.worldmodel->surfaces + node->firstsurface;
	for (i=0 ; i<node->numsurfaces ; i++, surf++)
	{
		if (surf->dlightframe != r_dlightframecount)
		{
			surf->dlightbits = 0;
			surf->dlightframe = r_dlightframecount;
		}
		surf->dlightbits |= bit;
	}

	R_MarkLights (light, bit, node->children[0]);
	R_MarkLights (light, bit, node->children[1]);
}
```

Each of up to `MAX_DLIGHTS` (32, `WinQuake/client.h:71`) simultaneous dlights
gets its own bit (`1<<i` in `R_PushDlights`, `WinQuake/r_light.c:128`), so a
surface's `dlightbits` records *which* lights touch it. The rasterizer later
blends only those lights into the surface cache or GL lightmap — compositing,
not recomputing the baked samples. `R_PushDlights` runs before `R_MarkLeaves`,
so it marks surfaces on the full render tree; unmarked-for-PVS surfaces are
simply never drawn.

> **.plan.** A 27 Aug 1996 note says a full-size lighting job had to run `vis`
> first or take “about 1000 times longer,” with a working set above 100 MB
> ([Carmack](../../../historical/plans/carmack/by_day/johnc_plan_19960827.txt)).
> PVS was therefore also an offline build dependency: expensive visibility work
> was moved out of the frame and into the map toolchain.

## Call graph

```
Host_Frame
 └─ SCR_UpdateScreen                       (screen.c:808)
     └─ V_RenderView                        (view.c:995)
         ├─ R_PushDlights                   (r_light.c:115)
         │   └─ R_MarkLights                (r_light.c:69)   -- render tree walk, sets surf->dlightbits
         └─ R_RenderView
             GL: (gl_rmain.c:1104)
             │   └─ R_RenderScene            (gl_rmain.c:949)
             │       ├─ R_SetupFrame         (gl_rmain.c:810)  -- r_viewleaf = Mod_PointInLeaf
             │       ├─ R_MarkLeaves         (gl_rsurf.c:1352)
             │       │   └─ Mod_LeafPVS      (model.c:155)
             │       │       └─ Mod_DecompressVis (model.c:115)
             │       └─ R_DrawWorld          (gl_rsurf.c:1316) -- visframe == r_visframecount
             SW: (r_main.c:1049) → R_RenderView_ (r_main.c:953)
                 ├─ R_SetupFrame             (r_misc.c:367)
                 ├─ R_MarkLeaves             (r_main.c:491)
                 └─ R_EdgeDrawing            (r_main.c:876) -- R_RenderWorld (r_bsp.c:648) walks visframe

SV_SendClientMessages (sv_main.c:819)
 └─ SV_SendClientDatagram                    (sv_main.c:720)
     └─ SV_WriteEntitiesToClient             (sv_main.c:427)
         └─ SV_FatPVS                        (sv_main.c:410)
             └─ SV_AddToFatPVS               (sv_main.c:367)
                 └─ Mod_LeafPVS              (model.c:155)
                     └─ Mod_DecompressVis    (model.c:115)

Mod_LoadModel
 └─ Mod_LoadBrushModel                       (model.c:1143)
     ├─ Mod_LoadPlanes                        (model.c:1087)
     ├─ Mod_LoadVisibility                    (model.c:521)
     ├─ Mod_LoadLeafs                         (model.c:897)
     ├─ Mod_LoadNodes                         (model.c:850)
     │   └─ Mod_SetParent                     (model.c:836)
     ├─ Mod_LoadClipnodes                     (model.c:944)  -- builds hulls[1], hulls[2]
     ├─ Mod_LoadSubmodels                     (model.c:583)
     └─ Mod_MakeHull0                         (model.c:998)  -- builds hulls[0] from render nodes

Collision (server physics, world.c)
 └─ SV_RecursiveHullCheck / SV_HullPointContents (world.c:581 / world.c:491)
     -- walk hull->clipnodes (dclipnode_t), independent of the render tree
```

## Key data structures

- `dheader_t` — `WinQuake/bspfile.h:91-95` — on-disk file header: version + 15 lump directory entries.
- `lump_t` — `WinQuake/bspfile.h:59-62` — `{fileofs, filelen}` byte range descriptor for one lump.
- `dplane_t` — `WinQuake/bspfile.h:128-133` — on-disk splitting plane (normal, dist, axis type).
- `dnode_t` — `WinQuake/bspfile.h:155-163` — on-disk render-tree node (plane, children, bbox, face range).
- `dclipnode_t` — `WinQuake/bspfile.h:165-169` — on-disk collision-tree node (plane, children as contents or node index).
- `dleaf_t` — `WinQuake/bspfile.h:213-225` — on-disk leaf (contents, vis offset, bbox, marksurfaces, ambient sound levels).
- `dface_t` — `WinQuake/bspfile.h:188-200` — on-disk surface (edges, texinfo, light styles, lightmap offset).
- `dmodel_t` — `WinQuake/bspfile.h:82-89` — on-disk submodel (bounds, per-hull headnode indices, visleafs, face range).
- `mplane_t` — `WinQuake/model.h:59-66` — in-memory plane, adds `signbits` for fast box-plane side tests.
- `mnode_t` — `WinQuake/model.h:128-144` — in-memory render node; shares its header layout with `mleaf_t` so a node pointer can be blindly cast to check `contents`.
- `mleaf_t` — `WinQuake/model.h:148-166` — in-memory leaf; holds `compressed_vis` pointer and `efrags` (temporary-entity fragment list).
- `hull_t` — `WinQuake/model.h:169-177` — in-memory collision hull: clipnode array, plane array, clipnode index range, and the box size this hull was expanded for.
- `msurface_t` — `WinQuake/model.h:102-126` — in-memory drawable surface: plane, edge range, texinfo, `visframe`, `dlightbits`, lightmap `samples`.
- `model_t` — `WinQuake/model.h:300-369` — the whole loaded model: all of the above arrays plus `hulls[MAX_MAP_HULLS]`.
- `fatpvs[MAX_MAP_LEAFS/8]` — `WinQuake/sv_main.c:365` — server-side static scratch buffer for the OR'd PVS of all leaves near a client.
- `mod_novis[MAX_MAP_LEAFS/8]` — `WinQuake/model.c:36` — static all-visible fallback vis buffer.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, chapters on Quake's engine
  (BSP, PVS, and 3-D clipping): local archive at
  `docs/historical/abrash_black_book/` ([Chapter 64: Quake's 3-D
  Engine](../../../historical/abrash_black_book/black-book.html#chapter-64-quakes-visible-surface-determination),
  [Chapter 65: 3-D
  Clipping](../../../historical/abrash_black_book/black-book.html#chapter-65-3-d-clipping-and-other-thoughts));
  also online at https://www.jagregory.com/abrash-black-book/
- John Carmack, [DOOM Engine Retrospective
  (1997)](../../../historical/doom_1993/carmack_doom_retrospective.txt) —
  reflections on 2D vs. 3D BSPs, line-of-sight testing, and collision hulls.
- Fabien Sanglard, "Quake Source Code Review":
  https://fabiensanglard.net/quakeSource/index.php
- Olivier Montanuy et al., "Unofficial Quake Specs":
  https://www.gamers.org/dEngine/quake/spec/quake-spec34/ (archived:
  https://web.archive.org/web/20251206223630/https://www.gamers.org/dEngine/quake/spec/quake-spec34/)
- Quake BSP file format spec:
  https://www.gamers.org/dEngine/quake/spec/quake-spec34/qkspec_4.htm (archived:
  https://web.archive.org/web/20250222033358/https://www.gamers.org/dEngine/quake/spec/quake-spec34/qkspec_4.htm)
- John Carmack .plan archive (design rationale from the original author,
  contemporaneous with Quake's development): local archive at
  `docs/historical/plans/carmack/` ([1996 .plan
  archive](../../../historical/plans/carmack/by_year/johnc_plan_1996.txt))
- Matthew Earl (Matt's Ramblings), "Quake's PVS: A hidden gem of rendering
  optimization" — the portal graph and the leaf-to-leaf visibility bitmap,
  animated: https://www.youtube.com/watch?v=IfCRHSIg6zo
- ericw-tools — the maintained qbsp/vis/light toolchain the mapping community
  uses today; the practical counterpart to the compile-time costs described
  here: https://github.com/ericwa/ericw-tools (docs:
  https://ericw-tools.readthedocs.io/)
