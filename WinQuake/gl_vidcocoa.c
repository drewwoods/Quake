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
// gl_vidcocoa.c -- macOS video driver for glquake.  The Quake half of the
// port; the Cocoa half lives in vid_cocoa.m behind the C interface in
// vid_cocoa.h.  Modelled on gl_vidlinuxglx.c.

#include <signal.h>
#include <stdarg.h>
#include <stdio.h>

#include "quakedef.h"
#include "vid_cocoa.h"

#define WARP_WIDTH		320
#define WARP_HEIGHT		200

unsigned short	d_8to16table[256];
unsigned	d_8to24table[256];
unsigned char	d_15to8table[65536];

cvar_t	vid_mode = {"vid_mode","0",false};

static qboolean	mouse_avail;
static qboolean	mouse_active;
static int	mx, my;
static int	old_mouse_x, old_mouse_y;

static cvar_t	in_mouse = {"in_mouse", "1", false};
static cvar_t	m_filter = {"m_filter", "0"};

static int	scr_width, scr_height;
static qboolean	vid_initialized = false;

/*-----------------------------------------------------------------------*/

int		texture_mode = GL_LINEAR;

int		texture_extension_number = 1;

float		gldepthmin, gldepthmax;

cvar_t	gl_ztrick = {"gl_ztrick","1"};

const char *gl_vendor;
const char *gl_renderer;
const char *gl_version;
const char *gl_extensions;

static float vid_gamma = 1.0;

qboolean is8bit = false;
qboolean isPermedia = false;
qboolean gl_mtexable = false;

/*-----------------------------------------------------------------------*/
void D_BeginDirectRect (int x, int y, byte *pbitmap, int width, int height)
{
}

void D_EndDirectRect (int x, int y, int width, int height)
{
}

/*
===============
MacKeyToQuake

Special keys come from the mac virtual keycode, which is layout independent.
Everything else falls back to the unshifted character Cocoa handed us, which
is already what Key_Event wants.  Returns 0 for keys Quake has no use for.
===============
*/
static int MacKeyToQuake (int keycode, int ch)
{
	switch (keycode)
	{
	case 53:	return K_ESCAPE;
	case 48:	return K_TAB;
	case 36:	return K_ENTER;
	case 76:	return K_ENTER;		// keypad enter
	case 51:	return K_BACKSPACE;
	case 117:	return K_DEL;
	case 114:	return K_INS;		// help, where insert would be

	case 123:	return K_LEFTARROW;
	case 124:	return K_RIGHTARROW;
	case 125:	return K_DOWNARROW;
	case 126:	return K_UPARROW;

	case 116:	return K_PGUP;
	case 121:	return K_PGDN;
	case 115:	return K_HOME;
	case 119:	return K_END;

	case 122:	return K_F1;
	case 120:	return K_F2;
	case 99:	return K_F3;
	case 118:	return K_F4;
	case 96:	return K_F5;
	case 97:	return K_F6;
	case 98:	return K_F7;
	case 100:	return K_F8;
	case 101:	return K_F9;
	case 109:	return K_F10;
	case 103:	return K_F11;
	case 111:	return K_F12;

	case 56: case 60:	return K_SHIFT;
	case 59: case 62:	return K_CTRL;
	case 58: case 61:	return K_ALT;
	case 55: case 54:	return 0;	// command is reserved for the menus
	case 57:		return 0;	// caps lock

	case 49:	return K_SPACE;
	}

	if (ch >= 'A' && ch <= 'Z')
		return ch - 'A' + 'a';

	if (ch > 0 && ch < 256)
		return ch;

	return 0;
}

static void IN_DeactivateMouse (void)
{
	if (!mouse_active)
		return;

	Cocoa_GrabMouse (0);
	mouse_active = false;
}

static void IN_ActivateMouse (void)
{
	if (!mouse_avail || mouse_active)
		return;

	mx = my = 0;			// don't spazz
	Cocoa_GrabMouse (1);
	mouse_active = true;
}

void VID_HandlePause (qboolean pause)
{
}

// NSOpenGL paces buffer swaps; the software renderer's cadence hooks do not apply.
float VID_RefreshInterval (void)
{
	return 0;
}

unsigned long long VID_VsyncSerial (void)
{
	return 0;
}

/*
===============
HandleEvents
===============
*/
static void HandleEvents (void)
{
	cocoaevent_t	ev;
	int		key;

	if (!vid_initialized)
		return;

	Cocoa_PumpEvents ();

	while (Cocoa_GetEvent (&ev))
	{
		switch (ev.type)
		{
		case COCOA_EV_KEY:
			key = MacKeyToQuake (ev.keycode, ev.ch);
			if (key)
				Key_Event (key, ev.down ? true : false);
			break;

		case COCOA_EV_MOUSEBTN:
			if (ev.keycode >= 0 && ev.keycode <= 2)
				Key_Event (K_MOUSE1 + ev.keycode, ev.down ? true : false);
			break;

		case COCOA_EV_MOUSEMOVE:
			if (mouse_active)
			{
				mx += ev.dx;
				my += ev.dy;
			}
			break;

		case COCOA_EV_WHEEL:
			key = (ev.dy > 0) ? K_MWHEELUP : K_MWHEELDOWN;
			Key_Event (key, true);
			Key_Event (key, false);
			break;

		case COCOA_EV_QUIT:
			Sys_Quit ();
			break;
		}
	}
}

void VID_Shutdown (void)
{
	if (!vid_initialized)
		return;

	IN_DeactivateMouse ();
	Cocoa_DestroyWindow ();

	vid_initialized = false;
}

void signal_handler (int sig)
{
	printf ("Received signal %d, exiting...\n", sig);
	Sys_Quit ();
	exit (0);
}

void InitSig (void)
{
	signal (SIGHUP, signal_handler);
	signal (SIGINT, signal_handler);
	signal (SIGQUIT, signal_handler);
	signal (SIGILL, signal_handler);
	signal (SIGTRAP, signal_handler);
	signal (SIGIOT, signal_handler);
	signal (SIGBUS, signal_handler);
	signal (SIGFPE, signal_handler);
	signal (SIGSEGV, signal_handler);
	signal (SIGTERM, signal_handler);
}

void VID_ShiftPalette (unsigned char *p)
{
//	VID_SetPalette(p);
}

void VID_SetPalette (unsigned char *palette)
{
	byte	*pal;
	unsigned r,g,b;
	unsigned v;
	int	r1,g1,b1;
	int	k;
	unsigned short i;
	unsigned	*table;
	int	dist, bestdist;

//
// 8 8 8 encoding
//
	pal = palette;
	table = d_8to24table;
	for (i=0 ; i<256 ; i++)
	{
		r = pal[0];
		g = pal[1];
		b = pal[2];
		pal += 3;

		v = (255<<24) + (r<<0) + (g<<8) + (b<<16);
		*table++ = v;
	}
	d_8to24table[255] &= 0xffffff;	// 255 is transparent

	for (i=0; i < (1<<15); i++) {
		/* Maps
		000000000000000
		000000000011111 = Red  = 0x1F
		000001111100000 = Blue = 0x03E0
		111110000000000 = Grn  = 0x7C00
		*/
		r = ((i & 0x1F) << 3)+4;
		g = ((i & 0x03E0) >> 2)+4;
		b = ((i & 0x7C00) >> 7)+4;
		pal = (unsigned char *)d_8to24table;
		for (v=0,k=0,bestdist=10000*10000; v<256; v++,pal+=4) {
			r1 = (int)r - (int)pal[0];
			g1 = (int)g - (int)pal[1];
			b1 = (int)b - (int)pal[2];
			dist = (r1*r1)+(g1*g1)+(b1*b1);
			if (dist < bestdist) {
				k=v;
				bestdist = dist;
			}
		}
		d_15to8table[i]=k;
	}
}

/*
===============
CheckMultiTextureExtensions

The ARB entry points are exported straight out of OpenGL.framework, so unlike
the Linux driver there is no dlsym dance to do here.
===============
*/
void CheckMultiTextureExtensions (void)
{
	if (COM_CheckParm("-nomtex"))
		return;

	if (!gl_extensions || !strstr(gl_extensions, "GL_ARB_multitexture"))
	{
		Con_Printf ("GL_ARB_multitexture not found, disabled.\n");
		return;
	}

	qglMTexCoord2f = glMultiTexCoord2fARB;
	qglSelectTexture = glActiveTextureARB;
	qglMTex0 = GL_TEXTURE0_ARB;
	qglMTex1 = GL_TEXTURE1_ARB;
	gl_mtexable = true;

	Con_Printf ("Multitexture extensions found.\n");
}

/*
===============
GL_Init
===============
*/
void GL_Init (void)
{
	gl_vendor = (const char *)glGetString (GL_VENDOR);
	Con_Printf ("GL_VENDOR: %s\n", gl_vendor);
	gl_renderer = (const char *)glGetString (GL_RENDERER);
	Con_Printf ("GL_RENDERER: %s\n", gl_renderer);

	gl_version = (const char *)glGetString (GL_VERSION);
	Con_Printf ("GL_VERSION: %s\n", gl_version);
	gl_extensions = (const char *)glGetString (GL_EXTENSIONS);

	CheckMultiTextureExtensions ();

	glClearColor (1,0,0,0);
	glCullFace(GL_FRONT);
	glEnable(GL_TEXTURE_2D);

	glEnable(GL_ALPHA_TEST);
	glAlphaFunc(GL_GREATER, 0.666);

	glPolygonMode (GL_FRONT_AND_BACK, GL_FILL);
	glShadeModel (GL_FLAT);

	glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
	glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
	glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
	glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);

	glBlendFunc (GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);

	glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE);
}

/*
=================
GL_BeginRendering
=================
*/
void GL_BeginRendering (int *x, int *y, int *width, int *height)
{
	*x = *y = 0;
	*width = scr_width;
	*height = scr_height;
}

void GL_EndRendering (void)
{
	glFlush ();
	Cocoa_SwapBuffers ();
}

qboolean VID_Is8bit (void)
{
	return is8bit;
}

static void Check_Gamma (unsigned char *pal)
{
	float	f, inf;
	unsigned char	palette[768];
	int	i;

	if ((i = COM_CheckParm("-gamma")) == 0)
		vid_gamma = 0.7;
	else
		vid_gamma = Q_atof(com_argv[i+1]);

	for (i=0 ; i<768 ; i++)
	{
		f = pow ( (pal[i]+1)/256.0 , vid_gamma );
		inf = f*255 + 0.5;
		if (inf < 0)
			inf = 0;
		if (inf > 255)
			inf = 255;
		palette[i] = inf;
	}

	memcpy (pal, palette, sizeof(palette));
}

void VID_Init (unsigned char *palette)
{
	int	i;
	char	gldir[MAX_OSPATH];
	int	width = 640, height = 480;
	qboolean fullscreen = false;
	qboolean hidpi = false;

	Cvar_RegisterVariable (&vid_mode);
	Cvar_RegisterVariable (&in_mouse);
	Cvar_RegisterVariable (&m_filter);
	Cvar_RegisterVariable (&gl_ztrick);

	vid.maxwarpwidth = WARP_WIDTH;
	vid.maxwarpheight = WARP_HEIGHT;
	vid.colormap = host_colormap;
	vid.fullbright = 256 - LittleLong (*((int *)vid.colormap + 2048));

// interpret command-line params

	// Unlike the X11 driver we default to windowed: a borderless fullscreen
	// window on top of the menu bar is a nuisance to escape from if
	// something goes wrong.
	if (COM_CheckParm("-fullscreen") || COM_CheckParm("-fs"))
		fullscreen = true;
	if (COM_CheckParm("-window"))
		fullscreen = false;

	// Off by default: at native retina resolution the 1996 art is very
	// small, and the upscaled 640x480 surface is closer to how this looked.
	if (COM_CheckParm("-hidpi"))
		hidpi = true;

	if ((i = COM_CheckParm("-width")) != 0)
		width = atoi(com_argv[i+1]);

	if ((i = COM_CheckParm("-height")) != 0)
		height = atoi(com_argv[i+1]);

	if ((i = COM_CheckParm("-conwidth")) != 0)
		vid.conwidth = Q_atoi(com_argv[i+1]);
	else
		vid.conwidth = 640;

	vid.conwidth &= 0xfff8; // make it a multiple of eight

	if (vid.conwidth < 320)
		vid.conwidth = 320;

	// pick a conheight that matches with correct aspect
	vid.conheight = vid.conwidth*3 / 4;

	if ((i = COM_CheckParm("-conheight")) != 0)
		vid.conheight = Q_atoi(com_argv[i+1]);
	if (vid.conheight < 200)
		vid.conheight = 200;

	if (Cocoa_CreateWindow ("Quake", width, height, fullscreen, hidpi))
		Sys_Error ("VID_Init: could not create a Cocoa OpenGL window");

	vid_initialized = true;

	Cocoa_GetDrawableSize (&scr_width, &scr_height);

	if (vid.conheight > scr_height)
		vid.conheight = scr_height;
	if (vid.conwidth > scr_width)
		vid.conwidth = scr_width;
	vid.width = vid.conwidth;
	vid.height = vid.conheight;

	vid.aspect = ((float)vid.height / (float)vid.width) * (320.0 / 240.0);
	vid.numpages = 2;

	InitSig(); // trap evil signals

	GL_Init();

	snprintf (gldir, sizeof(gldir), "%s/glquake", com_gamedir);
	Sys_mkdir (gldir);

	Check_Gamma (palette);
	VID_SetPalette (palette);

	Con_SafePrintf ("Video mode %dx%d initialized.\n", scr_width, scr_height);

	vid.recalc_refdef = 1;				// force a surface cache flush
}

void Sys_SendKeyEvents (void)
{
	HandleEvents ();
}

void Force_CenterView_f (void)
{
	cl.viewangles[PITCH] = 0;
}

void IN_Init (void)
{
	mouse_avail = !COM_CheckParm("-nomouse");

	Cmd_AddCommand ("force_centerview", Force_CenterView_f);
}

void IN_Shutdown (void)
{
	IN_DeactivateMouse ();
	mouse_avail = false;
}

/*
===========
IN_Commands
===========
*/
void IN_Commands (void)
{
	if (!vid_initialized)
		return;

	if (key_dest == key_game && in_mouse.value)
		IN_ActivateMouse ();
	else
		IN_DeactivateMouse ();
}

/*
===========
IN_MouseMove
===========
*/
void IN_MouseMove (usercmd_t *cmd)
{
	if (!mouse_avail)
		return;

	if (m_filter.value)
	{
		mx = (mx + old_mouse_x) * 0.5;
		my = (my + old_mouse_y) * 0.5;
	}
	old_mouse_x = mx;
	old_mouse_y = my;

	mx *= sensitivity.value;
	my *= sensitivity.value;

// add mouse X/Y movement to cmd
	if ( (in_strafe.state & 1) || (lookstrafe.value && (in_mlook.state & 1) ))
		cmd->sidemove += m_side.value * mx;
	else
		cl.viewangles[YAW] -= m_yaw.value * mx;

	if (in_mlook.state & 1)
		V_StopPitchDrift ();

	if ( (in_mlook.state & 1) && !(in_strafe.state & 1))
	{
		cl.viewangles[PITCH] += m_pitch.value * my;
		if (cl.viewangles[PITCH] > 80)
			cl.viewangles[PITCH] = 80;
		if (cl.viewangles[PITCH] < -70)
			cl.viewangles[PITCH] = -70;
	}
	else
	{
		if ((in_strafe.state & 1) && noclip_anglehack)
			cmd->upmove -= m_forward.value * my;
		else
			cmd->forwardmove -= m_forward.value * my;
	}
	mx = my = 0;
}

void IN_Move (usercmd_t *cmd)
{
	IN_MouseMove (cmd);
}
