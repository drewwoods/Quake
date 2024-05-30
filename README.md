## Overview

Vanilla Quake, slightly modified to compile on current Linux distributions

## Installing Dependencies

```sh
sudo dpkg --add-architecture i386
sudo apt update
sudo apt install build-essential libc6-dev-i386 libx11-dev:i386 libegl1-mesa-dev:i386 libxxf86dga1:i386 libxxf86dga1-dev libxxf86vm1:i386 libxxf86vm-dev
```

## Building

### WinQuake (this is probably what you want)

```sh
make -C WinQuake/ -f Makefile.linuxi386
```

### Quake World

```sh
make -C QW/ -f Makefile.Linux
```

## Running

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
