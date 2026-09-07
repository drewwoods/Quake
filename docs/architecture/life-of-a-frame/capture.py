#!/usr/bin/env python3
"""Capture the first native GLQuake revision; requires macOS, clang and sips."""
import argparse
import datetime
import io
import json
import pathlib
import platform
import re
import subprocess
import tarfile
import tempfile

COMMIT = '7a74a7c6d901e39f907b39bec94819476bb7b845'
BASELINE = '3ef8a7a9e53e226c831467f1b200bc77239e2e0d'
FRAME_WAITS = 200
OUTPUT = pathlib.Path(__file__).resolve().parent
REPO = OUTPUT.parents[2]
VARIANTS = {'normal': '', 'no-vis': 'r_novis 1',
            'no-entities': 'r_drawentities 0', 'lightmap': 'r_lightmap 1',
            'speeds': 'r_speeds 1\ncon_notifytime 3'}
SETTINGS = ('viewsize 100\nvolume 0\ncon_notifytime 0\ngl_texsort 1\n'
            'r_novis 0\nr_drawentities 1\nr_lightmap 0\nr_speeds 0\n')


def run_capture(root):
    shots = OUTPUT / 'shots'
    shots.mkdir(exist_ok=True)
    command = [str(root / 'WinQuake/build/macos/release/glquake'),
               '-basedir', str(root), '-window', '-width', '640', '-height', '480', '-nomtex']
    for name, setting in VARIANTS.items():
        # Fixed simulation steps and demo messages reproduce the same camera without a fake pause.
        cfg = SETTINGS + 'host_framerate 0.05\n' + setting + '\ntimedemo demo1\n'
        cfg += 'wait\n' * FRAME_WAITS + 'screenshot\ntoggleconsole\nquit\n'
        (root / 'id1/capture.cfg').write_text(cfg)
        (shots / (name + '.cfg')).write_text(cfg)
        existing = set((root / 'id1').glob('*.tga'))
        with tempfile.TemporaryFile() as log:
            subprocess.run(command + ['+exec', 'capture.cfg'], stdout=log,
                           stderr=subprocess.STDOUT, timeout=45, check=True)
        new = set((root / 'id1').glob('*.tga')) - existing
        if len(new) != 1:
            raise RuntimeError('Expected one screenshot: ' + name)
        subprocess.run(['sips', '-s', 'format', 'png', str(new.pop()), '--out',
                        str(shots / (name + '.png'))], check=True, stdout=subprocess.DEVNULL)

    # No fixed timestep or renderer counters in the measured run. Alias stays under the 8 KB command buffer.
    cfg = SETTINGS + 'host_framerate 0\ntimedemo demo1\nwait\nhost_speeds 1\n'
    cfg += 'alias wait100 "' + 'wait;' * 100 + '"\n' + 'wait100\n' * 20
    cfg += 'host_speeds 0\ntoggleconsole\nquit\n'
    (root / 'id1/timings.cfg').write_text(cfg)
    (OUTPUT / 'timings.cfg').write_text(cfg)
    with (OUTPUT / 'timings.log').open('w') as log:
        result = subprocess.run(command + ['+exec', 'timings.cfg'], stdout=log,
                                stderr=subprocess.STDOUT, timeout=60)
    log = (OUTPUT / 'timings.log').read_text()
    summary = re.search(r'(\d+ frames\s+[\d.]+ seconds\s+[\d.]+ fps)', log)
    if not summary:
        raise RuntimeError('No completed timedemo summary')
    rows = re.findall(r'^\s*(\d+) tot\s+(\d+) server\s+(\d+) gfx\s+(\d+) snd$',
                      log[:summary.start()], re.M)
    # host_speeds starts with a stale static timestamp; discard that initialization row.
    rows = [tuple(map(int, row)) for row in rows[1:]]
    notes = [
        'First native macOS GL revision; not an executable of documentation baseline ' + BASELINE[:7] + '.',
        'host.c, gl_rmain.c, gl_rsurf.c and gl_screen.c match the documentation baseline.',
        'Windowed 640×480, -nomtex, gl_texsort 1; volume 0; default display synchronization.',
        'Means of integer millisecond host_speeds rows before the completed demo summary; first stale-timestamp row excluded.',
        'The server bucket is the remainder between frames, including non-graphics client work, scheduling and printing; demo playback runs no local server.',
        'gfx measures SCR_UpdateScreen including presentation; snd measures S_Update and CD audio. These are wall times, not CPU-only costs.',
        'Integer truncation makes short stages read zero; zero is below measurement resolution, not free work.',
        'One instrumented run on modern hardware; console logging and scheduling affect timings. Not a historical performance claim.'
    ]
    if result.returncode:
        notes.append('This native revision exited with status ' + str(result.returncode) + ' after printing the completed timedemo summary; retained only pre-summary measurements.')
    data = dict(commit=COMMIT, baseline=BASELINE,
                captured_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                machine=subprocess.check_output(['sysctl', '-n', 'machdep.cpu.brand_string'], text=True).strip() + ', macOS ' + platform.mac_ver()[0],
                renderer='GLQuake Cocoa / Apple OpenGL, multipass lightmaps',
                command='WinQuake/build/macos/release/glquake -basedir <export> -window -width 640 -height 480 -nomtex +exec timings.cfg',
                samples=len(rows), means_ms={key: sum(row[i] for row in rows) / len(rows)
                    for i, key in enumerate(('total', 'server', 'gfx', 'snd'))},
                demo_summary=summary.group(1), log='timings.log', notes=notes)
    (OUTPUT / 'timings.json').write_text(json.dumps(data, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', type=pathlib.Path, help='Reuse a clean export of the pinned revision.')
    args = parser.parse_args()
    if args.export:
        run_capture(args.export)
        return
    with tempfile.TemporaryDirectory(prefix='quake-doc-capture-') as temporary:
        root = pathlib.Path(temporary)
        archive = subprocess.check_output(['git', '-C', str(REPO), 'archive', COMMIT])
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(root, filter='data')
        subprocess.run(['make', '-C', str(root / 'WinQuake'), '-f', 'Makefile.macos',
                        '-j8', 'glquake'], check=True)
        run_capture(root)


if __name__ == '__main__':
    main()
