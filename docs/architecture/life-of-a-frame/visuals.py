"""Render checked-in runtime evidence; the documentation build never runs Quake."""

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BAR_WIDTH = 358
BAR_Y = {"gfx": 701, "snd": 763}


def escaped(value):
    return html.escape(str(value), quote=True)


def refresh():
    timings = json.loads((HERE / 'timings.json').read_text(encoding="utf-8"))
    means = timings['means_ms']
    total = means['total']
    rows = []
    for key, label in [('server', 'Other host work (printed as “server”)'),
                       ('gfx', 'Screen update'), ('snd', 'Audio / light decay / CD update')]:
        share = means[key] / total if total else 0
        # host_speeds prints integer milliseconds, so a sub-millisecond stage
        # reads zero. Say that next to the number, not only in the notes below:
        # a bare "0.000 ms" invites "this stage is free".
        zero = (' <span class="bucket-note">(below measurement resolution)</span>'
                if means[key] == 0 else '')
        rows.append('<tr><th scope="row">%s</th><td>%.3f ms%s</td><td>%.1f%%</td></tr>'
                    % (label, means[key], zero, share * 100))
        if key == 'server':
            continue
        y = BAR_Y[key]
        # Only the two measured call groups get bars; no invented per-function costs.
        tip = '%s: %.3f ms; %.1f%% of logged total' % (label, means[key], share * 100)
        if means[key] == 0:
            tip += ('. Integer host_speeds rows truncate a sub-millisecond stage '
                    'to zero; below measurement resolution, not free work.')
        bar = ('<g class="measured-bar"><title>%s</title>'
               '<rect x="46" y="%d" width="%d" height="3" fill="var(--rule)"/>'
               '<rect x="46" y="%d" width="%.2f" height="3" fill="var(--cl)"/></g>'
               % (escaped(tip), y, BAR_WIDTH, y, BAR_WIDTH * share))
        (HERE / 'diagrams' / ('cost-' + key + '.html')).write_text(bar + '\n', encoding='utf-8')
    caption = ('<aside class="runtime-costs" aria-label="Measured frame costs">'
               '<h3>One measured demo run</h3><p>The thin bars in screen and sound boxes show shares '
               'of this run’s logged total; switching the process diagram does not remeasure them.</p>'
               '<table><caption>Mean of %s logged frames; total %.3f ms</caption>'
               '<thead><tr><th scope="col">Measured bucket</th><th scope="col">Mean</th>'
               '<th scope="col">Share</th></tr></thead><tbody>%s</tbody></table>'
               '<p>%s · %s · capture build <code>%s</code> · %s.</p><p><code>%s</code></p>'
               '<p>%s</p><p><a href="timings.json">Measurement data</a> · '
               '<a href="shots/README.md">Regeneration and capture provenance</a></p></aside>'
               % (timings['samples'], total, ''.join(rows), escaped(timings['machine']),
                  escaped(timings['renderer']), escaped(timings['commit']),
                  escaped(timings['captured_at']), escaped(timings['command']),
                  ' '.join(escaped(note) for note in timings['notes'])))
    (HERE / 'diagrams' / 'measured-costs.html').write_text(caption + '\n', encoding='utf-8')

    captures = json.loads((HERE / 'shots' / 'captures.json').read_text(encoding="utf-8"))
    renderers = captures.get('renderers')
    if not renderers:
        renderers = {'gl': {'label': 'GL', 'pairs': captures['pairs'],
                            'notes': captures.get('notes', [])}}
    keys = [key for key in ('software', 'gl', 'compare') if key in renderers] or list(renderers)
    figures = ['<div class="capture-gallery">',
               '<div class="capture-gallery-head">',
               '<h3>Same viewpoint, different renderer settings</h3>']
    if len(keys) > 1:
        figures.append('<div class="capture-renderer modeswitch" role="group" aria-label="Renderer">')
        for i, key in enumerate(keys):
            figures.append('<button type="button" data-renderer="%s" aria-pressed="%s">%s</button>'
                           % (escaped(key), 'true' if i == 0 else 'false',
                              escaped(renderers[key]['label'])))
        figures.append('</div>')
    figures.append('</div>')
    for key in keys:
        data = renderers[key]
        figures.append('<div class="capture-set" data-renderer="%s">'
                       '<p class="capture-renderer-label">%s renderer</p>'
                       % (escaped(key), escaped(data['label'])))
        for pair in data['pairs']:
            figure_id = 'capture-%s-%s' % (key, pair['id'])
            figures.append('<figure class="capture-pair" id="%s"><h4>%s</h4>'
                           '<div class="capture-images">' % (escaped(figure_id), escaped(pair['title'])))
            for side in ['before', 'after']:
                asset = HERE / 'shots' / pair[side]
                if not asset.is_file():
                    raise FileNotFoundError('Missing capture: %s' % asset)
                figures.append('<div class="capture-%s"><p>%s</p><img loading="lazy" '
                               'width="640" height="480" src="shots/%s" alt="%s"></div>'
                               % (side, escaped(pair[side + '_label']), escaped(pair[side]),
                                  escaped(pair[side + '_label'] + '. ' + pair['description'])))
            figures.append('</div><div class="capture-control" hidden><label for="%s-slider">'
                           'Reveal changed image (%s → %s)</label> <input id="%s-slider" type="range" min="0" '
                           'max="100" value="50" step="1" aria-describedby="%s-description"> '
                           '<output for="%s-slider">50%%</output></div>'
                           '<figcaption id="%s-description">%s</figcaption>'
                           '</figure>' % (figure_id, escaped(pair['before_label']), escaped(pair['after_label']),
                                          figure_id, figure_id, figure_id, figure_id,
                                          escaped(pair['description'])))
        figures.append('</div>')
    figures.append('</div>')
    (HERE / 'diagrams' / 'screenshots.html').write_text('\n'.join(figures) + '\n', encoding='utf-8')
