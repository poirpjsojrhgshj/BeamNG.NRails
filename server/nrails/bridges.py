"""EarthNRails: approach slabs (French "dalles de transition") past the road bridges' abutments.

A deck's abutment end sits at the ground's height there, but the physics ground is the terrain block's grid (2 m
posts): the post nearest an abutment often stands down the embankment, and the ground dipped up to 0.75 m in the last
2 m before the deck (a motorway bridge over the railway at a test town, tools/audit_road_joints.py, 2026-10-24): a slot the
wheels drop into and a vertical face they hit (punctured tyres). Each abutment end of a deck goes on as a colliding
concrete slab along the road: flat for FLAT_M (it bridges the grid's dip), then sinking SINK_M under the deck end's
height over RAMP_M (buried in the road's ground; where the ground lies lower, the wheels roll down its slope).

The slabs are made from the tile's deck context (roads.build_tile's deck_context: every deck part within
roads.DECK_CONTEXT_M of the tile), as a mesh added to the tile's deck mesh (roadmesh.deck with "tunnel" chunks: the
slab alone, no parapet, no girders, no asphalt). BNE_APPROACH_SLAB=off turns them off.
"""
import os

import numpy as np

ON = os.environ.get("BNE_APPROACH_SLAB", "on") != "off"
FLAT_M = 5.0
RAMP_M = 5.0
SINK_M = 0.35
JOIN_M = 0.75           # m: a deck end this close to another deck part (its end or its line) is a joint, not an abutment
EDGE_M = 0.5            # m: an end this close to the context box's edge was cut there (the part goes on)


def _seg_dist(line, p):
    a, b = line[:-1, :2], line[1:, :2]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    t = np.clip(((p[:2] - a) * ab).sum(1) / L2, 0.0, 1.0)
    return float(np.hypot(*(a + t[:, None] * ab - p[:2]).T).min())


def abutment_slabs(lines, box=None):
    """[(index into lines, slab points (3, 3))] for the deck lines [(pts (k, 3), width)]: past each end that no other
    line comes within JOIN_M of and that is not on box's edge (x0, y0, x1, y1: where the lines were cut). The slab's
    points run from the deck end outwards: the end, FLAT_M on (same height), FLAT_M + RAMP_M on (SINK_M lower). Pure."""
    if not ON:
        return []
    L = [np.asarray(p, np.float64) for p, _w in lines]
    out = []
    for i, pts in enumerate(L):
        if len(pts) < 2:
            continue
        for e in (0, 1):
            q = pts[0] if e == 0 else pts[-1]
            if box is not None:
                x0, y0, x1, y1 = box
                if min(q[0] - x0, x1 - q[0], q[1] - y0, y1 - q[1]) < EDGE_M:
                    continue
            if any(j != i and len(o) >= 2 and _seg_dist(o, q) < JOIN_M for j, o in enumerate(L)):
                continue
            a, b = (pts[1], pts[0]) if e == 0 else (pts[-2], pts[-1])
            d = (b - a)[:2]
            n = float(np.hypot(*d))
            if n < 1e-6:
                continue
            d /= n
            s = np.array([0.0, FLAT_M, FLAT_M + RAMP_M])
            out.append((i, np.c_[b[0] + d[0] * s, b[1] + d[1] * s, b[2] - np.array([0.0, 0.0, SINK_M])]))
    return out


def slab_chunks(ctx, exact, wide):
    """The approach slabs' chunks (roads chunk dicts, "fixed", "deck", "tunnel": roadmesh.deck makes the slab alone)
    of the deck context chunks ctx, clipped to the tile box exact. wide: the box ctx was cut to."""
    import roads
    lines = [(np.asarray(c["n"], np.float64), float(c.get("w", 7.0))) for c in ctx
             if c.get("deck") and not c.get("tunnel") and len(c.get("n", ())) >= 2]
    out = []
    for i, slab in abutment_slabs(lines, wide):
        for piece in roads.clip_polyline(slab, *exact):
            for c in roads.split(roads.densify(piece)):
                if len(c) >= 2:
                    ch = roads._chunk(roads.DECK, lines[i][1], c)
                    ch.update(fixed=True, deck=True, tunnel=True, nrails_slab=True)
                    out.append(ch)
    return out


def merge_meshes(a, b):
    """roadmesh.deck-style meshes (P, T, UV, mats, M) merged into one (either may be None)."""
    if a is None:
        return b
    if b is None:
        return a
    P1, T1, UV1, m1, M1 = a
    P2, T2, UV2, m2, M2 = b
    mats = list(m1)
    remap = []
    for m in m2:
        if m not in mats:
            mats.append(m)
        remap.append(mats.index(m))
    return (np.concatenate([P1, P2]), np.concatenate([T1, np.asarray(T2) + len(P1)]), np.concatenate([UV1, UV2]),
            mats, np.concatenate([M1, np.asarray(remap)[np.asarray(M2, int)]]))


def with_slabs(dmesh, ctx, tx, ty):
    """The tile's deck mesh dmesh (roadmesh.deck's, or None) with its approach slabs added."""
    if not ON or not ctx:
        return dmesh
    import roadmesh
    import roads
    x0, y0, x1, y1 = roads.tile_bbox(tx, ty)
    m = roads.DECK_CONTEXT_M
    sc = slab_chunks(ctx, (x0, y0, x1, y1), (x0 - m, y0 - m, x1 + m, y1 + m))
    if not sc:
        return dmesh
    return merge_meshes(dmesh, roadmesh.deck(sc, (x0, y0, 0.0)))
