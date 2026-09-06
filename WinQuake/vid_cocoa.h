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
// vid_cocoa.h -- plain C interface to the Cocoa/NSOpenGL window layer.
//
// The Objective-C side (vid_cocoa.m) must not include quakedef.h: Cocoa drags
// in <stdbool.h>, whose true/false macros collide with Quake's
// "typedef enum {false, true} qboolean".  So the Cocoa layer only speaks in
// terms of this header, and gl_vidcocoa.c does all the Quake-side work.

#ifndef VID_COCOA_H
#define VID_COCOA_H

// event types handed back by Cocoa_GetEvent
#define COCOA_EV_KEY		1	// keycode/ch/down are valid
#define COCOA_EV_MOUSEBTN	2	// keycode is the button index, down is valid
#define COCOA_EV_MOUSEMOVE	3	// dx/dy are valid
#define COCOA_EV_WHEEL		4	// dy > 0 is a scroll up
#define COCOA_EV_QUIT		5	// window closed or quit selected

typedef struct
{
	int		type;
	int		down;
	int		keycode;	// mac virtual keycode, or mouse button index
	int		ch;		// unshifted unicode char for the key, 0 if none
	int		dx, dy;
} cocoaevent_t;

// Brings up NSApplication.  Safe to call more than once.  Returns 0 on success.
int		Cocoa_Init (void);

// Creates the window and its GL context, and makes the context current.
// Returns 0 on success.
// hidpi selects a backing store at the display's native resolution; without
// it the GL surface is exactly width x height and the display scales it.
int		Cocoa_CreateWindow (const char *title, int width, int height,
					int fullscreen, int hidpi);
void	Cocoa_DestroyWindow (void);

// Backing size of the GL drawable, which is what the viewport wants.
void	Cocoa_GetDrawableSize (int *width, int *height);

void	Cocoa_SwapBuffers (void);

// Drains the NSApplication event queue into our own ring buffer.
void	Cocoa_PumpEvents (void);

// Pops one event.  Returns 0 when the queue is empty.
int		Cocoa_GetEvent (cocoaevent_t *ev);

// Hides the cursor and switches the mouse to deltas-only mode.
void	Cocoa_GrabMouse (int grab);

#endif	// VID_COCOA_H
