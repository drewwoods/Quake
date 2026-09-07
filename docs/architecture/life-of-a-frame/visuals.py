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
        rows.append('<tr><th scope="row">%s</th><td>%.3f ms</td><td>%.1f%%</td></tr>'
                    % (label, means[key], share * 100))
        if key == 'server':
            continue
        y = BAR_Y[key]
        # Only the two measured call groups get bars; no invented per-function costs.
        bar = ('<g class="measured-bar"><title>%s: %.3f ms; %.1f%% of logged total</title>'
               '<rect x="46" y="%d" width="%d" height="3" fill="var(--rule)"/>'
               '<rect x="46" y="%d" width="%.2f" height="3" fill="var(--cl)"/></g>'
               % (label, means[key], share * 100, y, BAR_WIDTH, y, BAR_WIDTH * share))
        (HERE / 'diagrams' / ('cost-' + key + '.html')).write_text(bar + '\n', encoding='utf-8')
    caption = ('<aside class="runtime-costs" aria-label="Measured frame costs">'
               '<h3>One measured demo run</h3><p>The thin bars in screen and sound boxes show shares '
               'of this run’s logged total; switching the process diagram does not remeasure them.</p>'
               '<table><caption>Mean of %s logged frames; total %.3f ms</caption>'
               '<thead><tr><th scope="col">Measured bucket</th><th scope="col">Mean</th>'
               '<th scope="col">Share</th></tr></thead><tbody>%s</tbody></table>'
               '<p>%s · %s · baseline <code>%s</code> · %s.</p><p><code>%s</code></p>'
               '<p>%s</p><p><a href="timings.json">Measurement data</a> · '
               '<a href="shots/README.md">Regeneration and capture provenance</a></p></aside>'
               % (timings['samples'], total, ''.join(rows), escaped(timings['machine']),
                  escaped(timings['renderer']), escaped(timings['commit']),
                  escaped(timings['captured_at']), escaped(timings['command']),
                  ' '.join(escaped(note) for note in timings['notes'])))
    (HERE / 'diagrams' / 'measured-costs.html').write_text(caption + '\n', encoding='utf-8')

    captures = json.loads((HERE / 'shots' / 'captures.json').read_text(encoding="utf-8"))
    figures = ['<div class="capture-gallery"><h3>Same viewpoint, different renderer settings</h3>']
    for pair in captures['pairs']:
        figure_id = 'capture-' + pair['id']
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
                       '<figcaption id="%s-description">%s Baseline <code>%s</code>. %s</figcaption>'
                       '</figure>' % (figure_id, escaped(pair['before_label']), escaped(pair['after_label']),
                                      figure_id, figure_id, figure_id, figure_id,
                                      escaped(pair['description']), escaped(captures['commit']),
                                      escaped(captures['scene'])))
    figures.append('<p>%s</p><p><a href="shots/README.md">Capture settings and regeneration</a>'
                   '</p></div>' % ' '.join(escaped(note) for note in captures['notes']))
    (HERE / 'diagrams' / 'screenshots.html').write_text('\n'.join(figures) + '\n', encoding='utf-8')
