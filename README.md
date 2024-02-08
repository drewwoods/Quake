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

```sh
./WinQuake/debugi386/bin/quake.x11 -nosound 1 -width 800 -height 600
```

### Retail

```sh
./WinQuake/debugi386/bin/quake.x11 -basedir <quake-base-dir> -nosound 1 -width 800 -height 600
```

## TODO

1. Fix sound (requires `/dev/dsp`)
    * consider pulse audio DSP emulation
1. Update Windows Builds
1. Debug GLX (builds, but doesnt run)
1. Fix VGA build (maybe)
