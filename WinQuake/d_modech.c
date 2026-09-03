/*
Copyright (C) 1996-1997 Id Software, Inc.

This program is free software; you can redistribute it and/or
modify it under the terms of the GNU General Public License
as published by the Free Software Foundation; either version 2
of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  

See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

*/
// d_modech.c: called when mode has just changed

#include "quakedef.h"
#include "d_local.h"

#define PARTICLE_BASE_WIDTH	320.0	// view width the particle sizes below assume
#define PARTICLE_BASE_SIZE	256.0	// resulting pix at z == 1

int	d_vrectx, d_vrecty, d_vrectright_particle, d_vrectbottom_particle;

int	d_y_aspect_shift, d_pix_min, d_pix_max, d_pix_shift;
float	d_particle_scale;

int		d_scantable[MAXHEIGHT];
short	*zspantable[MAXHEIGHT]; 

/*
================
D_Patch
================
*/
void D_Patch (void)
{
#if id386

	static qboolean protectset8 = false;

	if (!protectset8)
	{
		Sys_MakeCodeWriteable ((int)D_PolysetAff8Start,
						     (int)D_PolysetAff8End - (int)D_PolysetAff8Start);
		protectset8 = true;
	}

#endif	// id386
}


/*
================
D_ViewChanged
================
*/
void D_ViewChanged (void)
{
	int rowbytes;
	float pixscale;

	if (r_dowarp)
		rowbytes = WARP_WIDTH;
	else
		rowbytes = vid.rowbytes;

	scale_for_mip = xscale;
	if (yscale > xscale)
		scale_for_mip = yscale;

	d_zrowbytes = vid.width * 2;
	d_zwidth = vid.width;

// A particle is a pix*pix screen square, pix falling off as 1/z.  Sizes are
// defined for a 320-wide view (PARTICLE_BASE_SIZE / z pixels, clamped to
// 1..4) and scaled linearly with the viewport so a particle keeps the same
// angular size at any resolution.
//
// The original code computed pix as izi >> d_pix_shift, which quantizes the
// scale to powers of two: at 1600 wide it came out 3.2x too big, so nearby
// particles sat pinned at d_pix_max and never shrank with distance.
// d_pix_shift survives only for the i386 assembly path.
	pixscale = (float)r_refdef.vrect.width / PARTICLE_BASE_WIDTH;

	d_particle_scale = PARTICLE_BASE_SIZE * pixscale;

	d_pix_min = (int)pixscale;
	if (d_pix_min < 1)
		d_pix_min = 1;

	d_pix_max = (int)(4.0 * pixscale + 0.5);
	if (d_pix_max < 1)
		d_pix_max = 1;

	d_pix_shift = 8 - (int)(pixscale + 0.5);

	if (pixelAspect > 1.4)
		d_y_aspect_shift = 1;
	else
		d_y_aspect_shift = 0;

	d_vrectx = r_refdef.vrect.x;
	d_vrecty = r_refdef.vrect.y;
	d_vrectright_particle = r_refdef.vrectright - d_pix_max;
	d_vrectbottom_particle =
			r_refdef.vrectbottom - (d_pix_max << d_y_aspect_shift);

	{
		int		i;

		for (i=0 ; i<vid.height; i++)
		{
			d_scantable[i] = i*rowbytes;
			zspantable[i] = d_pzbuffer + i*d_zwidth;
		}
	}

	D_Patch ();
}

