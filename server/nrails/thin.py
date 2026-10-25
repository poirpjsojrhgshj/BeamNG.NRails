"""NRails: thin slab decks over the railway (the user's run, 2026-10-25, a test town: "pont trop bas ... la route
passe bien au-dessus du renfort en beton qui est tres epais. desepaissis le renfort / autre variante de ponts pour
petits ponts").

Upstream's road bridges are a 1.2 m slab on 1 m girders (roadmesh.DECK_DEPTH + GIRDER_D): 2.2 m under the road. Over a
railway nrails.decks asks the deck for RAIL_FREE_M of free height, but a short bridge between two abutments at the
ground's level cannot climb that high (roads.DECK_MAX_GRADE): south of a test town the girders hung 3.9 m over the
rails, in the trains' way. The short bridges over French lines are mostly slab bridges (SNCF / SETRA PSI-DA: a
solid slab of span / 25 or so, no beams under it). Here a deck chunk whose girders would leave less than
RAIL_FREE_M + SPARE_M over a track within REACH_M of it is drawn as such a slab: THIN_M thick, no girders (the hook in
roadmesh.deck reads the chunk's "thin"), and the piers under it reach up to its underside.
"""
import numpy as np

THIN_M = 0.6                # m of slab under the road (a PSI-DA of 15 m span)
REACH_M = 6.0               # m from the deck's edge a track counts as under it
SPARE_M = 0.5               # m of free height over RAIL_FREE_M a deck must keep for its girders to stay


def mark(chunks, lines):
    """Sets c["thin"] = THIN_M on the deck chunks of chunks over a track of lines [(k, (n, 3) rail tops)] with too
    little free height for upstream's girders. Returns how many."""
    import roadmesh
    from nrails import decks
    if not lines:
        return 0
    under = roadmesh.DECK_DEPTH + roadmesh.GIRDER_D
    need = decks.RAIL_FREE_M + SPARE_M
    rails_xyz = np.concatenate([np.asarray(p, np.float64) for _k, p in lines if len(p)])
    if not len(rails_xyz):
        return 0
    lo, hi = rails_xyz[:, :2].min(0), rails_xyz[:, :2].max(0)
    n = 0
    for c in chunks:
        if not c.get("deck") or c.get("tunnel") or not c.get("fixed") or c.get("thin"):
            continue
        p = np.asarray(c["n"], np.float64)
        if len(p) < 2 or p.shape[1] < 3:
            continue
        r = float(c.get("w", 0.0)) / 2 + REACH_M
        if ((p[:, :2].min(0) - r > hi) | (p[:, :2].max(0) + r < lo)).any():
            continue
        near = rails_xyz[(rails_xyz[:, 0] > p[:, 0].min() - r) & (rails_xyz[:, 0] < p[:, 0].max() + r)
                         & (rails_xyz[:, 1] > p[:, 1].min() - r) & (rails_xyz[:, 1] < p[:, 1].max() + r)]
        if not len(near):
            continue
        zd = _deck_z_at(p, near[:, :2], r)
        ok = np.isfinite(zd)
        if ok.any() and ((zd[ok] - under - near[ok, 2]) < need).any() and ((zd[ok] - near[ok, 2]) > 2.0).any():
            c["thin"] = THIN_M
            n += 1
    return n


def _deck_z_at(p, q, r):
    """The deck line p (k, 3)'s height at its point nearest each q (m, 2), nan where none is within r."""
    a, b = p[:-1, :2], p[1:, :2]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    t = np.clip((((q[:, None, :] - a[None]) * ab[None]).sum(2)) / L2[None], 0.0, 1.0)
    foot = a[None] + t[..., None] * ab[None]
    d = np.hypot(*(foot - q[:, None, :]).transpose(2, 0, 1))
    j = np.argmin(d, 1)
    i = np.arange(len(q))
    z = p[j, 2] + t[i, j] * (p[j + 1, 2] - p[j, 2])
    return np.where(d[i, j] <= r, z, np.nan)


def raise_piers(piers, chunks):
    """The piers with their tops up to the underside of a thin chunk over them (the girders they stood under gone)."""
    import roadmesh
    thin = [(np.asarray(c["n"], np.float64), float(c.get("w", 0.0)) / 2 + roadmesh.PARAPET_W, c["thin"])
            for c in chunks if c.get("thin")]
    if not thin or not piers:
        return list(piers)
    drop = roadmesh.DECK_DEPTH + roadmesh.GIRDER_D
    out = []
    for p in piers:
        p = tuple(p)
        x, y, zt = p[0], p[1], p[4]
        for line, hw, th in thin:
            d = np.hypot(line[:, 0] - x, line[:, 1] - y)
            k = int(np.argmin(d))
            if d[k] < hw + 2.0 and abs(line[k, 2] - drop - zt) < 1.0:
                p = p[:4] + (zt + drop - th,) + p[5:]
                break
        out.append(p)
    return out
