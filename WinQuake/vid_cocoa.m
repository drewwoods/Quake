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
// vid_cocoa.m -- Cocoa window + NSOpenGL context for glquake.
//
// Quake owns the main loop, so instead of running -[NSApplication run] we
// finish launching by hand and drain the event queue once a frame from
// Cocoa_PumpEvents().  Events we care about are translated into cocoaevent_t
// and buffered for the Quake side to pick up; everything else goes back to
// NSApp so window dragging, menus and Cmd-key equivalents still work.
//
// Nothing here may include quakedef.h -- see vid_cocoa.h for why.

#import <Cocoa/Cocoa.h>
#import <OpenGL/OpenGL.h>
#import <ApplicationServices/ApplicationServices.h>

#include "vid_cocoa.h"

#define MAX_COCOA_EVENTS	256

static cocoaevent_t	eventq[MAX_COCOA_EVENTS];
static int		eventq_head;	// next slot to write
static int		eventq_tail;	// next slot to read

static NSWindow		*window;
static NSOpenGLView	*glview;
static id		appdelegate;

static int		mouse_grabbed;		// physical state
static int		mouse_grab_wanted;	// what the game asked for
static int		windowed_width, windowed_height;
static int		hidpi_surface;

/*
===============
QueueEvent

Drops the event if the ring is full; a lost key beats blocking the game.
===============
*/
static void QueueEvent (const cocoaevent_t *ev)
{
	int		next;

	next = (eventq_head + 1) % MAX_COCOA_EVENTS;
	if (next == eventq_tail)
		return;

	eventq[eventq_head] = *ev;
	eventq_head = next;
}

static void QueueSimpleEvent (int type)
{
	cocoaevent_t	ev;

	memset (&ev, 0, sizeof(ev));
	ev.type = type;
	QueueEvent (&ev);
}

int Cocoa_GetEvent (cocoaevent_t *ev)
{
	if (eventq_tail == eventq_head)
		return 0;

	*ev = eventq[eventq_tail];
	eventq_tail = (eventq_tail + 1) % MAX_COCOA_EVENTS;
	return 1;
}

/*
=============================================================================

						APPLICATION / WINDOW DELEGATE

=============================================================================
*/

@interface QuakeAppDelegate : NSObject <NSApplicationDelegate, NSWindowDelegate>
- (void)requestQuit:(id)sender;
@end

@implementation QuakeAppDelegate

- (void)requestQuit:(id)sender
{
	QueueSimpleEvent (COCOA_EV_QUIT);
}

- (BOOL)windowShouldClose:(id)sender
{
	QueueSimpleEvent (COCOA_EV_QUIT);
	return NO;		// let Quake shut itself down in an orderly way
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender
{
	QueueSimpleEvent (COCOA_EV_QUIT);
	return NSTerminateCancel;
}

@end

/*
===============
CreateMenuBar

A bare-bones menu so the app behaves like a normal one (and Cmd-Q works)
even though we are not running from a .app bundle.
===============
*/
static void CreateMenuBar (void)
{
	NSMenu		*menubar, *appmenu;
	NSMenuItem	*appitem, *quititem;

	menubar = [[NSMenu alloc] init];
	appitem = [[NSMenuItem alloc] init];
	[menubar addItem:appitem];
	[NSApp setMainMenu:menubar];

	appmenu = [[NSMenu alloc] init];
	quititem = [[NSMenuItem alloc] initWithTitle:@"Quit Quake"
					      action:@selector(requestQuit:)
				       keyEquivalent:@"q"];
	[quititem setTarget:appdelegate];
	[appmenu addItem:quititem];
	[appitem setSubmenu:appmenu];
}

int Cocoa_Init (void)
{
	static int	initialized;

	if (initialized)
		return 0;

	@autoreleasepool {
		[NSApplication sharedApplication];
		[NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];

		appdelegate = [[QuakeAppDelegate alloc] init];
		[NSApp setDelegate:appdelegate];

		CreateMenuBar ();

		[NSApp finishLaunching];
		[NSApp activateIgnoringOtherApps:YES];
	}

	initialized = 1;
	return 0;
}

int Cocoa_CreateWindow (const char *title, int width, int height, int fullscreen,
			int hidpi)
{
	NSOpenGLPixelFormatAttribute	attrs[] = {
		NSOpenGLPFADoubleBuffer,
		NSOpenGLPFAAccelerated,
		NSOpenGLPFAColorSize, 24,
		NSOpenGLPFAAlphaSize, 8,
		NSOpenGLPFADepthSize, 24,
		0
	};

	if (Cocoa_Init ())
		return -1;

	@autoreleasepool {
		NSOpenGLPixelFormat	*fmt;
		NSRect			frame;
		NSUInteger		style;
		GLint			swap = 1;

		fmt = [[NSOpenGLPixelFormat alloc] initWithAttributes:attrs];
		if (!fmt)
		{
			fprintf (stderr, "Cocoa: no suitable OpenGL pixel format\n");
			return -1;
		}

		if (fullscreen)
		{
			frame = [[NSScreen mainScreen] frame];
			style = NSWindowStyleMaskBorderless;
		}
		else
		{
			frame = NSMakeRect (0, 0, width, height);
			style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
				NSWindowStyleMaskMiniaturizable;
		}

		window = [[NSWindow alloc] initWithContentRect:frame
						    styleMask:style
						      backing:NSBackingStoreBuffered
							defer:NO];
		if (!window)
		{
			fprintf (stderr, "Cocoa: failed to create window\n");
			return -1;
		}

		[window setTitle:[NSString stringWithUTF8String:title]];
		[window setDelegate:appdelegate];
		[window setAcceptsMouseMovedEvents:YES];
		[window setReleasedWhenClosed:NO];

		glview = [[NSOpenGLView alloc] initWithFrame:frame pixelFormat:fmt];
		if (!glview)
		{
			fprintf (stderr, "Cocoa: failed to create GL view\n");
			return -1;
		}

		// Point resolution by default, so -width/-height mean what they
		// say and the display scales the result up.
		hidpi_surface = hidpi;
		[glview setWantsBestResolutionOpenGLSurface:hidpi ? YES : NO];

		[window setContentView:glview];
		[window makeFirstResponder:glview];

		if (fullscreen)
		{
			[window setLevel:NSMainMenuWindowLevel + 1];
			[NSApp setPresentationOptions:
				NSApplicationPresentationHideDock |
				NSApplicationPresentationHideMenuBar];
		}
		else
			[window center];

		[window makeKeyAndOrderFront:nil];
		[NSApp activateIgnoringOtherApps:YES];

		[[glview openGLContext] makeCurrentContext];
		[[glview openGLContext] setValues:&swap
				     forParameter:NSOpenGLContextParameterSwapInterval];
	}

	windowed_width = (int)[glview bounds].size.width;
	windowed_height = (int)[glview bounds].size.height;

	return 0;
}

void Cocoa_DestroyWindow (void)
{
	if (!window)
		return;

	Cocoa_GrabMouse (0);

	@autoreleasepool {
		[NSOpenGLContext clearCurrentContext];
		[NSApp setPresentationOptions:NSApplicationPresentationDefault];
		[window orderOut:nil];
		[window setDelegate:nil];
		window = nil;
		glview = nil;
	}
}

void Cocoa_GetDrawableSize (int *width, int *height)
{
	if (!glview)
	{
		*width = windowed_width;
		*height = windowed_height;
		return;
	}

	@autoreleasepool {
		NSRect	rect = [glview bounds];

		// Only a hidpi surface is backed at the display's scale; without
		// it the GL drawable stays the size of the view in points, and
		// reporting backing pixels would leave the viewport oversized.
		if (hidpi_surface)
			rect = [glview convertRectToBacking:rect];

		*width = (int)rect.size.width;
		*height = (int)rect.size.height;
	}
}

void Cocoa_SwapBuffers (void)
{
	if (!glview)
		return;

	[[glview openGLContext] flushBuffer];
}

/*
=============================================================================

								MOUSE

=============================================================================
*/

/*
===============
WarpMouseToWindowCenter

CGWarpMouseCursorPosition works in screen coordinates with the origin at the
top left, so the window frame has to be flipped.
===============
*/
static void WarpMouseToWindowCenter (void)
{
	NSRect		frame, screen;
	CGPoint		center;

	if (!window)
		return;

	frame = [window frame];
	screen = [[NSScreen screens][0] frame];

	center.x = frame.origin.x + frame.size.width * 0.5;
	center.y = screen.size.height -
			(frame.origin.y + frame.size.height * 0.5);

	CGWarpMouseCursorPosition (center);
}

static void SetMouseGrab (int grab)
{
	if (grab == mouse_grabbed)
		return;

	if (grab)
	{
		WarpMouseToWindowCenter ();
		CGAssociateMouseAndMouseCursorPosition (false);
		CGDisplayHideCursor (kCGDirectMainDisplay);
	}
	else
	{
		CGAssociateMouseAndMouseCursorPosition (true);
		CGDisplayShowCursor (kCGDirectMainDisplay);
		WarpMouseToWindowCenter ();
	}

	mouse_grabbed = grab;
}

void Cocoa_GrabMouse (int grab)
{
	mouse_grab_wanted = grab;

	// Never hold the cursor while another app is in front.
	if (grab && !(window && [window isKeyWindow]))
		grab = 0;

	SetMouseGrab (grab);
}

/*
=============================================================================

								EVENTS

=============================================================================
*/

static void QueueKeyEvent (NSEvent *event, int down)
{
	cocoaevent_t	ev;
	NSString	*chars;

	memset (&ev, 0, sizeof(ev));
	ev.type = COCOA_EV_KEY;
	ev.down = down;
	ev.keycode = [event keyCode];

	chars = [event charactersIgnoringModifiers];
	if ([chars length] > 0)
		ev.ch = [chars characterAtIndex:0];

	QueueEvent (&ev);
}

static void QueueModifierEvent (NSEvent *event)
{
	cocoaevent_t		ev;
	NSEventModifierFlags	mask;

	switch ([event keyCode])
	{
	case 56: case 60:	mask = NSEventModifierFlagShift; break;		// shift
	case 59: case 62:	mask = NSEventModifierFlagControl; break;	// control
	case 58: case 61:	mask = NSEventModifierFlagOption; break;	// option
	case 55: case 54:	mask = NSEventModifierFlagCommand; break;	// command
	default:		return;
	}

	memset (&ev, 0, sizeof(ev));
	ev.type = COCOA_EV_KEY;
	ev.down = ([event modifierFlags] & mask) != 0;
	ev.keycode = [event keyCode];
	QueueEvent (&ev);
}

static void QueueMouseButtonEvent (NSEvent *event, int button, int down)
{
	cocoaevent_t	ev;

	memset (&ev, 0, sizeof(ev));
	ev.type = COCOA_EV_MOUSEBTN;
	ev.down = down;
	ev.keycode = button;
	QueueEvent (&ev);
}

static void QueueMouseMoveEvent (NSEvent *event)
{
	cocoaevent_t	ev;

	if (!mouse_grabbed)
		return;

	memset (&ev, 0, sizeof(ev));
	ev.type = COCOA_EV_MOUSEMOVE;
	ev.dx = (int)[event deltaX];
	ev.dy = (int)[event deltaY];

	if (ev.dx || ev.dy)
		QueueEvent (&ev);
}

static void QueueWheelEvent (NSEvent *event)
{
	cocoaevent_t	ev;
	CGFloat		delta = [event scrollingDeltaY];

	if (delta == 0)
		return;

	memset (&ev, 0, sizeof(ev));
	ev.type = COCOA_EV_WHEEL;
	ev.dy = (delta > 0) ? 1 : -1;
	QueueEvent (&ev);
}

void Cocoa_PumpEvents (void)
{
	@autoreleasepool {
		NSEvent		*event;

		while ((event = [NSApp nextEventMatchingMask:NSEventMaskAny
						   untilDate:[NSDate distantPast]
						      inMode:NSDefaultRunLoopMode
						     dequeue:YES]))
		{
			// Cmd-anything belongs to the menus, not to the game.
			if (([event modifierFlags] & NSEventModifierFlagCommand) &&
				([event type] == NSEventTypeKeyDown ||
				 [event type] == NSEventTypeKeyUp))
			{
				[NSApp sendEvent:event];
				continue;
			}

			switch ([event type])
			{
			case NSEventTypeKeyDown:
				QueueKeyEvent (event, 1);
				continue;	// swallow: nothing else wants it

			case NSEventTypeKeyUp:
				QueueKeyEvent (event, 0);
				continue;

			case NSEventTypeFlagsChanged:
				QueueModifierEvent (event);
				break;

			case NSEventTypeLeftMouseDown:
				QueueMouseButtonEvent (event, 0, 1);
				break;
			case NSEventTypeLeftMouseUp:
				QueueMouseButtonEvent (event, 0, 0);
				break;
			case NSEventTypeRightMouseDown:
				QueueMouseButtonEvent (event, 1, 1);
				break;
			case NSEventTypeRightMouseUp:
				QueueMouseButtonEvent (event, 1, 0);
				break;
			case NSEventTypeOtherMouseDown:
				QueueMouseButtonEvent (event, (int)[event buttonNumber], 1);
				break;
			case NSEventTypeOtherMouseUp:
				QueueMouseButtonEvent (event, (int)[event buttonNumber], 0);
				break;

			case NSEventTypeMouseMoved:
			case NSEventTypeLeftMouseDragged:
			case NSEventTypeRightMouseDragged:
			case NSEventTypeOtherMouseDragged:
				QueueMouseMoveEvent (event);
				break;

			case NSEventTypeScrollWheel:
				QueueWheelEvent (event);
				break;

			default:
				break;
			}

			[NSApp sendEvent:event];
		}

		// Drop the cursor grab whenever we lose focus, and take it back
		// when we get it again.
		Cocoa_GrabMouse (mouse_grab_wanted);
	}
}
