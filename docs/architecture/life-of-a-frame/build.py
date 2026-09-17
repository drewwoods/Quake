#!/usr/bin/env python3
"""Build quake-life-of-a-frame.html. Shared engine lives in ../build_doc.py."""

import base64
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import bsp_slice
import build_doc
import dem_slice
import visuals

PAK = os.path.normpath(os.path.join(HERE, "..", "..", "..", "id1", "pak0.pak"))
PVS_FRAGMENT = os.path.join(HERE, "diagrams", "pvs-explorer.html")
PVS_DATA = re.compile(r'(?s)(<script type="application/json" id="pvs-data">)'
                      r'.*?(</script>)')
PACKET_FRAGMENT = os.path.join(HERE, "diagrams", "packet.html")
PACKET_DATA = re.compile(r'(?s)(<script type="application/json" id="pk-data">)'
                         r'.*?(</script>)')
SPATIALIZE_FRAGMENT = os.path.join(HERE, "diagrams", "spatialize.html")
SOUND_DATA = re.compile(r'(?s)(<script type="application/json" id="sp-sounds">)'
                        r'.*?(</script>)')
# Small pak0.pak samples for the spatialization widget: two looping ambients,
# two one-shots. Raw wav bytes, base64 — about 80 KB embedded.
SOUNDS = ["sound/ambience/drone6.wav", "sound/ambience/wind2.wav",
          "sound/weapons/rocket1i.wav", "sound/misc/talk.wav"]


def refresh_sound_data(pak=PAK):
    """Embed the SOUNDS wavs into the spatialization widget as base64.

    Same contract as the other slices: no pak, no change; the widget then
    offers the synthetic tone alone.
    """
    if not os.path.exists(pak):
        print("  spatialize: %s not found, leaving embedded sounds as-is" % pak)
        return
    data = {}
    for name in SOUNDS:
        wav = bsp_slice.pak_extract(pak, name)
        if wav is None:
            print("  spatialize: %s missing from pak, skipped" % name)
            continue
        data[name] = base64.b64encode(wav).decode("ascii")
    with open(SPATIALIZE_FRAGMENT, encoding="utf-8") as f:
        frag = f.read()
    blob = json.dumps(data, separators=(",", ":"))
    updated = SOUND_DATA.sub(lambda m: m.group(1) + blob + m.group(2), frag, count=1)
    if updated != frag:
        with open(SPATIALIZE_FRAGMENT, "w", encoding="utf-8") as f:
            f.write(updated)
    print("  spatialize: %d sounds, %.1f KB embedded" % (len(data), len(blob) / 1024.0))


def refresh_packet_data(pak=PAK):
    """Re-derive one dissected demo frame into the packet diagram.

    Same contract as the PVS slice: without the pak the fragment keeps what is
    checked in, and the figure says so itself rather than failing the build.
    """
    data = dem_slice.frame_slice(pak)
    if not data:
        print("  packet: no dissectable frame from %s, leaving embedded data as-is" % pak)
        return
    with open(PACKET_FRAGMENT, encoding="utf-8") as f:
        frag = f.read()
    updated = PACKET_DATA.sub(lambda m: m.group(1) + dem_slice.to_json(data) + m.group(2),
                              frag, count=1)
    if updated != frag:
        with open(PACKET_FRAGMENT, "w", encoding="utf-8") as f:
            f.write(updated)
    print("  packet: %s frame %d, %d bytes, %d entity updates, %d fields"
          % (data["demo"], data["frame"], data["size"], data["updates"],
             len(data["spans"])))


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
    refresh_packet_data()
    refresh_sound_data()
    visuals.refresh()
    build_doc.build(DOC)
