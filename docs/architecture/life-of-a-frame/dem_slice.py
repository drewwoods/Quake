#!/usr/bin/env python3
"""Dissect one frame of demo1.dem into labelled protocol fields.

The client's view of a frame arrives as one network message: a flat byte
stream of svc_* commands. This walks that stream the way CL_ParseServerMessage
does and records where each field starts and how long it is, so the guide can
show the bytes with the protocol laid over them.

Correctness check: a correct walk consumes the message exactly. Any error in
the field table desyncs and either overruns the message or leaves a tail, and
both are refused rather than rendered.

Demo container (WinQuake/cl_demo.c:118-136):
    ascii cd-track digits, newline
    repeated: [int32 length][float32 viewangles x3][length bytes of message]
"""

import json
import struct

import bsp_slice

DEMO = "demo1.dem"
BLOCK_HEADER = 16                       # int32 length + 3 float32 viewangles

# WinQuake/protocol.h:83-117. Value -> (name, fixed payload size or None).
# None means the length depends on the payload and needs its own reader.
SVC = {
    0: ("svc_bad", 0), 1: ("svc_nop", 0), 2: ("svc_disconnect", 0),
    3: ("svc_updatestat", 5), 4: ("svc_version", 4), 5: ("svc_setview", 2),
    6: ("svc_sound", None), 7: ("svc_time", 4), 8: ("svc_print", None),
    9: ("svc_stufftext", None), 10: ("svc_setangle", 3), 11: ("svc_serverinfo", None),
    12: ("svc_lightstyle", None), 13: ("svc_updatename", None),
    14: ("svc_updatefrags", 3), 15: ("svc_clientdata", None),
    16: ("svc_stopsound", 2), 17: ("svc_updatecolors", 2), 18: ("svc_particle", None),
    19: ("svc_damage", 5), 20: ("svc_spawnstatic", None), 22: ("svc_spawnbaseline", None),
    23: ("svc_temp_entity", None), 24: ("svc_setpause", 1), 25: ("svc_signonnum", 1),
    26: ("svc_centerprint", None), 27: ("svc_killedmonster", 0),
    28: ("svc_foundsecret", 0), 29: ("svc_spawnstaticsound", 9),
    30: ("svc_intermission", None), 31: ("svc_finale", None),
    32: ("svc_cdtrack", 2), 33: ("svc_sellscreen", 0), 34: ("svc_cutscene", None),
}

# Entity delta bits, WinQuake/protocol.h:25-41.
U_MOREBITS, U_ORIGIN1, U_ORIGIN2, U_ORIGIN3 = 1 << 0, 1 << 1, 1 << 2, 1 << 3
U_ANGLE2, U_NOLERP, U_FRAME, U_SIGNAL = 1 << 4, 1 << 5, 1 << 6, 1 << 7
U_ANGLE1, U_ANGLE3, U_MODEL = 1 << 8, 1 << 9, 1 << 10
U_COLORMAP, U_SKIN, U_EFFECTS, U_LONGENTITY = 1 << 11, 1 << 12, 1 << 13, 1 << 14

# (mask, bytes, label) in CL_ParseUpdate read order: origin and angle interleave
# per axis, which is why this is a list and not a bit walk.
UPDATE_FIELDS = [
    (U_MODEL, 1, "model"), (U_FRAME, 1, "frame"), (U_COLORMAP, 1, "colormap"),
    (U_SKIN, 1, "skin"), (U_EFFECTS, 1, "effects"),
    (U_ORIGIN1, 2, "origin x"), (U_ANGLE1, 1, "angle x"),
    (U_ORIGIN2, 2, "origin y"), (U_ANGLE2, 1, "angle y"),
    (U_ORIGIN3, 2, "origin z"), (U_ANGLE3, 1, "angle z"),
]

# svc_clientdata bits, WinQuake/protocol.h:44-58.
SU_VIEWHEIGHT, SU_IDEALPITCH = 1 << 0, 1 << 1
SU_WEAPONFRAME, SU_ARMOR, SU_WEAPON = 1 << 12, 1 << 13, 1 << 14


class Desync(Exception):
    """The field table disagrees with the bytes; refuse rather than guess."""


class Reader(object):
    def __init__(self, buf):
        self.buf, self.pos = buf, 0

    def take(self, n):
        if n < 0 or self.pos + n > len(self.buf):
            raise Desync("read %d at %d of %d" % (n, self.pos, len(self.buf)))
        self.pos += n
        return self.buf[self.pos - n:self.pos]

    def u8(self):
        return self.take(1)[0]

    def u16(self):
        return struct.unpack("<H", self.take(2))[0]

    def string(self):
        """Null-terminated; the terminator is part of the field."""
        end = self.buf.find(b"\0", self.pos)
        if end < 0:
            raise Desync("unterminated string at %d" % self.pos)
        return self.take(end - self.pos + 1)


def _clientdata(r):
    """A bitmask, then only the fields it names, then the always-sent tail."""
    bits = r.u16()
    for mask in (SU_VIEWHEIGHT, SU_IDEALPITCH):
        if bits & mask:
            r.u8()
    for axis in range(3):                       # punch and velocity interleave
        if bits & (1 << (2 + axis)):
            r.u8()
        if bits & (1 << (5 + axis)):
            r.u8()
    r.take(4)                                   # items, always sent
    for mask in (SU_WEAPONFRAME, SU_ARMOR, SU_WEAPON):
        if bits & mask:
            r.u8()
    r.take(2)                                   # health
    r.take(1)                                   # ammo
    r.take(4)                                   # shells, nails, rockets, cells
    r.take(1)                                   # active weapon


# WinQuake/protocol.h:146-166. Payload after the type byte: the beam types
# carry an entity and two points; a colour-mapped explosion adds two bytes;
# everything else is a single point.
TE_BEAMS = (5, 6, 9, 13)
TE_EXPLOSION2 = 12


def _temp_entity(r):
    kind = r.u8()
    if kind in TE_BEAMS:
        r.take(2 + 12)                          # entity short, start and end
    elif kind == TE_EXPLOSION2:
        r.take(6 + 2)                           # point, colour start and length
    else:
        r.take(6)                               # a single point


def _particle(r):
    """WinQuake/r_part.c R_ParseParticleEffect: point, direction, count, colour."""
    r.take(6 + 3 + 1 + 1)


def _sound(r):
    mask = r.u8()
    if mask & 1:
        r.u8()                                  # volume
    if mask & 2:
        r.u8()                                  # attenuation
    r.take(2)                                   # channel
    r.u8()                                      # sound number
    r.take(6)                                   # origin, three coords


VARIABLE = {
    8: lambda r: r.string(), 9: lambda r: r.string(),
    12: lambda r: (r.u8(), r.string()), 13: lambda r: (r.u8(), r.string()),
    26: lambda r: r.string(), 30: lambda r: r.string(),
    15: _clientdata, 6: _sound, 18: _particle, 23: _temp_entity,
}


def dissect(msg):
    """Walk one message; return the field spans, or raise Desync."""
    r, spans = Reader(msg), []

    def span(start, kind, label, detail=""):
        spans.append({"at": start, "len": r.pos - start, "kind": kind,
                      "label": label, "detail": detail})

    while r.pos < len(msg):
        start = r.pos
        cmd = r.u8()

        if cmd & 128:                           # fast entity update
            bits = cmd & 127
            if bits & U_MOREBITS:
                bits |= r.u8() << 8
            span(start, "cmd", "entity update", "delta bits 0x%03x" % bits)
            head = r.pos
            num = r.u16() if bits & U_LONGENTITY else r.u8()
            span(head, "entnum", "entity %d" % num,
                 "%s index" % ("short" if bits & U_LONGENTITY else "byte"))
            for mask, size, label in UPDATE_FIELDS:
                if not bits & mask:
                    continue
                at = r.pos
                r.take(size)
                span(at, "field", label, "carried because its bit is set")
            continue

        if cmd not in SVC:
            raise Desync("unknown command %d at %d" % (cmd, start))
        name, size = SVC[cmd]
        # The id byte and its payload are different things and the figure
        # colours them differently, so they are separate spans.
        span(start, "svc", name, "message id, one byte")
        body = r.pos
        if size is None:
            if cmd not in VARIABLE:
                raise Desync("no reader for %s" % name)
            VARIABLE[cmd](r)
        else:
            r.take(size)
        if r.pos > body:
            spans.append({"at": body, "len": r.pos - body, "kind": "field",
                          "label": name + " payload",
                          "detail": "%d byte%s" % (r.pos - body,
                                                   "" if r.pos - body == 1 else "s")})

    if r.pos != len(msg):
        raise Desync("tail of %d bytes" % (len(msg) - r.pos))
    return spans


def blocks(demo):
    """Yield each message in the demo container."""
    nl = demo.find(b"\n")
    if nl < 0:
        raise Desync("no cd-track header")
    pos = nl + 1
    while pos + BLOCK_HEADER <= len(demo):
        size = struct.unpack_from("<i", demo, pos)[0]
        body = pos + BLOCK_HEADER
        if size < 0 or body + size > len(demo):
            return
        yield demo[body:body + size]
        pos = body + size


def frame_slice(pak_path, demo_name=DEMO, min_updates=6, max_bytes=320):
    """Pick one ordinary in-game frame and dissect it.

    Wanted: small enough to show byte by byte, and carrying a server timestamp,
    the player's own state and several entity updates — the shape of a normal
    frame rather than the signon burst at the start of the demo.
    """
    demo = bsp_slice.pak_extract(pak_path, demo_name)
    if demo is None:
        return None
    scanned = 0
    for msg in blocks(demo):
        scanned += 1
        if not msg or len(msg) > max_bytes:
            continue
        try:
            spans = dissect(msg)
        except Desync:
            continue
        names = [s["label"] for s in spans]
        updates = sum(1 for n in names if n == "entity update")
        if updates < min_updates or "svc_time" not in names:
            continue
        return {"demo": demo_name, "frame": scanned, "size": len(msg),
                "bytes": list(msg), "spans": spans, "updates": updates}
    return None


def to_json(data):
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


if __name__ == "__main__":
    import sys
    d = frame_slice(sys.argv[1] if len(sys.argv) > 1 else "id1/pak0.pak")
    if not d:
        print("no suitable frame found")
        raise SystemExit(1)
    print("frame %d, %d bytes, %d entity updates, %d spans"
          % (d["frame"], d["size"], d["updates"], len(d["spans"])))
    for s in d["spans"]:
        print("  %4d +%-2d %-8s %-16s %s"
              % (s["at"], s["len"], s["kind"], s["label"], s["detail"]))
