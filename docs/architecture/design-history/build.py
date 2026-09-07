#!/usr/bin/env python3
"""Build quake-design-history.html. Shared engine lives in ../build_doc.py."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

import build_doc

DOC = build_doc.Doc(
    here=HERE,
    out="quake-design-history.html",
    # Chapters are added here as they are written; see BRIEF.md for the plan.
    files=[
        ("01-before-quake.md", "Origins"),
        ("02-discarded-renderers.md", "Visibility"),
    ],
    xrefs={"frame": os.path.join("..", "life-of-a-frame",
                                 "quake-life-of-a-frame.html")},
)

if __name__ == "__main__":
    build_doc.build(DOC)
