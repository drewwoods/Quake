#!/usr/bin/env python3
"""Capture the pinned native macOS revision; requires macOS, clang and sips."""
import argparse
import datetime
import io
import json
import pathlib
import platform
import re
import struct
import subprocess
import tarfile
import tempfile
import zlib

COMMIT = '78216afaad7ece08e98b0bff0b835a7628b699ee'
BASELINE = '3ef8a7a9e53e226c831467f1b200bc77239e2e0d'
FRAME_WAITS = 200
WAIT_BATCH = 100
TIMING_BATCHES = 20
BUILD_JOBS = 8
OUTPUT = pathlib.Path(__file__).resolve().parent
REPO = OUTPUT.parents[2]
SCENE = ('demo1, %d wait commands after timedemo starts; '
         '640×480; fixed host_framerate 0.05' % FRAME_WAITS)
DEMO_SCENE = 'timedemo demo1\n' + 'wait\n' * FRAME_WAITS

# Extra viewpoints captured in both renderers with default settings, for the
# Compare tab. Values are the console script that reaches the viewpoint.
COMPARE_SCENES = {
    # Explosion mid-air: particles and a dynamic light on the surrounding walls.
    'explosion': 'timedemo demo3\n' + 'wait\n' * 680,
    # e1m1 corridor lamps in a dark spot: fullbright texels. A local server, not
    # a demo: spawn, walk 15 fixed steps forward, let the view bob settle.
    'fullbright': 'map e1m1\n' + 'wait\n' * 20 + '+forward\n' + 'wait\n' * 15
                  + '-forward\n' + 'wait\n' * 10,
}
COMPARE_PAIRS = [
    {'id': 'renderers',
     'title': 'Renderer: GLQuake (OpenGL) vs Software Quake',
     'before': 'software/normal.png', 'after': 'normal.png',
     'before_label': 'Software', 'after_label': 'GL',
     'description': ('The exact same camera viewpoint rendered by Software Quake and '
                     'GLQuake. Software Quake uses the 8-bit paletted software pipeline '
                     'with surface caching and span rasterization; GLQuake uses hardware '
                     'rasterization with bilinear filtering and multipass dynamic lightmaps.')},
    {'id': 'fullbright',
     'title': 'Fullbright texels: e1m1 corridor lamps',
     'before': 'software/fullbright.png', 'after': 'fullbright.png',
     'before_label': 'Software', 'after_label': 'GL',
     'description': ('Every light level of the colormap maps palette indices 224–255 to '
                     'themselves, so the software renderer draws lamp faces at full '
                     'intensity whatever the lightmap says. GLQuake converts textures to RGB '
                     'and multiplies every texel by the lightmap, so the same lamps fade into '
                     'the dark. Torch models are exempt: R_DrawAliasModel forces flame.mdl to '
                     'full light. Not a demo: a local server, 15 fixed steps forward from spawn.')},
    {'id': 'explosion',
     'title': 'Dynamic light and particles: demo3 rocket explosion',
     'before': 'software/explosion.png', 'after': 'explosion.png',
     'before_label': 'Software', 'after_label': 'GL',
     'description': ('The software renderer adds the explosion dlight into the surface '
                     'cache, so nearby walls brighten. GLQuake defaults to gl_flashblend 1: '
                     'lightmaps are left alone and R_RenderDlights draws an additive sphere '
                     'instead. Particles are distance-scaled squares in software and small '
                     'textured triangles in GL. Same demo message in both.')},
]

# GL writes TGA; software writes 8-bit PCX. Same viewpoint via timedemo+wait.
RENDERERS = {
    'gl': {
        'label': 'GL',
        'target': 'glquake',
        'binary': 'WinQuake/build/macos/release/glquake',
        'args': ['-window', '-width', '640', '-height', '480', '-nomtex'],
        'shot_ext': '.tga',
        'source_files': ('host.c', 'gl_rmain.c', 'gl_rsurf.c', 'gl_screen.c'),
        'settings': ('viewsize 100\nvolume 0\ncon_notifytime 0\ngl_texsort 1\n'
                     'r_novis 0\nr_drawentities 1\nr_lightmap 0\nr_speeds 0\n'),
        'variants': {'normal': '', 'no-vis': 'r_novis 1',
                     'no-entities': 'r_drawentities 0', 'lightmap': 'r_lightmap 1',
                     'speeds': 'r_speeds 1\ncon_notifytime 3'},
        'subdir': '',
        'pairs': [
            {'id': 'visibility',
             'title': 'Visibility: more submitted geometry need not change the view',
             'before': 'normal.png', 'after': 'no-vis.png',
             'before_label': 'r_novis 0', 'after_label': 'r_novis 1',
             'description': ('PVS rejection is disabled. Walls still occlude geometry '
                             'through depth testing, so a similar image does not imply '
                             'equal rendering work.')},
            {'id': 'entities',
             'title': 'World geometry and entities',
             'before': 'normal.png', 'after': 'no-entities.png',
             'before_label': 'r_drawentities 1', 'after_label': 'r_drawentities 0',
             'description': ('The enemy, pickup and weapon disappear. The bars also '
                             'disappear: moving brush models are entities. The static '
                             'BSP world and particles remain.')},
            {'id': 'lightmaps',
             'title': 'The lightmap pass',
             'before': 'normal.png', 'after': 'lightmap.png',
             'before_label': 'r_lightmap 0', 'after_label': 'r_lightmap 1',
             'description': ('The multipass path draws its lightmap texture without the '
                             'usual blend. This diagnostic is not a final illumination-only '
                             'render; entities keep their textures. Both captures use '
                             '-nomtex and gl_texsort 1.')},
            {'id': 'speeds',
             'title': 'Renderer counters in the console notification area',
             'before': 'normal.png', 'after': 'speeds.png',
             'before_label': 'r_speeds 0', 'after_label': 'r_speeds 1',
             'description': ('The top-left console notifications show milliseconds, world '
                             'polygons (wpoly), and entity polygons (epoly). Several recent '
                             'frames remain visible; the displayed timing is one instrumented run.')},
        ],
        'notes': [
            'Captured from clean native macOS commit ' + COMMIT[:7] + ', not documentation baseline ' + BASELINE[:7] + '. Host and GL render paths cited here are unchanged between those commits.',
            'Unedited engine screenshots, converted from TGA to PNG with sips. No overlays were drawn onto the images.',
            'Separate scripted runs use the same demo-message index, fixed 0.05-second simulation step, and camera. The baseline pause command does not freeze demo playback; timedemo plus wait supplies reproducible frame selection instead.',
            'All shots use -nomtex, gl_texsort 1, viewsize 100, and muted audio. r_lightmap has no effect in the default multitexture path.',
            'Each variant has a companion .cfg. Reproduce from the repository with python3 docs/architecture/life-of-a-frame/capture.py --renderer gl. This creates a temporary clean export and builds the pinned revision.',
        ],
    },
    'software': {
        'label': 'Software',
        'target': 'build/macos/release/quake',
        'binary': 'WinQuake/build/macos/release/quake',
        'args': ['-width', '640', '-height', '480'],
        'shot_ext': '.pcx',
        'source_files': ('host.c', 'r_main.c', 'r_misc.c', 'screen.c', 'd_edge.c'),
        'settings': ('viewsize 100\nvolume 0\ncon_notifytime 0\n'
                     'r_drawentities 1\nr_drawflat 0\nr_speeds 0\n'),
        'variants': {'normal': '', 'no-entities': 'r_drawentities 0',
                     'drawflat': 'r_drawflat 1',
                     'speeds': 'r_speeds 1\ncon_notifytime 3'},
        'subdir': 'software',
        'pairs': [
            {'id': 'entities',
             'title': 'World geometry and entities',
             'before': 'software/normal.png', 'after': 'software/no-entities.png',
             'before_label': 'r_drawentities 1', 'after_label': 'r_drawentities 0',
             'description': ('The enemy, pickup and weapon disappear. The bars also '
                             'disappear: moving brush models are entities. The static '
                             'BSP world and particles remain.')},
            {'id': 'drawflat',
             'title': 'Surface span rasterization',
             'before': 'software/normal.png', 'after': 'software/drawflat.png',
             'before_label': 'r_drawflat 0', 'after_label': 'r_drawflat 1',
             'description': ('Surfaces are drawn in solid colors without textures, '
                             'showing how the BSP front-to-back traversal and edge scan '
                             'conversion partition the visible scene into surface spans.')},
            {'id': 'speeds',
             'title': 'Renderer counters in the console notification area',
             'before': 'software/normal.png', 'after': 'software/speeds.png',
             'before_label': 'r_speeds 0', 'after_label': 'r_speeds 1',
             'description': ('The top-left console notifications show render time in milliseconds, '
                             'faceclip, polygon count, drawn polygon count, and surface count (c_surf).')},
        ],
        'notes': [
            'Captured from clean native macOS commit ' + COMMIT[:7] + ', not documentation baseline ' + BASELINE[:7] + '. Host and software render paths cited here are unchanged between those commits.',
            'Unedited engine screenshots, converted from the software renderer’s PCX output to PNG. No overlays were drawn onto the images.',
            'Separate scripted runs use the same demo-message index, fixed 0.05-second simulation step, and camera as the GL captures. The baseline pause command does not freeze demo playback; timedemo plus wait supplies reproducible frame selection instead.',
            'Windowed 640×480, viewsize 100, muted audio. r_novis and r_lightmap are GL-only; r_drawflat is the software-only world-span diagnostic.',
            'Each variant has a companion .cfg. Reproduce from the repository with python3 docs/architecture/life-of-a-frame/capture.py --renderer software. This creates a temporary clean export and builds the pinned revision.',
        ],
    },
}


def png_chunk(tag, payload):
    crc = zlib.crc32(tag + payload) & 0xffffffff
    return struct.pack('>I', len(payload)) + tag + payload + struct.pack('>I', crc)


def write_png(path, width, height, rgb):
    rows = b''.join(b'\x00' + rgb[y * width * 3:(y + 1) * width * 3] for y in range(height))
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + png_chunk(b'IHDR', ihdr)
                     + png_chunk(b'IDAT', zlib.compress(rows, 9)) + png_chunk(b'IEND', b''))


def pcx_to_png(src, dest):
    """Software screenshots are 8-bit RLE PCX; decode here so capture.py stays the converter."""
    data = src.read_bytes()
    if len(data) < 128 + 769 or data[0] != 10 or data[3] != 8:
        raise RuntimeError('Unsupported PCX: ' + str(src))
    xmin, ymin, xmax, ymax = struct.unpack_from('<HHHH', data, 4)
    width, height = xmax - xmin + 1, ymax - ymin + 1
    planes = data[65]
    stride = struct.unpack_from('<H', data, 66)[0]
    if planes != 1 or data[-769] != 12:
        raise RuntimeError('Unsupported PCX: ' + str(src))
    palette = data[-768:]
    raw = bytearray()
    i = 128
    end = len(data) - 769
    needed = height * stride
    while i < end and len(raw) < needed:
        b = data[i]
        i += 1
        if b >= 0xC0:
            if i >= end:
                raise RuntimeError('Truncated PCX: ' + str(src))
            raw.extend([data[i]] * (b & 0x3F))
            i += 1
        else:
            raw.append(b)
    if len(raw) < needed:
        raise RuntimeError('Short PCX image: ' + str(src))
    rgb = bytearray(width * height * 3)
    o = 0
    for y in range(height):
        row = raw[y * stride:y * stride + width]
        for pix in row:
            p = pix * 3
            rgb[o:o + 3] = palette[p:p + 3]
            o += 3
    write_png(dest, width, height, bytes(rgb))


def convert_shot(src, dest):
    if src.suffix.lower() == '.tga':
        subprocess.run(['sips', '-s', 'format', 'png', str(src), '--out', str(dest)],
                       check=True, stdout=subprocess.DEVNULL)
        return
    if src.suffix.lower() == '.pcx':
        pcx_to_png(src, dest)
        return
    raise RuntimeError('Unknown screenshot format: ' + str(src))


def load_metadata(shots):
    path = shots / 'captures.json'
    metadata = json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}
    if 'renderers' in metadata:
        return metadata
    # Older captures.json listed only GL pairs at the top level.
    migrated = {
        'commit': metadata.get('commit', COMMIT),
        'scene': metadata.get('scene', SCENE),
        'renderers': {
            'gl': {
                'label': 'GL',
                'pairs': metadata.get('pairs', RENDERERS['gl']['pairs']),
                'notes': metadata.get('notes', RENDERERS['gl']['notes']),
            }
        },
    }
    if metadata.get('captured_at'):
        migrated['captured_at'] = metadata['captured_at']
        migrated['renderers']['gl']['captured_at'] = metadata['captured_at']
    return migrated


def capture_renderer(root, name):
    spec = RENDERERS[name]
    shots = OUTPUT / 'shots'
    dest = shots / spec['subdir'] if spec['subdir'] else shots
    dest.mkdir(parents=True, exist_ok=True)
    command = [str(root / spec['binary']), '-basedir', str(root)] + spec['args']
    scenes = [(variant, DEMO_SCENE, setting) for variant, setting in spec['variants'].items()]
    scenes += [(scene, script, '') for scene, script in COMPARE_SCENES.items()]
    for variant, scene, setting in scenes:
        # Fixed simulation steps and demo messages reproduce the same camera without a fake pause.
        cfg = spec['settings'] + 'host_framerate 0.05\n' + setting + '\n' + scene
        cfg += 'screenshot\ntoggleconsole\nquit\n'
        (root / 'id1/capture.cfg').write_text(cfg)
        (dest / (variant + '.cfg')).write_text(cfg)
        existing = set((root / 'id1').glob('*' + spec['shot_ext']))
        with tempfile.TemporaryFile() as log:
            subprocess.run(command + ['+exec', 'capture.cfg'], stdout=log,
                           stderr=subprocess.STDOUT, timeout=60, check=True)
        new = set((root / 'id1').glob('*' + spec['shot_ext'])) - existing
        if len(new) != 1:
            raise RuntimeError('Expected one screenshot: %s/%s' % (name, variant))
        convert_shot(new.pop(), dest / (variant + '.png'))

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    metadata = load_metadata(shots)
    metadata['commit'] = COMMIT
    metadata['scene'] = SCENE
    metadata['captured_at'] = now
    renderers = metadata.setdefault('renderers', {})
    renderers[name] = {
        'label': spec['label'],
        'captured_at': now,
        'pairs': spec['pairs'],
        'notes': spec['notes'],
    }
    renderers['compare'] = {'label': 'Compare', 'pairs': COMPARE_PAIRS, 'notes': []}
    (shots / 'captures.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    return command


def capture_timings(root, command):
    # No fixed timestep or renderer counters in the measured run. Alias stays under the 8 KB command buffer.
    cfg = RENDERERS['gl']['settings'] + 'host_framerate 0\ntimedemo demo1\nwait\nhost_speeds 1\n'
    cfg += 'alias wait100 "' + 'wait;' * WAIT_BATCH + '"\n' + 'wait100\n' * TIMING_BATCHES
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
    if not rows:
        raise RuntimeError('No timing samples after initialization')
    notes = [
        'Native macOS GL revision ' + COMMIT[:7] + '; not an executable of documentation baseline ' + BASELINE[:7] + '.',
        'host.c, gl_rmain.c, gl_rsurf.c and gl_screen.c match the documentation baseline.',
        'Windowed 640×480, -nomtex, gl_texsort 1; volume 0; default display synchronization.',
        'Means of integer millisecond host_speeds rows before the completed demo summary; first stale-timestamp row excluded.',
        'The server bucket is the remainder between frames, including non-graphics client work, scheduling and printing; demo playback runs no local server.',
        'gfx measures SCR_UpdateScreen including presentation; snd includes S_Update, CL_DecayLights and CD audio. These are wall times, not CPU-only costs.',
        'Integer truncation makes short stages read zero; zero is below measurement resolution, not free work.',
        'One instrumented run on modern hardware; console logging and scheduling affect timings. Not a historical performance claim.'
    ]
    signal = re.search(r'Received signal (\d+), exiting', log[summary.end():])
    if signal:
        notes.append('The native signal handler reported signal ' + signal.group(1)
                     + ' after the completed summary; it can exit with status zero. '
                     'Only pre-summary measurements are retained.')
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


def selected_renderers(choice):
    return ('gl', 'software') if choice == 'both' else (choice,)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--renderer', choices=('gl', 'software', 'both'), default='both',
                        help='Which native build to capture (default: both)')
    args = parser.parse_args()
    names = selected_renderers(args.renderer)
    # Always build the pinned source; reused exports could silently mislabel measurements.
    checked = []
    for name in names:
        for source in RENDERERS[name]['source_files']:
            if source in checked:
                continue
            checked.append(source)
            path = 'WinQuake/' + source
            baseline = subprocess.check_output(['git', '-C', str(REPO), 'show', BASELINE + ':' + path])
            native = subprocess.check_output(['git', '-C', str(REPO), 'show', COMMIT + ':' + path])
            if baseline != native:
                raise RuntimeError('Capture source differs from documented baseline: ' + path)
    with tempfile.TemporaryDirectory(prefix='quake-doc-capture-') as temporary:
        root = pathlib.Path(temporary)
        archive = subprocess.check_output(['git', '-C', str(REPO), 'archive', COMMIT])
        with tarfile.open(fileobj=io.BytesIO(archive)) as source:
            source.extractall(root, filter='data')
        targets = [RENDERERS[name]['target'] for name in names]
        subprocess.run(['make', '-C', str(root / 'WinQuake'), '-f', 'Makefile.macos',
                        '-j%d' % BUILD_JOBS] + targets, check=True)
        gl_command = None
        for name in names:
            command = capture_renderer(root, name)
            if name == 'gl':
                gl_command = command
        if gl_command:
            capture_timings(root, gl_command)


if __name__ == '__main__':
    main()

