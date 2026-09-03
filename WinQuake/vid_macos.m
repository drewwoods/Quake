/*
 * vid_macos.m -- Cocoa video and input for the original software renderer.
 */

#import <Cocoa/Cocoa.h>
#import <CoreGraphics/CoreGraphics.h>

#include "quakedef.h"
#include "d_local.h"

#define BASEWIDTH  320
#define BASEHEIGHT 200

viddef_t vid;
unsigned short d_8to16table[256];
unsigned d_8to24table[256];

void (*vid_menudrawfn)(void);
void (*vid_menukeyfn)(int key);

static NSWindow *quakeWindow;
static NSView *quakeView;
static byte *frameBuffer;
static byte *rgbaBuffer;
static byte currentPalette[768];
static void *renderMemory;
static int renderWidth;
static int renderHeight;
static float mouseX;
static float mouseY;
static float oldMouseX;
static float oldMouseY;
static qboolean headlessMode;
static qboolean mouseCaptured;
static qboolean mouseCaptureAllowed;
static qboolean suppressMouseDeltas;
static CGFloat wheelAccum;

cvar_t _windowed_mouse = {"_windowed_mouse", "1", true};
cvar_t m_filter = {"m_filter", "0", true};

@interface QuakeView : NSView
@end

@interface QuakeWindowDelegate : NSObject <NSWindowDelegate>
@end

static qboolean CenterMouseInWindow(void)
{
    NSRect contentFrame;
    NSRect screenFrame;
    NSPoint center;
    NSScreen *screen;
    NSNumber *screenNumber;
    CGDirectDisplayID display;
    CGPoint displayPoint;

    screen = [quakeWindow screen];
    screenNumber = [[screen deviceDescription] objectForKey:@"NSScreenNumber"];
    if (!screen || !screenNumber)
        return false;

    contentFrame = [quakeWindow contentRectForFrameRect:[quakeWindow frame]];
    screenFrame = [screen frame];
    center = NSMakePoint(NSMidX(contentFrame), NSMidY(contentFrame));
    display = (CGDirectDisplayID)[screenNumber unsignedIntValue];
    displayPoint = CGPointMake(center.x - NSMinX(screenFrame),
        NSMaxY(screenFrame) - center.y);

    return CGDisplayMoveCursorToPoint(display, displayPoint) == kCGErrorSuccess;
}

static void SetMouseCapture(qboolean capture)
{
    if (headlessMode)
        capture = false;
    if (capture == mouseCaptured)
        return;

    if (capture)
    {
        if (CGAssociateMouseAndMouseCursorPosition(false) != kCGErrorSuccess)
            return;
        if (!CenterMouseInWindow())
        {
            CGAssociateMouseAndMouseCursorPosition(true);
            return;
        }
        [NSCursor hide];
        mouseCaptured = true;
        suppressMouseDeltas = true;
    }
    else
    {
        CGAssociateMouseAndMouseCursorPosition(true);
        [NSCursor unhide];
        mouseCaptured = false;
        suppressMouseDeltas = false;
    }

    mouseX = mouseY = 0;
    oldMouseX = oldMouseY = 0;
}

static void UpdateMouseCapture(void)
{
    SetMouseCapture(mouseCaptureAllowed && _windowed_mouse.value &&
        !headlessMode && quakeWindow && [quakeWindow isKeyWindow] &&
        [NSApp isActive]);
}

static int QuakeKeyForEvent(NSEvent *event)
{
    switch ([event keyCode])
    {
        case 53: return K_ESCAPE;
        case 48: return K_TAB;
        case 36: case 76: return K_ENTER;
        case 51: return K_BACKSPACE;
        case 117: return K_DEL;
        case 123: return K_LEFTARROW;
        case 124: return K_RIGHTARROW;
        case 125: return K_DOWNARROW;
        case 126: return K_UPARROW;
        case 115: return K_HOME;
        case 119: return K_END;
        case 116: return K_PGUP;
        case 121: return K_PGDN;
        case 122: return K_F1;
        case 120: return K_F2;
        case 99:  return K_F3;
        case 118: return K_F4;
        case 96:  return K_F5;
        case 97:  return K_F6;
        case 98:  return K_F7;
        case 100: return K_F8;
        case 101: return K_F9;
        case 109: return K_F10;
        case 103: return K_F11;
        case 111: return K_F12;
    }

    NSString *characters = [[event charactersIgnoringModifiers] lowercaseString];
    if ([characters length] == 0)
        return 0;
    unichar key = [characters characterAtIndex:0];
    if (key >= 32 && key <= 126)
        return (int)key;
    return 0;
}

@implementation QuakeView

- (BOOL)acceptsFirstResponder
{
    return YES;
}

- (BOOL)isFlipped
{
    return YES;
}

- (void)drawRect:(NSRect)dirtyRect
{
    CGContextRef context;
    CGColorSpaceRef colorSpace;
    CGDataProviderRef provider;
    CGImageRef image;

    (void)dirtyRect;
    if (!rgbaBuffer)
        return;

    colorSpace = CGColorSpaceCreateDeviceRGB();
    provider = CGDataProviderCreateWithData(NULL, rgbaBuffer,
        (size_t)renderWidth * renderHeight * 4, NULL);
    image = CGImageCreate(renderWidth, renderHeight, 8, 32,
        (size_t)renderWidth * 4, colorSpace,
        kCGBitmapByteOrderDefault | kCGImageAlphaNoneSkipLast,
        provider, NULL, false, kCGRenderingIntentDefault);

    context = [[NSGraphicsContext currentContext] CGContext];
    CGContextSetInterpolationQuality(context, kCGInterpolationNone);
    CGContextSaveGState(context);
    CGContextTranslateCTM(context, 0, NSHeight([self bounds]));
    CGContextScaleCTM(context, 1, -1);
    CGContextDrawImage(context, NSRectToCGRect([self bounds]), image);
    CGContextRestoreGState(context);

    CGImageRelease(image);
    CGDataProviderRelease(provider);
    CGColorSpaceRelease(colorSpace);
}

- (void)keyDown:(NSEvent *)event
{
    int key = QuakeKeyForEvent(event);
    if (key)
        Key_Event(key, true);
}

- (void)keyUp:(NSEvent *)event
{
    int key = QuakeKeyForEvent(event);
    if (key)
        Key_Event(key, false);
}

- (void)flagsChanged:(NSEvent *)event
{
    int key = 0;
    NSEventModifierFlags mask = 0;

    switch ([event keyCode])
    {
        case 56: case 60: key = K_SHIFT; mask = NSEventModifierFlagShift; break;
        case 59: case 62: key = K_CTRL;  mask = NSEventModifierFlagControl; break;
        case 58: case 61: key = K_ALT;   mask = NSEventModifierFlagOption; break;
    }
    if (key)
        Key_Event(key, ([event modifierFlags] & mask) != 0);
}

- (void)mouseDown:(NSEvent *)event
{
    (void)event;
    Key_Event(K_MOUSE1, true);
}

- (void)mouseUp:(NSEvent *)event
{
    (void)event;
    Key_Event(K_MOUSE1, false);
}

- (void)rightMouseDown:(NSEvent *)event
{
    (void)event;
    Key_Event(K_MOUSE2, true);
}

- (void)rightMouseUp:(NSEvent *)event
{
    (void)event;
    Key_Event(K_MOUSE2, false);
}

- (void)otherMouseDown:(NSEvent *)event
{
    (void)event;
    Key_Event(K_MOUSE3, true);
}

- (void)otherMouseUp:(NSEvent *)event
{
    (void)event;
    Key_Event(K_MOUSE3, false);
}

- (void)mouseMoved:(NSEvent *)event
{
    if (!mouseCaptured || suppressMouseDeltas)
        return;
    mouseX += [event deltaX];
    mouseY += [event deltaY];
}

- (void)mouseDragged:(NSEvent *)event      { [self mouseMoved:event]; }
- (void)rightMouseDragged:(NSEvent *)event { [self mouseMoved:event]; }
- (void)otherMouseDragged:(NSEvent *)event { [self mouseMoved:event]; }

- (void)scrollWheel:(NSEvent *)event
{
    CGFloat delta = [event deltaY];
    int key;

    if (delta == 0)
        return;
    if ((wheelAccum < 0 && delta > 0) || (wheelAccum > 0 && delta < 0))
        wheelAccum = 0;
    wheelAccum += delta;
    while (wheelAccum >= 1.0)
    {
        key = K_MWHEELUP;
        Key_Event(key, true);
        Key_Event(key, false);
        wheelAccum -= 1.0;
    }
    while (wheelAccum <= -1.0)
    {
        key = K_MWHEELDOWN;
        Key_Event(key, true);
        Key_Event(key, false);
        wheelAccum += 1.0;
    }
}

@end

@implementation QuakeWindowDelegate
- (void)windowDidBecomeKey:(NSNotification *)notification
{
    (void)notification;
    UpdateMouseCapture();
}

- (void)windowDidResignKey:(NSNotification *)notification
{
    (void)notification;
    SetMouseCapture(false);
    Key_ClearStates();
}

- (BOOL)windowShouldClose:(NSWindow *)sender
{
    (void)sender;
    Sys_Quit();
    return YES;
}
@end

static QuakeWindowDelegate *windowDelegate;

void VID_SetPalette(unsigned char *palette)
{
    int i;
    memcpy(currentPalette, palette, sizeof(currentPalette));
    for (i = 0; i < 256; ++i)
    {
        unsigned r = palette[i * 3 + 0];
        unsigned g = palette[i * 3 + 1];
        unsigned b = palette[i * 3 + 2];
        d_8to16table[i] = (unsigned short)(((r >> 3) << 11) |
            ((g >> 2) << 5) | (b >> 3));
        d_8to24table[i] = (r << 16) | (g << 8) | b;
    }
}

void VID_ShiftPalette(unsigned char *palette)
{
    VID_SetPalette(palette);
}

void VID_Init(unsigned char *palette)
{
    @autoreleasepool {
    int pnum;
    int cacheSize;
    int zSize;
    NSRect frame;
    NSWindowStyleMask style;

    headlessMode = COM_CheckParm("-headless") != 0;
    mouseCaptureAllowed = true;
    renderWidth = BASEWIDTH;
    renderHeight = BASEHEIGHT;
    if ((pnum = COM_CheckParm("-winsize")) && pnum < com_argc - 2)
    {
        renderWidth = Q_atoi(com_argv[pnum + 1]);
        renderHeight = Q_atoi(com_argv[pnum + 2]);
    }
    if ((pnum = COM_CheckParm("-width")) && pnum < com_argc - 1)
        renderWidth = Q_atoi(com_argv[pnum + 1]);
    if ((pnum = COM_CheckParm("-height")) && pnum < com_argc - 1)
        renderHeight = Q_atoi(com_argv[pnum + 1]);
    if (renderWidth < 320 || renderHeight < 200)
        Sys_Error("VID: minimum window size is 320x200");
    if (renderWidth > MAXWIDTH || renderHeight > MAXHEIGHT)
        Sys_Error("VID: maximum software-renderer size is %dx%d",
            MAXWIDTH, MAXHEIGHT);

    frameBuffer = calloc((size_t)renderWidth * renderHeight, 1);
    if (!headlessMode)
        rgbaBuffer = calloc((size_t)renderWidth * renderHeight, 4);
    cacheSize = D_SurfaceCacheForRes(renderWidth, renderHeight);
    zSize = renderWidth * renderHeight * sizeof(*d_pzbuffer);
    renderMemory = malloc((size_t)zSize + cacheSize);
    if (!frameBuffer || (!headlessMode && !rgbaBuffer) || !renderMemory)
        Sys_Error("VID: unable to allocate framebuffer");

    d_pzbuffer = renderMemory;
    D_InitCaches((byte *)renderMemory + zSize, cacheSize);

    vid.width = vid.conwidth = renderWidth;
    vid.height = vid.conheight = renderHeight;
    vid.maxwarpwidth = WARP_WIDTH;
    vid.maxwarpheight = WARP_HEIGHT;
    vid.aspect = ((float)renderHeight / renderWidth) * (320.0 / 240.0);
    vid.numpages = 1;
    vid.colormap = host_colormap;
    vid.fullbright = 256 - LittleLong(*((int *)vid.colormap + 2048));
    vid.buffer = vid.conbuffer = frameBuffer;
    vid.rowbytes = vid.conrowbytes = renderWidth;
    vid.direct = NULL;
    VID_SetPalette(palette);

    if (headlessMode)
    {
        Con_Printf("VID: headless mode; Cocoa window and input disabled\n");
        return;
    }

    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [NSApp finishLaunching];

    frame = NSMakeRect(0, 0, renderWidth * 2, renderHeight * 2);
    style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable |
        NSWindowStyleMaskMiniaturizable | NSWindowStyleMaskResizable;
    quakeWindow = [[NSWindow alloc] initWithContentRect:frame
        styleMask:style backing:NSBackingStoreBuffered defer:NO];
    quakeView = [[QuakeView alloc] initWithFrame:frame];
    windowDelegate = [[QuakeWindowDelegate alloc] init];
    [quakeWindow setDelegate:windowDelegate];
    [quakeWindow setTitle:@"Quake"];
    [quakeWindow setContentAspectRatio:NSMakeSize(renderWidth, renderHeight)];
    [quakeWindow setAcceptsMouseMovedEvents:YES];
    [quakeWindow setContentView:quakeView];
    [quakeWindow makeFirstResponder:quakeView];
    [quakeWindow center];
    [quakeWindow makeKeyAndOrderFront:nil];
    [NSApp activateIgnoringOtherApps:YES];
    UpdateMouseCapture();
    }
}

void VID_Update(vrect_t *rects)
{
    if (headlessMode)
        return;

    @autoreleasepool {
    int x, y;
    (void)rects;

    for (y = 0; y < renderHeight; ++y)
    {
        const byte *src = frameBuffer + y * renderWidth;
        byte *dst = rgbaBuffer + (size_t)y * renderWidth * 4;
        for (x = 0; x < renderWidth; ++x)
        {
            int color = src[x] * 3;
            *dst++ = currentPalette[color + 0];
            *dst++ = currentPalette[color + 1];
            *dst++ = currentPalette[color + 2];
            *dst++ = 255;
        }
    }
    [quakeView setNeedsDisplay:YES];
    [quakeView displayIfNeeded];
    }
}

/*
================
VID_RefreshInterval

Seconds between display refreshes, or 0 if unknown.  Sampled once: moving
the window to a monitor with a different refresh rate will not be noticed.
================
*/
float VID_RefreshInterval(void)
{
    static int      sampled;
    static float    interval;

    if (!sampled)
    {
        CGDisplayModeRef mode;
        double           rate = 0.0;

        sampled = 1;
        interval = 0.0f;
        if (!headlessMode)
        {
            mode = CGDisplayCopyDisplayMode(CGMainDisplayID());
            if (mode)
            {
                rate = CGDisplayModeGetRefreshRate(mode);
                CGDisplayModeRelease(mode);
            }
            // 0 is returned for variable-refresh and some external displays
            if (rate > 0.0)
                interval = (float)(1.0 / rate);
        }
    }
    return interval;
}

void VID_Shutdown(void)
{
    @autoreleasepool {
    SetMouseCapture(false);
    [quakeWindow orderOut:nil];
    quakeView = nil;
    quakeWindow = nil;
    windowDelegate = nil;
    free(frameBuffer);
    free(rgbaBuffer);
    free(renderMemory);
    frameBuffer = NULL;
    rgbaBuffer = NULL;
    renderMemory = NULL;
    d_pzbuffer = NULL;
    }
}

void VID_HandlePause(qboolean pause)
{
    mouseCaptureAllowed = !pause;
    UpdateMouseCapture();
}

void D_BeginDirectRect(int x, int y, byte *bitmap, int width, int height)
{
    (void)x; (void)y; (void)bitmap; (void)width; (void)height;
}

void D_EndDirectRect(int x, int y, int width, int height)
{
    (void)x; (void)y; (void)width; (void)height;
}

void Sys_SendKeyEvents(void)
{
    if (headlessMode)
        return;

    @autoreleasepool {
    NSEvent *event;
    do
    {
        event = [NSApp nextEventMatchingMask:NSEventMaskAny
            untilDate:[NSDate distantPast]
            inMode:NSDefaultRunLoopMode dequeue:YES];
        if (event)
            [NSApp sendEvent:event];
    } while (event);
    suppressMouseDeltas = false;
    }
}

void IN_Init(void)
{
    Cvar_RegisterVariable(&_windowed_mouse);
    Cvar_RegisterVariable(&m_filter);
}

void IN_Shutdown(void)
{
    SetMouseCapture(false);
}

void IN_Commands(void)
{
    UpdateMouseCapture();
}

void IN_Move(usercmd_t *cmd)
{
    float dx = mouseX;
    float dy = mouseY;
    mouseX = mouseY = 0;

    if (!mouseCaptured)
        return;

    if (m_filter.value)
    {
        dx = (dx + oldMouseX) * 0.5;
        dy = (dy + oldMouseY) * 0.5;
    }
    oldMouseX = dx;
    oldMouseY = dy;
    dx *= sensitivity.value;
    dy *= sensitivity.value;

    if ((in_strafe.state & 1) || (lookstrafe.value && (in_mlook.state & 1)))
        cmd->sidemove += m_side.value * dx;
    else
        cl.viewangles[YAW] -= m_yaw.value * dx;

    if (in_mlook.state & 1)
        V_StopPitchDrift();
    if ((in_mlook.state & 1) && !(in_strafe.state & 1))
    {
        cl.viewangles[PITCH] += m_pitch.value * dy;
        if (cl.viewangles[PITCH] > 80)
            cl.viewangles[PITCH] = 80;
        if (cl.viewangles[PITCH] < -70)
            cl.viewangles[PITCH] = -70;
    }
    else if ((in_strafe.state & 1) && noclip_anglehack)
        cmd->upmove -= m_forward.value * dy;
    else
        cmd->forwardmove -= m_forward.value * dy;
}
