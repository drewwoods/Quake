## Overview

Vanilla Quake, slightly modified to compile on current Linux distributions
and macOS.

## Installing Dependencies

### Linux

```sh
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install build-essential libc6-dev-i386 libx11-dev:i386 libegl1-mesa-dev:i386 libxxf86dga1:i386 libxxf86dga1-dev libxxf86vm1:i386 libxxf86vm-dev
```

### macOS

Only the Xcode command line tools:

```sh
xcode-select --install
```

## Building

### macOS

```sh
make -C WinQuake -f Makefile.macos
```

This builds `build/macos/release/quake` and `build/macos/release/glquake`.

### WinQuake (this is probably what you want)

```sh
make -C WinQuake/ -f Makefile.linuxi386
```

### Quake World

```sh
make -C QW/ -f Makefile.Linux
```

### DOS Quake

Install a DJGPP cross-compiler that provides
`i586-pc-msdosdjgpp-gcc`, then run:

```sh
make -C WinQuake -f Makefile.dos
make -C WinQuake -f Makefile.dos dist
```

The first command builds `WinQuake/build/dos/quake.exe`. The second also
places `quake.exe` and the required `cwsdpmi.exe` DPMI host in
`WinQuake/build/dos/dist/`.

To use a toolchain with a different prefix or location, set
`CROSS_COMPILE`, including its trailing dash:

```sh
make -C WinQuake -f Makefile.dos \
  CROSS_COMPILE=/opt/djgpp/bin/i586-pc-msdosdjgpp-
```

The cross-platform DJGPP build scripts and binary releases are available
from [build-djgpp](https://github.com/andrewwutw/build-djgpp). To run the
result, use DOS or FreeDOS with `quake.exe`, `cwsdpmi.exe`, and an `id1`
directory containing licensed Quake game data.

## Running

### macOS

```sh
./WinQuake/build/macos/release/glquake -width 800 -height 600
```

Music uses `id1/music/track02.wav` through `track11.wav`. Files must be 44.1
kHz stereo signed 16-bit PCM. Run with `-sndspeed 44100`. Convert other formats
with `afconvert -f WAVE -d LEI16@44100 -c 2 track02.mp3 track02.wav`.

Windowed by default; `-fullscreen` gives a borderless window over the whole
screen. The GL surface is the size you ask for and the display scales it up,
which keeps the original art looking like itself; pass `-hidpi` to render at
the display's native resolution instead. Add `-basedir <quake-base-dir>` to
play retail data.

### Shareware (included)

**Software:**

```sh
./WinQuake/debugi386/bin/quake.x11 -nosound 1 -width 800 -height 600
```

**OpenGL:**

```sh
./WinQuake/debugi386/bin/glquake.glx -nosound 1 -width 800 -height 600
```

### Retail

**Software:**

```sh
./WinQuake/debugi386/bin/quake.x11 -basedir <quake-base-dir> -nosound 1 -width 800 -height 600
```

**OpenGL:**

```sh
./WinQuake/debugi386/bin/glquake.glx -basedir <quake-base-dir> -nosound 1 -width 800 -height 600
```

## TODO

1. Fix sound (requires `/dev/dsp`)
    * consider pulse audio DSP emulation
    * See [OSS Support for Older Games](https://www.reddit.com/r/linux_gaming/comments/15uc26c/oss_support_for_older_games/)
    * See [Dev Notes](./NOTES.md#13-feb)
1. Update Windows Builds
1. Debug GLX (builds, ~~but doesnt run~~ runs, but desktop resolution not restored on shutdown)
    * See [Dev Notes](./NOTES.md#10-april '10 April')
1. Fix VGA build (maybe)
