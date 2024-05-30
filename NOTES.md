
# 13 Feb

* Looking at linux sound to try fix quake linux.  Need oss `/dev/dsp` device, but oss has been replaced by ALSA (see below).  ALSA replaced OSS, when OSS went proprietary, but subsequently OSS4 was released under opensource, but the integration has been minimal
  * OPTIONS:
    * Trying to emulate OSS wih `padsp` or `osspd`
      * `padsp` provides cap 0x5100 (`DSP_CAP_TRIGGER|DSP_CAP_MULTI|DSP_CAP_DUPLEX`)
      * `osspd` provides cap 0x5300 (`DSP_CAP_TRIGGER|DSP_CAP_MULTI|DSP_CAP_REALTIME|DSP_CAP_DUPLEX`)
        * App <—> /dev/dsp <—> CUSE <—> osspd <—> ossp-padsp <—> pulseaudio
        * Verified installation by `cat /dev/urandom > /dev/dsp`
        * followed [Bug \#1857810 “osspd no longer works: ERR: failed to connect cont...” : Bugs : osspd package : Ubuntu](https://bugs.launchpad.net/ubuntu/+source/osspd/+bug/1857810)
          * Test game, ETQW Demo 1.4:
            > [https://cdn.splashdamage.com/downloads/games/etqw/ETQW-demo2-client-full.r1.x86.run](https://cdn.splashdamage.com/downloads/games/etqw/ETQW-demo2-client-full.r1.x86.run)[https://www.splashdamage.com/games/enemy-territory-quake-wars/](https://www.splashdamage.com/games/enemy-territory-quake-wars/)
            > A) If the game fails to launch with "etqw-rthread", remove libgcc_s.so.1, libjpeg.so.62, libstdc++.so.6 from the game's directory; install libsdl1.2debian:i386, libjpeg62:i386, libstdc++6:i386
            > B) After launching and creating an account, quit the game. Edit ~/.etqwcl/base/etqwconfig.cfg:
            > seta s_driver "oss"
            > c) Relaunch the game with "etqw-rthread", test voice input in Settings and in-game.
      * neither seem to provide `DSP_CAP_MMAP` which is needed for quake

# 10 April

* Fixed GLX initialization (extension limit ed8974a08fceab21e126bbe88f36479406cd4db2)
* Fixed full screen GL (fe4e67025e7b76b2c697877b137252ea61f1c2a3)
* TODO: Restoring video mode on shutdown is not functioning (desktop is left at whatever resolution game ran at)

wip:

```diff
diff --git a/WinQuake/gl_vidlinuxglx.c b/WinQuake/gl_vidlinuxglx.c
index 3f5dd95..31b9b86 100644
--- a/WinQuake/gl_vidlinuxglx.c
+++ b/WinQuake/gl_vidlinuxglx.c
@@ -444,13 +444,24 @@ void VID_Shutdown(void)
                return;
        IN_DeactivateMouse();
        if (dpy) {
-               if (ctx)
+               XSync(dpy, False);
+               if (ctx) {
+                       printf("Found context, destroying...\n");
                        glXDestroyContext(dpy, ctx);
-               if (win)
+               }
+               if (win) {
+                       printf("Found window, destroying...\n");
                        XDestroyWindow(dpy, win);
-               if (vidmode_active)
+               }
+// This seems to hang, unsure why
+#define ATTEMPT_TO_FIX_X_GLX_BUG
+#ifdef ATTEMPT_TO_FIX_X_GLX_BUG
+               if (vidmode_active) {
+                       printf("Restoring video mode...\n");
                        XF86VidModeSwitchToMode(dpy, scrnum, vidmodes[0]);
+               }
                XCloseDisplay(dpy);
+#endif
        }
        vidmode_active = false;
        dpy = NULL;
```        
