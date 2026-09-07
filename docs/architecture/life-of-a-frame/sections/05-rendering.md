# Rendering: from screen update to pixels (software and GL paths)

Rendering starts with the client’s view of the world and a camera. Quake’s software and GL builds turn those inputs into pixels using different algorithms behind the same function names.

> **First pass.** Choose one path for your first read: **software** if you want to understand how a CPU paints the world, **GL** if you want to follow polygon submission to graphics hardware. In both, view setup precedes rendering and HUD drawing follows it. World surfaces and animated model entities take different drawing paths. Source: `WinQuake/screen.c:893-932`, `WinQuake/gl_screen.c:874-921`, `WinQuake/r_main.c:876-1030`. [Next: sound and plumbing →](#sec-7)

After the software pipeline, the [assembly walkthrough](#assembly-walkthrough-where-the-pentium-speedup-comes-from) follows the actual pixel-writing instructions and explains the historical performance comparison.

::: diagram rendering

## Where it sits in the frame

In the baseline loop, `_Host_Frame` calls `SCR_UpdateScreen` once per accepted frame. It is the top of the rendering pipeline. The software build's version locks the video buffer and calls the view code:

```c
// WinQuake/screen.c:884-891
	D_DisableBackBufferAccess ();	// for adapters that can't stay mapped in
									//  for linear writes all the time

	VID_LockBuffer ();

	V_RenderView ();

	VID_UnlockBuffer ();
```
(`WinQuake/screen.c:808` is `SCR_UpdateScreen`'s definition.) The GL build's `SCR_UpdateScreen` (`WinQuake/gl_screen.c:821`) has no hardware framebuffer to lock — it just calls `V_RenderView ()` at `WinQuake/gl_screen.c:874` and follows with `GL_Set2D ()` for the HUD/console overlay.

`V_RenderView` (`WinQuake/view.c:995`) is shared between both builds. It computes the refdef (view origin/angles, including bob and punch-kick), pushes dynamic lights, and calls the renderer-specific `R_RenderView`:

```c
// WinQuake/view.c:995-1052
void V_RenderView (void)
{
	if (con_forcedup)
		return;
	...
	if (cl.intermission)
	{	// intermission / finale rendering
		V_CalcIntermissionRefdef ();	
	}
	else
	{
		if (!cl.paused /* && ... */ )
			V_CalcRefdef ();
	}

	R_PushDlights ();
	...
	R_RenderView ();
```

`R_RenderView` is then implemented separately in `WinQuake/r_main.c:1049` (software, a stack-alignment guard that calls the real work in `R_RenderView_` at `r_main.c:953`) and in `WinQuake/gl_rmain.c:1104` (GL). From here the two renderers do not share code again until particle drawing (`r_part.c`, `#ifdef GLQUAKE`-forked in place) and the alias-model/sprite drawing conventions.

## View setup: bob, punchangle, and color shifts (`view.c`)

Before either renderer touches a BSP node, `V_CalcRefdef` (`WinQuake/view.c:864`) builds `r_refdef` — the single struct both renderers treat as ground truth for the frame (origin, angles, FOV, viewport rect). Two purely presentational effects are folded in here rather than in the renderer, because they are properties of the *camera*, not the *scene*:

- **View bob** — a sinusoidal vertical/forward offset proportional to XY speed, meant to sell the feeling of a body moving on foot without any actual skeletal animation:
```c
// WinQuake/view.c:112-133
float V_CalcBob (void)
{
	float	bob;
	float	cycle;
	
	cycle = cl.time - (int)(cl.time/cl_bobcycle.value)*cl_bobcycle.value;
	cycle /= cl_bobcycle.value;
	if (cycle < cl_bobup.value)
		cycle = M_PI * cycle / cl_bobup.value;
	else
		cycle = M_PI + M_PI*(cycle-cl_bobup.value)/(1.0 - cl_bobup.value);

// bob is proportional to velocity in the xy plane
// (don't count Z, or jumping messes it up)

	bob = sqrt(cl.velocity[0]*cl.velocity[0] + cl.velocity[1]*cl.velocity[1]) * cl_bob.value;
	bob = bob*0.3 + bob*0.7*sin(cycle);
	if (bob > 4)
		bob = 4;
	else if (bob < -7)
		bob = -7;
	return bob;
}
```
  The result is added into `r_refdef.vieworg[2]` at `WinQuake/view.c:892` and into the view-weapon's origin at `WinQuake/view.c:930-936`.

- **Punchangle** — the recoil/impact kick the server applies to `cl.punchangle` (set from `svc_...` messages elsewhere) is summed straight into the view angles right before stair-step smoothing:
```c
// WinQuake/view.c:958
	VectorAdd (r_refdef.viewangles, cl.punchangle, r_refdef.viewangles);
```

- **Color shifts (cshift)** — damage flashes, powerup tints, and underwater/lava/slime overlays are accumulated per-frame into `cl.cshifts[NUM_CSHIFTS]` (`cshift_empty`/`cshift_water`/`cshift_slime`/`cshift_lava` constants at `WinQuake/view.c:254-257`). The two renderers apply them completely differently, which is a good illustration of the palette-vs-RGB divide: the software build owns an 8-bit indexed hardware palette, so it *rewrites the palette itself* every frame a shift is active —
```c
// WinQuake/view.c:642-649 (non-GLQUAKE V_UpdatePalette)
	V_CalcPowerupCshift ();
	...
// drop the damage value
	cl.cshifts[CSHIFT_DAMAGE].percent -= host_frametime*150;
	if (cl.cshifts[CSHIFT_DAMAGE].percent <= 0)
		cl.cshifts[CSHIFT_DAMAGE].percent = 0;
```
  eventually calling `VID_ShiftPalette (pal)` at `WinQuake/view.c:611` — while the GL build has a true RGBA framebuffer and instead computes a blend color and draws a translucent full-screen quad in `R_PolyBlend` (`WinQuake/gl_rmain.c:718`), fed by `V_CalcBlend` (`WinQuake/view.c:482-517`, `#ifdef GLQUAKE`), which alpha-composites all active shifts:
```c
// WinQuake/view.c:492-507
	for (j=0 ; j<NUM_CSHIFTS ; j++)	
	{
		if (!gl_cshiftpercent.value)
			continue;

		a2 = ((cl.cshifts[j].percent * gl_cshiftpercent.value) / 100.0) / 255.0;
		if (!a2)
			continue;
		a = a + a2*(1-a);
		a2 = a2/a;
		r = r*(1-a2) + cl.cshifts[j].destcolor[0]*a2;
		g = g*(1-a2) + cl.cshifts[j].destcolor[1]*a2;
		b = b*(1-a2) + cl.cshifts[j].destcolor[2]*a2;
	}
```

## Software renderer: edge-based visible-surface determination

The software path's central design constraint is that there is no rasterizer hardware at all — every filled pixel costs CPU cycles for texture sampling, lighting, and the write itself. On a 60-100MHz Pentium-class part in 1996, filling pixels twice (overdraw) was directly, linearly wasted work. So the software renderer inverts the naive "walk polygons, scan-convert each one, z-test each pixel" approach and instead computes **exactly which pixel spans are visible before any texturing happens**, via a global edge list and an active-surface stack sorted by depth — the technique Michael Abrash devotes roughly a dozen chapters of the *Graphics Programming Black Book* to (chapters 57-70, "Quake's Visible-Surface Determination" and related).

`R_RenderView_` (`WinQuake/r_main.c:953`) drives the frame:
```c
// WinQuake/r_main.c:962-972
	R_SetupFrame ();

#ifdef PASSAGES
SetVisibilityByPassages ();
#else
	R_MarkLeaves ();	// done here so we know if we're in water
#endif

// make FDIV fast. This reduces timing precision after we've been running for a
// while, so we don't do it globally.  This also sets chop mode, and we do it
// here so that setup stuff like the refresh area calculations match what's
// done in screen.c
	Sys_LowFPPrecision ();
```
`R_SetupFrame` (`WinQuake/r_misc.c:367`) resets per-frame counters, applies ambient light and light-style animation (`R_AnimateLight`), and bumps `r_framecount`. `R_MarkLeaves` (`WinQuake/r_main.c:491`) walks the precomputed PVS (potentially-visible-set) bit vector for the leaf the camera is standing in and stamps `visframe` up the BSP parent chain, so later BSP walks can reject whole subtrees with an integer compare:
```c
// WinQuake/r_main.c:503-517
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

The real work happens in `R_EdgeDrawing` (`WinQuake/r_main.c:876`), which allocates a stack-resident edge/surface pool, calls `R_RenderWorld`, and then rasterizes:
```c
// WinQuake/r_main.c:900-910
	R_BeginEdgeFrame ();

	if (r_dspeeds.value)
	{
		rw_time1 = Sys_FloatTime ();
	}

	R_RenderWorld ();

	if (r_drawculledpolys)
		R_ScanEdges ();
```

`R_RenderWorld` (`WinQuake/r_bsp.c:648`) sets `modelorg` to the eye position (in model space) and recurses `R_RecursiveWorldNode` from the root, front-to-back-ordered by which side of each splitting plane the eye is on:
```c
// WinQuake/r_bsp.c:648-660
void R_RenderWorld (void)
{
	int			i;
	model_t		*clmodel;
	btofpoly_t	btofpolys[MAX_BTOFPOLYS];

	pbtofpolys = btofpolys;

	currententity = &cl_entities[0];
	VectorCopy (r_origin, modelorg);
	clmodel = currententity->model;
	r_pcurrentvertbase = clmodel->vertexes;

	R_RecursiveWorldNode (clmodel->nodes, 15);
```
The initial `clipflags` of `15` (all four frustum-plane bits set) is the seed for hierarchical frustum culling: `R_RecursiveWorldNode` (`WinQuake/r_bsp.c:448`) tests each node's bounding box against only the *still-relevant* clip planes, clearing bits once a plane trivially accepts the whole subtree, so deep, on-screen parts of the BSP stop paying the clip cost:
```c
// WinQuake/r_bsp.c:461-495
	if (clipflags)
	{
		for (i=0 ; i<4 ; i++)
		{
			if (! (clipflags & (1<<i)) )
				continue;	// don't need to clip against it

			pindex = pfrustum_indexes[i];

			rejectpt[0] = (float)node->minmaxs[pindex[0]];
			rejectpt[1] = (float)node->minmaxs[pindex[1]];
			rejectpt[2] = (float)node->minmaxs[pindex[2]];
			
			d = DotProduct (rejectpt, view_clipplanes[i].normal);
			d -= view_clipplanes[i].dist;

			if (d <= 0)
				return;

			acceptpt[0] = (float)node->minmaxs[pindex[3+0]];
			acceptpt[1] = (float)node->minmaxs[pindex[3+1]];
			acceptpt[2] = (float)node->minmaxs[pindex[3+2]];

			d = DotProduct (acceptpt, view_clipplanes[i].normal);
			d -= view_clipplanes[i].dist;

			if (d >= 0)
				clipflags &= ~(1<<i);	// node is entirely on screen
		}
	}
```
This accept/reject-corner trick (picking the two box corners most/least aligned with a plane's normal via the precomputed `pfrustum_indexes` sign table) is exactly the frustum test Abrash walks through in the Black Book — no square roots, no per-vertex transform, just sign-driven corner selection. Notably, the *software* renderer has no `R_CullBox`-style generic helper — the corner logic is inlined directly in `R_RecursiveWorldNode` for speed, whereas the GL renderer (below) factors the equivalent test into a reusable `BoxOnPlaneSide`-based function.

Leaf nodes push their marked surfaces (`SURF_...` flagged `msurface_t`s, `WinQuake/model.h:102`) into visibility for the frame; interior nodes pick a side via the splitting plane and, for solid, front-facing surfaces, call `R_RenderFace` (`WinQuake/r_draw.c:386`), which walks the surface's edge loop and hands each edge to the global edge-insertion machinery (`R_ClipEdge`/`R_EmitCachedEdge` in `r_draw.c`; edge results land in `newedges[]`/`removeedges[]` scan-line buckets declared at `WinQuake/r_edge.c:44-45`). Each surface polygon becomes a doubly-linked list of `edge_t` (`WinQuake/r_shared.h:144-153`) sorted by screen-space `u`, one bucket per scanline where the edge starts/ends — the classic "global edge table" from software-rasterizer literature, here specialized so a single sweep never has to re-sort more than the edges newly entering or leaving that row.

`R_ScanEdges` (`WinQuake/r_edge.c:663`) is the sweep itself: for each scanline it inserts newly-active edges into a horizontally-sorted active edge list, and for every edge crossing decides whether a surface is entering (`R_LeadingEdgeBackwards`) or leaving (`R_TrailingEdge`) the active set — maintaining a *surface* stack (not just an edge stack) ordered by a `key` field that encodes BSP traversal order:
```c
// WinQuake/r_edge.c:663-706
void R_ScanEdges (void)
{
	int		iv, bottom;
	byte	basespans[MAXSPANS*sizeof(espan_t)+CACHE_SIZE];
	espan_t	*basespan_p;
	surf_t	*s;
	...
	bottom = r_refdef.vrectbottom - 1;

	for (iv=r_refdef.vrect.y ; iv<bottom ; iv++)
	{
		current_iv = iv;
		fv = (float)iv;

	// mark that the head (background start) span is pre-included
		surfaces[1].spanstate = 1;

		if (newedges[iv])
		{
			R_InsertNewEdges (newedges[iv], edge_head.next);
		}

		(*pdrawfunc) ();
```
The surface stack sort is the payoff: because the world BSP is walked front-to-back, a surface's `key` (`WinQuake/r_shared.h:83`, "sorting key (BSP order)") is already nearly depth-ordered, so `R_LeadingEdgeBackwards` (`WinQuake/r_edge.c:335`) only has to walk forward from the current top-of-stack to find the insertion point, falling back to comparing `nearzi` (nearest 1/z) only when two brush-model surfaces genuinely tie in BSP order:
```c
// WinQuake/r_edge.c:347-353
	if (++surf->spanstate == 1)
	{
		surf2 = surfaces[1].next;

		if (surf->key > surf2->key)
			goto newtop;
```
Whenever the topmost surface on the stack changes, the accumulated span is appended to that surface's `spans` list. Opaque world surfaces therefore own only the horizontal runs where they are frontmost, without a depth buffer. This avoids world-surface overdraw during texturing; later entity, particle, sky, and turbulent passes can still draw over existing pixels. See Abrash, *Graphics Programming Black Book*, chapters on "Adventures in Sorting" and "The Genesis of a General-Purpose Polygon Engine": https://www.jagregory.com/abrash-black-book/

Once a scanline's spans threaten to exceed the preallocated `MAXSPANS` budget, or at end of frame, `D_DrawSurfaces` (declared `WinQuake/d_iface.h:154`) is called to actually texture each surface's span list.

### Surface caching (`d_surf.c`)

Texturing a lightmapped BSP surface in software means resampling the base texture and blending up to four lightstyles into it — expensive enough that Quake caches the *composited* result per surface rather than recomputing it every time the surface is visible. `D_CacheSurface` (`WinQuake/d_surf.c:264`) is the entry point, called from `D_DrawSurfaces`'s per-surface span walk in `WinQuake/d_edge.c:300`:
```c
// WinQuake/d_surf.c:264-291
surfcache_t *D_CacheSurface (msurface_t *surface, int miplevel)
{
	surfcache_t     *cache;

//
// if the surface is animating or flashing, flush the cache
//
	r_drawsurf.texture = R_TextureAnimation (surface->texinfo->texture);
	r_drawsurf.lightadj[0] = d_lightstylevalue[surface->styles[0]];
	r_drawsurf.lightadj[1] = d_lightstylevalue[surface->styles[1]];
	r_drawsurf.lightadj[2] = d_lightstylevalue[surface->styles[2]];
	r_drawsurf.lightadj[3] = d_lightstylevalue[surface->styles[3]];
	
//
// see if the cache holds apropriate data
//
	cache = surface->cachespots[miplevel];

	if (cache && !cache->dlight && surface->dlightframe != r_framecount
			&& cache->texture == r_drawsurf.texture
			&& cache->lightadj[0] == r_drawsurf.lightadj[0]
			&& cache->lightadj[1] == r_drawsurf.lightadj[1]
			&& cache->lightadj[2] == r_drawsurf.lightadj[2]
			&& cache->lightadj[3] == r_drawsurf.lightadj[3] )
		return cache;
```
The cache is keyed by mip level and invalidated when the texture animates, a dynamic light touches the surface, or a lightstyle changes; otherwise the existing `surfcache_t` (`WinQuake/d_local.h:37-49`) is reused untouched. On a miss, `D_SCAlloc` allocates from a renderer-private heap sized by `SURFCACHE_SIZE_AT_320X200` (`WinQuake/d_local.h:35`) and `R_DrawSurface` rebuilds the pixels. Eviction is not LRU: a single rover pointer sweeps the heap in address order, freeing and coalescing whatever blocks it lands on until the request fits, and wrapping to the start when it runs off the end. `r_cache_thrash` is set when that wrap happens more than once in a frame — the signal that the working set no longer fits.

> **.plan.** “increased surface cache size” — [Carmack, 12 Jun 1996](../../../historical/plans/carmack/by_day/johnc_plan_19960612.txt). The cache budget was a release-time tuning parameter: higher resolutions increased the set of distinct surface/lightmap composites the software path had to keep.

### Perspective-correct span texturing (`d_scan.c`)

The final step is walking each surface's horizontal spans and writing textured, lit pixels. True per-pixel perspective correction (dividing by depth for every texel) was too slow for 1996 CPUs, so Quake's span drawers compute the perspective-correct `s`/`t` texture coordinates only every *N* pixels and linearly interpolate (affine-map) the texels in between — Abrash's classic "subdivided affine" approximation. The 8-bit portable-C polygon span drawer subdivides every 8 pixels:
```c
// WinQuake/d_scan.c:274-290
	do
	{
		pdest = (unsigned char *)((byte *)d_viewbuffer +
				(screenwidth * pspan->v) + pspan->u);

		count = pspan->count;

	// calculate the initial s/z, t/z, 1/z, s, and t and clamp
		du = (float)pspan->u;
		dv = (float)pspan->v;

		sdivz = d_sdivzorigin + dv*d_sdivzstepv + du*d_sdivzstepu;
		tdivz = d_tdivzorigin + dv*d_tdivzstepv + du*d_tdivzstepu;
		zi = d_ziorigin + dv*d_zistepv + du*d_zistepu;
		z = (float)0x10000 / zi;	// prescale to 16.16 fixed-point

		s = (int)(sdivz * z) + sadjust;
```
(`D_DrawSpans8`, `WinQuake/d_scan.c:257-383`, guarded `#if !id386` — the shipped x86 build used a hand-tuned assembly equivalent in `WinQuake/d_draw.s`, traced in the [assembly walkthrough](#assembly-walkthrough-where-the-pentium-speedup-comes-from).) The turbulent/underwater warp span drawer, `Turbulent8` (`WinQuake/d_scan.c:122-246`), performs the same subdivided-perspective technique but at a coarser 16-pixel granularity (cheaper per-pixel since it also has to apply the sine-wave UV distortion):
```c
// WinQuake/d_scan.c:170-199
		do
		{
		// calculate s and t at the far end of the span
			if (count >= 16)
				r_turb_spancount = 16;
			else
				r_turb_spancount = count;

			count -= r_turb_spancount;

			if (count)
			{
			// calculate s/z, t/z, zi->fixed s and t at far end of span,
			// calculate s and t steps across span by shifting
				sdivz += sdivz16stepu;
				tdivz += tdivz16stepu;
				zi += zi16stepu;
				z = (float)0x10000 / zi;	// prescale to 16.16 fixed-point

				snext = (int)(sdivz * z) + sadjust;
				if (snext > bbextents)
					snext = bbextents;
				else if (snext < 16)
					snext = 16;	// prevent round-off error on <0 steps from
```
The subdivision width is a direct fill-rate/quality tradeoff: too coarse and distant, steeply-angled surfaces visibly warp ("wobble") between correction points; too fine and the per-chunk division (`0x10000 / zi`) dominates the cost. Abrash discusses tuning this constant in the Black Book chapters on Quake's texture mapper: https://www.jagregory.com/abrash-black-book/

### Alias models, sprites, particles, and the entity list

Skeletal-free MDL models (monsters, the player, pickups) are drawn by `R_AliasDrawModel` (`WinQuake/r_alias.c:703`), called per-visible-entity from `R_DrawEntitiesOnList` (`WinQuake/r_main.c:527`):
```c
// WinQuake/r_alias.c:703-738
void R_AliasDrawModel (alight_t *plighting)
{
	finalvert_t		finalverts[MAXALIASVERTS +
						((CACHE_SIZE - 1) / sizeof(finalvert_t)) + 1];
	auxvert_t		auxverts[MAXALIASVERTS];

	r_amodels_drawn++;

// cache align
	pfinalverts = (finalvert_t *)
			(((long)&finalverts[0] + CACHE_SIZE - 1) & ~(CACHE_SIZE - 1));
	pauxverts = &auxverts[0];

	paliashdr = (aliashdr_t *)Mod_Extradata (currententity->model);
	pmdl = (mdl_t *)((byte *)paliashdr + paliashdr->model);

	R_AliasSetupSkin ();
	R_AliasSetUpTransform (currententity->trivial_accept);
	R_AliasSetupLighting (plighting);
	R_AliasSetupFrame ();
	...
	if (currententity->trivial_accept)
		R_AliasPrepareUnclippedPoints ();
	else
		R_AliasPreparePoints ();
}
```
This is Quake's own miniature software triangle rasterizer, entirely separate from the BSP edge-list machinery: it transforms model-space vertices, interpolates lighting per vertex (Gouraud), and rasterizes independent, self-contained affine/perspective triangles (with an optimized path, `trivial_accept == 3`, when the whole model is known to be fully on-screen and needs no clipping). `R_DrawEntitiesOnList` (`WinQuake/r_main.c:527-596`) is also where sprites are dispatched via `R_DrawSprite` for `mod_sprite` entities, and where dynamic-light contribution is folded into an entity's `alight_t` before the alias draw call. Particles are handled separately again — `R_DrawParticles` (`WinQuake/r_part.c:653`) is one function shared textually between both renderers via `#ifdef GLQUAKE` (software draws particles as software-projected quads via `D_StartParticles`/`D_DrawParticle`, GL draws camera-facing triangles with `glBegin(GL_TRIANGLES)`), reflecting that particles never interact with the BSP edge list or lightmaps at all — they are pure billboard geometry layered on top of the already-resolved scene.

## Assembly walkthrough: where the Pentium speedup comes from

The assembly makes most sense after surface caching and span generation: Quake has already decided which pixels survive visibility testing and has a lit texture ready to sample. Now a small routine must write those pixels millions of times. Follow **`D_DrawSpans8` in `WinQuake/d_draw.s`** alongside its C equivalent, `WinQuake/d_scan.c:257-383`. `D_DrawSurfaces` obtains the cache and calls through `d_drawspans` at `WinQuake/d_edge.c:299-307`.

> **What “about 2×” measures.** In [Fabien Sanglard’s “How Michael Abrash doubled Quake framerate”](https://fabiensanglard.net/quake_asm_optimizations/index.html), his 2026 recreation on a Pentium MMX 233 MHz runs the VC++ 6 release build at **42.2 fps with assembly versus 22.7 fps with C**: about **1.86× the frame rate**. Both run `timedemo demo1` with `-wavonly +d_subdiv16 0`. Disabling 16-pixel subdivision matters because `D_DrawSpans16` has no C counterpart. This is a whole-engine comparison on period hardware, not a claim that every assembly routine is twice as fast, or a measurement of today’s compilers. His function-by-function experiment identifies `D_DrawSpans8` as the largest contributor.

The selection is explicit in `WinQuake/d_init.c:148-155`: the x86 build can choose the 16-pixel drawer, while the portable path uses the 8-pixel drawer. The walkthrough below traces the repository’s 8-pixel implementation; it does not reproduce the benchmark.

### 1. Keep the integer side working while division runs

#### Historical context: perspective correctness vs. affine warping

In 1995–1996, 3D titles on contemporary platforms (PlayStation 1, Sega Saturn, PC titles like *Descent*) relied on affine texture mapping. Linear interpolation in screen space causes textures on receding walls and floors to warp and swim as the viewpoint shifts.

Carmack refused affine mapping for Quake's world geometry, insisting on perspective-correct texturing. True perspective requires dividing $(s, t)$ by depth $z$ per pixel. On the original P5 Pentium, an 80-bit double-extended precision `fdiv` instruction took 39 clock cycles. Dividing at every pixel on a 90–133 MHz processor was impossible for real-time rendering.

Carmack and Abrash resolved this with piecewise-linear approximation: compute exact $(s/z, t/z, 1/z)$ perspective endpoints every 8 or 16 pixels, and linearly interpolate across each span. Abrash documented in [*Black Book* Chapter 68](../../../historical/abrash_black_book/chapter-68.md) that the polynomial approximation error across 16 pixels is imperceptible on screen except at extreme glancing angles. The cvar `d_subdiv16` (`WinQuake/d_init.c:148-155`) toggles between 16-pixel (`D_DrawSpans16`) and 8-pixel (`D_DrawSpans8`) modes.

The 1996 `.plan` files start after this mapper shipped, so they do not debate it. The preference is still there thirteen years later: affine swim was a ship-blocker.

> **.plan.** I searched around in the level for a view that would confirm my suspicion, and when I found a clear enough view of some angled geometry I saw the tell-tale mid-polygon affine swim in the texture as I rotated. They were using the software rasterizer on the iPhone. — [Carmack, 26 Mar 2009](../../../historical/plans/carmack/by_day/johnc_plan_20090326.txt), on a later title; same refusal.

#### Slashing FDIV latency via x87 precision control

Even across 8 or 16 pixels, a 39-cycle division latency was too long to hide behind integer pixel writes. Abrash exploited an architectural detail of the x87 FPU documented in [*Black Book* Chapter 63](../../../historical/abrash_black_book/chapter-63.md): setting the FPU control word to 24-bit single precision mode via `fldcw` dropped `fdiv` execution time from 39 cycles to 19 cycles.

Quake executes this mode switch in `WinQuake/r_main.c:972-976` immediately before edge rasterization:

```c
// WinQuake/r_main.c:972-976
// make FDIV fast. This reduces timing precision after we've been running for a
// while, so we don't do it globally.  This also sets chop mode, and we do it
// here so that setup stuff like the refresh area calculations match what's
// done in screen.c
	Sys_LowFPPrecision ();
```

`Sys_LowFPPrecision` (`WinQuake/sys_wina.s:68-72`, `WinQuake/sys_dosa.s:47-51`) loads `single_cw` (`0x003f` masked and configured with `orb $0x0C, %ah` in `WinQuake/sys_wina.s:105` for single precision and chop mode). Once the scene finishes rendering, `Sys_HighFPPrecision` (`WinQuake/r_main.c:1048`) restores 64-bit precision (`full_cw`).

> **Pentium FDIV bug.** The overlapping `fdiv` this inner loop depends on is also where Abrash reproduced Intel’s 1994 FDIV bug (missing SRT-table entries; wrong quotients from some camera angles). Romero described that hunt in a 2019 talk; it is not in the `.plan` files. See [Pentium FDIV bug](https://en.wikipedia.org/wiki/Pentium_FDIV_bug).

The C algorithm already amortizes perspective correction across eight pixels. Once it has the texture coordinates and their steps, its inner loop is tiny:

```c
// WinQuake/d_scan.c:370-375
            do
            {
                *pdest++ = *(pbase + (s >> 16) + (t >> 16) * cachewidth);
                s += sstep;
                t += tstep;
            } while (--spancount > 0);
```

The assembly keeps that algorithm but changes its execution schedule and its representation of the texture address. The key scheduling opportunity is that drawing the current segment needs its existing integer steps, while calculating a later segment’s endpoint needs floating-point division. Those jobs can overlap. Abrash describes this integer/FPU overlap in [Black Book chapter 68](https://www.phatcode.net/res/224/files/html/ch68/68-03.html (archived: https://web.archive.org/web/20260313002527/https://www.phatcode.net/res/224/files/html/ch68/68-03.html)); his quoted 7.5 cycles per pixel concerns the **16-pixel** mapper, so it should not be attached to this 8-pixel listing.

These are ordinary 32-bit x86 instructions plus the **x87 floating-point stack**, not MMX vector instructions. A few reading conventions are enough: AT&T syntax writes **source, destination**; `%` marks a register, `$` an immediate constant, and `4(%edi)` memory four bytes after `%edi`. The suffixes `b` and `l` mean byte and 32-bit integer operations here. `%st(0)` is the top x87 stack register; `fxch` swaps it with another stack entry. `C(name)` is Quake’s assembler macro for platform-dependent symbol naming (`WinQuake/asm_i386.h:25-29`).

In the steady path, after writing pixels 0–3, the code advances the perspective quantities to the endpoint needed **after the current segment**, starts its division, and resumes integer drawing:

```asm
// WinQuake/d_draw.s:459-478
LSetupNotLast2:
    fadds   zi8stepu
    fxch    %st(2)
    fadds   sdivz8stepu
    fxch    %st(2)
    flds    tdivz8stepu
    faddp   %st(0),%st(2)
    flds    fp_64k
    fdiv    %st(1),%st(0)    // z = 1/1/z
                            // this is what we've gone to all this trouble to
                            //  overlap
LFDIVInFlight2:
    movl    %ecx,counttemp

    addl    tstep,%edx
    sbbl    %ecx,%ecx
    movb    %al,4(%edi)
    addl    %ebp,%ebx
    movb    (%esi),%al
    adcl    advancetable+4(,%ecx,4),%esi
```

`fp_64k` supplies 65536, so the division computes `65536 / zi`, preparing a reciprocal depth scaled for 16.16 texture coordinates. The following integer operations do not consume that result. They advance fractional coordinates, write pixel 4 and load the next texel. Pixels 5–7 and segment bookkeeping follow (`WinQuake/d_draw.s:480-509`). Only when execution returns to `LNotLastSegment` does it use the division result to multiply `s/z` and `t/z`, then convert the new endpoints to integers (`WinQuake/d_draw.s:313-330`).

::: diagram asm-overlap

This is one instruction stream arranged to keep different execution resources useful. Issuing the divide early creates room to hide its latency; it does not guarantee that every divide finishes before it is needed. The first segment has a separate setup: its initial division overlaps integer coordinate clamping and address preparation (`WinQuake/d_draw.s:261-311`). The short final segment has its own endpoint calculation. That setup/steady-state/tail structure explains much of the apparent complexity in the assembly.

### 2. Turn texture-coordinate overflow into an address increment

The C loop expresses each source address as `pbase + floor(s) + floor(t) * cachewidth`. The assembly instead **keeps a running texel pointer** in `%esi`. It splits each step into a signed integer part and a fractional part. Setup computes two possible integer pointer advances once per segment (`WinQuake/d_draw.s:361-398`):

| Table entry | Stored byte advance |
|---|---|
| `advancetable + 4` | `base = floor(sstep) + floor(tstep) * cachewidth` |
| `advancetable` | `base + cachewidth` — one additional texture row |

Here `floor(sstep)` means the whole-texel component of the fixed-point step, not a floating-point operation in the loop. The fractions are left-justified in 32-bit registers, so wrapping past one texel sets the CPU’s carry flag. Even a negative step fits this decomposition: its integer part rounds downward and its remaining fractional part is nonnegative. A carry then supplies the extra column or row when that fraction wraps.

Read one repeated pixel operation from `WinQuake/d_draw.s:400-405`:

```asm
// WinQuake/d_draw.s:400-405
    addl    tstep,%edx
    sbbl    %ecx,%ecx
    movb    (%esi),%al
    addl    %ebp,%ebx
    movb    %al,1(%edi)
    adcl    advancetable+4(,%ecx,4),%esi
```

| Instruction | What it does for this pixel |
|---|---|
| `addl tstep,%edx` | Advance the fractional `t` accumulator; carry means an extra row. |
| `sbbl %ecx,%ecx` | Compute `ecx - ecx - carry`: zero without a carry, −1 with one. Save the row decision as a table selector. |
| `movb (%esi),%al` | Fetch the current 8-bit texel from the already-lit surface cache. |
| `addl %ebp,%ebx` | Advance the fractional `s` accumulator; this produces a new carry for an extra column. |
| `movb %al,1(%edi)` | Write this pixel at a fixed offset in the unrolled segment. `mov` preserves the carry flag. |
| `adcl advancetable+4(,%ecx,4),%esi` | Select the base or extra-row advance, then add it **plus the `s` carry** to the source pointer. |

The address expression is `advancetable + 4 + ecx * 4`: `ecx = 0` selects the ordinary advance; `ecx = -1` selects the extra-row entry. The four outcomes are therefore:

| `t` carry | `s` carry | Pointer advances by |
|---|---|---|
| 0 | 0 | `base` |
| 0 | 1 | `base + 1` |
| 1 | 0 | `base + cachewidth` |
| 1 | 1 | `base + cachewidth + 1` |

For example, with a 64-byte cache row and integer steps of one column and zero rows, `base` is 1. If both fractions wrap, the pointer advances **66 bytes**: two columns and one row. No per-pixel multiply, shifts to recover whole coordinates, or conditional branches for those two wrap decisions are needed. The multiplication moved into segment setup. Notice how the **flags are part of the data flow**: inserting an instruction that changes carry between the `s` add and `adc` would break the address calculation.

### 3. Specialize the end of the span

Eight copies of the pixel work use fixed destination offsets; the full-segment path tests the remaining count once per segment (`WinQuake/d_draw.s:400-509`). But a wall edge rarely gives a multiple of eight pixels. Drawing beyond the span would overwrite another surface, and extrapolating the texture endpoint could also reach outside the cached image.

The portable code handles the last segment by evaluating perspective at its **last actual pixel**, using `spancount - 1` as the distance, and dividing the coordinate differences by that distance (`WinQuake/d_scan.c:338-367`). Assembly preserves that endpoint rule while replacing the step divisions with fixed-point reciprocal-table multiplies. Then `entryvec_table` selects a short-span handler and `jmp *jumptemp` enters the appropriate drawing path (`WinQuake/d_draw.s:514-605`). Those handlers arrange the registers and destination offset for the remaining unrolled pixel writes; a single pixel has a separate path (`WinQuake/d_draw.s:609-755`).

That removes a decrement-and-branch for every tail pixel. It does **not** make branches or prediction disappear: there is still an indirect dispatch and special-case setup. The tradeoff is more code and more carefully maintained entry conditions in exchange for a shorter frequently executed path.

### 4. Build lit texels with byte registers and patched instructions

Now move one stage earlier, to a **surface-cache miss**. `R_DrawSurfaceBlock8_mip0` builds a block of the lit texture that the span drawer will later read. The corresponding C combines an interpolated lighting value with the source palette index and looks up the lit palette index (`WinQuake/r_surf.c:361-374`):

```c
// WinQuake/r_surf.c:368-374
            for (b=15; b>=0; b--)
            {
                pix = psource[b];
                prowdest[b] = ((unsigned char *)vid.colormap)
                        [(light & 0xFF00) + pix];
                light += lightstep;
            }
```

The index is already naturally two bytes: **`0x0000LLTT`**, with light-table row `LL` above texture palette index `TT`. In `WinQuake/surf8.s:103-125`, the upper bits of `%ebx` are cleared, then `movb %dh,%bh` puts the lighting byte in the high byte and `movb 15(%esi),%bl` puts the texel in the low byte. Together `%ebx` becomes the index without a separate mask, shift and addition. `%ecx` constructs a second index alongside it.

The lookup itself contains something surprising:

```asm
// WinQuake/surf8.s:121-126
    movb    0x12345678(%ebx),%ah
LBPatch0:
    movb    13(%esi),%bl

    movb    0x12345678(%ecx),%al
LBPatch1:
```

**`0x12345678` is a patch location, not the real colormap address.** During `R_ViewChanged`, Quake makes the relevant code writable, assigns `colormap = vid.colormap`, and calls `R_Surf8Patch` (`WinQuake/r_main.c:467-473`). A table contains addresses such as `LBPatch0 - 4`: the four-byte displacement immediately before that label (`WinQuake/surf8.s:728-760`). The patch routine overwrites those displacements with the actual colormap base:

```asm
// WinQuake/surf8.s:769-777
    movl    C(colormap),%eax
    movl    $LPatchTable8,%ebx
    movl    $32,%ecx
LPatchLoop8:
    movl    (%ebx),%edx
    addl    $4,%ebx
    movl    %eax,(%edx)
    decl    %ecx
    jnz     LPatchLoop8
```

The hot lookup now embeds an invariant address directly in its instruction, freeing a general-purpose register from holding the colormap base. Patching happens outside the texel loop. This is runtime specialization using self-modifying code, with an explicit writable-code setup in this engine.

Finally, `%ah` and `%al` collect two lit texels; `rorl $16,%eax` moves them into the upper half, allowing the next two lookups to fill the lower half. A single `movl %eax,12(%edi)` writes four neighboring texels into the cache (`WinQuake/surf8.s:121-144`). The reverse texel order, rotation and little-endian store fit together to preserve their order in memory. This is scalar packing into one 32-bit store, not four simultaneous SIMD lookups.

### What to look for when reading the rest of the assembly

Follow **where a value becomes available and where it is next consumed**. In the span drawer that exposes a place to overlap division, a carry flag that replaces a coordinate calculation, and a tail whose length becomes a code-entry choice. In the surface builder it exposes a lookup index assembled through byte registers and a constant baked into the instruction stream. These are concrete changes to scheduling and representation around Quake’s renderer design; the concise C loops alone do not show them.

For a source-reading session, trace `LNotLastSegment` → `LSetupNotLast2` → `LFDIVInFlight2` → `LNotLastSegment` first, with a span long enough to take the steady path. Then follow `LLastSegment`, and only afterward the clamp branches. Keep `d_scan.c` open as the algorithmic reference and `surf8.s` as the separate cache-building example.

## GL renderer: texture chains, lightmaps, and hardware rasterization

The GL renderer keeps the *same* BSP walk logic (front-to-back recursive node traversal driven by the eye's position relative to each splitting plane) because it is still the cheapest way to reject non-visible geometry using the PVS, but it no longer needs the edge list at all — the GPU rasterizer resolves per-pixel visibility itself via the depth buffer. So GL's `R_RecursiveWorldNode` (`WinQuake/gl_rsurf.c:1190`) does the same node/leaf recursion as the software version, but instead of feeding an edge table it either draws a surface immediately or, more commonly, links it into one of several **texture chains** so that all surfaces sharing a texture (and hence a GL bind) are drawn consecutively — minimizing state changes, the GL-era equivalent of the software renderer's overdraw-avoidance concern:
```c
// WinQuake/gl_rsurf.c:1273-1296
				// if sorting by texture, just store it out
				if (gl_texsort.value)
				{
					if (!mirror
					|| surf->texinfo->texture != cl.worldmodel->textures[mirrortexturenum])
					{
						surf->texturechain = surf->texinfo->texture->texturechain;
						surf->texinfo->texture->texturechain = surf;
					}
				} else if (surf->flags & SURF_DRAWSKY) {
					surf->texturechain = skychain;
					skychain = surf;
				} else if (surf->flags & SURF_DRAWTURB) {
					surf->texturechain = waterchain;
					waterchain = surf;
				} else
					R_DrawSequentialPoly (surf);
```
Also note the explicit box-vs-frustum test at the top of this function, factored into a reusable helper rather than inlined as in the software path:
```c
// WinQuake/gl_rsurf.c:1200-1205
	if (node->contents == CONTENTS_SOLID)
		return;		// solid

	if (node->visframe != r_visframecount)
		return;
	if (R_CullBox (node->minmaxs, node->minmaxs+3))
		return;
```
`R_CullBox` (`WinQuake/gl_rmain.c:111-118`) is a tight loop over the four frustum planes using `BoxOnPlaneSide`:
```c
// WinQuake/gl_rmain.c:111-119
qboolean R_CullBox (vec3_t mins, vec3_t maxs)
{
	int		i;

	for (i=0 ; i<4 ; i++)
		if (BoxOnPlaneSide (mins, maxs, &frustum[i]) == 2)
			return true;
	return false;
}
```
Its simplicity versus the software renderer's inlined corner-selection code is a good example of the GL renderer trading an additional helper call against the "every cycle counts" discipline the software path was written under — a call the id programmers could make once the GPU was doing the actual per-pixel work.

Once the BSP walk finishes, `DrawTextureChains` (`WinQuake/gl_rsurf.c:1029`) flushes the per-texture chains built above, in ordinary (non-multitexture) or lightmap-blended passes, and `R_DrawWorld` (`WinQuake/gl_rsurf.c:1316`) ties it together:
```c
// WinQuake/gl_rsurf.c:1316-1339
void R_DrawWorld (void)
{
	entity_t	ent;
	int			i;

	memset (&ent, 0, sizeof(ent));
	ent.model = cl.worldmodel;

	VectorCopy (r_refdef.vieworg, modelorg);

	currententity = &ent;
	currenttexture = -1;

	glColor3f (1,1,1);
	memset (lightmap_polys, 0, sizeof(lightmap_polys));
#ifdef QUAKE2
	R_ClearSkyBox ();
#endif

	R_RecursiveWorldNode (cl.worldmodel->nodes);

	DrawTextureChains ();

	R_BlendLightmaps ();
```

### Lightmaps and multitexture

Lightmaps are precomputed low-resolution light grids baked at BSP-compile time and, at runtime, packed into shared `BLOCK_WIDTH x BLOCK_HEIGHT` GL texture atlases (`lightmaps[]`, `WinQuake/gl_rsurf.c:55`; up to `MAX_LIGHTMAPS` textures starting at `texture_extension_number`, `WinQuake/gl_rsurf.c:1613-1614`). Without multitexturing, Quake would have to render every lightmapped surface twice — once for the base texture, once more with the lightmap texture blended over it (visible in the disabled `#if 0` legacy path at `WinQuake/gl_rsurf.c:316`). `GL_ARB_multitexture`/`GL_SGIS_multitexture` let both texture units be sampled and combined in a single rasterization pass, which is exactly what `R_DrawSequentialPoly` (`WinQuake/gl_rsurf.c:413`) does when available.

> **.plan.** Because of the very fill-rate intensive nature of the way I implemented this version of glquake (using a blend pass to do the light maps), performance is not likely to be very good on any current generation consumer level board except 3dfx. — [Carmack, 23 Nov 1996](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt)
```c
// WinQuake/gl_rsurf.c:429-459
		R_RenderDynamicLightmaps (s);
		if (gl_mtexable) {
			p = s->polys;

			t = R_TextureAnimation (s->texinfo->texture);
			// Binds world to texture env 0
			GL_SelectTexture(qglMTex0);
			GL_Bind (t->gl_texturenum);
			glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE);
			// Binds lightmap to texenv 1
			GL_EnableMultitexture(); // Same as SelectTexture (TEXTURE1)
			GL_Bind (lightmap_textures + s->lightmaptexturenum);
			i = s->lightmaptexturenum;
			if (lightmap_modified[i])
			{
				lightmap_modified[i] = false;
				theRect = &lightmap_rectchange[i];
				glTexSubImage2D(GL_TEXTURE_2D, 0, 0, theRect->t, 
					BLOCK_WIDTH, theRect->h, gl_lightmap_format, GL_UNSIGNED_BYTE,
					lightmaps+(i* BLOCK_HEIGHT + theRect->t) *BLOCK_WIDTH*lightmap_bytes);
				...
			}
			glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_BLEND);
			glBegin(GL_POLYGON);
			v = p->verts[0];
			for (i=0 ; i<p->numverts ; i++, v+= VERTEXSIZE)
			{
				qglMTexCoord2f (qglMTex0, v[3], v[4]);
				qglMTexCoord2f (qglMTex1, v[5], v[6]);
				glVertex3fv (v);
			}
			glEnd ();
			return;
		}
```
The extension probing itself lives in `CheckMultiTextureExtensions` and is the piece added in this branch's history for portability beyond Windows: `WinQuake/gl_vidlinuxglx.c:548-581` checks for either `GL_SGIS_multitexture` or `GL_ARB_multitexture` and resolves the right entry points (`glMTexCoord2fSGIS`/`glSelectTextureSGIS` vs. `glMultiTexCoord2fARB`/`glActiveTextureARB`) via `dlsym`:
```c
// WinQuake/gl_vidlinuxglx.c:552-571
	qboolean gl_mtex_avail = strstr(gl_extensions, "GL_SGIS_multitexture ") || strstr(gl_extensions, "GL_ARB_multitexture ");

	if (gl_mtex_avail && !COM_CheckParm("-nomtex")) {
		...
		if (strstr(gl_extensions, "GL_SGIS_multitexture ")) {
			qglMTexCoord2f = (void *) dlsym(prjobj, "glMTexCoord2fSGIS");
			qglSelectTexture = (void *) dlsym(prjobj, "glSelectTextureSGIS");
			qglMTex0 = TEXTURE0_SGIS;
			qglMTex1 = TEXTURE1_SGIS;
		} else {
			qglMTexCoord2f = (void *) dlsym(prjobj, "glMultiTexCoord2fARB");
			qglSelectTexture = (void *) dlsym(prjobj, "glActiveTextureARB");
			qglMTex0 = TEXTURE0_ARB;
			qglMTex1 = TEXTURE1_ARB;
		}
```
When neither extension is present (`gl_mtexable == false`), the fallback path in the same function draws the base-textured polygon, then re-binds the lightmap texture and re-draws the same polygon with `GL_BLEND` enabled — functionally identical output at twice the vertex/rasterization cost, which is exactly the cost multitexturing was designed to eliminate.

### Sky and water warp (`gl_warp.c`)

Underwater surfaces and sky are both procedurally distorted in texture space rather than geometrically re-tessellated. `EmitWaterPolys` (`WinQuake/gl_warp.c:194`) perturbs each pre-fragmented `glpoly_t`'s texture coordinates with a sine lookup table (`turbsin[]`, generated into `gl_warp_sin.h`) as a function of both the *other* texture axis and time — a texture-space water effect. The software renderer also warps water texture coordinates in `Turbulent8` (`WinQuake/d_scan.c:122-246`); its separate `D_WarpScreen` (`WinQuake/d_scan.c:44`) distorts the final image when the camera is underwater:
```c
// WinQuake/gl_warp.c:194-219
void EmitWaterPolys (msurface_t *fa)
{
	glpoly_t	*p;
	float		*v;
	int			i;
	float		s, t, os, ot;

	for (p=fa->polys ; p ; p=p->next)
	{
		glBegin (GL_POLYGON);
		for (i=0,v=p->verts[0] ; i<p->numverts ; i++, v+=VERTEXSIZE)
		{
			os = v[3];
			ot = v[4];

			s = os + turbsin[(int)((ot*0.125+realtime) * TURBSCALE) & 255];
			s *= (1.0/64);

			t = ot + turbsin[(int)((os*0.125+realtime) * TURBSCALE) & 255];
			t *= (1.0/64);

			glTexCoord2f (s, t);
			glVertex3fv (v);
		}
		glEnd ();
	}
}
```
Sky is drawn in two layers (a slow-scrolling opaque cloud layer and a faster alpha-blended layer) bound to `solidskytexture`/`alphaskytexture`, via `R_DrawSkyChain` (`WinQuake/gl_warp.c:304`, the `#ifndef QUAKE2` variant used by this codebase):
```c
// WinQuake/gl_warp.c:304-326
void R_DrawSkyChain (msurface_t *s)
{
	msurface_t	*fa;

	GL_DisableMultitexture();

	// used when gl_texsort is on
	GL_Bind(solidskytexture);
	speedscale = realtime*8;
	speedscale -= (int)speedscale & ~127 ;

	for (fa=s ; fa ; fa=fa->texturechain)
		EmitSkyPolys (fa);

	glEnable (GL_BLEND);
	GL_Bind (alphaskytexture);
	speedscale = realtime*16;
	speedscale -= (int)speedscale & ~127 ;

	for (fa=s ; fa ; fa=fa->texturechain)
		EmitSkyPolys (fa);

	glDisable (GL_BLEND);
}
```

### Alias models: `R_DrawAliasModel` and `gl_mesh.c` strips/fans

The GL renderer bounds-culls, lights (identically to the software path's ambient/dlight accumulation), and transforms alias entities in `R_DrawAliasModel` (`WinQuake/gl_rmain.c:446`):
```c
// WinQuake/gl_rmain.c:446-465
void R_DrawAliasModel (entity_t *e)
{
	...
	clmodel = currententity->model;

	VectorAdd (currententity->origin, clmodel->mins, mins);
	VectorAdd (currententity->origin, clmodel->maxs, maxs);

	if (R_CullBox (mins, maxs))
		return;

	VectorCopy (currententity->origin, r_entorigin);
	VectorSubtract (r_origin, r_entorigin, modelorg);
```
but instead of rasterizing triangles itself, it delegates to `GL_DrawAliasFrame` (`WinQuake/gl_rmain.c:289`), which walks a command stream built once at model load by `gl_mesh.c`. `BuildTris` (`WinQuake/gl_mesh.c:194-282`) greedily chains adjacent triangles into `GL_TRIANGLE_STRIP` or `GL_TRIANGLE_FAN` runs (`StripLength`/`FanLength`, `WinQuake/gl_mesh.c:58`/`127`), reducing repeated vertex submissions. The strip/fan length is sign-encoded into a single `commands[]` int array (positive = strip length, negative = fan length):
```c
// WinQuake/gl_mesh.c:245-249
		if (besttype == 1)
			commands[numcommands++] = (bestlen+2);
		else
			commands[numcommands++] = -(bestlen+2);
```
`GL_DrawAliasFrame` then just replays that command stream every frame, re-transforming the (fixed) vertex order against the *current* frame's pose data and shading:
```c
// WinQuake/gl_rmain.c:306-332
	order = (int *)((byte *)paliashdr + paliashdr->commands);

	while (1)
	{
		// get the vertex count and primitive type
		count = *order++;
		if (!count)
			break;		// done
		if (count < 0)
		{
			count = -count;
			glBegin (GL_TRIANGLE_FAN);
		}
		else
			glBegin (GL_TRIANGLE_STRIP);

		do
		{
			// texture coordinates come from the draw list
			glTexCoord2f (((float *)order)[0], ((float *)order)[1]);
			order += 2;

			// normals and vertexes come from the frame list
			l = shadedots[verts->lightnormalindex] * shadelight;
			glColor3f (l, l, l);
			glVertex3f (verts->v[0], verts->v[1], verts->v[2]);
			verts++;
		} while (--count);

		glEnd ();
	}
```
Per-vertex lighting here does not compute a dot product against each live normal. `shadedots` indexes a precomputed table for 162 quantized vertex normals (`r_avertexnormal_dots`), trading repeated vector math for a lookup.

### The GL frame in one call

`R_RenderView` (`WinQuake/gl_rmain.c:1104`) clears buffers, then calls `R_RenderScene` (`WinQuake/gl_rmain.c:949`), which is the GL analogue of the software `R_EdgeDrawing`/`R_DrawEntitiesOnList` sequence, minus any edge-list bookkeeping:
```c
// WinQuake/gl_rmain.c:949-968
void R_RenderScene (void)
{
	R_SetupFrame ();

	R_SetFrustum ();

	R_SetupGL ();

	R_MarkLeaves ();	// done here so we know if we're in water

	R_DrawWorld ();		// adds static entities to the list

	S_ExtraUpdate ();	// don't let sound get messed up if going slow

	R_DrawEntitiesOnList ();

	GL_DisableMultitexture();

	R_RenderDlights ();

	R_DrawParticles ();
}
```
`R_SetFrustum` (`WinQuake/gl_rmain.c:769`) computes the four frustum plane normals from the current view vectors and FOV (rotating the view-plane-normal by half the horizontal/vertical FOV), which is what `R_CullBox` tests candidate boxes against for the remainder of the frame.

## Call graph

```
Host_Frame
  SCR_UpdateScreen                    screen.c:808 / gl_screen.c:821
    V_RenderView                      view.c:995
      V_CalcRefdef                    view.c:864
        V_CalcBob                     view.c:112
        CalcGunAngle                  view.c (called view.c:924)
      R_PushDlights
      R_RenderView  [software]        r_main.c:1049 -> R_RenderView_ r_main.c:953
        R_SetupFrame                  r_misc.c:367
        R_MarkLeaves                  r_main.c:491
        R_EdgeDrawing                 r_main.c:876
          R_RenderWorld                r_bsp.c:648
            R_RecursiveWorldNode       r_bsp.c:448
              R_RenderFace              r_draw.c:386
          R_ScanEdges                  r_edge.c:663
            R_LeadingEdgeBackwards      r_edge.c:335
            R_TrailingEdge
            D_DrawSurfaces              d_iface.h:154 (d_edge.c)
              D_CacheSurface            d_surf.c:264
                R_DrawSurface
                  D_DrawSpans8 / Turbulent8   d_scan.c:257 / d_scan.c:122
        R_DrawEntitiesOnList          r_main.c:527
          R_AliasDrawModel            r_alias.c:703
          R_DrawSprite
        R_DrawViewModel               r_main.c:606
        R_DrawParticles               r_part.c:653
        D_WarpScreen                  d_scan.c:44
      R_RenderView  [GL]              gl_rmain.c:1104
        R_Clear                       gl_rmain.c:983
        R_RenderScene                 gl_rmain.c:949
          R_SetupFrame                gl_rmain.c:810
          R_SetFrustum                gl_rmain.c:769
          R_MarkLeaves
          R_DrawWorld                 gl_rsurf.c:1316
            R_RecursiveWorldNode       gl_rsurf.c:1190
              R_CullBox                 gl_rmain.c:111
            DrawTextureChains          gl_rsurf.c:1029
              R_DrawSequentialPoly      gl_rsurf.c:413
              R_DrawSkyChain            gl_warp.c:304
                EmitSkyPolys
            R_BlendLightmaps
          R_DrawEntitiesOnList        r_main.c:527 (shared)
            R_DrawAliasModel           gl_rmain.c:446
              GL_DrawAliasFrame         gl_rmain.c:289
        R_DrawViewModel                gl_rmain.c:647
        R_DrawWaterSurfaces
          EmitWaterPolys                gl_warp.c:194
        R_Mirror
        R_PolyBlend                    gl_rmain.c:718
```

## Key data structures

- `surf_t` — `WinQuake/r_shared.h:79-99` — active-surface-stack node in `r_edge.c`; carries `key` (BSP sort order), `spans`, and `nearzi` for the software renderer's depth resolution.
- `edge_t` — `WinQuake/r_shared.h:144-153` — one BSP-surface edge in the global edge table; `u`/`u_step` are the fixed-point screen-x position and per-scanline slope.
- `espan_t` — `WinQuake/r_shared.h:71-75` — a single horizontal visible pixel run (`u`, `v`, `count`) queued for texturing.
- `surfcache_t` — `WinQuake/d_local.h:37-49` — one cached, pre-lit/pre-textured surface bitmap in the software surface-cache heap; invalidated by animation, dlights, or lightstyle changes.
- `msurface_t` — `WinQuake/model.h:102-126` — a BSP face: plane, texinfo, lighting styles, `SURF_*` flags (sky/turb/planeback/underwater).
- `mnode_t` — `WinQuake/model.h:128-144` — BSP interior/leaf node; carries `minmaxs` bounding box used by both frustum-cull paths and `visframe` for PVS marking.
- `glpoly_t` — `WinQuake/gl_model.h:115-122` — GL renderer's fragmented (t-junction-free) polygon representation, `verts[][VERTEXSIZE]` packing xyz + two texcoord pairs (base + lightmap).
- `aliashdr_t` / MDL command stream — `WinQuake/gl_mesh.c` builds `commands[]`/`vertexorder[]` consumed by `GL_DrawAliasFrame` (`gl_rmain.c:289`).
- `cshift_t` / `cl.cshifts[NUM_CSHIFTS]` — `WinQuake/view.c:254-257` (constants) — per-cause (water/slime/lava/damage/bonus/powerup) destination color + blend percent.

## Further reading

- Michael Abrash, *Graphics Programming Black Book*, chapters on Quake's renderer (edge lists, span sorting, surface caching, perspective texture mapping): local archive at `docs/historical/abrash_black_book/` ([Chapter 63: Floating-Point Optimization](../../../historical/abrash_black_book/chapter-63.md), [Chapter 64: Quake's 3-D Engine](../../../historical/abrash_black_book/chapter-64.md), [Chapter 68: Surface Caching and Span Drawing](../../../historical/abrash_black_book/chapter-68.md)); also online at https://www.jagregory.com/abrash-black-book/
- Fabien Sanglard, "How Michael Abrash doubled Quake framerate" — benchmark setup and assembly investigation: https://fabiensanglard.net/quake_asm_optimizations/index.html
- Fabien Sanglard, "Quake Source Code Review": https://fabiensanglard.net/quakeSource/index.php
- Olivier Montanuy et al., "Unofficial Quake Specs": https://www.gamers.org/dEngine/quake/spec/quake-spec34/ (archived: https://web.archive.org/web/20251206223630/https://www.gamers.org/dEngine/quake/spec/quake-spec34/)
- John Carmack .plan archive (renderer-era design notes): local archive at `docs/historical/plans/carmack/` ([23 Nov 1996, GLQuake blend-pass lightmaps](../../../historical/plans/carmack/by_day/johnc_plan_19961123.txt), [26 Mar 2009, affine swim](../../../historical/plans/carmack/by_day/johnc_plan_20090326.txt))
- Matthew Earl (Matt's Ramblings), "How Quake's software renderer ELIMINATES overdraw" — the edge list and span sorting, visualised. Title carries a flashing-images warning: https://www.youtube.com/watch?v=zdXsHWHxeBY
- Matthew Earl (Matt's Ramblings), "Shedding light on Quake I and II lightmapping" — how lightmaps are built and applied: https://www.youtube.com/watch?v=bxientPsqRg
- Michael Abrash, *Ramblings in Realtime* (Blue's News, 2000) — the Quake articles as Abrash released them, with his own permission note and acknowledgements: https://www.bluesnews.com/abrash/ (archived: https://web.archive.org/web/20260603214111/https://www.bluesnews.com/abrash/) (mirror, if that host blocks you: https://valvedev.info/archives/abrash/contents.html). Content matches *Black Book* ch. 64 and 66-70, held locally.
