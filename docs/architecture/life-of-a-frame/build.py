#!/usr/bin/env python3
"""Build quake-life-of-a-frame.html. Shared engine lives in ../build_doc.py."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import build_doc

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
    extra={"{{OWNERSHIP}}": os.path.join("diagrams", "ownership.html")},
    xrefs={"design": os.path.join("..", "design-history", "quake-design-history.html")},
)

if __name__ == "__main__":
    build_doc.build(DOC)
