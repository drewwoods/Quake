#!/usr/bin/env python3
"""Derive a top-down leaf/PVS slice of a map from id1/pak0.pak. Stdlib only.

The pak is id's data, not GPL, so this emits *derived* values only: quantised
leaf bounding boxes and the PVS bit relationships between them. No textures,
no entity string, no raw lump bytes.

Field layouts below follow WinQuake/bspfile.h; the vis decompressor mirrors
Mod_DecompressVis (WinQuake/model.c:115).

Output geometry is a plan view rotated 90 degrees clockwise, so the map's long
north-south axis (+y) runs left-to-right on screen:

    map +y (north) --> screen +x        map +x (east) --> screen +y
"""

import json
import os
import struct

# --- pak0.pak directory: "PACK", int dirofs, int dirlen; 64-byte entries -----
PAK_MAGIC = b"PACK"
PAK_ENTRY_SIZE = 64
PAK_NAME_SIZE = 56

# --- bspfile.h --------------------------------------------------------------
BSP_VERSION = 29
HEADER_LUMPS = 15
LUMP_VISIBILITY = 4
LUMP_LEAFS = 10
LUMP_MODELS = 14

# dleaf_t: int contents, int visofs, short mins[3], short maxs[3],
#          ushort firstmarksurface, ushort nummarksurfaces, byte ambient[4]
DLEAF_FMT = "<ii6h2H4B"
DLEAF_SIZE = struct.calcsize(DLEAF_FMT)          # 28

# dmodel_t: float mins[3], maxs[3], origin[3], int headnode[4],
#           int visleafs, int firstface, int numfaces
DMODEL_FMT = "<9f7i"
DMODEL_SIZE = struct.calcsize(DMODEL_FMT)        # 64
DMODEL_VISLEAFS = 13                             # field index in DMODEL_FMT

NO_VIS = -1                                      # dleaf_t.visofs sentinel

# --- output encoding --------------------------------------------------------
# Base-64 varint: 5 payload bits per character, bit 5 means "another follows".
# Keeps the embedded JSON to plain string literals with no escaping.
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-_"
VARINT_CONTINUE = 32
VARINT_MASK = 31
ROW_SEP = "."                                    # absent from ALPHABET

GRID = 4                                         # map units per output unit
BOX_FIELDS = 6                                   # x, y, w, h, z, dz per leaf


def varint(n):
    out = []
    while True:
        c = n & VARINT_MASK
        n >>= 5
        out.append(ALPHABET[c | (VARINT_CONTINUE if n else 0)])
        if not n:
            return "".join(out)


# ---------------------------------------------------------------- pak / bsp

def pak_extract(pak_path, name):
    """Return one file's bytes from a .pak, or None if it is not there."""
    with open(pak_path, "rb") as f:
        blob = f.read()
    if blob[:4] != PAK_MAGIC:
        raise ValueError("%s: not a pak file" % pak_path)
    dirofs, dirlen = struct.unpack("<ii", blob[4:12])
    want = name.encode("ascii")
    for i in range(dirlen // PAK_ENTRY_SIZE):
        e = blob[dirofs + i * PAK_ENTRY_SIZE:][:PAK_ENTRY_SIZE]
        if e[:PAK_NAME_SIZE].split(b"\0")[0] != want:
            continue
        ofs, length = struct.unpack("<ii", e[PAK_NAME_SIZE:])
        return blob[ofs:ofs + length]
    return None


def bsp_lumps(bsp):
    version = struct.unpack("<i", bsp[:4])[0]
    if version != BSP_VERSION:
        raise ValueError("bsp version %d, expected %d" % (version, BSP_VERSION))
    return [struct.unpack("<ii", bsp[4 + 8 * i:12 + 8 * i])
            for i in range(HEADER_LUMPS)]


def decompress_vis(vis, ofs, row):
    """Mod_DecompressVis: literal bytes, and a zero byte means a zero run.

    A leaf with no vis row (visofs == -1) is "everything visible", exactly as
    the engine's mod_novis path treats it.
    """
    if ofs == NO_VIS:
        return bytearray(b"\xff" * row)
    out = bytearray()
    i = ofs
    while len(out) < row:
        if vis[i]:
            out.append(vis[i])
            i += 1
            continue
        out.extend(b"\0" * vis[i + 1])
        i += 2
    return out[:row]


# ---------------------------------------------------------------- slice

def leaf_slice(pak_path, mapname="e1m1"):
    """Parse one map and return the JSON-ready slice, or None if unavailable."""
    if not os.path.exists(pak_path):
        return None
    bsp = pak_extract(pak_path, "maps/%s.bsp" % mapname)
    if bsp is None:
        return None

    lumps = bsp_lumps(bsp)
    mofs = lumps[LUMP_MODELS][0]
    # Submodel 0 is the world; the engine uses its visleafs as model->numleafs,
    # so PVS rows cover leaves 1..visleafs and bit i means leaf i+1.
    numleafs = struct.unpack(DMODEL_FMT, bsp[mofs:mofs + DMODEL_SIZE])[DMODEL_VISLEAFS]

    lofs, llen = lumps[LUMP_LEAFS]
    leaves = [struct.unpack(DLEAF_FMT, bsp[lofs + i * DLEAF_SIZE:][:DLEAF_SIZE])
              for i in range(llen // DLEAF_SIZE)]
    world = leaves[1:numleafs + 1]          # leaf 0 is the shared solid leaf

    visofs, vislen = lumps[LUMP_VISIBILITY]
    vis = bsp[visofs:visofs + vislen]
    row = (numleafs + 7) >> 3

    rows = []
    for leaf in world:
        bits = decompress_vis(vis, leaf[1], row)
        rows.append([j for j in range(numleafs) if bits[j >> 3] & (1 << (j & 7))])

    # Sanity: every leaf must see itself, and none may see all or nothing.
    for i, seen in enumerate(rows):
        if i not in seen:
            raise ValueError("leaf %d does not see itself" % (i + 1))
        if not seen or len(seen) == numleafs:
            raise ValueError("leaf %d sees %d of %d leaves"
                             % (i + 1, len(seen), numleafs))

    # Quantise bounding boxes onto a GRID-unit lattice, rounding outward so no
    # leaf collapses to nothing. This is the only geometric simplification:
    # boxes have no collinear edges to merge.
    def lo(v):
        return v // GRID
    def hi(v):
        return -(-v // GRID)

    ymin = min(l[3] for l in world)
    xmin = min(l[2] for l in world)
    zmin = min(l[4] for l in world)
    box = []
    width = height = 0
    for l in world:
        # screen x from map y, screen y from map x (90-degree clockwise turn)
        sx, sy = lo(l[3]) - lo(ymin), lo(l[2]) - lo(xmin)
        w = max(1, hi(l[6]) - lo(l[3]))
        h = max(1, hi(l[5]) - lo(l[2]))
        z, dz = lo(l[4]) - lo(zmin), max(1, hi(l[7]) - lo(l[4]))
        width, height = max(width, sx + w), max(height, sy + h)
        box.append("".join(varint(v) for v in (sx, sy, w, h, z, dz)))

    pvs = []
    for seen in rows:
        parts = []
        prev, i = -1, 0
        while i < len(seen):
            j = i
            while j + 1 < len(seen) and seen[j + 1] == seen[j] + 1:
                j += 1
            parts.append(varint(seen[i] - prev) + varint(j - i + 1))
            prev = seen[j]
            i = j + 1
        pvs.append("".join(parts))

    counts = [len(r) for r in rows]
    return {
        "map": mapname,
        "leaves": numleafs,
        "grid": GRID,
        "w": width,
        "h": height,
        "zmax": max(hi(l[7]) - lo(zmin) for l in world),
        "box": "".join(box),
        "pvs": ROW_SEP.join(pvs),
        "start": counts.index(max(counts)),
        "min": min(counts),
        "max": max(counts),
        "mean": round(sum(counts) / float(len(counts)), 1),
        "rle": vislen,
        "raw": numleafs * row,
    }


def to_json(data):
    return json.dumps(data, separators=(",", ":"))


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", "..", ".."))
    d = leaf_slice(os.path.join(root, "id1", "pak0.pak"))
    if not d:
        raise SystemExit("no pak0.pak")
    print("%s: %d world leaves, PVS %d-%d (mean %.1f, %.1f%%), "
          "vis lump %d B vs %d B raw"
          % (d["map"], d["leaves"], d["min"], d["max"], d["mean"],
             100.0 * d["mean"] / d["leaves"], d["rle"], d["raw"]))
    print("json %.1f KB (box %.1f KB, pvs %.1f KB)"
          % (len(to_json(d)) / 1024.0, len(d["box"]) / 1024.0,
             len(d["pvs"]) / 1024.0))
