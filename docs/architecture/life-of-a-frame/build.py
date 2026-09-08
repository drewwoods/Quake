#!/usr/bin/env python3
"""Build quake-life-of-a-frame.html. Shared engine lives in ../build_doc.py."""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import bsp_slice
import build_doc
import visuals

PAK = os.path.normpath(os.path.join(HERE, "..", "..", "..", "id1", "pak0.pak"))
PVS_FRAGMENT = os.path.join(HERE, "diagrams", "pvs-explorer.html")
PVS_DATA = re.compile(r'(?s)(<script type="application/json" id="pvs-data">)'
                      r'.*?(</script>)')


def refresh_pvs_data(pak=PAK):
    """Re-derive the e1m1 leaf/PVS slice into the diagram fragment.

    Without the pak the fragment keeps whatever data is checked in (none, on a
    fresh tree — the figure then shows its own "unavailable" note), so a build
    never fails just because the game data is absent.
    """
    data = bsp_slice.leaf_slice(pak)
    if not data:
        print("  pvs-explorer: %s not found, leaving embedded data as-is" % pak)
        return
    with open(PVS_FRAGMENT, encoding="utf-8") as f:
        frag = f.read()
    updated = PVS_DATA.sub(lambda m: m.group(1) + bsp_slice.to_json(data) + m.group(2),
                           frag, count=1)
    if updated != frag:
        with open(PVS_FRAGMENT, "w", encoding="utf-8") as f:
            f.write(updated)
    print("  pvs-explorer: %s, %d leaves, PVS %d-%d (mean %.1f, %.1f%%), %.1f KB embedded"
          % (data["map"], data["leaves"], data["min"], data["max"], data["mean"],
             100.0 * data["mean"] / data["leaves"],
             len(bsp_slice.to_json(data)) / 1024.0))


DOC = build_doc.Doc(
    here=HERE,
    out="quake-life-of-a-frame.html",
    files=[
        ("01-frame-overview.md", "Frame"),
        ("02-server-physics-progs.md", "Server"),
        ("03-collision.md", "Collision"),
        ("04-bsp-pvs.md", "World"),
        ("05-rendering.md", "Render"),
        ("06-input-client-net.md", "Client"),
        ("07-sound-misc.md", "Sound"),
    ],
    extra={"{{OWNERSHIP}}": os.path.join("diagrams", "ownership.html"),
           "{{GFX_COST}}": os.path.join("diagrams", "cost-gfx.html"),
           "{{SND_COST}}": os.path.join("diagrams", "cost-snd.html"),
           "{{MEASURED_COSTS}}": os.path.join("diagrams", "measured-costs.html")},
    xrefs={"design": os.path.join("..", "design-history", "quake-design-history.html")},
)

if __name__ == "__main__":
    refresh_pvs_data()
    visuals.refresh()
    build_doc.build(DOC)
