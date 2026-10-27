"""NRails: physically drivable railway track for a road tile (TILE x TILE m of the anchor frame).

Overture / OpenStreetMap rail segments (layer "roads", subtype "rail") become, per road tile:

  rail_<a>_<tx>_<ty>.cdae     render-only: UIC rails (real profile), concrete sleepers, ballast, bridge slabs,
                              the outer slabs and ramps of level crossings
  railcol_<a>_<tx>_<ty>.cdae  collision-only ("Colmesh"): one box per rail, as wide as the rail head and RAIL_COL_DEPTH
                              deep (the MRK track kit's 100 x 356 mm boxes, here at the real head width), the outer
                              crossing slabs and ramps
  railx_<a>_<tx>_<ty>.cdae    the inner slabs of level crossings (between the rails, 45 mm flangeways): drawn always,
                              colliding only while no rail vehicle is near (roads.lua M.updateRailCrossings)

Why the inner slab toggles: the rail mods' wheelsets (WLD FS30-2, TEM2, the tanker; tools/train_envelope.py) are a tread
cylinder (1.50-1.53 m) riding on the rail heads plus a "flange disc" cylinder (r 0.60-0.68, 1.37 m wide) that fills the
whole space between the rails 155-180 mm under the rail top: anything solid between the rails above
rail top - CLEAR_UNDER_M stops the train. Hence also: sleepers and ballast never collide, the track always stands at
least MIN_CLEAR_M over the physics ground, and where two tracks meet (turnouts, diamonds) a rail's collision is left out
where it runs inside another track's gauge (a simplified frog: both tracks keep their flange guidance).

Vertical profile (EN 13803 in spirit): the ground under the track (max of three samples across it) is lifted to its
upper envelope over ENVELOPE_M, smoothed (SIGMA_M) and raised FORMATION_M; bridge ranges (Overture level_rules /
road_flags, roads.level_ranges) are straight between their ends; tunnel ranges and class "subway" are left out (no
tube yet). Horizontal: the mapped polyline's corners rounded (Chaikin) before resampling every STEP_M. The ends of a
segment are pinned to a height computed from that point alone (ground in a disc), so segments meeting at a node agree.

Trams ("tram"): street track, flush with the road (grooved rail heads only, render-only, no collision: cars keep
driving over them).

Settings (environment, set by the NRails Hub): BNGE_RAILS on|off, BNGE_RAIL_PROFILE uic60|uic54|uic50|jis60,
BNGE_RAIL_TRAMS on|off, BNGE_RAIL_CROSSINGS on|off. Pure but for elev (numpy only).
"""
import logging
import math
import os

import numpy as np

GAUGE_M = 1.435             # standard gauge, between the inner faces of the rail heads
# (height H, head width C, foot width B, web thickness t), m: EN 13674-1 / JIS E 1101
PROFILES = {
    "uic60": (0.172, 0.072, 0.150, 0.0165),
    "uic54": (0.159, 0.070, 0.140, 0.016),
    "uic50": (0.152, 0.070, 0.125, 0.015),
    "jis60": (0.174, 0.065, 0.145, 0.0165),
}
# (not "unknown": Overture's class of OSM's railway=abandoned / disused, the trackbeds of lines long gone: the TEB's
# by a test city laid a track through streets, 2026-10-25, 39 of 39 "unknown" round a test city; narrow_gauge: Japan's JR,
# the Swiss and Corsican lines; BNGE_RAIL_UNKNOWN=on: "unknown" too)
HEAVY_CLASSES = {"standard_gauge", "light_rail", "narrow_gauge"} | (
    {"unknown"} if os.environ.get("BNGE_RAIL_UNKNOWN", "off").strip().lower() in ("on", "1", "true", "yes") else set())
TRAM_CLASSES = {"tram"}
STEP_M = 2.0                # m between profile samples along a track
CHAIKIN_ITER = 3            # corner rounding passes on the mapped polyline
NEAR_M = 500.0              # a track is profiled this far around the tile, not along all of its mapped segment: more
                            # than every reach of one sample's height (GRADE_REACH_M + the smoothing, the pins' and the
                            # side-by-side easing), so every tile computes the same heights where they meet (200 m
                            # left 0.2-6 m steps where a grade cap's ramp or a node reached past it, 2026-10-25)
BRIDGE_SPAN_MAX_M = 1500.0  # ... but a bridge reaching into that window whole, up to this long
# Tunnels (Overture level_rules / road_flags is_tunnel): the track runs on through them, straight in profile from portal
# to portal (the linear grade between the two portals' heights, along the whole chain of mapped segments the tunnel is
# made of), in a concrete tube (roadmesh.tunnel's: walls, vault, lamps, portal faces; "nrailtun", drawn and colliding),
# the terrain cut at the portals (terrain_holes: the block's holes, as upstream cuts its road tunnels'). Every window
# that reaches a tunnel holds all of its chain and TUNNEL_PORTAL_REACH_M of track past each portal, so every tile and
# terrain block computes the same heights in it.
TUNNEL_SPAN_MAX_M = 60000.0     # a tunnel chain longer than this is cut at the window (its profile then per window):
#                                 the longest (Gotthard 57 km, Seikan 54 km, the Channel Tunnel 50 km) whole
TUNNEL_PORTAL_REACH_M = 300.0   # m of track profiled past a portal (the portal's height: smoothing and pins)
TUNNEL_FLOOR_M = 0.55           # m the tube's floor lies under the rail top (the ballast's foot)
TUNNEL_TRACK_W = 4.0            # m of tube floor per track between the shoulders (roadmesh.TUNNEL_SHOULDER each side)
TUNNEL_H = 7.0                  # m from the floor to the vault's top (a single track's tube, catenary room)
TUNNEL_TWIN_M = 7.5             # tracks in tunnels this close (centre to centre): one tube round both
TUNNEL_COVER_M = 15.0           # m under the ground a tunnel lies with no portal known (a chain cut by its window)
TUNNEL_HOLE_MARGIN_M = 0.5      # m around the tube a portal's terrain hole reaches (roads.TUNNEL_HOLE_MARGIN)
PORTAL_UP_READ_M = 16.0         # m into the hill the ground read for a portal face's height (the mouth's cut)
OVERLAP_M = 2.0             # m a track reaches past its tile's edge (roads.OVERLAP)
SIDE_SAMPLE_M = 1.6         # ground also read this far either side of the centre line
ENVELOPE_M = 8.0            # m either side over which the ground's upper envelope is taken
ROBUST_M = 16.0             # m either side of the median taken first (the bumps it drops: _base)
SIGMA_M = 24.0              # m, Gaussian smoothing of the track's level
FORMATION_M = 0.50          # m the rail top stands over the smoothed envelope (ballast + sleeper + rail)
MIN_CLEAR_M = 0.32          # m the rail top stands over the physics ground at least (flange disc 0.18 + margin)
LIFT_SIGMA_M = 8.0          # m: a shortfall of that clearance is lifted out as a hump this smooth
PIN_R_M = 6.0               # m: (pin_height, a lone point's height) reads the ground in this disc
PIN_BLEND_M = 60.0          # m over which a node's height eases into a track's profile
PIN_BLEND_MAX_M = 100.0     # ... up to this for a large lift (its grade), inside the windows' NEAR_M
NODE_TOL_M = 1.0            # m: a segment end this close to another track meets it (a node, a turnout's branch)
MAX_GRADE_PERMILLE = (5.0, 35.0, 80.0)  # min, default, max of BNGE_RAIL_MAX_GRADE (per mille: the Hub's setting)


def max_grade():
    """A track's grade at most (BNGE_RAIL_MAX_GRADE per mille, default 35: EN 13803 / high-speed lines; a classic
    main line 12.5-25, a mountain line up to ~60, Swiss metre gauge with no rack ~70). Steeper ground is crossed on
    an embankment (grade_cap raises the track, never lowers it into the ground)."""
    lo, dflt, hi = MAX_GRADE_PERMILLE
    try:
        v = float(os.environ.get("BNGE_RAIL_MAX_GRADE", dflt))
    except ValueError:
        v = dflt
    return float(min(max(v, lo), hi)) / 1000.0


MAX_GRADE = max_grade()
GRADE_SIGMA_M = 8.0         # m: the smoothing of grade_cap's corners
GRADE_REACH_M = 360.0       # m: the open track's grade cap reaches this far round a high point (a road tile's window
#                             holds NEAR_M round it: the same embankment in every tile that draws it)
RAIL_COL_DEPTH = 0.36       # m the collision box of a rail reaches under the rail top (MRK: 0.356)
CLEAR_UNDER_M = 0.21        # m under the rail top kept free between the rails (MRK ballast: 0.209)
SLEEPER_EVERY_M = 0.60
SLEEPER = (2.60, 0.28, 0.20)    # length across, width along, height (m): a B70-type concrete sleeper
PAD_M = 0.008               # rail pad between the rail foot and the sleeper
BALLAST_TOP_M = 0.20        # m under the rail top: the ballast's crest (drawn)
# The ballast also collides (railcol): a lean copy of its section, its crest BALLAST_COL_TOP_M under the rail top, below
# CLEAR_UNDER_M (the flange discs reach 0.155-0.18 m down between the rails): cars and hi-rail trucks can drive up onto
# the track bed and over it, a train's discs still run free. The sleepers stay render-only (their tops, 0.18 m under the
# rail top, would catch the discs).
BALLAST_COL_TOP_M = 0.23
BALLAST_HALF_M = 1.60       # half-width of the ballast's top
BALLAST_SLOPE = 1.5         # horizontal per vertical of its sides ...
BALLAST_DEPTH_M = 0.90      # ... down to this far under its crest (the terrain hides the rest)
BRIDGE_SLAB = (2.30, 0.90)  # half-width, depth under the ballast crest of a bridge's concrete slab
FROG_MARGIN_M = 0.03        # a rail's collision is dropped where it is closer than gauge/2 - this to another track
X_FLANGEWAY_M = 0.045       # level crossing: groove left inside each rail for the wheel flanges
X_OUTER_M = 0.90            # flat slab outside each rail ...
X_RAMP_M = 3.0              # ... then a ramp down to the road, this long at least ...
X_RAMP_GRADE = 0.10         # ... and no steeper than this ...
X_RAMP_MAX_M = 15.0         # ... up to this long
X_SLAB_DEPTH_M = 0.25
X_END_M = 1.0               # m the slabs reach along the track past the road's edges
X_HALF_MAX_M = 18.0
# Level crossing height: the track eases down (or up) to the road there, its rail top X_RISE_M over the road's surface
# (the slabs at rail top, the ground under the gauge 0.25 m lower: the flange discs reach 0.155-0.18 m down), flat over
# the platform, over X_PIN_BLEND_M either side (a cosine ease: no kink). Before, the track kept its own level (0.3-0.6 m
# over the road) and each track got its own ramps: across the four tracks by a test town station a car met four humps
# with ramps between them and got caught (the user, 2026-10-24).
X_RISE_M = 0.25
X_PIN_BLEND_M = 40.0
X_CLUSTER_M = 12.0          # crossings of one road by parallel tracks this close: one platform over them all
TRAM_LIFT_M = 0.012         # a tram rail head over the street
MAX_MESH_VERTS = 60000      # per shape: the engine's 16-bit indices (buildings.MAX_MESH_VERTS)
PARTS_MAX = 4               # shapes per kind and tile: "nrail", "nrail2".."nrail4" (the mod's lists)
SW_SHAPES_MAX = 160         # turnout routes' shapes per tile: "nrailsw1".."nrailsw160" (nrails.switches, the mod's list)
# Contact (the user, 2026-10-27, a big station's throat: "toutes les autres voies qui ne sont pas dans l'itineraire et
# qui rentrent en contact avec notre voie, leurs collisions sont desactivees ... les bogies restent colles sur la meme
# voie"): outside the turnouts' zones, a track's rails within CONTACT_M of another track's centre line (two tracks
# converging, crossing at a shallow angle, mapped too close: within reach of a bogie, a snowplow, a guided wheel) go
# into a collision shape of their own per track, "nrailct1".."nrailct<CT_SHAPES_MAX>": the mod makes it non-solid
# while a rail vehicle runs on another track there and none on this one (nrails.lua M.updateContacts). Its row
# ("railc") carries the track's centre line round the contact (CT_LINE_M either side) for the mod to tell which
# track a vehicle is on.
CONTACT_M = 2.2
CT_SHAPES_MAX = 64
CT_LINE_M = 80.0

MAT_STEEL, MAT_SLEEPER, MAT_BALLAST, MAT_CONCRETE, MAT_TRAM = range(5)
# (bne_nrail_*: BeamNG.Earth 1.6.3 defines bne_rail_* materials of its own, tunnel.materials.json)
MATERIALS = ["bne_nrail_steel", "bne_nrail_sleeper", "bne_nrail_ballast", "bne_bridge_concrete", "bne_nrail_steel"]


_LOGGED = set()


def _log_once(what):
    """A warning logged once per process for each kind of failure (a part of a tile left out, the rest built)."""
    if what not in _LOGGED:
        _LOGGED.add(what)
        logging.getLogger("earthd.nrails").warning("NRails %s", what[:240])


def _on(name, default="on"):
    return os.environ.get(name, default).strip().lower() not in ("off", "0", "false", "no")


def enabled():
    return _on("BNGE_RAILS")


def profile():
    return PROFILES.get(os.environ.get("BNGE_RAIL_PROFILE", "uic60").strip().lower(), PROFILES["uic60"])


# --- geometry helpers ---------------------------------------------------------------------------------------------

def chaikin(xy, iterations=CHAIKIN_ITER):
    """Corner cutting (1/4, 3/4) keeping both ends: a polyline with rounded corners (k, 2). Pure."""
    p = np.asarray(xy, np.float64)
    for _ in range(iterations):
        if len(p) < 3:
            return p
        a, b = p[:-1], p[1:]
        q = np.empty((2 * len(a), 2))
        q[0::2] = 0.75 * a + 0.25 * b
        q[1::2] = 0.25 * a + 0.75 * b
        p = np.vstack([p[:1], q[1:-1], p[-1:]])
    return p


def resample(xy, step=STEP_M):
    """(points (n, 2) every ~step m, their arc length s (n,)). Pure."""
    xy = np.asarray(xy, np.float64)
    seg = np.hypot(*np.diff(xy, axis=0).T)
    s = np.r_[0.0, np.cumsum(seg)]
    L = float(s[-1])
    if L <= 1e-6:
        return xy[:1].copy(), np.zeros(1)
    n = max(2, int(math.ceil(L / step)) + 1)
    t = np.linspace(0.0, L, n)
    return np.c_[np.interp(t, s, xy[:, 0]), np.interp(t, s, xy[:, 1])], t


def gsmooth(v, sigma_samples):
    """Gaussian smoothing with edge padding. Pure."""
    v = np.asarray(v, np.float64)
    if sigma_samples <= 0.0 or len(v) < 3:
        return v.copy()
    r = max(1, int(3 * sigma_samples))
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma_samples) ** 2)
    k /= k.sum()
    return np.convolve(np.pad(v, r, mode="edge"), k, mode="valid")


def maxfilter(v, half):
    """Sliding maximum over +-half samples (edge padding). Pure."""
    v = np.asarray(v, np.float64)
    if half <= 0 or len(v) < 2:
        return v.copy()
    pad = np.pad(v, half, mode="edge")
    return np.lib.stride_tricks.sliding_window_view(pad, 2 * half + 1).max(axis=1)


def medfilter(v, half):
    """Sliding median over +-half samples (edge padding). Pure."""
    v = np.asarray(v, np.float64)
    if half <= 0 or len(v) < 2:
        return v.copy()
    pad = np.pad(v, half, mode="edge")
    return np.median(np.lib.stride_tricks.sliding_window_view(pad, 2 * half + 1), axis=1)


def normals(xy):
    """Unit left normals (n, 2) of a polyline from central differences. Pure."""
    d = np.gradient(np.asarray(xy, np.float64), axis=0) if len(xy) > 1 else np.array([[1.0, 0.0]])
    d /= np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None]
    return np.c_[-d[:, 1], d[:, 0]]


def _run_medfilter(v, keep, half):
    """v with each run of kept samples median-filtered over +-half samples of that run only (the window cut at the run's
    ends: a spike at an end is outvoted, not padded); the others as they were. Pure."""
    v = np.asarray(v, np.float64).copy()
    if half <= 0:
        return v
    for run in _runs(np.asarray(keep, bool)):
        lo, hi = int(run[0]), int(run[-1]) + 1
        if hi - lo < 2:
            continue
        r = v[lo:hi].copy()
        n = len(r)
        out = np.empty(n)
        if n > 2 * half:                            # the inside: the whole window
            out[half:n - half] = np.median(np.lib.stride_tricks.sliding_window_view(r, 2 * half + 1), axis=1)
        for i in [*range(min(half, n)), *range(max(half, n - half), n)]:      # the ends: the window cut
            out[i] = np.median(r[max(0, i - half):i + half + 1])
        v[lo:hi] = out
    return v


def _fill_masked(v, keep):
    """v with the samples not in keep replaced by linear interpolation of the kept ones. Pure."""
    v = np.asarray(v, np.float64).copy()
    idx = np.flatnonzero(keep)
    if len(idx) == 0 or len(idx) == len(v):
        return v
    v[~keep] = np.interp(np.flatnonzero(~keep), idx, v[idx])
    return v


BRIDGE_EDGE_M = 40.0        # m beyond a bridge's mapped end where the valley's slope may go on
BRIDGE_EDGE_DROP_M = 1.0    # m under the ground at that distance a sample there is taken for the valley


def bridge_edges(g, kind, s):
    """The samples in the open at a bridge's ends that are the valley's slopes, not the track's ground: from each end
    of a bridge run outward, those within BRIDGE_EDGE_M whose ground stands more than BRIDGE_EDGE_DROP_M under the
    highest ground between there and BRIDGE_EDGE_M (a bridge mapped shorter than its valley: by a village the LGV's
    viaduct ended 12 m before the valley's rim; the slope's low ground, smoothed into the track's level, dipped it
    and the lift over the rim made 0.7 m humps either side, 2026-10-25). Bool (k,). Pure."""
    out = np.zeros(len(g), bool)
    if not (kind == 1).any():
        return out
    for run in _runs(kind == 1):
        for end, step in ((int(run[0]), -1), (int(run[-1]), 1)):
            i = end + step
            idx = []
            while 0 <= i < len(g) and kind[i] == 0 and abs(s[i] - s[end]) <= BRIDGE_EDGE_M:
                idx.append(i)
                i += step
            if not idx:
                continue
            gi = g[idx]
            rim = np.maximum.accumulate(gi[::-1])[::-1]         # the highest ground from each sample outward
            low = gi < rim - BRIDGE_EDGE_DROP_M
            # (only those contiguous from the bridge's end: the slope, not a ditch further out)
            n = int(np.argmin(low)) if not low.all() else len(low)
            out[idx[:n]] = True
    return out


# --- the ground and the profile ----------------------------------------------------------------------------------

GROUND_CHUNK = 1500         # points per DEM read along a long track (Ground.z)
GROUND_SPAN_M = 4000.0      # ... when they spread over more than this


class Ground:
    """Ground heights in the frame's up (z) at frame (x, y) points, through elev(lat, lon) like roads.build_tile."""

    def __init__(self, frame, elev):
        self.frame, self.elev = frame, elev

    def z(self, x, y):
        x = np.asarray(x, np.float64).ravel()
        y = np.asarray(y, np.float64).ravel()
        # (points along a long track in runs of GROUND_CHUNK: the DEM reads the box round the points it is given, a
        # 50 km tunnel's box was a 112 MB mosaic, 2026-10-24; a track's samples come in order, so a run is local)
        if len(x) > GROUND_CHUNK and max(np.ptp(x), np.ptp(y)) > GROUND_SPAN_M:
            return np.concatenate([self.z(x[i:i + GROUND_CHUNK], y[i:i + GROUND_CHUNK])
                                   for i in range(0, len(x), GROUND_CHUNK)])
        la, lo, _ = self.frame.enu_to_geodetic(x, y, np.zeros_like(x))
        h = np.asarray(self.elev(np.asarray(la), np.asarray(lo)), np.float64)
        _, _, u = self.frame.geodetic_to_enu(np.asarray(la), np.asarray(lo), h)
        return np.asarray(u, np.float64)


def pin_height(ground, x, y):
    """Rail top height at a segment end from that point alone (both segments meeting there agree): the highest
    ground in a PIN_R_M disc + FORMATION_M. Pure given ground."""
    a = np.linspace(0.0, 2 * math.pi, 8, endpoint=False)
    px = np.r_[x, x + PIN_R_M * np.cos(a), x + 0.5 * PIN_R_M * np.cos(a + 0.4)]
    py = np.r_[y, y + PIN_R_M * np.sin(a), y + 0.5 * PIN_R_M * np.sin(a + 0.4)]
    return float(ground.z(px, py).max()) + FORMATION_M


def kinds_along(s, total, ranges):
    """Per sample: 0 ground, 1 bridge, 2 tunnel, from roads.level_ranges' (start, end, kind) fractions. Pure."""
    k = np.zeros(len(s), np.int8)
    if total <= 0:
        return k
    f = s / total
    for a, b, kind in ranges:
        sel = (f >= a) & (f <= b)
        k[sel] = 2 if kind == "tunnel" else 1
    return k


def _runs(mask):
    """Index arrays of the runs of True in a boolean array. Pure."""
    idx = np.flatnonzero(mask)
    if len(idx) == 0:
        return []
    return np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1)


class Piece:
    """A run of one mapped segment's samples inside the profiling window, through the two passes of the profile:
    xy (k, 2), s (k,) from its first sample, kind (0 ground, 1 bridge, 2 tunnel), first / last: its first / last sample
    is an end of the mapped segment (a node), else a cut at the window's edge; base: the rail-top heights before the
    ends are pinned (pass 1); g: the ground under it; clear: the clearance it needs over g."""
    __slots__ = ("fid", "xy", "s", "kind", "first", "last", "base", "g", "clear", "z", "s0", "gt", "bb")

    def __init__(self, fid, xy, s, kind, first, last, s0=0.0):
        self.fid, self.xy, self.s, self.kind, self.first, self.last = fid, xy, s, kind, first, last
        self.base = self.g = self.clear = self.z = None
        self.gt = None              # the ground over its tunnel samples (NaN elsewhere): the tunnels' cover
        self.s0 = s0                # its first sample's arc length along the mapped segment
        self.bb = None              # (_z_at: its box and longest step)


def _window(xy_raw, ranges, near, force=False):
    """(xy, s, kind, sel) of a mapped segment resampled every STEP_M (corners rounded): sel the samples to profile,
    in `near` plus a whole bridge reaching into it (up to BRIDGE_SPAN_MAX_M), a whole tunnel and TUNNEL_PORTAL_REACH_M
    past its portals (up to TUNNEL_SPAN_MAX_M; force: every tunnel of the segment, a chain reaching into the window),
    None if none. Pure."""
    xy_raw = np.asarray(xy_raw, np.float64)
    if len(xy_raw) < 2:
        return None
    raw_len = float(np.hypot(*np.diff(xy_raw, axis=0).T).sum())
    xy, s = resample(chaikin(xy_raw))
    if len(xy) < 2:
        return None
    kind = kinds_along(s * (raw_len / max(float(s[-1]), 1e-9)), raw_len, ranges)
    n = len(xy)
    if near is None:
        sel = np.ones(n, bool)
    else:
        x0, y0, x1, y1 = near
        sel = (xy[:, 0] >= x0) & (xy[:, 0] <= x1) & (xy[:, 1] >= y0) & (xy[:, 1] <= y1)
        if force:                               # (a tunnel chain reaching into the window: its tunnels whole)
            sel |= kind == 2
        if not sel.any():
            return None
        for run in _runs(kind == 1):            # a bridge is straight between its ends: both are needed
            lo, hi = max(run[0] - 1, 0), min(run[-1] + 2, n)
            if sel[lo:hi].any() and s[run[-1]] - s[run[0]] <= BRIDGE_SPAN_MAX_M:
                sel[lo:hi] = True
        for run in _runs(kind == 2):            # a tunnel too, and the track past its portals
            lo, hi = max(run[0] - 1, 0), min(run[-1] + 2, n)
            if sel[lo:hi].any() and s[run[-1]] - s[run[0]] <= TUNNEL_SPAN_MAX_M:
                sel |= (s >= s[run[0]] - TUNNEL_PORTAL_REACH_M) & (s <= s[run[-1]] + TUNNEL_PORTAL_REACH_M)
    return xy, s, kind, sel


def _base(ground, pc, pins, masks=()):
    """Pass 1 of a piece: its rail top without its ends pinned: the ground's upper envelope smoothed + FORMATION_M,
    bridges straight, eased to the level crossings (pins: (s, z, flat half length)), lifted where it would come
    closer to the ground than its clearance, and its grade capped at MAX_GRADE (only ever raised: an embankment, never
    into the ground). masks: (s0, s1) ranges where the ground is not the track's (a road crossing over or under it on
    a structure: its deck, its abutments' embankments, its cutting): the ground there taken as the straight line
    between the samples either side. Sets pc.base / g / clear."""
    xy, s, kind = pc.xy, pc.s, pc.kind
    nrm = normals(xy)
    on_ground = kind == 0
    struct = np.zeros(len(s), bool)
    for a, b in masks:
        struct |= (s >= a) & (s <= b)
    if not (kind != 2).any():                       # all in a tunnel: TUNNEL_COVER_M under the ground until the chain's
        g = ground.z(xy[:, 0], xy[:, 1])            # portals set it (_tunnel_chains)
        pc.base = gsmooth(g, SIGMA_M / STEP_M) - TUNNEL_COVER_M
        pc.g, pc.clear, pc.gt = g, np.zeros(len(g)), g
        return
    g = np.zeros(len(xy))
    read = kind != 2                                # (no ground read inside a tunnel: the mountain over it)
    pc.gt = np.full(len(xy), np.nan)
    if (~read).any():                               # (... but its cover, every 10th sample: _tunnel_cover)
        ti = np.flatnonzero(~read)
        ti = np.unique(np.r_[ti[::10], ti[-1]])
        pc.gt[ti] = ground.z(xy[ti, 0], xy[ti, 1])
    if read.any():
        px, py, pn = xy[read, 0], xy[read, 1], nrm[read]
        gx = np.concatenate([px, px + SIDE_SAMPLE_M * pn[:, 0], px - SIDE_SAMPLE_M * pn[:, 0]])
        gy = np.concatenate([py, py + SIDE_SAMPLE_M * pn[:, 1], py - SIDE_SAMPLE_M * pn[:, 1]])
        # (the middle of the three: a DSM's tree or a bridge's abutment beside the track is not its ground)
        g[read] = np.median(ground.z(gx, gy).reshape(3, int(read.sum())), axis=0)
    # (the fills below anchor on the samples next to a tunnel or a structure: each run of read ground median-filtered
    # on its own first, a cliff over a portal read by its first sample in the open is not the tunnel's level: on the
    # a main line by a village it raised one bore 13 m at its portal, the track 5 % down to the valley, 2026-10-25)
    g = _run_medfilter(g, read & ~struct, int(round(ROBUST_M / STEP_M)))
    g = _fill_masked(g, read & ~struct)             # (a structure crossing it: bridged over, as the track is there)
    edge = bridge_edges(g, kind, s)                 # (the valley's slopes past a bridge's mapped ends)
    g_fill = _fill_masked(g, on_ground & ~edge)     # a bridge's valley / a tunnel's mountain do not shape the track
    # the ground's level without its bumps shorter than 2 ROBUST_M (the elevation data's trees and houses, a road
    # bridge's deck and ramps past its mapped ends: under the road bridge at a village the track climbed 5 m onto
    # them, 2026-10-25), then its upper envelope; what stands over the track is cut away (nrails.corridor)
    g = medfilter(g, int(round(ROBUST_M / STEP_M)))
    env = maxfilter(medfilter(g_fill, int(round(ROBUST_M / STEP_M))), int(round(ENVELOPE_M / STEP_M)))
    z = gsmooth(env, SIGMA_M / STEP_M) + FORMATION_M
    z = _fill_masked(z, on_ground | (np.arange(len(z)) == 0) | (np.arange(len(z)) == len(z) - 1))
    clear = np.full(len(z), MIN_CLEAR_M)
    for sp, zp, flat in pins:                       # level crossings: eased to the road's height + X_RISE_M
        w = _ease(s - sp, flat, X_PIN_BLEND_M)
        z = z + w * (zp - z)
        clear = np.where(w > 0, np.minimum(clear, X_RISE_M), clear)
    short = np.where(on_ground & ~edge, np.maximum(0.0, g + clear - z), 0.0)
    if short.any():                                 # the shortfall lifted as a smooth hump, its peak kept
        sig = LIFT_SIGMA_M / STEP_M
        z = z + gsmooth(maxfilter(short, int(math.ceil(3 * sig))), sig)
    z = grade_cap(z, s, MAX_GRADE, GRADE_REACH_M)
    pc.base, pc.g, pc.clear = z, g, clear


def _tunnel_forced(segments, near):
    """The fids of the segments [(fid, xy ring, ranges)] whose tunnels must be profiled whole for window `near`: the
    segments of a tunnel chain (segments joined at ends that are both in a tunnel) one of whose tunnels reaches into
    the window. Pure."""
    if near is None:
        return set()
    info = []
    for fid, xy_raw, ranges in segments:
        if not any(k == "tunnel" for _a, _b, k in ranges):
            continue
        w = _window(xy_raw, ranges, None)
        if w is None:
            continue
        xy, s, kind, _ = w
        x0, y0, x1, y1 = near
        inside = (xy[:, 0] >= x0) & (xy[:, 0] <= x1) & (xy[:, 1] >= y0) & (xy[:, 1] <= y1)
        reach = False
        for run in _runs(kind == 2):
            ss = (s >= s[run[0]] - TUNNEL_PORTAL_REACH_M) & (s <= s[run[-1]] + TUNNEL_PORTAL_REACH_M)
            if (inside & ss).any():
                reach = True
        info.append((fid, xy[0] if kind[0] == 2 else None, xy[-1] if kind[-1] == 2 else None, reach))
    parent = {f: f for f, *_ in info}

    def root(f):
        while parent[f] != f:
            parent[f] = parent[parent[f]]
            f = parent[f]
        return f
    ends = [(f, p) for f, a, b, _r in info for p in (a, b) if p is not None]
    for i in range(len(ends)):
        for j in range(i + 1, len(ends)):
            if ends[i][0] != ends[j][0] and np.hypot(*(ends[i][1] - ends[j][1])) <= NODE_TOL_M:
                parent[root(ends[i][0])] = root(ends[j][0])
    hit = {root(f) for f, *_r, reach in info if reach}
    return {f for f, *_ in info if root(f) in hit}


def _tunnel_chains(pieces, ground=None):
    """The tunnels' profiles (pc.base, in place, pass 1): every run of tunnel samples of the pieces is an edge between
    its two ends; ends that meet (within NODE_TOL_M: a long tunnel mapped as several segments, a crossover, a branch)
    are one node; a portal (the track goes on in the open just outside) is a node fixed at the rail top there. The
    nodes' heights: linear along the edges between the portals (the harmonic solution, weights 1 / length: a chain of
    runs is one straight line from portal to portal; a network of bores and crossovers one consistent level, the
    same in every window that holds it), then the cover (_tunnel_cover); each run linear between its two nodes. A
    network with one portal stays at its level; with none, as _base made it. Pure but for setting pc.base."""
    runs = []
    for pc in pieces:
        for run in _runs(pc.kind == 2):
            lo, hi = int(run[0]), int(run[-1])
            n = len(pc.s)
            ends = []
            for i, out in ((lo, lo - 1), (hi, hi + 1)):
                if 0 <= out < n:                    # a portal: the track goes on in the open there
                    ends.append({"pt": pc.xy[i], "z": float(pc.base[out]), "s": float(pc.s[out])})
                else:                               # a segment end (or the window's): another run may go on
                    ends.append({"pt": pc.xy[i], "z": None, "s": float(pc.s[i])})
            runs.append({"pc": pc, "lo": lo, "hi": hi, "ends": ends,
                         "L": max(ends[1]["s"] - ends[0]["s"], 1e-3)})
    if not runs:
        return
    _open_meets(runs, pieces)
    runs = _split_runs(runs, pieces)
    # the nodes: each portal its own (fixed), the other ends merged within NODE_TOL_M (+ a sample: a branch's end on a
    # run's sample)
    nodes = []                                      # {"pt", "z" (fixed) or None}
    for r in runs:
        r["nodes"] = []
        for e in r["ends"]:
            k = None
            if e["z"] is None:
                for j, nd in enumerate(nodes):
                    if nd["z"] is None and float(np.hypot(*(nd["pt"] - e["pt"]))) <= NODE_TOL_M + STEP_M:
                        k = j
                        break
            if k is None:
                nodes.append({"pt": e["pt"], "z": e["z"]})
                k = len(nodes) - 1
            r["nodes"].append(k)
    nn = len(nodes)
    adj = [[] for _ in range(nn)]
    for ri, r in enumerate(runs):
        a, b = r["nodes"]
        if a != b:
            adj[a].append((b, r["L"], ri))
            adj[b].append((a, r["L"], ri))
    # components
    comp = [-1] * nn
    for i in range(nn):
        if comp[i] >= 0:
            continue
        stack, comp[i] = [i], i
        while stack:
            u = stack.pop()
            for v, _l, _r in adj[u]:
                if comp[v] < 0:
                    comp[v] = i
                    stack.append(v)
    z = np.full(nn, np.nan)
    for c in set(comp):
        members = [i for i in range(nn) if comp[i] == c]
        fixed = [i for i in members if nodes[i]["z"] is not None]
        if not fixed:
            continue                                # (no portal known: _base's level stays)
        for i in fixed:
            z[i] = nodes[i]["z"]
        free = [i for i in members if nodes[i]["z"] is None]
        if not free:
            continue
        idx = {u: k for k, u in enumerate(free)}
        M = np.zeros((len(free), len(free)))
        rhs = np.zeros(len(free))
        for u in free:
            for v, L, _r in adj[u]:
                w = 1.0 / L
                M[idx[u], idx[u]] += w
                if v in idx:
                    M[idx[u], idx[v]] -= w
                else:
                    rhs[idx[u]] += w * nodes[v]["z"]
        for u in free:                              # (a node with no edge: its neighbours' mean, nothing)
            if M[idx[u], idx[u]] == 0:
                M[idx[u], idx[u]] = 1.0
        try:
            sol = np.linalg.solve(M, rhs)
        except np.linalg.LinAlgError:
            sol = np.linalg.lstsq(M, rhs, rcond=None)[0]
        for u in free:
            z[u] = sol[idx[u]]
    _tunnel_cover(runs, nodes, adj, z)
    for r in runs:
        a, b = r["nodes"]
        if not (np.isfinite(z[a]) and np.isfinite(z[b])):
            continue
        pc, lo, hi = r["pc"], r["lo"], r["hi"]
        if r.get("prof") is not None:
            pc.base[lo:hi + 1] = r["prof"]
        else:
            t = (pc.s[lo:hi + 1] - r["ends"][0]["s"]) / r["L"]
            pc.base[lo:hi + 1] = z[a] + (z[b] - z[a]) * t


def _open_meets(runs, pieces):
    """A tunnel run's end (not a portal of its own) on another track in the open (a tunnel segment mapped from its
    portal on, joining the line outside; the Channel Tunnel's service tunnel at Folkestone): a portal there, at that
    track's level (in place). Pure but for the runs."""
    for r in runs:
        for e in r["ends"]:
            if e["z"] is not None:
                continue
            best = None
            for pc in pieces:
                if pc is r["pc"]:
                    continue
                xy = pc.xy
                if (e["pt"] < xy.min(0) - 3).any() or (e["pt"] > xy.max(0) + 3).any():
                    continue
                d = np.hypot(xy[:, 0] - e["pt"][0], xy[:, 1] - e["pt"][1])
                k = int(np.argmin(d))
                if d[k] <= NODE_TOL_M + STEP_M and pc.kind[k] != 2 and (best is None or d[k] < best[0]):
                    best = (float(d[k]), float(pc.base[k]))
            if best is not None:
                e["z"] = best[1]


def _split_runs(runs, pieces=()):
    """The tunnel runs cut where another run's end (not a portal) lies on them (a crossover or a branch leaving a bore
    in the tunnel: the Channel Tunnel's service tunnel and crossovers met the bores mid-run, were left out of their
    network at the level of the ground - 15 m, and the node lifted them 15 m over 100 m, 2026-10-25): each cut a node
    shared by both halves and the branch."""
    cuts = {i: {} for i in range(len(runs))}      # run -> {sample: fixed height or None}
    meets = [(e["pt"], None, a) for a, r in enumerate(runs) for e in r["ends"] if e["z"] is None]
    # (a track in the open ending on a tunnel run: a junction there, at that track's level)
    for pc in pieces:
        for e, flag in ((0, pc.first), (-1, pc.last)):
            if flag and pc.kind[e] != 2:
                meets.append((pc.xy[e], float(pc.base[e]), None))
    for pt, zfix, a in meets:
        for b, o in enumerate(runs):
            if b == a or o["hi"] - o["lo"] < 2:
                continue
            xy = o["pc"].xy[o["lo"]:o["hi"] + 1]
            lo_, hi_ = xy.min(0) - NODE_TOL_M - STEP_M, xy.max(0) + NODE_TOL_M + STEP_M
            if (pt < lo_).any() or (pt > hi_).any():
                continue
            d = np.hypot(xy[:, 0] - pt[0], xy[:, 1] - pt[1])
            k = int(np.argmin(d))
            if d[k] <= NODE_TOL_M + STEP_M and 0 < k < len(xy) - 1:
                old = cuts[b].get(o["lo"] + k)
                cuts[b][o["lo"] + k] = zfix if old is None else (old if zfix is None else max(old, zfix))
    out = []
    for i, r in enumerate(runs):
        if not cuts[i]:
            out.append(r)
            continue
        pc = r["pc"]
        marks = [r["lo"]] + sorted(cuts[i]) + [r["hi"]]
        for j, (a, b) in enumerate(zip(marks[:-1], marks[1:])):
            e0 = r["ends"][0] if j == 0 else {"pt": pc.xy[a], "z": cuts[i][a], "s": float(pc.s[a])}
            e1 = r["ends"][1] if j == len(marks) - 2 else {"pt": pc.xy[b], "z": cuts[i][b], "s": float(pc.s[b])}
            out.append({"pc": pc, "lo": a, "hi": b, "ends": [e0, e1], "L": max(e1["s"] - e0["s"], 1e-3)})
    return out


# A tunnel under a valley, an estuary, the sea (the Channel Tunnel, 2026-10-24): the straight line between its portals
# (or the one portal's level, a chain cut by its window) ran over the sea floor, the tube in the water. Where the vault
# would stand out of the ground (TUNNEL_FREE_M or more from every portal), the network's rail tops are lowered to keep
# TUNNEL_SOIL_M of ground (smoothed) over the vault, reached from the portals at TUNNEL_DIVE_GRADE (the line's
# MAX_GRADE when a shore is too close to its portal for that): a tunnel dives under what it passes beneath, its
# portals where they were. A mountain tunnel's straight line already lies deeper: unchanged.
TUNNEL_SOIL_M = 8.0             # m of ground over a tunnel's vault at least, away from its portals
TUNNEL_DIVE_GRADE = 0.0125      # the grade it dives at from a portal (the Channel Tunnel's ramps: 1.1 %)
TUNNEL_COVER_SIGMA_M = 60.0     # m, the smoothing of the ground over it
TUNNEL_FREE_M = 200.0           # m from a portal within which the cover is not asked for


def _tunnel_cover(runs, nodes, adj, z):
    """The cover (see above) of the tunnel network of _tunnel_chains: its node heights z (in place, never raised over
    the linear solution but to the portals' reach) and each run's profile r["prof"] (None: linear between its
    nodes). Pure but for z and the runs."""
    import heapq
    vault = TUNNEL_H - TUNNEL_FLOOR_M
    nn = len(nodes)
    portals = [i for i in range(nn) if nodes[i]["z"] is not None]
    if not portals:
        return
    dist = np.full(nn, np.inf)                      # along the tunnels to the nearest portal
    q = [(0.0, p) for p in portals]
    for p in portals:
        dist[p] = 0.0
    heapq.heapify(q)
    while q:
        d, u = heapq.heappop(q)
        if d > dist[u]:
            continue
        for v, L, _r in adj[u]:
            if d + L < dist[v]:
                dist[v] = d + L
                heapq.heappush(q, (d + L, v))
    # per run: its samples' along-run position, the linear line, the cap, the free zone
    bad = False
    for r in runs:
        a, b = r["nodes"]
        r["prof"] = None
        if not (np.isfinite(z[a]) and np.isfinite(z[b])):
            continue
        pc, lo, hi = r["pc"], r["lo"], r["hi"]
        s = pc.s[lo:hi + 1] - r["ends"][0]["s"]
        g = pc.gt[lo:hi + 1] if pc.gt is not None else np.full(len(s), np.nan)
        if not np.isfinite(g).any():
            r["cap"] = None
            continue
        g = np.interp(s, s[np.isfinite(g)], g[np.isfinite(g)])
        step = max(float(np.median(np.diff(s))) if len(s) > 1 else STEP_M, 0.5)
        r["s"] = s
        r["cap"] = gsmooth(g, TUNNEL_COVER_SIGMA_M / step) - vault - TUNNEL_SOIL_M
        r["far"] = np.minimum(dist[a] + s, dist[b] + (r["L"] - s)) >= TUNNEL_FREE_M
        line = z[a] + (z[b] - z[a]) * s / r["L"]
        if (r["far"] & (line > r["cap"] + TUNNEL_SOIL_M)).any():    # (a vault out of the ground: then to the soil)
            bad = True
    if not bad:
        return
    # (one pass, continuous in the portals' heights: the lowering spreads at TUNNEL_DIVE_GRADE, the portals' cones and
    # the edges at MAX_GRADE; a switch between two grades flipped a whole network by 30 m between two windows whose
    # portals stood 2.5 m apart, 2026-10-25)
    grade, dive = max(MAX_GRADE, TUNNEL_DIVE_GRADE), TUNNEL_DIVE_GRADE
    zz = z.copy()
    for u in range(nn):                             # the nodes: lowered to their cap where far from the portals
        if nodes[u]["z"] is not None or not np.isfinite(zz[u]) or dist[u] < TUNNEL_FREE_M:
            continue
        caps = []
        for v, _L, ri in adj[u]:
            r = runs[ri]
            if r.get("cap") is not None:
                caps.append(float(r["cap"][0] if r["nodes"][0] == u else r["cap"][-1]))
        if caps:
            zz[u] = min(zz[u], min(caps))
    reach = np.full(nn, -np.inf)
    for p in portals:                               # never under the portals' reach (cones along the network)
        dp = np.full(nn, np.inf)
        dp[p] = 0.0
        q = [(0.0, p)]
        while q:
            d, u = heapq.heappop(q)
            if d > dp[u]:
                continue
            for v, L, _r in adj[u]:
                if d + L < dp[v]:
                    dp[v] = d + L
                    heapq.heappush(q, (d + L, v))
        reach = np.maximum(reach, nodes[p]["z"] - grade * dp)
    zz = np.where(np.isfinite(zz), np.maximum(zz, reach), zz)
    for p in portals:                               # (a portal stays where the open track meets it)
        zz[p] = nodes[p]["z"]
    for _ in range(4 * nn + 4):                     # no edge steeper than the grade: raised, never a portal
        moved = False
        for u in range(nn):
            if nodes[u]["z"] is not None or not np.isfinite(zz[u]):
                continue
            for v, L, _r in adj[u]:
                if np.isfinite(zz[v]) and zz[u] < zz[v] - grade * L - 1e-6:
                    zz[u] = zz[v] - grade * L
                    moved = True
        if not moved:
            break
    for r in runs:
        a, b = r["nodes"]
        if r.get("cap") is None or not (np.isfinite(zz[a]) and np.isfinite(zz[b])):
            r["prof"] = None
            continue
        s, L = r["s"], r["L"]
        line = zz[a] + (zz[b] - zz[a]) * s / L
        want = np.where(r["far"], np.minimum(line, r["cap"]), line)
        cones = np.maximum(zz[a] - grade * s, zz[b] - grade * (L - s))
        low = np.maximum(-grade_cap(-want, s, dive / 0.9), cones) if len(s) >= 3 else line
        # (never over the line between its nodes: at a node s = 0 / L both are its height; a portal's node is the
        # sample just outside; an edge steeper than the grade between two fixed nodes stays that line, no step)
        r["prof"] = np.minimum(low, line)
    z[:] = zz


def grade_cap(z, s, grade, reach=None):
    """z raised to the lowest profile over it whose grade is nowhere steeper than `grade` (the upper envelope of the
    cones z_j - grade |s - s_j|, a forward and a backward pass), then smoothed a little (GRADE_SIGMA_M) and kept over
    that envelope's original: a railway climbs a hill on an embankment, it does not drop off a DEM spike. reach: each
    cone only that far (m; None: all the way). Pure."""
    z = np.asarray(z, np.float64)
    s = np.asarray(s, np.float64)
    if len(z) < 3:
        return z.copy()
    up = z.copy()
    ds = np.diff(s)
    grade = 0.9 * grade                             # (margin for the smoothing's and the hump's own slopes below)
    if reach is None:
        for i in range(1, len(up)):                 # forward: no faster drop than `grade`
            up[i] = max(up[i], up[i - 1] - grade * ds[i - 1])
        for i in range(len(up) - 2, -1, -1):        # backward
            up[i] = max(up[i], up[i + 1] - grade * ds[i])
    else:
        # (every cone within reach of its peak: a sample's height depends on the ground within reach only, the same
        # in every window that holds that stretch: an unbounded cone lifted the track toward a portal 400 m away in
        # one road tile and not in the next, a 4.3 m step at Folkestone, 2026-10-25)
        # (a cone falls at grade, or faster where it must be down to the sample's own height within reach: no step
        # where it ends; a spike over grade x reach gets a steeper embankment)
        for k in range(1, len(z)):
            d = s[k:] - s[:-k]
            if d.min() > reach:
                break
            ok = d <= reach
            fa = z[:-k] - np.maximum(grade, (z[:-k] - z[k:]) / reach) * d        # from i - k onto i
            fb = z[k:] - np.maximum(grade, (z[k:] - z[:-k]) / reach) * d         # from i + k onto i
            up[k:] = np.where(ok, np.maximum(up[k:], fa), up[k:])
            up[:-k] = np.where(ok, np.maximum(up[:-k], fb), up[:-k])
    if np.allclose(up, z):
        return z.copy()
    sig = GRADE_SIGMA_M / max(float(np.mean(ds)), 1e-9)
    sm = gsmooth(up, sig)                           # (smoothing keeps the grade cap, but lowers the peaks a little:)
    short = np.maximum(0.0, z - sm)                 # lifted back as a smooth hump, never by a max() step
    if short.any():
        sm = sm + gsmooth(maxfilter(short, int(math.ceil(3 * sig))), sig)
    return np.maximum(sm, z)


def _finish(pc, pins):
    """Pass 2 of a piece: raised to the node heights at its pins [(s, z, at an end)] (node_pins: never lower than
    its own pass-1 profile there), each eased in over PIN_BLEND_M (a cosine: no kink). Raising only, so its clearance
    (pass 1) holds without a clamp: a clamp made steps of up to 0.24 m (11.7 %) where an end was eased down under it.
    Sets pc.z; returns [(pts (k, 3), kind (k,): 0 ground, 1 bridge, 2 tunnel)]."""
    s, base = pc.s, (pc.base if pc.z is None else pc.z)     # (again over the finished profile: profile_network)
    lift = np.zeros(len(s))
    blend0 = min(PIN_BLEND_M, float(s[-1])) if s[-1] > 0 else 1.0
    for sp, zp, _ in pins:
        delta = zp - float(np.interp(sp, s, base))
        if delta <= 0:
            continue
        # (long enough for the grade: the cosine's steepest is delta pi / (2 blend); a 12 m lift at a node in the
        # Channel Tunnel over 60 m was a 30 % ramp, 2026-10-25; but within PIN_BLEND_MAX_M: a window reads NEAR_M round
        # its tile, a longer reach would differ by window)
        blend = max(blend0, min(PIN_BLEND_MAX_M, delta * math.pi / (2 * 0.9 * MAX_GRADE)))
        u = np.clip(np.abs(s - sp) / blend, 0.0, 1.0)
        lift = np.maximum(lift, delta * 0.5 * (1.0 + np.cos(np.pi * u)))
    z = base + lift
    pc.z = z
    return [(np.c_[pc.xy, z], pc.kind.copy())]


def _z_at(pieces, p, tol, skip=None, base=True):
    """The pieces passing within tol of point p: [(distance, z there, piece, s there, at one of its ends)]. Pure."""
    out = []
    for pc in pieces:
        if pc is skip:
            continue
        xy = pc.xy
        if len(xy) < 2:
            continue
        bb = pc.bb
        if bb is None:                      # (its box and longest step, once: node_pins asks every end of every
            seg = float(np.hypot(*np.diff(xy, axis=0).T).max())     # piece against every piece; a window's
            pc.bb = bb = (*xy.min(0), *xy.max(0), seg)              # thousands of pieces took 20 s, 2026-10-25)
        if p[0] < bb[0] - tol or p[0] > bb[2] + tol or p[1] < bb[1] - tol or p[1] > bb[3] + tol:
            continue
        r = tol + bb[4]                     # (only the segments whose start lies within reach)
        cand = np.flatnonzero((np.abs(xy[:-1, 0] - p[0]) <= r) & (np.abs(xy[:-1, 1] - p[1]) <= r))
        if len(cand) == 0:
            continue
        a, b = xy[cand], xy[cand + 1]
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(axis=1), 1e-12)
        tt = np.clip(((p - a) * ab).sum(axis=1) / L2, 0, 1)
        dd = np.hypot(*(a + tt[:, None] * ab - p).T)
        j = int(np.argmin(dd))
        if dd[j] > tol:
            continue
        i = int(cand[j])
        d = {i: float(dd[j])}
        t = {i: float(tt[j])}
        zz = pc.base if base else pc.z
        z = float(zz[i] + t[i] * (zz[i + 1] - zz[i]))
        sp = float(pc.s[i] + t[i] * (pc.s[i + 1] - pc.s[i]))
        end = (i == 0 and t[i] < 1e-6 and pc.first) or (i == len(xy) - 2 and t[i] > 1 - 1e-6 and pc.last)
        out.append((float(d[i]), z, pc, sp, end))
    return out


def node_pins(pieces, base=True):
    """Where tracks meet (a mapped segment's end on another segment's end, or on a track running on through it: a
    turnout's branch, a siding off a main line): one height for all of them, the highest of their pass-1 profiles
    there (each clears its own ground, so raising the others to it keeps theirs), {piece: [(s, z, at an end)]}: the
    pins _finish eases each track to, the through tracks included. The same in every tile whose window holds the node.
    Before, each segment pinned its ends from the ground round the node alone: steps of up to 1.2 m where a siding left
    a main line by a test town station (tools/audit_rail_continuity.py, 2026-10-24). Pure."""
    pins = {pc: [] for pc in pieces}
    for pc in pieces:
        for e, flag in ((0, pc.first), (1, pc.last)):
            if not flag:
                continue
            p = pc.xy[0] if e == 0 else pc.xy[-1]
            meet = _z_at(pieces, p, NODE_TOL_M, skip=pc, base=base)     # (base False: the finished profiles)
            if not meet:
                continue
            zz_own = pc.base if base else pc.z
            own = float(zz_own[0] if e == 0 else zz_own[-1])
            z = max([own] + [r[1] for r in meet])
            pins[pc].append((0.0 if e == 0 else float(pc.s[-1]), z, True))
            for d, zz, o, sp, end in meet:
                if not end:                         # a track running on through the node: pinned there too
                    pins[o].append((sp, z, False))
    return pins


# Grade-separated crossings (the user's run, 2026-10-24: "la voie monte jusqu'au niveau de la route au dessus"). Every
# road crossing a track was a level crossing: a road over the track on an unflagged structure eased the track up to it,
# and the ground of a flagged overpass's abutments (the envelope's +-8 m reach) lifted the track under it toward the
# deck (a road deck at the rail top by the a test town tunnel; a high-speed line under its overpasses). A crossing is a
# level crossing only where the map joins the two (a shared Overture connector: OSM's railway=level_crossing node);
# without one (or without connector data) only a minor road whose ground shows no structure (the DEM at the crossing
# within SEP_BUMP_M of the straight line between SEP_PROBE_M either side along the track, and no OSM layer) and never a
# major road. A separated crossing, and every road bridge / tunnel part over / under the track, masks the ground the
# track reads over its width + SEP_PAD_M either side (the abutments): the track goes straight through, at its level.
SEP_BUMP_M = 1.5
SEP_PROBE_M = 25.0
SEP_PAD_M = 12.0
SEP_MAJOR = {"motorway", "trunk", "primary", "motorway_link", "trunk_link", "primary_link"}


def feature_connectors(feats, i):
    """The Overture connector ids of feature i (its "connectors" rule rows), a set (empty without that data)."""
    t = getattr(feats, "rules", {}).get("connectors") if hasattr(feats, "rules") else None
    if t is None or len(t.feature) == 0:
        return set()
    return {str(t.value[j]) for j in t.rows(i)}


def rail_connectors(cells):
    """{fid: connector ids} of the rail segments in cells."""
    out = {}
    for feats in cells:
        if feats is None or len(feats) == 0 or "subtype" not in feats.attrs:
            continue
        sub = feats.attrs["subtype"]
        for i in range(len(feats)):
            if str(sub[i]) == "rail":
                out.setdefault(str(feats.ids[i]), set()).update(feature_connectors(feats, i))
    return out


ROAD_REACH_M = TUNNEL_PORTAL_REACH_M + 100.0      # m round a window the roads crossing its tracks are read


def _road_box(near):
    r = ROAD_REACH_M
    return (near[0] - r, near[1] - r, near[2] + r, near[3] + r)


def road_structs(cells, frame, near):
    """{fid: {"cls", "layer" (OSM layer or 0), "conns" (connector ids), "parts": [(kind "ground" | "bridge" |
    "tunnel", xy (k, 2), half width)]}} of the roads near box `near`: what a crossing with a track needs to tell a level
    crossing from a grade-separated one. (near widened by ROAD_REACH_M: see road_lines.)"""
    import mapgeom
    import roads
    near = _road_box(near)
    out = {}
    for feats in cells:
        if feats is None or len(feats) == 0 or "subtype" not in feats.attrs:
            continue
        specs = roads.road_specs(feats, None, None, False)
        boxes = feats.boxes(frame)
        lay = feats.attrs.get("osm_layer")
        for i, sp in enumerate(specs):
            fid = str(feats.ids[i])
            if sp is None or fid in out:
                continue
            fb = boxes[i]
            if fb[2] < near[0] or fb[0] > near[2] or fb[3] < near[1] or fb[1] > near[3]:
                continue
            try:
                layer = float(lay[i]) if lay is not None else 0.0
            except (TypeError, ValueError):
                layer = 0.0
            parts = []
            for kind, fn in (("ground", roads.ground_parts), ("bridge", roads.bridge_parts),
                             ("tunnel", roads.tunnel_parts)):
                for ring in fn(feats, i):
                    if len(ring) < 2:
                        continue
                    e, n = mapgeom.enu_xy(feats, frame, ring)
                    parts.append((kind, np.c_[e, n], float(sp.width) / 2))
            out[fid] = {"cls": sp.cls, "layer": 0.0 if not np.isfinite(layer) else layer,
                        "conns": feature_connectors(feats, i), "parts": parts}
    return out


def is_level_crossing(x, rail_conns, st, ground, xy, s):
    """Is crossing x (crossings_on's dict) of a track (xy, s; its connector ids rail_conns) with road st
    (road_structs' entry) a level crossing (see above)? Pure given ground."""
    if rail_conns and st["conns"] and rail_conns & st["conns"]:
        return True
    if st["layer"] != 0.0:
        return False
    if st["cls"] in SEP_MAJOR and rail_conns:
        return False                                # (a main road meets the track at a node when it is level)
    sp = np.array([x["s"] - SEP_PROBE_M, x["s"], x["s"] + SEP_PROBE_M])
    sp = np.clip(sp, s[0], s[-1])
    px, py = np.interp(sp, s, xy[:, 0]), np.interp(sp, s, xy[:, 1])
    g = ground.z(px, py)
    if sp[2] - sp[0] < SEP_PROBE_M:
        return True                                 # (too short a stretch to tell: as before)
    line = g[0] + (g[2] - g[0]) * (sp[1] - sp[0]) / (sp[2] - sp[0])
    return abs(float(g[1] - line)) < SEP_BUMP_M


def structure_masks(xy, s, kind, sel, rail_conns, structs, ground, roads_near, fid):
    """(level crossings [crossings_on dicts], masks [(s0, s1)]) of a sampled track: its crossings with the ground
    roads sorted into level ones and grade-separated ones, and the ranges masked under every grade-separated crossing
    and road bridge / tunnel part (see above). structs None: every ground crossing is level (no mask). Pure given
    ground."""
    level, masks = [], []
    n = len(xy)
    for x in crossings_on(xy, s, roads_near):
        k = int(np.clip(np.searchsorted(s, x["s"]), 0, n - 1))
        if kind[k] != 0 or not sel[k]:
            continue
        st = structs.get(x["road"]) if structs is not None and _on("BNGE_RAIL_SEP") else None
        if st is None or is_level_crossing(x, rail_conns, st, ground, xy, s):
            level.append(x)
        else:
            masks.append((x["s"] - x["half"] - SEP_PAD_M, x["s"] + x["half"] + SEP_PAD_M))
    if structs and _on("BNGE_RAIL_SEP"):
        over = [(rf, q, hw) for rf, st in structs.items() for kd, q, hw in st["parts"] if kd != "ground"]
        for x in crossings_on(xy, s, over):
            masks.append((x["s"] - x["half"] - SEP_PAD_M, x["s"] + x["half"] + SEP_PAD_M))
    return level, masks


# Tracks side by side (double track, a station's tracks: each mapped as its own line) lie at one level (the user's
# run, 2026-10-24): each profiled alone read its own strip of a side-hill and they came out up to tens of cm apart.
# Where a track has another on the ground within PAR_FULL_M (centre to centre), running parallel (within PAR_COS), it is
# raised to the higher of the two (raised only: each keeps its clearance), fading out to PAR_ZERO_M apart (a turnout's
# branch leaving, a track drawing away). Two passes: a yard's tracks all come to one level.
PAR_FULL_M = 6.5
PAR_ZERO_M = 10.0
PAR_COS = 0.96
PAR_EASE_M = 20.0           # m from a neighbour's end over which its pull eases in (no step where it ends)
PAR_TOL_M = 0.002           # the fixed point: until no track moves more than this
PAR_GRADE = 0.012           # a raise eases in and out no steeper than this
PAR_REACH_M = 80.0          # ... within this of its peak (steeper for a raise over PAR_GRADE x PAR_REACH_M)
EASE_ROUND_M = 5.0          # m, sigma of the rounding of a raise's corners (_ease_raise)
BRIDGE_ROUND_M = 16.0       # m: a bridge's ends rounded into its approaches with a Gaussian of half this (level_parallel)


def _ease_raise(r, s, grade, reach):
    """Raises r (>= 0, along s) eased in and out: the upper envelope of each one's cone, falling at grade, or faster
    so that it is down to 0 within reach of its peak. Bounded, so a sample's raise depends on its neighbours within
    reach only, the same in every window that holds them (the unbounded 1.2 % cones carried a raise by the Folkestone
    portals 500 m along a track in one road tile's window and not in its neighbour's, 2026-10-25). Pure."""
    r = np.asarray(r, np.float64)
    s = np.asarray(s, np.float64)
    out = r.copy()
    if len(r) < 2 or r.max() <= 0:
        return out
    for k in range(1, len(r)):
        d = s[k:] - s[:-k]
        if d.min() > reach:
            break
        ok = d <= reach
        fa = r[:-k] - np.maximum(grade, r[:-k] / reach) * d           # from sample i - k forward
        fb = r[k:] - np.maximum(grade, r[k:] / reach) * d             # from sample i + k backward
        out[k:] = np.where(ok, np.maximum(out[k:], fa), out[k:])
        out[:-k] = np.where(ok, np.maximum(out[:-k], fb), out[:-k])
    # the cones' corners rounded (a raise's flat top meeting its 1.2 %+ flank, the flank meeting the track: kinks of
    # up to 2.7 % in one 2 m sample on a siding by a test town station, 2026-10-25), never under the raise: the
    # upper envelope widened by 3 sigma, then smoothed
    sig = EASE_ROUND_M / max(float(np.median(np.diff(s))), 1e-3)
    return gsmooth(maxfilter(out, int(math.ceil(3 * sig))), sig)


def _nearest_on(p, q, reach=None):
    """(distances (n,), points (n, 2), segment index (n,), t (n,)) from points p to polyline q. reach: only the
    segments of q within reach of a point count (inf distance where none is: the Channel Tunnel's 25 000 sample bores,
    side by side over 50 km, took level_parallel 140 s for all of them against all, 2026-10-24). Pure."""
    p, q = np.asarray(p, np.float64)[:, :2], np.asarray(q, np.float64)[:, :2]
    a, b = q[:-1], q[1:]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    dist = np.full(len(p), np.inf)
    seg = np.zeros(len(p), np.int64)
    tt = np.zeros(len(p))
    if len(a) == 0:
        return dist, np.zeros((len(p), 2)), seg, tt
    lo, hi = (np.minimum(a, b), np.maximum(a, b)) if reach is not None else (None, None)
    for k0 in range(0, len(p), 256):
        pp = p[k0:k0 + 256]
        if reach is not None:
            c0, c1 = pp.min(0) - reach, pp.max(0) + reach
            cand = np.flatnonzero((hi[:, 0] >= c0[0]) & (lo[:, 0] <= c1[0]) & (hi[:, 1] >= c0[1]) & (lo[:, 1] <= c1[1]))
            if len(cand) == 0:
                continue
        else:
            cand = None
        aa, bb, ll = (a, ab, L2) if cand is None else (a[cand], ab[cand], L2[cand])
        t = np.clip(((pp[:, None, :] - aa[None]) * bb[None]).sum(-1) / ll[None], 0.0, 1.0)
        d = np.hypot(*(pp[:, None, :] - (aa[None] + t[..., None] * bb[None])).transpose(2, 0, 1))
        j = np.argmin(d, axis=1)
        r = np.arange(len(pp))
        dj = d[r, j]
        if reach is not None:
            dj = np.where(dj <= reach, dj, np.inf)
        dist[k0:k0 + 256], seg[k0:k0 + 256], tt[k0:k0 + 256] = dj, (j if cand is None else cand[j]), t[r, j]
    return dist, a[seg] + tt[:, None] * ab[seg], seg, tt


def level_parallel(pieces, attr="base"):
    """The profiles (pc.<attr>: "base" pass 1, "z" the finished ones) of tracks side by side raised to one level (see
    above), in place, each raise eased in and out along the track (its peak kept: PAR_EASE_M, no step where a
    neighbour ends); their bridges straight again between their (raised) ends. Pure but for the profiles."""
    if len(pieces) < 2 or not _on("BNGE_RAIL_PARALLEL"):
        return
    boxes = [(pc.xy.min(0) - PAR_ZERO_M, pc.xy.max(0) + PAR_ZERO_M) for pc in pieces]
    dirs = []
    for pc in pieces:
        d = np.gradient(pc.xy, axis=0) if len(pc.xy) > 1 else np.zeros_like(pc.xy)
        dirs.append(d / np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None])
    pairs = []
    # (a grid of PAR_ZERO_M squares: a's samples with one of b's in their square or the next: a station's 75 tracks
    # crossed by every box test made this a cell profile's largest cost, 2026-10-25)
    gk = []
    for pc in pieces:
        q = np.floor(pc.xy / PAR_ZERO_M).astype(np.int64)
        gk.append(q)
    sets = []
    off9 = np.array([[dx, dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1)])
    for q in gk:
        nb = (q[:, None, :] + off9[None]).reshape(-1, 2)
        sets.append(np.unique(nb[:, 0] * 1000003 + nb[:, 1]))          # (sorted: searched, not isin's sort per pair)
    # (the boxes' overlaps all at once: a station's hundred pieces made ten thousand small tests one by one)
    bl = np.array([b[0] for b in boxes])
    bh = np.array([b[1] for b in boxes])
    over = ((bh[:, None, :] >= bl[None, :, :]) & (bh[None, :, :] >= bl[:, None, :])).all(axis=2)
    longp = np.array([len(pc.xy) >= 2 for pc in pieces])
    over &= longp[:, None] & longp[None, :]
    np.fill_diagonal(over, False)
    for i, a in enumerate(pieces):
        js = np.flatnonzero(over[i])
        if len(js) == 0:
            continue
        ka = gk[i][:, 0] * 1000003 + gk[i][:, 1]
        open_a = np.asarray(a.kind) != 2
        for j in js:
            j = int(j)
            b = pieces[j]
            # (only a's samples within reach of b's, against b's stretch within reach of those: the long pieces of a
            # tunnel chain made this the profile's largest cost; and never in a tunnel: no pull there, below)
            sj = sets[j]
            pos = np.minimum(np.searchsorted(sj, ka), len(sj) - 1)
            ina = (sj[pos] == ka) & open_a
            if not ina.any():
                continue
            alo, ahi = a.xy[ina].min(0) - PAR_ZERO_M, a.xy[ina].max(0) + PAR_ZERO_M
            inb = np.flatnonzero(((b.xy >= alo) & (b.xy <= ahi)).all(axis=1))
            if len(inb) == 0:
                continue
            b0, b1 = max(int(inb[0]) - 1, 0), min(int(inb[-1]) + 2, len(b.xy))
            if b1 - b0 < 2:
                continue
            d = np.full(len(a.xy), np.inf)
            seg = np.zeros(len(a.xy), np.int64)
            t = np.zeros(len(a.xy))
            d[ina], _c, sg, t[ina] = _nearest_on(a.xy[ina], b.xy[b0:b1], reach=2 * PAR_ZERO_M)
            seg[ina] = sg + b0
            cos = np.abs((dirs[i] * dirs[j][seg]).sum(1))
            # (every weight a ramp, never a cut-off: a cut-off left a step where it switched)
            w = np.clip((PAR_ZERO_M - d) / (PAR_ZERO_M - PAR_FULL_M), 0.0, 1.0)
            w = w * np.clip((cos - PAR_COS) / (1.0 - PAR_COS) * 2.0, 0.0, 1.0) * np.clip((d - 0.3) / 0.7, 0.0, 1.0)
            w = np.where((a.kind != 2) & (b.kind[seg] != 2) & (b.kind[np.minimum(seg + 1, len(b.kind) - 1)] != 2),
                         w, 0.0)
            # (eased in over PAR_EASE_M from the neighbour's own ends: a siding's buffer stop beside a main line left
            # a step in the main line where the raise stopped; not at a cut at the window's edge)
            sb = b.s[seg] + t * (b.s[np.minimum(seg + 1, len(b.s) - 1)] - b.s[seg])
            far = np.full(len(sb), np.inf)
            if b.first:
                far = np.minimum(far, sb)
            if b.last:
                far = np.minimum(far, b.s[-1] - sb)
            w = w * np.clip(far / PAR_EASE_M, 0.0, 1.0)
            if w.any():
                pairs.append((a, b, w, seg, t))
    if not pairs:
        return
    get = lambda pc: getattr(pc, attr)          # noqa: E731
    orig = {id(pc): get(pc).copy() for pc in pieces}
    # a fixed point of raises only, each to a weighted level of its neighbour's (bounded by the highest of them: no
    # creep, no growth round after round)
    for _round in range(2):
        for _ in range(24):
            moved = 0.0
            for a, b, w, seg, t in pairs:
                za, zbv = get(a), get(b)
                zb = zbv[seg] + t * (zbv[np.minimum(seg + 1, len(zbv) - 1)] - zbv[seg])
                o = orig[id(a)]
                z = np.maximum(za, o + w * np.maximum(0.0, zb - o))
                moved = max(moved, float((z - za).max()))
                setattr(a, attr, z)
            if moved < PAR_TOL_M:
                break
        # each raise eased in and out at PAR_GRADE at most (the upper envelope of its cones: still raises only): two
        # tracks drawing together came to one level over a few metres, a 12 % ramp on the lower one
        for pc in pieces:
            r = get(pc) - orig[id(pc)]
            if r.max() <= 0 or len(r) < 2:
                continue
            setattr(pc, attr, orig[id(pc)] + _ease_raise(r, pc.s, PAR_GRADE, PAR_REACH_M))
    for pc in pieces:                               # bridges straight between their ends again ...
        if (pc.kind == 1).any():
            keep = (pc.kind != 1) | (np.arange(len(pc.kind)) == 0) | (np.arange(len(pc.kind)) == len(pc.kind) - 1)
            z = _fill_masked(get(pc), keep)
            # ... their ends rounded into the approaches (a straight deck met its approach's curve in a 1-2 % kink at
            # the LGV's viaduct by a village, 2026-10-25), the piece's own ends kept (its nodes)
            if len(z) > 4:
                w = np.clip(np.minimum(pc.s - pc.s[0], pc.s[-1] - pc.s) / BRIDGE_ROUND_M, 0.0, 1.0)
                sb = pc.s[pc.kind == 1]             # (only round the bridges' ends: the rest as it was)
                near = np.abs(pc.s[:, None] - sb[None, [0, -1]]).min(1) if len(sb) else np.full(len(z), np.inf)
                for run in _runs(pc.kind == 1):
                    near = np.minimum(near, np.minimum(np.abs(pc.s - pc.s[run[0]]), np.abs(pc.s - pc.s[run[-1]])))
                w = w * np.clip(2.0 - near / BRIDGE_ROUND_M, 0.0, 1.0) * (pc.kind != 2)
                z = z + w * (gsmooth(z, BRIDGE_ROUND_M / 2 / STEP_M) - z)
            setattr(pc, attr, z)


def profile_network(ground, segments, near=None, roads_near=(), found=None, arcs=None, structs=None, conns=None):
    """The tracks of several mapped segments, profiled together: segments [(fid, xy (k, 2) ring, ranges)];
    returns {fid: [(pts (k, 3) rail-top centre line, kind (k,): 0 ground, 1 bridge, 2 tunnel)]} in `near`
    (None: all). found: a list that gets the level crossings (crossings_on's dicts + z_road, z: the platform's rail top,
    fid). Pure given ground.

    Pass 1 profiles each segment alone (_base: smoothed, crossings, clearance, grade cap); pass 2 pins every node to
    one height shared by all the tracks meeting there (node_pins) and eases each track to it (_finish). Before, each
    segment pinned its ends from the ground around the node alone, then moved them again: steps of up to 1.2 m where a
    siding left a main line, and segments meeting at a node at different heights (a test town station, 2026-10-24)."""
    pieces, xs = [], []
    forced = _tunnel_forced(segments, near)
    wins = []
    for fid, xy_raw, ranges in segments:
        wins.append((fid, ranges, _window(xy_raw, ranges, near, force=fid in forced), xy_raw))
    # (the tracks round a structure's ends that a window profiles past its box: see AUX_M)
    aux = _aux_boxes([w for _f, _r, w, _x in wins if w is not None], near)
    for fid, ranges, w, xy_raw in wins:
        if aux and w is None:
            w = _window(xy_raw, ranges, _bbox_of(aux), force=False)
            if w is not None:
                w = (w[0], w[1], w[2], _in_boxes(w[0], aux))
        elif aux:
            w = (w[0], w[1], w[2], w[3] | _in_boxes(w[0], aux))
        if w is None or not w[3].any():
            continue
        xy, s, kind, sel = w
        n = len(xy)
        mine, masks = [], []
        if roads_near or structs:
            level, masks = structure_masks(xy, s, kind, sel, (conns or {}).get(fid, set()), structs, ground,
                                           roads_near, fid)
            for x in level:
                x["z_road"] = float(ground.z(np.array([x["at"][0]]), np.array([x["at"][1]]))[0])
                x["z"] = x["z_road"] + X_RISE_M
                x["fid"] = fid
                mine.append(x)
        xs += mine
        for grp in _runs(sel):
            if len(grp) < 2:
                continue
            s0, s1 = s[grp[0]], s[grp[-1]]
            pc = Piece(fid, xy[grp], s[grp] - s0, kind[grp], grp[0] == 0, grp[-1] == n - 1, float(s0))
            pins = [(x["s"] - s0, x["z"], x["half"]) for x in mine if s0 - X_PIN_BLEND_M <= x["s"] <= s1 + X_PIN_BLEND_M]
            _base(ground, pc, pins, [(a - s0, b - s0) for a, b in masks])
            pieces.append(pc)
    level_parallel(pieces)          # tracks side by side at one level
    _tunnel_chains(pieces, ground)  # the tunnels straight from portal to portal, over their whole chains
    pins = node_pins(pieces)
    for pc in pieces:
        _finish(pc, pins[pc])
    level_parallel(pieces, "z")     # again: a node's raise of one track of a pair shared with the other
    out = {}
    for pc in pieces:
        out.setdefault(pc.fid, []).append((np.c_[pc.xy, pc.z], pc.kind.copy()))
        if arcs is not None:        # (each part's arc along its segment: masts, anything placed by distance)
            arcs.setdefault(pc.fid, []).append(pc.s + pc.s0)
    if found is not None:
        for x in xs:            # the platform at the rail top the profile ended with
            near_z = [r for r in _z_at([pc for pc in pieces if pc.fid == x["fid"]], x["at"], 2 * STEP_M, base=False)]
            if near_z:
                x["z"] = min(near_z, key=lambda r: r[0])[1]
                found.append(x)
    return out


# A window profiles a whole bridge or tunnel reaching into it (and TUNNEL_PORTAL_REACH_M past a portal), past its box:
# the other tracks round those ends (the next track of a double-track viaduct, a yard by a portal) are profiled there
# too, within AUX_M of each such end outside the box: what levels the structure's ends (level_parallel, the nodes) is
# then the same in every window that holds the structure (a viaduct's end raised in one road tile and not in the next
# moved its whole straight deck, 0.26 m at the Folkestone terminal, 2026-10-25).
AUX_M = 100.0


def _aux_boxes(wins, near):
    if near is None:
        return []
    x0, y0, x1, y1 = near
    out = []
    for xy, _s, kind, sel in wins:
        k = np.asarray(kind)
        edge = np.zeros(len(k), bool)
        edge[1:] |= k[1:] != k[:-1]
        edge[:-1] |= k[1:] != k[:-1]
        outside = (xy[:, 0] < x0) | (xy[:, 0] > x1) | (xy[:, 1] < y0) | (xy[:, 1] > y1)
        for i in np.flatnonzero(edge & sel & outside):
            out.append((xy[i, 0] - AUX_M, xy[i, 1] - AUX_M, xy[i, 0] + AUX_M, xy[i, 1] + AUX_M))
    return out


def _in_boxes(xy, boxes):
    m = np.zeros(len(xy), bool)
    for a, b, c, d in boxes:
        m |= (xy[:, 0] >= a) & (xy[:, 0] <= c) & (xy[:, 1] >= b) & (xy[:, 1] <= d)
    return m


def _bbox_of(boxes):
    b = np.array(boxes)
    return (float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max()))


def track_profile(ground, xy_raw, ranges, near=None, roads_near=(), found=None):
    """One mapped segment profiled alone (profile_network with it only): [(pts (k, 3), kind (k,))]. Pure given
    ground."""
    return profile_network(ground, [("_", xy_raw, ranges)], near, roads_near, found).get("_", [])


def _ease(d, flat, blend):
    """1 within flat of a pin, a cosine down to 0 at flat + blend, 0 beyond (d: distances). Pure."""
    u = np.clip((np.abs(d) - flat) / max(blend, 1e-9), 0.0, 1.0)
    return 0.5 * (1.0 + np.cos(np.pi * u))


def clip_track(pts, bridge, box):
    """Pieces of a sampled track inside box (x0, y0, x1, y1): [(pts, bridge)], whole samples (a sample just outside
    each end kept so the meshes overlap at tile seams). Pure."""
    x0, y0, x1, y1 = box
    inside = (pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= y0) & (pts[:, 1] <= y1)
    if not inside.any():
        return []
    grow = inside.copy()
    grow[1:] |= inside[:-1]
    grow[:-1] |= inside[1:]
    idx = np.flatnonzero(grow)
    out = []
    for part in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
        if len(part) >= 2:
            out.append((pts[part], bridge[part]))
    return out


# --- meshes ------------------------------------------------------------------------------------------------------

class Mesh:
    """Positions / triangles / uvs / material indices, tile-local (origin subtracted)."""

    def __init__(self, origin):
        self.o = np.asarray(origin, np.float64)
        self.P, self.T, self.UV, self.M = [], [], [], []
        self.nv = 0

    def add(self, P, T, UV, mat, inside=None):
        """Triangles T (m, 3) over P (n, 3) frame points. inside: (m, 3) points the faces must look away from (their
        winding is fixed to face outward from them); None: as given."""
        P = np.asarray(P, np.float64)
        T = np.asarray(T, np.int64).reshape(-1, 3)
        if len(T) == 0:
            return
        if inside is not None:
            V = P[T]
            nrm = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
            flip = (nrm * (V.mean(axis=1) - inside)).sum(axis=1) < 0
            T = T.copy()
            T[flip] = T[flip][:, ::-1]
        self.P.append(P - self.o)
        self.T.append(T + self.nv)
        self.UV.append(np.asarray(UV, np.float64).reshape(-1, 2))
        self.M.append(np.full(len(T), mat, np.int64))
        self.nv += len(P)

    def extend(self, other):
        """Another Mesh's triangles added (same origin)."""
        base = 0
        for P, T, UV, M in zip(other.P, other.T, other.UV, other.M):
            self.P.append(P)
            self.T.append(T - base + self.nv)
            self.UV.append(UV)
            self.M.append(M)
            self.nv += len(P)
            base += len(P)

    def empty(self):
        return self.nv == 0

    def arrays(self):
        return (np.concatenate(self.P).astype(np.float32), np.concatenate(self.T).astype(np.int64),
                np.concatenate(self.UV).astype(np.float32), list(MATERIALS), np.concatenate(self.M))

    def parts(self, max_verts=None):
        """The mesh as arrays() of at most max_verts vertices each (whole add() calls per part; the engine draws a
        shape with 16-bit indices: buildings.MAX_MESH_VERTS), [] if empty."""
        max_verts = max_verts or MAX_MESH_VERTS
        out, cur, n = [], [], 0
        for k in range(len(self.P)):
            m = len(self.P[k])
            if cur and n + m > max_verts:
                out.append(cur)
                cur, n = [], 0
            cur.append(k)
            n += m
        if cur:
            out.append(cur)
        start = np.cumsum([0] + [len(p) for p in self.P])      # first vertex of each add() in the whole mesh
        res = []
        for ks in out:
            base = np.cumsum([0] + [len(self.P[k]) for k in ks[:-1]])
            res.append((np.concatenate([self.P[k] for k in ks]).astype(np.float32),
                        np.concatenate([self.T[k] - start[k] + b for k, b in zip(ks, base)]).astype(np.int64),
                        np.concatenate([self.UV[k] for k in ks]).astype(np.float32), list(MATERIALS),
                        np.concatenate([self.M[k] for k in ks])))
        return res


def signed_area(prof):
    """Shoelace area of a cross-section in (lateral-left, up) coordinates (closed by its last edge). Pure."""
    x, y = prof[:, 0], prof[:, 1]
    return 0.5 * float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum())


def _sweep(mesh, pts, nrm, profile_pts, mat, closed=False, uv_scale=1.0, caps=False, tilt=None):
    """Extrude a cross-section along a track. profile_pts (q, 2): (lateral offset to the left, height over the rail top
    line). The basis (left normal, up, along) is right-handed, so a counter-clockwise section has its outward faces
    from (a, b, c) quads; a clockwise one (or an open chain, judged as closed by its last edge) from (a, c, b).
    Caps (closed sections): the end faces, the first looking back along the track, the last forward. tilt (k,): the
    cant, m of rise per m to the left (cant_tilt), the section turned about the centre line."""
    k, q = len(pts), len(profile_pts)
    prof = np.asarray(profile_pts, np.float64)
    P = (pts[:, None, :2] + nrm[:, None, :] * prof[None, :, 0:1])
    Z = pts[:, None, 2] + prof[None, :, 1]
    if tilt is not None:
        Z = Z + np.asarray(tilt, np.float64)[:, None] * prof[None, :, 0]
    P = np.concatenate([P, Z[..., None]], axis=2).reshape(-1, 3)
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts[:, :2], axis=0).T))]
    perim = np.r_[0.0, np.cumsum(np.hypot(*np.diff(prof, axis=0).T))]
    UV = np.stack(np.broadcast_arrays(perim[None, :] * uv_scale, s[:, None] * uv_scale), axis=2).reshape(-1, 2)
    seg = q if closed else q - 1
    i = np.arange(k - 1)[:, None]
    j = np.arange(seg)[None, :]
    a = i * q + j
    b = i * q + (j + 1) % q
    c = a + q
    d = b + q
    if signed_area(prof) > 0:
        T = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([b, d, c], -1).reshape(-1, 3)])
    else:
        T = np.concatenate([np.stack([a, c, b], -1).reshape(-1, 3), np.stack([b, c, d], -1).reshape(-1, 3)])
    mesh.add(P, T, UV, mat)
    if caps and closed and q >= 3:
        ccw = signed_area(prof) > 0                 # a counter-clockwise fan faces along the track
        fan = np.stack([np.zeros(q - 2, np.int64), np.arange(1, q - 1), np.arange(2, q)], -1)
        for e, forward in ((0, False), (k - 1, True)):
            Tc = fan if ccw == forward else fan[:, ::-1]
            mesh.add(P[e * q:(e + 1) * q], Tc, prof * uv_scale, mat)


def rail_section(prof):
    """The rail's cross-section (lateral from its centre, height from its top), counter-clockwise. Pure."""
    H, C, B, t = prof
    hh = 0.037 * H / 0.172          # head depth
    fh = 0.0115 * H / 0.172         # foot edge thickness
    half = [(-C / 2 + 0.004, 0.0), (-C / 2, -hh), (-t / 2, -hh - 0.012), (-t / 2, -H + 0.030), (-B / 2, -H + fh),
            (-B / 2, -H)]
    right = [(-x, z) for x, z in reversed(half)]
    return np.array(half + right)


def _box_strip(mesh, pts, nrm, lat0, lat1, z_top, z_bot, mat, tilt=None):
    """A closed box swept along pts between lateral offsets lat0 < lat1 and heights z_top > z_bot (over the rail top
    line), with end caps."""
    _sweep(mesh, pts, nrm, [(lat0, z_top), (lat0, z_bot), (lat1, z_bot), (lat1, z_top)], mat, closed=True, caps=True,
           tilt=tilt)


# Cant (French "dévers"): in a curve the outer rail stands higher, by the equilibrium cant of the line's speed there
# (EN 13803: 11.8 V^2 / R mm, V km/h), at most CANT_MAX_M; the speed taken as the curve allows it (V = 4.6 sqrt(R)
# with 150 mm of cant and 100 of deficiency, at most CANT_V_KMH). The curvature is smoothed over CANT_SIGMA_M first,
# so the cant ramps in and out along the curve's ends as over a transition curve (a clothoid's linear ramp), and none
# within CANT_X_CLEAR_M of a level crossing (its platform is flat).
CANT_ON = os.environ.get("BNGE_RAIL_CANT", "on").strip().lower() not in ("off", "0", "false", "no")
CANT_MAX_M = 0.150
CANT_V_KMH = 160.0
CANT_SIGMA_M = 30.0
CANT_X_CLEAR_M = 25.0
CANT_SPAN_M = GAUGE_M + 0.07        # m between the rails' running centres (1.5 m)


def curvature(xy, sigma_m=CANT_SIGMA_M):
    """Signed horizontal curvature (1/m, + turning left) of a track sampled every ~STEP_M, smoothed. Pure."""
    xy = np.asarray(xy, np.float64)
    if len(xy) < 3:
        return np.zeros(len(xy))
    d = np.gradient(xy, axis=0)
    h = np.unwrap(np.arctan2(d[:, 1], d[:, 0]))
    ds = np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)
    k = np.gradient(h) / ds
    return gsmooth(k, sigma_m / max(float(np.median(ds)), 1e-9))


def cant_tilt(xy, clear_pts=()):
    """Per sample: the cant as a tilt (m of rise per m to the left of the centre line): -sign(k) c / CANT_SPAN_M,
    c = min(CANT_MAX_M, 11.8 V^2 R / 1e3 ...) (see above); 0 near the points clear_pts (level crossings, turnouts' zones). Pure."""
    xy = np.asarray(xy, np.float64)
    if not CANT_ON or len(xy) < 3:
        return np.zeros(len(xy))
    k = curvature(xy)
    R = 1.0 / np.maximum(np.abs(k), 1e-9)
    v = np.minimum(4.6 * np.sqrt(R), CANT_V_KMH)
    c = np.minimum(CANT_MAX_M, 11.8 * v * v / R / 1000.0)
    c = np.where(R > 20000.0, 0.0, c)
    tilt = -np.sign(k) * c / CANT_SPAN_M
    if len(clear_pts):
        cp = np.asarray([[float(p[0]), float(p[1])] for p in clear_pts])
        lo, hi = xy.min(axis=0) - 2 * CANT_X_CLEAR_M, xy.max(axis=0) + 2 * CANT_X_CLEAR_M
        cp = cp[(cp[:, 0] >= lo[0]) & (cp[:, 0] <= hi[0]) & (cp[:, 1] >= lo[1]) & (cp[:, 1] <= hi[1])]
        for k0 in range(0, len(cp), 256):           # (the nearest clear point: no cant within CANT_X_CLEAR_M, eased
            c = cp[k0:k0 + 256]                     # back in over as much again)
            d = np.hypot(xy[:, None, 0] - c[None, :, 0], xy[:, None, 1] - c[None, :, 1]).min(axis=1)
            tilt = tilt * np.clip((d - CANT_X_CLEAR_M) / CANT_X_CLEAR_M, 0.0, 1.0)
    return tilt


def _sleepers(mesh, pts, nrm, H, tilt=None):
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts[:, :2], axis=0).T))]
    if s[-1] < SLEEPER_EVERY_M:
        return
    at = np.arange(SLEEPER_EVERY_M / 2, s[-1], SLEEPER_EVERY_M)
    cx = np.interp(at, s, pts[:, 0])
    cy = np.interp(at, s, pts[:, 1])
    cz = np.interp(at, s, pts[:, 2]) - H - PAD_M
    nx = np.interp(at, s, nrm[:, 0])
    ny = np.interp(at, s, nrm[:, 1])
    nn = np.maximum(np.hypot(nx, ny), 1e-9)
    nx, ny = nx / nn, ny / nn
    tx, ty = ny, -nx                                # along the track
    tl = np.interp(at, s, tilt) if tilt is not None else np.zeros(len(at))
    L, W, Hs = SLEEPER
    corners = []
    for la, al, z in ((-L / 2, -W / 2, 0), (L / 2, -W / 2, 0), (L / 2, W / 2, 0), (-L / 2, W / 2, 0),
                      (-L / 2, -W / 2, -Hs), (L / 2, -W / 2, -Hs), (L / 2, W / 2, -Hs), (-L / 2, W / 2, -Hs)):
        corners.append(np.c_[cx + nx * la + tx * al, cy + ny * la + ty * al, cz + z + tl * la])
    P = np.stack(corners, axis=1)                   # (n, 8, 3)
    faces = np.array([[0, 1, 2], [0, 2, 3], [0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2], [2, 6, 7], [2, 7, 3],
                      [3, 7, 4], [3, 4, 0]])
    n = len(at)
    T = (faces[None, :, :] + 8 * np.arange(n)[:, None, None]).reshape(-1, 3)
    centre = np.c_[cx, cy, cz - Hs / 2]
    inside = np.repeat(centre, len(faces), axis=0)
    UV = np.tile(np.array([[0, 0], [1, 0], [1, 0.3], [0, 0.3], [0, 0.1], [1, 0.1], [1, 0.4], [0, 0.4]]), (n, 1))
    mesh.add(P.reshape(-1, 3), T, UV, MAT_SLEEPER, inside=inside)


# Over a hollow (the user's run, 2026-10-27, LGV by a village: "generation de terrain en dessous des rails"): a road
# passing under the line in a cutting wider than its mapped rail bridge (a 5 m bridge over a 20 m cutting) left the
# track on the ground over nothing, its ballast hanging. Where the ballast's foot stands more than AUTO_BRIDGE_M over
# the graded ground for at most AUTO_BRIDGE_MAX_M, the track is drawn as a bridge (slab, parapets, abutments), as the
# real line crosses it; a longer hollow is the bed's grading's to fill.
AUTO_BRIDGE_M = 1.0
AUTO_BRIDGE_MAX_M = 80.0
ABUTMENT_T_M = 0.8          # m: an abutment wall's thickness along the track


def _auto_bridges(pts, kd, ground):
    """kd (0 ground, 1 bridge, 2 tunnel) with the on-ground runs over a hollow (see above) made bridges. Pure given
    ground (a new array; kd untouched)."""
    kd = np.asarray(kd).copy()
    if ground is None or len(pts) < 3 or not (kd == 0).any():
        return kd
    g = np.asarray(ground.z(pts[:, 0], pts[:, 1]), np.float64)
    foot = pts[:, 2] - BALLAST_TOP_M - BALLAST_DEPTH_M
    hollow = (kd == 0) & (foot - g > AUTO_BRIDGE_M)
    if not hollow.any():
        return kd
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts[:, :2], axis=0).T))]
    for run in _runs(hollow):
        if len(run) and s[run[-1]] - s[run[0]] <= AUTO_BRIDGE_MAX_M:
            kd[run] = 1
    return kd


def _abutments(mesh, pts, nrm, under, ground, lo, hi):
    """An abutment wall at each end of the bridge run lo:hi (where the slab meets the bank): from the slab's underside
    (`under` m from the rail top) down to the ground and BRIDGE_PIER_FOOT_M into it, as wide as the slab."""
    hw, _dep = BRIDGE_SLAB
    for i, sgn in ((lo, 1.0), (hi - 1, -1.0)):
        if i < 0 or i >= len(pts):
            continue
        j = min(max(i + int(sgn), 0), len(pts) - 1)
        t = pts[j, :2] - pts[i, :2]
        L = float(np.hypot(*t))
        if L < 1e-6:
            continue
        t = t / L
        c = pts[i, :2] + t * ABUTMENT_T_M / 2
        gz = float(np.min(ground.z(np.array([c[0] - nrm[i, 0] * hw, c[0], c[0] + nrm[i, 0] * hw]),
                                   np.array([c[1] - nrm[i, 1] * hw, c[1], c[1] + nrm[i, 1] * hw]))))
        top = float(pts[i, 2] + under)
        if top - gz < 0.3:
            continue
        _box(mesh, c, t, ABUTMENT_T_M / 2, hw, gz - BRIDGE_PIER_FOOT_M, top, MAT_CONCRETE)


def _bridge_runs(pts, bridge):
    """(lo, hi) slices of the bridge runs of a piece, one sample either side included (the slab meets the bank)."""
    if not np.any(bridge):
        return []
    idx = np.flatnonzero(bridge)
    out = []
    for part in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
        lo, hi = max(part[0] - 1, 0), min(part[-1] + 2, len(pts))
        if hi - lo >= 2:
            out.append((lo, hi))
    return out


# Viaducts (NRails): the slab under the ballast gets a parapet each side (drawn and colliding: a derailed train
# stays on the deck) and, every BRIDGE_PIER_EVERY_M, a pier down into the ground (drawn; the ground read under it).
BRIDGE_PARAPET = (0.25, 1.0)    # m thick, m over the slab's top, at the slab's edges
BRIDGE_PIER_EVERY_M = 30.0
BRIDGE_PIER = (1.6, 3.2)        # m along, m across the track
BRIDGE_PIER_MIN_M = 1.5         # m of clear height under the slab for a pier to be worth it
BRIDGE_PIER_FOOT_M = 1.0        # m a pier reaches into the ground


# A viaduct carrying tracks side by side (the user's run, 2026-10-24: "les bordures des ponts ferroviaires rentrent en
# conflit avec la voie adjacente"): each track's slab had its two parapets, the inner ones standing in the next train's
# way. Towards a track within BRIDGE_NEIGHBOUR_M (centre to centre) there is no parapet and the slab runs on to half
# way, so the two slabs make one deck; the parapets stay on the outer sides.
BRIDGE_NEIGHBOUR_M = 7.0


def side_room(pts, nrm, others, reach=None):
    """(left, right) per sample: m from the track's centre line to the nearest other track's centre line on that side
    (inf without one within reach, default 2 BRIDGE_NEIGHBOUR_M), measured along the left normal. others: [(k, 2)].
    Pure."""
    n = len(pts)
    left, right = np.full(n, np.inf), np.full(n, np.inf)
    reach = 2 * BRIDGE_NEIGHBOUR_M if reach is None else reach
    for o in others:
        if len(o) < 2:
            continue
        lo, hi = pts[:, :2].min(0) - reach, pts[:, :2].max(0) + reach
        if (o.max(0) < lo).any() or (o.min(0) > hi).any():
            continue
        d, c, _seg, _t = _nearest_on(pts[:, :2], o, reach=reach)
        lat = ((c - pts[:, :2]) * nrm).sum(1)
        # (beside, not ahead: the piece carrying the same line on from this one's end is no neighbour)
        ok = (d <= reach) & (np.abs(lat) >= 0.7 * d)
        left = np.where(ok & (lat > 0), np.minimum(left, np.abs(lat)), left)
        right = np.where(ok & (lat <= 0), np.minimum(right, np.abs(lat)), right)
    return left, right


def _deck_sides(pts, nrm, lo, hi, room, top, bottom, mesh, tilt, parapet_top=None):
    """A bridge run's slab (lo:hi) with its parapets (parapet_top: their top over the rail top; None: no parapets)
    on the sides with no neighbouring track (room: side_room's), the slab carried on to half way where there is one."""
    hw, _dep = BRIDGE_SLAB
    pt = BRIDGE_PARAPET[0]
    p, nn = pts[lo:hi], nrm[lo:hi]
    tl = None if tilt is None else tilt[lo:hi]
    _box_strip(mesh, p, nn, -hw, hw, top, bottom, MAT_CONCRETE, tl)
    for sgn, r in ((1.0, room[0][lo:hi]), (-1.0, room[1][lo:hi])):
        near = r <= BRIDGE_NEIGHBOUR_M
        for keep, pairs in ((~near, None), (near, True)):
            for run in _runs(keep):
                if len(run) < 2:
                    continue
                a, b = run[0], run[-1] + 1
                b = min(b + 1, len(p))              # (one sample on: the pieces meet)
                rt = None if tl is None else tl[a:b]
                if pairs:                           # the slab on to half way to the next track (one deck)
                    half = max(hw, float(np.median(r[run])) / 2 + 0.05)
                    x0, x1 = sorted((sgn * hw, sgn * half))
                    _box_strip(mesh, p[a:b], nn[a:b], x0, x1, top, bottom, MAT_CONCRETE, rt)
                elif parapet_top is not None:
                    x0, x1 = sorted((sgn * (hw - pt), sgn * hw))
                    _box_strip(mesh, p[a:b], nn[a:b], x0, x1, parapet_top, top, MAT_CONCRETE, rt)


def _ballast_collision(mesh, pts, nrm, bridge, tilt=None, room=None):
    """The track bed's collision: the ballast's top and side slopes (open section, faces up), its crest
    BALLAST_COL_TOP_M under the rail top; on bridges the slab's box under it and its parapets (not toward a track
    beside it: room, side_room's)."""
    top = -BALLAST_COL_TOP_M
    w0 = BALLAST_HALF_M
    w1 = w0 + BALLAST_SLOPE * BALLAST_DEPTH_M
    _sweep(mesh, pts, nrm, [(-w1, top - BALLAST_DEPTH_M), (-w0, top), (w0, top), (w1, top - BALLAST_DEPTH_M)],
           MAT_BALLAST, closed=False, tilt=tilt)
    if room is None:
        room = (np.full(len(pts), np.inf), np.full(len(pts), np.inf))
    for lo, hi in _bridge_runs(pts, bridge):
        _hw, dep = BRIDGE_SLAB
        _deck_sides(pts, nrm, lo, hi, room, top - 0.02, -BALLAST_TOP_M - dep, mesh, tilt,
                    -BALLAST_TOP_M + BRIDGE_PARAPET[1])


def _ballast(mesh, pts, nrm, bridge, tilt=None, ground=None, room=None, avoid=()):
    top = -BALLAST_TOP_M
    w0 = BALLAST_HALF_M
    w1 = w0 + BALLAST_SLOPE * BALLAST_DEPTH_M
    section = [(-w1, top - BALLAST_DEPTH_M), (-w0, top), (w0, top), (w1, top - BALLAST_DEPTH_M)]
    _sweep(mesh, pts, nrm, section, MAT_BALLAST, closed=False, uv_scale=0.5, tilt=tilt)
    if room is None:
        room = (np.full(len(pts), np.inf), np.full(len(pts), np.inf))
    for lo, hi in _bridge_runs(pts, bridge):        # a concrete slab under the ballast on bridges, parapets, piers
        _hw, dep = BRIDGE_SLAB
        _deck_sides(pts, nrm, lo, hi, room, top - 0.05, top - dep, mesh, tilt, top + BRIDGE_PARAPET[1])
        if ground is not None:
            _bridge_piers(mesh, pts[lo:hi], nrm[lo:hi], top - dep, ground, avoid)
            _abutments(mesh, pts, nrm, top - dep, ground, lo, hi)


# The collision of a track is its own coarser line (the user's run, 2026-10-24: 5-22 s per static collision rebuild
# once big collision meshes were in, a railcol of a station tile 20k triangles): the samples a straight box between
# them keeps within COL_TOL_M of (x, y, z, and the cant's lift of the rail), at most COL_MAX_SEG_M apart, and the
# mesh in parts of at most COL_MAX_VERTS vertices (~2x as many triangles; upstream's own collision meshes stay under
# ~5k triangles each).
COL_TOL_M = 0.01
COL_MAX_SEG_M = 24.0
COL_MAX_VERTS = 2400
COL_PARTS_MAX = 12


def simplify_keep(pts, tilt=None, extra=(), tol=COL_TOL_M, max_seg=COL_MAX_SEG_M):
    """Sorted indices of the samples of a track line pts (k, 3) to keep (Douglas-Peucker on x, y, z and the cant's
    lift over the rail span; its ends, `extra` and every max_seg m kept). Pure."""
    n = len(pts)
    if n <= 2:
        return np.arange(n)
    v = np.c_[pts[:, :3], (np.zeros(n) if tilt is None else np.asarray(tilt) * CANT_SPAN_M)]
    keep = np.zeros(n, bool)
    keep[0] = keep[-1] = True
    for e in extra:
        if 0 <= e < n:
            keep[e] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        ab = v[b] - v[a]
        L2 = float((ab * ab).sum())
        w = v[a + 1:b] - v[a]
        t = np.clip((w @ ab) / L2, 0.0, 1.0) if L2 > 1e-12 else np.zeros(len(w))
        d = np.linalg.norm(w - t[:, None] * ab, axis=1)
        i = int(np.argmax(d))
        seg = float(np.hypot(*(pts[b, :2] - pts[a, :2])))
        if d[i] > tol or seg > max_seg:
            m = a + 1 + i if d[i] > tol else (a + b) // 2
            keep[m] = True
            stack += [(a, m), (m, b)]
    inner = [k for k in np.flatnonzero(keep)]
    return np.asarray(inner, np.int64)


PIER_ROAD_M = 1.5           # m a viaduct's pier keeps off the carriageway of a road under it (1.6.3's railways.py:
#                             "a pier stood in the lanes of a road under a rail bridge")
PIER_TRACK_M = 2.5          # m off the centre line of another track under it (its train's envelope, ~1.7 m, and room)


def _pier_clear(c, avoid):
    """Per pier centre c (n, 2): clear of every avoid line [(xy (k, 2), m from its centre line)] by the pier's own
    half diagonal too. Pure."""
    ok = np.ones(len(c), bool)
    if not len(c):
        return ok
    half = float(np.hypot(*BRIDGE_PIER)) / 2
    for line, clear in avoid:
        line = np.asarray(line, np.float64)[:, :2]
        if len(line) < 2:
            continue
        lo, hi = line.min(0) - clear - half, line.max(0) + clear + half
        inb = ((c >= lo) & (c <= hi)).all(1)
        if not inb.any():
            continue
        a, b = line[:-1], line[1:]
        d = b - a
        L2 = np.maximum((d * d).sum(1), 1e-12)
        cc = c[inb]
        t = np.clip(((cc[:, None, :] - a[None]) * d[None]).sum(2) / L2[None], 0.0, 1.0)
        dist = np.hypot(*(cc[:, None, :] - (a[None] + t[..., None] * d[None])).transpose(2, 0, 1)).min(1)
        ok[np.flatnonzero(inb)[dist <= clear + half]] = False
    return ok


def _bridge_piers(mesh, pts, nrm, under, ground, avoid=()):
    """Piers every BRIDGE_PIER_EVERY_M along a bridge run (not within half that of its ends: the abutments), from the
    slab's underside (`under`, m from the rail top) down BRIDGE_PIER_FOOT_M into the ground; none on what runs under
    the bridge (avoid: [(line, clearance)]: the roads' carriageways + PIER_ROAD_M, the other tracks + PIER_TRACK_M)."""
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts[:, :2], axis=0).T))]
    L = float(s[-1])
    n = int(L // BRIDGE_PIER_EVERY_M)
    if n < 1:
        return
    at = np.linspace(0.0, L, n + 2)[1:-1]
    cx, cy = np.interp(at, s, pts[:, 0]), np.interp(at, s, pts[:, 1])
    top = np.interp(at, s, pts[:, 2]) + under
    g = ground.z(cx, cy)
    clear = _pier_clear(np.c_[cx, cy], avoid) if avoid else np.ones(len(at), bool)
    for i in range(len(at)):
        if top[i] - g[i] < BRIDGE_PIER_MIN_M or not clear[i]:
            continue
        j = int(np.clip(np.searchsorted(s, at[i]), 1, len(s) - 1))
        nl = nrm[j]
        t = np.array([nl[1], -nl[0]])
        a, w = BRIDGE_PIER[0] / 2, BRIDGE_PIER[1] / 2
        c = np.array([cx[i], cy[i]])
        quad = [c - t * a - nl * w, c + t * a - nl * w, c + t * a + nl * w, c - t * a + nl * w]
        zt, zb = top[i], g[i] - BRIDGE_PIER_FOOT_M
        P = np.array([[*q, zt] for q in quad] + [[*q, zb] for q in quad])
        T = np.array([[0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2], [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]])
        UV = np.array([[0, 0], [0.5, 0], [1, 0], [1.5, 0], [0, (zt - zb) / 4], [0.5, (zt - zb) / 4],
                       [1, (zt - zb) / 4], [1.5, (zt - zb) / 4]])
        mesh.add(P, T, UV, MAT_CONCRETE, inside=np.repeat([[cx[i], cy[i], (zt + zb) / 2]], len(T), axis=0))


# Catenary (overhead line, drawn only: a pantograph never touches it in the game, and a mast between two tracks would
# stop a train on the other). Overture's rail data names no electrification (its rail_flags are not in upstream's
# map data), so it is a setting: BNGE_RAIL_CATENARY on (the default: every main line class, most of Europe's are
# electrified) or off. A mast every CAT_SPAN_M on the side of the track with the most room (away from the
# neighbouring tracks), its bracket over the track, the contact wire CAT_WIRE_M over the rail top and the messenger
# wire CAT_MESSENGER_M; in tunnels the wires alone (hung from the vault).
CATENARY_CLASSES = {"standard_gauge", "light_rail"}
CAT_SPAN_M = 55.0
CAT_MAST_OFF_M = 3.1            # m from the track's centre to a mast's
CAT_MAST_H_M = 7.6              # m over the rail top
CAT_MAST_W_M = 0.30
CAT_MAST_ROOM_M = 3.2           # m a mast keeps from every other track's centre (a train's half width 1.6 + its
#                                 clearance; 2 m set masts between a yard's tracks, the user's run 2026-10-25)
CAT_WIRE_M = 5.5
CAT_MESSENGER_M = 6.7
CAT_WIRE_D_M = 0.025            # a wire's drawn thickness (thicker than life: seen from the cab)


def catenary_on():
    return _on("BNGE_RAIL_CATENARY")


def _catenary(mesh, pts, nrm, kind, tilt, others, arc=None, own=None):
    """The overhead line of a track piece (see above). others: the other tracks' centre lines [(k, 2)] (the masts on
    the side away from them); arc (k,): the samples' arc length along their mapped segment (the masts at its whole
    multiples of CAT_SPAN_M: the same masts in every tile)."""
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts[:, :2], axis=0).T))]
    if s[-1] < 2.0:
        return
    if arc is None:
        arc = s
    arc = np.asarray(arc, np.float64)
    tl = np.zeros(len(pts)) if tilt is None else np.asarray(tilt)
    d = CAT_WIRE_D_M
    for h in (CAT_WIRE_M, CAT_MESSENGER_M):        # the wires: thin boxes along the track (cant: they follow it)
        _box_strip(mesh, pts, nrm, -d, d, h + d, h - d, MAT_STEEL, tl)
    lo, hi = float(min(arc[0], arc[-1])), float(max(arc[0], arc[-1]))
    for a in np.arange(math.ceil(lo / CAT_SPAN_M) * CAT_SPAN_M, hi, CAT_SPAN_M):
        j = int(np.argmin(np.abs(arc - a)))
        if kind is not None and int(np.asarray(kind)[j]) == 2:
            continue                                # (in a tunnel: hung from the vault)
        c = pts[j]
        if own is not None and not (own[0] <= c[0] < own[2] and own[1] <= c[1] < own[3]):
            continue                                # (a mast in the overlap: the neighbouring tile's)
        nl = nrm[j]
        side = 1.0
        if others:
            room = []
            for sg in (1.0, -1.0):
                p = c[:2] + nl * sg * CAT_MAST_OFF_M
                room.append(min(float(np.hypot(*(o - p).T).min()) for o in others if len(o)))
            side = 1.0 if room[0] >= room[1] else -1.0
            if max(room) < CAT_MAST_ROOM_M:
                continue                            # (no room between the tracks: the next span's mast)
        t = np.array([nl[1], -nl[0]])
        w = CAT_MAST_W_M / 2
        base = c[:2] + nl * side * CAT_MAST_OFF_M
        z0 = c[2] - 1.0
        z1 = c[2] + CAT_MAST_H_M
        quad = [base - t * w - nl * w, base + t * w - nl * w, base + t * w + nl * w, base - t * w + nl * w]
        P = np.array([[*q, z1] for q in quad] + [[*q, z0] for q in quad])
        T = np.array([[0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2], [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0],
                      [0, 1, 2], [0, 2, 3]])
        UV = np.array([[0, 0], [0.1, 0], [0.2, 0], [0.3, 0], [0, 2], [0.1, 2], [0.2, 2], [0.3, 2]])
        mesh.add(P, T, UV, MAT_STEEL, inside=np.repeat([[*base, (z0 + z1) / 2]], len(T), axis=0))
        arm = np.array([[*(base + t * 0.05), c[2] + CAT_MESSENGER_M + 0.3], [*(c[:2] + t * 0.05), c[2] +
                        CAT_MESSENGER_M + 0.3]])
        an = np.array([side * t, side * t])         # (the arm's own left: it runs from the mast toward the track)
        _box_strip(mesh, arm, an, -0.06, 0.06, 0.06, -0.06, MAT_STEEL)


# --- turnouts and level crossings ---------------------------------------------------------------------------------

def _grow(mask):
    """mask with one more sample at each end of its runs."""
    m = np.asarray(mask, bool)
    out = m.copy()
    out[1:] |= m[:-1]
    out[:-1] |= m[1:]
    return out


def _rail_runs(mesh, idx, pts, nrm, tl, lat0, lat1):
    """One rail's collision boxes over the runs of the sample indices idx."""
    for part in (np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1) if len(idx) else []):
        if len(part) >= 2:
            sub = part[simplify_keep(pts[part], tl[part])]
            _box_strip(mesh, pts[sub], nrm[sub], lat0, lat1, 0.0, -RAIL_COL_DEPTH, MAT_STEEL, tl[sub])


def frog_mask(rail_xy, own, centres):
    """Per rail sample: True where its collision is kept (not inside another track's gauge). rail_xy (n, 2), own: the
    index of its track; centres: [(xy (k, 2), track index)] of every track in the tile. Pure."""
    return other_dist(rail_xy, own, centres) >= GAUGE_M / 2 - FROG_MARGIN_M


def other_dist(rail_xy, own, centres, reach=3.0):
    """Per sample of rail_xy (n, 2): the distance to the nearest centre line of the other tracks (centres: [(xy,
    track index)], own's left out); inf where none within the box's `reach` m. Pure."""
    out = np.full(len(rail_xy), np.inf)
    for xy, idx in centres:
        if idx == own or len(xy) < 2:
            continue
        lo = rail_xy.min(axis=0) - reach
        hi = rail_xy.max(axis=0) + reach
        if (xy[:, 0].max() < lo[0] or xy[:, 0].min() > hi[0] or xy[:, 1].max() < lo[1] or xy[:, 1].min() > hi[1]):
            continue
        a, b = xy[:-1], xy[1:]
        ab = b - a
        L2 = np.maximum((ab ** 2).sum(axis=1), 1e-12)
        for k0 in range(0, len(rail_xy), 512):
            p = rail_xy[k0:k0 + 512]
            t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(-1) / L2[None], 0, 1)
            d = np.hypot(*(p[:, None, :] - (a[None] + t[..., None] * ab[None])).transpose(2, 0, 1)).min(axis=1)
            out[k0:k0 + 512] = np.minimum(out[k0:k0 + 512], d)
    return out


def contact_line(pts, mask, every=3):
    """The track's centre line (flat x, y, cm) round the samples of mask, CT_LINE_M either side, every `every`-th
    sample: [[x, y, x, y, ...], ...] one per run. Pure."""
    if not mask.any():
        return []
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts[:, :2], axis=0).T))]
    out = []
    idx = np.flatnonzero(mask)
    for part in np.split(idx, np.flatnonzero(np.diff(idx) > 1) + 1):
        sel = np.flatnonzero((s >= s[part[0]] - CT_LINE_M) & (s <= s[part[-1]] + CT_LINE_M))
        sel = np.r_[sel[::every], sel[-1]] if len(sel) > 1 else sel
        out.append([round(float(v), 2) for v in pts[sel, :2].ravel()])
    return out


def _seg_intersections(p, q):
    """All intersections of polylines p (n, 2) and q (m, 2): [(i, ti, j, uj)] segment indices and parameters. Pure."""
    a, b = p[:-1], p[1:]
    c, d = q[:-1], q[1:]
    r = b - a
    s = d - c
    den = r[:, None, 0] * s[None, :, 1] - r[:, None, 1] * s[None, :, 0]
    ca = c[None, :, :] - a[:, None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (ca[..., 0] * s[None, :, 1] - ca[..., 1] * s[None, :, 0]) / den
        u = (ca[..., 0] * r[:, None, 1] - ca[..., 1] * r[:, None, 0]) / den
    hit = (np.abs(den) > 1e-9) & (t >= 0) & (t <= 1) & (u >= 0) & (u <= 1)
    i, j = np.nonzero(hit)
    return [(int(ii), float(t[ii, jj]), int(jj), float(u[ii, jj])) for ii, jj in zip(i, j)]


def road_lines(cells, frame, near):
    """[(fid, xy (k, 2), carriageway half width)] of the ground roads near box `near`: the level crossing candidates.
    From the map data (not the tile's chunks), so every tile whose profiling window holds a crossing sees it the same
    way (its track eases to the crossing's height over X_PIN_BLEND_M, across tile seams). near is widened by
    ROAD_REACH_M: a window profiles its tracks past its box (TUNNEL_PORTAL_REACH_M past a portal), and a road crossing
    them there is the same road for every window (a bridge over the track by the Folkestone portals, outside one road
    tile's box and inside its neighbour's, made a 1.7 m step between the two, 2026-10-25)."""
    import mapgeom
    import roads
    near = _road_box(near)
    out, seen = [], set()
    for feats in cells:
        if feats is None or len(feats) == 0 or "subtype" not in feats.attrs:
            continue
        specs = roads.road_specs(feats, None, None, False)
        boxes = feats.boxes(frame)
        for i, sp in enumerate(specs):
            if sp is None or str(feats.ids[i]) in seen:
                continue
            seen.add(str(feats.ids[i]))
            fb = boxes[i]
            if fb[2] < near[0] or fb[0] > near[2] or fb[3] < near[1] or fb[1] > near[3]:
                continue
            for ring in roads.ground_parts(feats, i):
                e, n = mapgeom.enu_xy(feats, frame, ring)
                out.append((str(feats.ids[i]), np.c_[e, n], float(sp.width) / 2))
    return sorted(out, key=lambda r: r[0])


def crossings_on(xy, s, roads_near):
    """The level crossings of a sampled track (xy (n, 2), arc lengths s): dicts s (m along it), at, t (its unit
    direction), n (left normal), road (fid), half (m of slab either side along the track), sorted by s. Pure."""
    out = []
    if len(xy) < 2:
        return out
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    for fid, q, half_w in roads_near:
        if len(q) < 2:
            continue
        if q[:, 0].max() < lo[0] or q[:, 0].min() > hi[0] or q[:, 1].max() < lo[1] or q[:, 1].min() > hi[1]:
            continue                                # (a road nowhere near: most of a cell's)
        qlo, qhi = q.min(axis=0), q.max(axis=0)
        near = (xy[:, 0] >= qlo[0] - 1) & (xy[:, 0] <= qhi[0] + 1) & (xy[:, 1] >= qlo[1] - 1) & (xy[:, 1] <= qhi[1] + 1)
        if not near.any():
            continue
        k0, k1 = max(int(np.flatnonzero(near)[0]) - 1, 0), min(int(np.flatnonzero(near)[-1]) + 2, len(xy))
        for i, ti, j, _ in [(i + k0, ti, j, u) for i, ti, j, u in _seg_intersections(xy[k0:k1], q)]:
            tr = xy[i + 1] - xy[i]
            tr = tr / max(np.hypot(*tr), 1e-9)
            rd = q[j + 1] - q[j]
            rd = rd / max(np.hypot(*rd), 1e-9)
            sin = abs(tr[0] * rd[1] - tr[1] * rd[0])
            if sin < 0.25:                          # (a road along the track, not across it)
                continue
            at = s[i] + ti * (s[i + 1] - s[i])
            if any(o["road"] == fid and abs(o["s"] - at) < 3.0 for o in out):
                continue
            out.append({"s": float(at), "at": xy[i] + ti * (xy[i + 1] - xy[i]), "t": tr,
                        "n": np.array([-tr[1], tr[0]]), "road": fid, "rd": rd, "hw": float(half_w),
                        "half": float(min(X_HALF_MAX_M, half_w / sin + X_END_M))})
    return sorted(out, key=lambda o: o["s"])


def _track_near(parts, at, half):
    """The profiled track (parts: [(pts (n, 3), kind)]) within `half` m along it either side of its point nearest `at`:
    (pts (m, 3), left normals (m, 2), index of the nearest), or None (no part within 2 STEP_M). Pure."""
    best = None
    at = np.asarray(at, np.float64)
    for pts, _kd in parts:
        pts = np.asarray(pts, np.float64)
        if len(pts) < 2:
            continue
        d = np.hypot(pts[:, 0] - at[0], pts[:, 1] - at[1])
        i = int(np.argmin(d))
        if d[i] <= 2 * STEP_M and (best is None or d[i] < best[0]):
            best = (float(d[i]), pts, i)
    if best is None:
        return None
    _, pts, i = best
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts[:, :2], axis=0).T))]
    sel = np.flatnonzero(np.abs(s - s[i]) <= half + 1e-6)
    if len(sel) < 2:
        return None
    seg = pts[sel[0]:sel[-1] + 1]
    return seg, normals(seg[:, :2]), i - sel[0]


def _platform(x, others, vis, col, inner, track=None, tracks=()):
    """The slabs of one track's level crossing, all into `inner` (drawn, solid only without a rail vehicle near: the
    user's runs 2026-10-27, "passage a niveau toujours aussi pourri ... desactive les collisions du PN quand on s'en
    approche": the outer slabs and ramps, always solid, still caught a bogie or a snowplow; vis and col are left alone). Towards a neighbouring track of the same crossing
    (parallel tracks: x's cluster in `others`) the outer slab runs to half way, one platform over all the tracks; on an
    outer side it ends in a ramp down to the road. With `track` (_track_near: the profiled track along the crossing)
    the slabs follow it, its curve and its rail top sample by sample; else a straight strip at x["z"]."""
    _, C, _, _ = profile()
    # (arrays: the shared profiles' disk cache gives them back as lists, 2026-10-25: "can't multiply sequence by
    # non-int of type 'float'" lost whole road tiles' tracks)
    p, t, nrm = (np.asarray(x[k], np.float64) for k in ("at", "t", "n"))
    zr, zd = float(x["z"]), float(x["z_road"])
    hl = x["half"]
    if track is not None:
        # (a straight strip at the centre's height stood over the rail top where the track curves or climbs: up to
        # 0.18 m at a crossing's ends on a 1 % grade, under a WLD FS30-2's snowplow (0.13 m over the rail top), the
        # user's run 2026-10-25: "le WLD ne passe pas les passages a niveau"; a TEM2 clears 0.20 m)
        pts, nn, ic = track
        if float(np.dot(nn[ic], nrm)) < 0:          # (the crossing's normal: the side of the others' offsets)
            nn = -nn
        nrm = nn[ic]
    else:
        pts = np.array([[*(p - t * hl), zr], [*(p + t * hl), zr]])
        nn = np.array([nrm, nrm])
    gi = GAUGE_M / 2 - X_FLANGEWAY_M
    _box_strip(inner, pts, nn, -gi, gi, 0.0, -X_SLAB_DEPTH_M, MAT_CONCRETE)
    go = GAUGE_M / 2 + C
    drop = zd + 0.02 - zr                           # (negative: the road lies under the rail top)
    run = float(np.clip(abs(drop) / X_RAMP_GRADE, X_RAMP_M, X_RAMP_MAX_M))    # (a higher platform: longer)
    for sgn in (-1.0, 1.0):
        lat = [float(np.dot(np.asarray(o["at"]) - p, nrm)) for o in others]
        near_side = [abs(d) for d in lat if sgn * d > 2 * go and abs(d) <= X_CLUSTER_M]
        # each sample's room on this side: up to the next track's outer rail edge (any track: a crossing's
        # neighbour, a turnout's other route converging, a siding), never into its rails or its gauge (a straight
        # "half way" taken at the centre ran into a converging track's gauge at the slab's ends, at rail-top height:
        # a WLD's bogie hit it, the user's run 2026-10-26 "parfois ca ne touche qu'une seule bogie")
        free = _side_free(pts[:, :2], nn, sgn, tracks or ()) - go - X_SLAB_GAP_M
        if near_side:                               # a neighbouring track: the platform spans the gap (to it)
            want, ramp_too = min(near_side) - go - X_SLAB_GAP_M, False
        else:
            want, ramp_too = go + X_OUTER_M, True
        for i in range(len(pts) - 1):
            seg, sn = pts[i:i + 2], nn[i:i + 2]
            room = float(min(free[i], free[i + 1]))
            b = min(want, room)
            if b > go + 0.05:
                a0, b0 = sorted((sgn * go, sgn * b))
                _box_strip(inner, seg, sn, a0, b0, 0.0, -X_SLAB_DEPTH_M, MAT_CONCRETE)
            if not ramp_too or room <= go + X_OUTER_M + 0.05:
                continue
            r_end = min(go + X_OUTER_M + run, room)
            dr = drop * (r_end - go - X_OUTER_M) / run
            r0, r1 = sgn * (go + X_OUTER_M), sgn * r_end
            ramp = [(r0, 0.0), (r1, dr), (r1, dr - X_SLAB_DEPTH_M), (r0, -X_SLAB_DEPTH_M)]
            _sweep(inner, seg, sn, ramp, MAT_CONCRETE, closed=True, caps=True)


X_SLAB_GAP_M = 0.05         # m a crossing's slab keeps off another track's outer rail edge


def crossing_bar(x, others):
    """A road's level crossing over one or more parallel tracks (x and its cluster `others`, build's), for the mod's
    barriers and lights (nrailsxing.lua): one row per crossing, made by the cluster's first track (fid order; None for
    the others). at: the centre on the road (x, y, the road's z), rd: the road's unit direction, hw: its half width,
    d0 / d1: m along rd from the centre to the outer edges of the outermost tracks, tr: the track's direction. Pure."""
    rd = x.get("rd")
    if rd is None:
        return None
    if any(str(o.get("fid")) < str(x.get("fid")) for o in others):
        return None
    rd = np.asarray(rd, np.float64)
    members = [x] + list(others)
    at = np.mean([np.asarray(m["at"], np.float64) for m in members], axis=0)
    d = [float(np.dot(np.asarray(m["at"], np.float64) - at, rd)) for m in members]
    tr = np.asarray(x["t"], np.float64)
    sin = max(abs(tr[0] * rd[1] - tr[1] * rd[0]), 0.25)
    foot = (GAUGE_M / 2 + profile()[1] + X_OUTER_M) / sin     # (a track's platform along the road)
    return {"at": [round(float(at[0]), 2), round(float(at[1]), 2), round(float(x["z_road"]), 2)],
            "rd": [round(float(rd[0]), 4), round(float(rd[1]), 4)], "hw": round(float(x.get("hw", 3.0)), 2),
            "d0": round(min(d) - foot, 2), "d1": round(max(d) + foot, 2),
            "tr": [round(float(tr[0]), 4), round(float(tr[1]), 4)], "z": round(float(x["z"]), 2)}


def _side_free(xy, nn, sgn, tracks, reach=None):
    """Per sample of xy (m, 2) with left normals nn: the distance along sgn * normal to the nearest of the other
    tracks' centre lines (tracks: [(k, 2)]), inf where none within reach (X_CLUSTER_M + 2 m). Pure."""
    reach = X_CLUSTER_M + 2.0 if reach is None else reach
    out = np.full(len(xy), np.inf)
    if not len(tracks):
        return out
    d = sgn * np.asarray(nn, np.float64)
    lo, hi = xy.min(axis=0) - reach, xy.max(axis=0) + reach
    for line in tracks:
        line = np.asarray(line, np.float64)[:, :2]
        if len(line) < 2:
            continue
        keep = (line[:, 0] >= lo[0]) & (line[:, 0] <= hi[0]) & (line[:, 1] >= lo[1]) & (line[:, 1] <= hi[1])
        if not keep.any():
            continue
        idx = np.flatnonzero(keep)
        i0, i1 = max(int(idx[0]) - 1, 0), min(int(idx[-1]) + 2, len(line))
        a, e = line[i0:i1 - 1], np.diff(line[i0:i1], axis=0)
        if not len(a):
            continue
        ap = a[None, :, :] - xy[:, None, :]                 # (m, s, 2)
        den = d[:, None, 0] * e[None, :, 1] - d[:, None, 1] * e[None, :, 0]
        ok = np.abs(den) > 1e-9
        den = np.where(ok, den, 1.0)
        t = (ap[..., 0] * e[None, :, 1] - ap[..., 1] * e[None, :, 0]) / den
        u = (ap[..., 0] * d[:, None, 1] - ap[..., 1] * d[:, None, 0]) / den
        hit = ok & (u >= 0) & (u <= 1) & (t > 0) & (t <= reach)
        if hit.any():
            out = np.minimum(out, np.where(hit, t, np.inf).min(axis=1))
    return out


# --- the tile -----------------------------------------------------------------------------------------------------

def rail_priority(cells):
    """{fid: score} of the rail segments in cells: 1 for a named line (OSM's main lines, drawn dark, carry the line's
    name; its sidings, yards and spurs seldom do), else 0. Pure."""
    out = {}
    for feats in cells:
        if feats is None or len(feats) == 0 or "subtype" not in feats.attrs:
            continue
        sub, names = feats.attrs["subtype"], feats.attrs.get("name")
        for i in range(len(feats)):
            if str(sub[i]) != "rail":
                continue
            nm = "" if names is None else str(names[i] or "")
            out[str(feats.ids[i])] = 1.0 if nm.strip() and nm.lower() not in ("nan", "none") else 0.0
    return out


def rail_features(cells, frame, near):
    """[(fid, class, xy (k, 2) ring, ranges)] of the rail segments near box `near`, once per id, sorted by id."""
    import mapgeom
    import roads
    seen = {}
    for feats in cells:
        if feats is None or len(feats) == 0 or "subtype" not in feats.attrs:
            continue
        sub = feats.attrs["subtype"]
        cls = feats.attrs.get("class")
        boxes = feats.boxes(frame)
        for i in range(len(feats)):
            if str(sub[i]) != "rail":
                continue
            fid = str(feats.ids[i])
            if fid in seen:
                continue
            c = str(cls[i]) if cls is not None else "standard_gauge"
            if c not in HEAVY_CLASSES and c not in TRAM_CLASSES:
                continue
            fb = boxes[i]
            if fb[2] < near[0] or fb[0] > near[2] or fb[3] < near[1] or fb[1] > near[3]:
                continue
            if rail_gone(feats, i):
                continue
            rings = [ring for part in feats.parts(i) for ring in part if len(ring) >= 2]
            if not rings:
                continue
            e, n = mapgeom.enu_xy(feats, frame, rings[0])
            seen[fid] = (fid, c, np.c_[e, n], rail_ranges(feats, i))
    return _drop_stubs([seen[k] for k in sorted(seen)])


# (from BeamNG.Earth 1.6.3's railways.py, mpsteppe's PR #287, with NRails' tunnels in mind)
SHORT_TUNNEL_M = 60.0       # m: a tunnel range this short inside a segment, open track either side of it, is the line
#                             under a road bridge (OSM tags those tunnel=yes / layer=-1): open track there, no tube (the
#                             road's deck over it clears it: nrails.decks). A tunnel range at a segment's end is kept: it
#                             may be one piece of a long tunnel mapped as several segments (a gap in a mountain else).
GONE_FLAGS = ("is_abandoned",)  # Overture's rail_flags (1.6.3's map data): no track left. Not is_disused (unlike 1.6.3):
#                             a disused line mostly keeps its rails, and a train may go and explore it.
MIN_LINE_M = 50.0           # m: connected track shorter than this left out (a siding's piece cut off by its abandoned
#                             rest, 12 m under a bridge on its own: 1.6.3's)


def rail_ranges(feats, i):
    """roads.level_ranges of rail feature i, its short inner tunnels (SHORT_TUNNEL_M) taken as open track."""
    import roads
    rngs = roads.level_ranges(feats, i)
    if not any(k == "tunnel" for _a, _b, k in rngs):
        return rngs
    L = roads._feature_length_m(feats, i)
    eps = 1e-6
    return [(a, b, k) for a, b, k in rngs
            if not (k == "tunnel" and a > eps and b < 1.0 - eps and (b - a) * L < SHORT_TUNNEL_M)]


def rail_ground_parts(feats, i):
    """The on-ground pieces of rail feature i (lon/lat polylines): roads.ground_parts, with rail_ranges' open short
    tunnels on the ground."""
    import roads
    rngs = rail_ranges(feats, i)
    if len(rngs) == len(roads.level_ranges(feats, i)):
        return roads.ground_parts(feats, i)
    spans, at = [], 0.0
    for a, b, _k in rngs:
        if a - at > roads.MIN_PART:
            spans.append((at, a))
        at = max(at, b)
    if 1.0 - at > roads.MIN_PART:
        spans.append((at, 1.0))
    out = []
    for part in feats.parts(i):
        for ring in part:
            if len(ring) < 2:
                continue
            for a, b in spans:
                r = ring if (a, b) == (0.0, 1.0) else roads.sub_polyline(ring, a, b)
                if len(r) >= 2:
                    out.append(r)
    return out


def rail_gone(feats, i):
    """Is rail feature i abandoned (GONE_FLAGS) over most of its length (1.6.3's map data: its rail_flags)?"""
    rules = getattr(feats, "rules", None)
    t = rules.get("flags") if rules is not None else None
    if t is None or len(t.feature) == 0:
        return False
    return sum(float(t.end[j]) - float(t.start[j]) for j in t.rows(i)
               if any(g in str(t.value[j]) for g in GONE_FLAGS)) > 0.5


def _drop_stubs(feats):
    """rail_features' rows without the connected groups of segments (ends within 0.5 m) shorter than MIN_LINE_M."""
    if len(feats) < 1:
        return feats
    import roads
    nodes, edges, _adj = roads._chain_graph([np.asarray(xy, np.float64) for _f, _c, xy, _r in feats])
    parent = list(range(len(nodes)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b, _s in edges:
        parent[find(a)] = find(b)
    total = {}
    for a, _b, s in edges:
        total[find(a)] = total.get(find(a), 0.0) + float(s[-1])
    return [f for f, (a, _b, _s) in zip(feats, edges) if total[find(a)] >= MIN_LINE_M]


# --- tunnels ------------------------------------------------------------------------------------------------------

CHAIN_CELLS_MAX = 96            # map cells read at most to close the tunnel chains of a window (more_cells: the
#                                 Channel Tunnel's 50 km, with TUNNEL_PORTAL_REACH_M round it)


FEATURE_REACH_M = TUNNEL_SPAN_MAX_M     # m round a window its cells' rail segments are listed (a whole tunnel chain)


def _feature_box(near):
    r = FEATURE_REACH_M
    return (near[0] - r, near[1] - r, near[2] + r, near[3] + r)


def tunnel_cell_keys(cells):
    """The map cell keys under the tunnels of the rail segments in cells (and TUNNEL_PORTAL_REACH_M past their
    portals): the cells a window must read so that every tunnel chain reaching into it is whole (its other segments,
    the track past its far portal). Pure."""
    import mapcells
    import roads
    keys = set()
    for feats in cells:
        if feats is None or len(feats) == 0 or "subtype" not in feats.attrs:
            continue
        sub = feats.attrs["subtype"]
        for i in range(len(feats)):
            if str(sub[i]) != "rail":
                continue
            ranges = [r for r in rail_ranges(feats, i) if r[2] == "tunnel"]
            if not ranges:
                continue
            for part in feats.parts(i):
                for ring in part:
                    ring = np.asarray(ring, np.float64)
                    if len(ring) < 2:
                        continue
                    pad = TUNNEL_PORTAL_REACH_M / 111320.0
                    lat = ring[:, 1]
                    padlon = pad / max(0.05, math.cos(math.radians(float(np.mean(lat)))))
                    keys |= set(mapcells.cells_for_points(lat, ring[:, 0], pad, padlon))
    return keys


def more_cells(keys, cell_fn, cells=None, have=None):
    """{key: cell} of keys and the cells their tunnel chains need (tunnel_cell_keys, repeated until closed, up to
    CHAIN_CELLS_MAX more). cell_fn(key) -> a cell's "roads" layer (None on failure). have(key) -> whether a cell is
    already cached: the chains' extra cells are read only then (a cell not cached is a download, seconds to tens of
    seconds each: a terrain block waited on them and the game on its block, 2026-10-24); None: all are read."""
    got = dict(cells or {})
    for k in keys:
        if k not in got:
            got[k] = cell_fn(k)
    extra = 0
    for _ in range(6):
        want = [k for k in sorted(tunnel_cell_keys(list(got.values())), key=str) if k not in got]
        if have is not None:
            want = [k for k in want if have(k)]
        if not want:
            break
        for k in want[:max(0, CHAIN_CELLS_MAX - extra)]:
            got[k] = cell_fn(k)
            extra += 1
        if extra >= CHAIN_CELLS_MAX:
            break
    return got


def _near_edge(p, box, tol):
    x0, y0, x1, y1 = box
    return min(p[0] - x0, x1 - p[0], p[1] - y0, y1 - p[1]) < tol


def tunnel_tubes(heavy, box, ground=None):
    """The tubes round the tunnel samples of the heavy track pieces [(track index, pts (k, 3), kind (k,))]: dicts xy
    (k, 2) centre line, z (k,) floor, w (m of floor between the shoulders), portal (at its first / last point: the
    track goes on in the open there; not where a piece was cut at box's edge or where another tunnel run goes on),
    up (m of portal face over the vault: the ground over it, read 10 m in; None without ground). Tracks in tunnels
    within TUNNEL_TWIN_M of each other share one tube round both (centre between them, as wide as both). Pure given
    ground."""
    runs = []
    for k, pts, kind in heavy:
        for run in _runs(np.asarray(kind) == 2):
            lo, hi = int(run[0]), int(run[-1])
            if hi - lo < 1:
                continue
            runs.append({"k": k, "pts": pts[lo:hi + 1], "open": (lo > 0, hi < len(pts) - 1), "skip": None})
    if not runs:
        return []

    def portal(r, e):
        if r["open"][e]:
            return True                             # the same piece goes on in the open
        p = r["pts"][0 if e == 0 else -1, :2]
        if _near_edge(p, box, 1.5 * STEP_M):
            return False                            # cut at the tile's / block's edge
        for o in runs:
            if o is r:
                continue
            for q in (o["pts"][0, :2], o["pts"][-1, :2]):
                if np.hypot(*(q - p)) <= NODE_TOL_M + STEP_M:
                    return False                    # another tunnel run goes on from here
        return True

    def nearest(p, q):
        """Distances from points p (n, 2) to polyline q (m, 2) and the nearest points on it."""
        a, b = q[:-1], q[1:]
        ab = b - a
        L2 = np.maximum((ab * ab).sum(1), 1e-12)
        t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(-1) / L2[None], 0.0, 1.0)
        c = a[None] + t[..., None] * ab[None]
        d = np.hypot(*(p[:, None, :] - c).transpose(2, 0, 1))
        j = np.argmin(d, axis=1)
        return d[np.arange(len(p)), j], c[np.arange(len(p)), j]

    tubes = []
    for i, r in enumerate(runs):
        if r["skip"] is not None and r["skip"].all():
            continue
        xy, z = r["pts"][:, :2].copy(), r["pts"][:, 2].copy()
        w = np.full(len(xy), TUNNEL_TRACK_W)
        for j, o in enumerate(runs):                # a twin track: one tube round both
            if j <= i or len(o["pts"]) < 2:
                continue
            d, c = nearest(r["pts"][:, :2], o["pts"][:, :2])
            twin = (d > 0.5) & (d <= TUNNEL_TWIN_M)
            if twin.mean() < 0.5:
                continue
            xy[twin] = (xy[twin] + c[twin]) / 2
            w[twin] = TUNNEL_TRACK_W + d[twin]
            back, _ = nearest(o["pts"][:, :2], r["pts"][:, :2])
            o["skip"] = back <= TUNNEL_TWIN_M if o["skip"] is None else (o["skip"] | (back <= TUNNEL_TWIN_M))
            break
        keep = np.ones(len(xy), bool) if r["skip"] is None else ~r["skip"]
        for part in _runs(keep):
            if len(part) < 2:
                continue
            first, last = part[0] == 0, part[-1] == len(xy) - 1
            tube = {"xy": xy[part], "z": z[part] - TUNNEL_FLOOR_M, "w": float(np.median(w[part])),
                    "portal": (first and portal(r, 0), last and portal(r, 1)), "up": (None, None)}
            if ground is not None:
                ups = []
                for e, at in ((0, 0), (1, -1)):
                    if not tube["portal"][e]:
                        ups.append(None)
                        continue
                    p, q = tube["xy"][at], tube["xy"][1 if at == 0 else -2]
                    t = (q - p) / max(float(np.hypot(*(q - p))), 1e-9)
                    # (the highest ground over the mouth's cut, mouth_reach's: the face hides it all from the front)
                    inn = p[None] + t[None] * np.arange(2.0, PORTAL_UP_READ_M + 0.1, 2.0)[:, None]
                    gz = float(np.max(ground.z(inn[:, 0], inn[:, 1])))
                    ups.append(float(np.clip(gz - (tube["z"][at] + TUNNEL_H), 1.0, 15.0)))
                tube["up"] = tuple(ups)
            tubes.append(tube)
    return tubes


TUBE_SRC_M = TUNNEL_TWIN_M + 20.0  # m round a tile the tracks' tunnel runs are looked at for its tubes


def tile_tubes(pm, index, near, box, ground=None):
    """A road tile's share of the rail tunnels' tubes: the tubes made from the whole tunnel runs of every profiled
    track reaching within TUBE_SRC_M of the tile (profile_network's pieces, pm, not the tile's clipped ones), the same
    in every tile, then each cut to the samples whose centre line lies in the tile (one more either side: the pieces
    meet). A twin track's tube is so made once, round both tracks, whichever tile each track's samples fall in: two
    tracks 4.8 m apart on either side of a tile seam had their twin tube in one tile and the lone track's own tube in
    the other, a tube in a tube (LGV, the user's run 2026-10-26: "double tunnel")."""
    x0, y0, x1, y1 = box
    m = TUBE_SRC_M
    src = []
    for fid in sorted(pm):
        if fid not in index:
            continue
        for pts, kd in pm[fid]:
            kd = np.asarray(kd)
            if not (kd == 2).any():
                continue
            t = pts[kd == 2]
            if ((t[:, 0] >= x0 - m) & (t[:, 0] <= x1 + m) & (t[:, 1] >= y0 - m) & (t[:, 1] <= y1 + m)).any():
                src.append((index[fid], pts, kd.astype(np.int8)))
    if not src:
        return []
    out = []
    for t in tunnel_tubes(src, near, ground):
        xy = t["xy"]
        inside = (xy[:, 0] >= x0) & (xy[:, 0] < x1) & (xy[:, 1] >= y0) & (xy[:, 1] < y1)
        grow = inside.copy()
        grow[1:] |= inside[:-1]
        grow[:-1] |= inside[1:]
        for run in _runs(grow):
            if len(run) < 2:
                continue
            a, b = int(run[0]), int(run[-1])
            first, last = a == 0, b == len(xy) - 1
            out.append(dict(t, xy=xy[a:b + 1], z=t["z"][a:b + 1],
                            portal=(first and t["portal"][0], last and t["portal"][1]),
                            up=(t["up"][0] if first else None, t["up"][1] if last else None)))
    return out


def tube_chunks(tubes):
    """roadmesh.tunnel's chunks for the tubes (tunnel_tubes): "tunnel" decks whose floor is the tube's, portals,
    TUNNEL_H high, the portal faces up to the ground over them."""
    import roads
    out = []
    for t in tubes:
        ch = roads._chunk(roads.TUNNEL, t["w"], np.c_[t["xy"], t["z"]])
        ch.update(fixed=True, deck=True, tunnel=True, portal=list(t["portal"]), tunnel_h=TUNNEL_H,
                  portal_up=list(t["up"]))
        out.append(ch)
    return out


def tunnel_hole_mask(tubes, u, cx, cy, square):
    """Where the terrain block (heights u [iy, ix]: sample (ix, iy) at (cx - half + ix square, cy - half + iy square),
    half = n square / 2) must be a hole for the rail tunnels' tubes (tunnel_tubes): their portals' openings into the
    hillside (upstream's kernel, roads.tunnel_hole_mask's: the samples over a tube's footprint whose ground lies between
    its floor and its vault). Pure."""
    import fast
    import roadmesh
    import roads
    n = u.shape[0]
    half = n * square / 2
    mask = np.zeros(u.shape, bool)
    if not tubes:
        return mask
    fast.require(0, "tunnel_holes")
    u = np.ascontiguousarray(u, np.float64)
    for t in tubes:
        if not any(t["portal"]):
            continue
        hw = t["w"] / 2 + roadmesh.TUNNEL_SHOULDER + TUNNEL_HOLE_MARGIN_M
        fast._ef.tunnel_holes(mask, u, float(cx - half), float(cy - half), float(square),
                              np.ascontiguousarray(t["xy"], np.float64), np.ascontiguousarray(t["z"], np.float64),
                              float(hw), float(TUNNEL_H), False, bool(t["portal"][0]), bool(t["portal"][1]),
                              float(TUNNEL_HOLE_MARGIN_M), float(roads.LOW_HOLE_M + roads.LOW_HOLE_STEP),
                              float(roads.ARCH_SIDE_M + 1.0))
        # the mouths cut whatever the height (see MOUTH_CUT_*), each end on its own
        for e in (0, 1):
            if not t["portal"][e] or not _on("BNGE_RAIL_MOUTH_CUT"):
                continue
            reach = mouth_reach(t, e, u, cx - half, cy - half, square)
            fast._ef.tunnel_holes(mask, u, float(cx - half), float(cy - half), float(square),
                                  np.ascontiguousarray(t["xy"], np.float64), np.ascontiguousarray(t["z"], np.float64),
                                  float(hw), float(TUNNEL_H), True, e == 0, e == 1, float(TUNNEL_HOLE_MARGIN_M),
                                  float(reach), float(MOUTH_CUT_SIDE_M))
    return mask


# A portal's mouth (the user's run, 2026-10-24: "les entrées et sorties sont bloquées partiellement par les falaises qui
# tombent devant l'entrée ... comme si on avait mal extrudé"): the hole kernel cut the samples whose ground lay between
# the tube's floor and its vault; the terrain square from the last of them to the first sample over the vault stayed,
# a slope hanging down into the opening (one grid step: 1 to 2 m across the mouth, the whole vault on a steep face).
# Into the hill from each portal until the ground stands MOUTH_CUT_SOIL_M over the vault (and a grid step more), every
# sample over the tube's footprint is cut whatever its height: the opening is clear, the portal face (its height set to
# the highest ground over that stretch: tunnel_tubes' up) covers the cut from the front.
MOUTH_CUT_SOIL_M = 2.0          # m of ground over the vault where the mouth's cut ends
MOUTH_CUT_MIN_M = 4.0           # m into the hill the mouth is cut at least
MOUTH_CUT_MAX_M = 40.0          # ... and at most
MOUTH_CUT_SIDE_M = 0.5          # m beside the tube's footprint (shoulders + margin) the mouth's cut reaches


def _bilinear(u, x0, y0, square, xy):
    n = u.shape[0]
    fx = np.clip((xy[:, 0] - x0) / square, 0, n - 1.000001)
    fy = np.clip((xy[:, 1] - y0) / square, 0, n - 1.000001)
    ix, iy = fx.astype(int), fy.astype(int)
    ax, ay = fx - ix, fy - iy
    return (u[iy, ix] * (1 - ax) * (1 - ay) + u[iy, ix + 1] * ax * (1 - ay) + u[iy + 1, ix] * (1 - ax) * ay
            + u[iy + 1, ix + 1] * ax * ay)


def mouth_reach(t, e, u, x0, y0, square):
    """m into the hill from a tube's (tunnel_tubes) end e (0: first point, 1: last) its mouth is cut (see above): to
    where the ground (block heights u, sample (ix, iy) at (x0 + ix square, y0 + iy square)) over the tube's centre line
    first stands MOUTH_CUT_SOIL_M over its vault, plus a grid step. Pure."""
    xy, z = np.asarray(t["xy"], np.float64), np.asarray(t["z"], np.float64)
    if e == 1:
        xy, z = xy[::-1], z[::-1]
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    step = max(0.5, square / 2)
    ss = np.arange(0.0, min(float(s[-1]), MOUTH_CUT_MAX_M) + 1e-9, step)
    if len(ss) < 2:
        return MOUTH_CUT_MIN_M
    p = np.c_[np.interp(ss, s, xy[:, 0]), np.interp(ss, s, xy[:, 1])]
    g = _bilinear(np.asarray(u, np.float64), x0, y0, square, p)
    over = g >= np.interp(ss, s, z) + TUNNEL_H + MOUTH_CUT_SOIL_M
    if not over.any():          # (a shallow tube: the ground never stands over it; the floor-to-vault cut is enough)
        return MOUTH_CUT_MIN_M
    at = float(ss[int(np.argmax(over))])
    return float(np.clip(at + square, MOUTH_CUT_MIN_M, MOUTH_CUT_MAX_M))


def block_tubes(frame, cells, elev, box):
    """The rail tunnels' tubes of a terrain block's box (the same profile as the road tiles': profile_network with
    the box + NEAR_M as its window), [] when no rail tunnel is near. Pure given elev."""
    near = (box[0] - NEAR_M, box[1] - NEAR_M, box[2] + NEAR_M, box[3] + NEAR_M)
    feats = rail_features(cells, frame, _feature_box(near))
    segments = [(fid, xy, ranges) for fid, cls, xy, ranges in feats if cls in HEAVY_CLASSES]
    if not any(k == "tunnel" for _f, _xy, rg in segments for _a, _b, k in rg):
        return []
    ground = Ground(frame, elev)
    heavy = []
    roads_near, structs = (road_lines(cells, frame, near), road_structs(cells, frame, near)) \
        if _on("BNGE_RAIL_CROSSINGS") else ((), None)       # (as build: the same profile as the road tiles')
    for fid, parts in profile_network(ground, segments, near, roads_near, None, None, structs,
                                      rail_connectors(cells)).items():
        for pts, kd in parts:
            heavy.append((fid, pts, kd))
    return tunnel_tubes(heavy, near)


class RailTile:
    """vis / col: lists of mesh arrays (parts under MAX_MESH_VERTS, at most PARTS_MAX), inner: arrays or None,
    xpts: level crossing centres [x, y, z_rail], boxes: {"nrailx": [...]} (roads.collider_boxes' format)."""

    def __init__(self, vis, col, inner, xpts, boxes, lines=(), tunnel=None):
        self.vis, self.col, self.inner, self.xpts, self.boxes = vis, col, inner, xpts, boxes
        self.lines = list(lines)    # [(track index, rail-top centre line (k, 3))] of the heavy track in the tile
        self.tunnel = tunnel        # roadmesh.tunnel's mesh of the tile's rail tunnels (drawn, colliding) or None
        self.sw_shapes = []         # [("nrailswN", mesh arrays)]: the turnouts' routes' rails (nrails.switches)
        self.sig_rows = []          # the turnouts' signals for the mod (_signals)
        self.sw_rows = []           # the turnouts for the mod (switches.mod_rows)
        self.sw_need = []           # each "nrailswN" shape's turnout settings (switches.shape_rows)

    def line_rows(self, every=2):
        """The centre lines for the mod (roads.lua M.snapToRail): flat [x, y, z, x, y, z ...] per piece, every
        `every`-th sample (and the last), in the anchor frame, cm."""
        out = []
        for _, pts in self.lines:
            idx = np.r_[np.arange(0, len(pts) - 1, every), len(pts) - 1]
            out.append([round(float(v), 2) for v in pts[idx].ravel()])
        return out

    def shapes(self):
        """[(what, mesh arrays, collision_only)]: "nrail", "nrail2".., "nrailcol", "nrailcol2".., "nrailx", "nrailtun"
        ("nrail": BeamNG.Earth 1.6.3 has a "rail" kind and rail_* shape files of its own)."""
        out = []
        for stem, parts, col, cap in (("nrail", self.vis, False, PARTS_MAX), ("nrailcol", self.col, True, COL_PARTS_MAX)):
            if len(parts) > cap:
                import logging
                logging.getLogger("earthd.nrails").warning("NRails: %d %s parts, %d kept", len(parts), stem, cap)
            for k, m in enumerate(parts[:cap]):
                out.append((stem if k == 0 else f"{stem}{k + 1}", m, col))
        if self.inner is not None:
            out.append(("nrailx", self.inner, False))
        if self.tunnel is not None:
            out.append(("nrailtun", self.tunnel, False))
        for what, m in self.sw_shapes:
            out.append((what, m, True))
        for what, m in getattr(self, "ct_shapes", ()):
            out.append((what, m, True))
        return out


def build(frame, tx, ty, cells, elev, chunks=(), with_crossings=None, trams_on=None, platforms=(), cell_fn=None):
    """The rail meshes of road tile (tx, ty): a RailTile (meshes None when empty), or None without any track here.
    chunks: (unused since the level crossings come from the map data: road_lines). platforms: the mapped platforms'
    outlines near the tile (nrails.stations.platform_rings). cell_fn(key): a map cell's "roads" layer: the heavy
    tracks' heights from the map cells' shared profiles (nrails.canon); None: profiled here (tests, tools)."""
    import roads
    x0, y0, x1, y1 = roads.tile_bbox(tx, ty)
    box = (x0 - OVERLAP_M, y0 - OVERLAP_M, x1 + OVERLAP_M, y1 + OVERLAP_M)
    near = (x0 - NEAR_M, y0 - NEAR_M, x1 + NEAR_M, y1 + NEAR_M)
    # (the features of the cells round it: a tunnel chain reaching into the window is profiled whole, _tunnel_forced)
    feats = rail_features(cells, frame, _feature_box(near))
    if not feats:
        return None
    with_crossings = _on("BNGE_RAIL_CROSSINGS") if with_crossings is None else with_crossings
    trams_on = _on("BNGE_RAIL_TRAMS") if trams_on is None else trams_on
    here = with_crossings and cell_fn is None       # (profiled here, not from the cells' profiles)
    roads_near = road_lines(cells, frame, near) if here else ()
    structs = road_structs(cells, frame, near) if here else None
    conns = rail_connectors(cells)
    found = []                                      # the level crossings of every track in the window
    ground = Ground(frame, elev)
    origin = (x0, y0, 0.0)
    vis, col, inner = Mesh(origin), Mesh(origin), Mesh(origin)
    prof = profile()
    H, C, _, _ = prof
    section = rail_section(prof)
    heavy, trams = [], []                           # (track index, pts, bridge) pieces in the tile
    index = {}
    electrified = set()                             # the track indices with a catenary (_catenary)
    segments = []
    for k, (fid, cls, xy, ranges) in enumerate(feats):
        tram = cls in TRAM_CLASSES
        if tram and not trams_on:
            continue
        if tram:                                    # street track: on the ground, no smoothing or formation
            xy2, _ = resample(chaikin(xy))
            flat = np.c_[xy2, np.zeros(len(xy2))]
            for piece, br in clip_track(flat, np.zeros(len(flat), bool), box):     # (ground read in the tile only)
                piece[:, 2] = ground.z(piece[:, 0], piece[:, 1]) + TRAM_LIFT_M
                trams.append((k, piece, br))
            continue
        index[fid] = k
        segments.append((fid, xy, ranges))
        if cls in CATENARY_CLASSES and catenary_on():
            electrified.add(k)
    # the heavy tracks profiled together: one height per node, shared by every track meeting there
    tilts, parcs = [], []                           # the cant of each heavy piece (cant_tilt: on the whole window's
    xat = None                                      # track, so tiles meeting at a seam agree), its arc length
    arcs = {}
    if cell_fn is not None:
        from nrails import canon
        pm, found[:], arcs = canon.profile_box(frame, box, cell_fn, elev)
        found[:] = [dict(x) for x in found if x["fid"] in index]       # (copies: the cache's are shared)
    else:
        pm = profile_network(ground, segments, near, roads_near, found, arcs, structs, conns)
    # the turnouts (nrails.switches) reaching into the tile, and round it as far as their cant easing reaches
    sws, sw_cant = [], []
    if _on("BNGE_RAIL_SWITCHES"):
        try:
            from nrails import switches as swmod
            reach = swmod.ZONE_MAX_M + swmod.ARM_M + 2 * CANT_X_CLEAR_M + 10.0
            sw_feats = feats
            if cell_fn is not None:     # (the map cells round the tile: every node's routes whole, in every tile)
                more = [cell_fn(kk) for kk in roads.cells_of_tile(frame, tx, ty, margin=reach)]
                sw_feats = rail_features(more, frame, (x0 - 400.0, y0 - 400.0, x1 + 400.0, y1 + 400.0))
            lines = swmod.lines_of(sw_feats)
            prio = rail_priority(more if cell_fn is not None else cells)
            m = 2 * CANT_X_CLEAR_M + 5.0
            sw_near = swmod.find(lines, (x0 - m, y0 - m, x1 + m, y1 + m), prio)  # (once: the tile's are among them)
            sws = [sw for sw in sw_near if swmod.reaches(sw, box)] + swmod.find_diamonds(lines, box, prio)
            sw_cant = [q for sw in sw_near for r in sw.routes for q in r.xy[::2]]
        except Exception as e:      # noqa: BLE001 - the turnouts as before (both routes' rails, the frog mask)
            _log_once(f"turnouts: {type(e).__name__}: {e}")
            sws, sw_cant = [], []
    for fid, parts in pm.items():
        if fid not in index:
            continue
        if xat is None:
            # (no cant at level crossings nor through turnouts: a turnout's routes at different cants left the set
            # route's rails twisted against the other's, the user's run 2026-10-25: "les aiguillages ... pas prenables
            # quand les voies sont twistees")
            xat = [x["at"] for x in found] + sw_cant
        for (pts, kd), arc in zip(parts, arcs[fid]):
            kd = _auto_bridges(pts, kd, ground)          # (over a hollow: a bridge)
            aux = np.c_[kd, cant_tilt(pts[:, :2], xat), arc]
            for piece, b in clip_track(pts, aux, box):
                heavy.append((index[fid], piece, b[:, 0].astype(np.int8)))
                tilts.append(b[:, 1])
                parcs.append(b[:, 2])
    for x in found:
        x["k"] = index[x["fid"]]
    if not heavy and not trams:
        return None
    centres = [(p[:, :2], k) for k, p, _ in heavy]
    # (what a viaduct's piers keep off: the roads under it, from the map data as the crossings'; made only for a tile
    # with a bridge)
    _pa = []

    def pier_avoid():
        if not _pa:
            _pa.append([(q, hw + PIER_ROAD_M) for _f, q, hw in (roads_near or road_lines(cells, frame, near))])
        return _pa[0]
    xpts, xboxes, xbars = [], [], []
    # the turnouts reaching into the tile (sws, above): their routes' rails in shapes of their own
    sw_meshes = {}
    ct_meshes = {}                                  # track -> [Mesh, contact samples, pts] (CONTACT_M)
    fid_of = {kk: f for f, kk in index.items()}
    for (k, pts, br), tl, arc in zip(heavy, tilts, parcs):
        nrm = normals(pts[:, :2])
        room = side_room(pts, nrm, [c for c, kk in centres if kk != k])
        # the collision's own coarser line (simplify_keep): the bridge runs' ends kept
        edges = np.flatnonzero(np.diff((br == 1).astype(np.int8)) != 0)
        ck = simplify_keep(pts, tl, np.r_[edges, edges + 1])
        zk = swmod.zone_keys(pts[:, :2], fid_of.get(k), sws) if sws else [()] * len(pts)
        out_zone = np.array([not z for z in zk], bool)
        for sgn in (-1.0, 1.0):                     # the two rails, centred GAUGE/2 + C/2 off the centre line
            off = sgn * (GAUGE_M / 2 + C / 2)
            _sweep(vis, pts, nrm, section + np.array([off, 0.0]), MAT_STEEL, closed=True, uv_scale=1.0, tilt=tl)
            rail_xy = pts[:, :2] + nrm * off
            dmin = other_dist(rail_xy, k, centres)
            keep = dmin >= GAUGE_M / 2 - FROG_MARGIN_M
            lat0, lat1 = sorted((sgn * GAUGE_M / 2, sgn * (GAUGE_M / 2 + C)))
            # (the rails outside the turnouts' zones as before, but those in contact with another track (CONTACT_M):
            # a shape of their own per track; a run touching a zone takes one sample of it: no gap)
            cmask = out_zone & (dmin < CONTACT_M)
            _rail_runs(col, np.flatnonzero(keep & _grow(out_zone & ~cmask)), pts, nrm, tl, lat0, lat1)
            if cmask.any():
                cm = ct_meshes.setdefault(k, [Mesh(origin), np.zeros(len(pts), bool), pts])
                _rail_runs(cm[0], np.flatnonzero(keep & _grow(cmask)), pts, nrm, tl, lat0, lat1)
                cm[1] |= cmask
            for key in sorted({z for z in zk if z}):
                # (a sample in several zones (a crossover, a ladder): its own shape, solid when every one of those
                # turnouts is set to its route; no frog mask against those turnouts' other routes)
                mates = {r.fid for i, _j in key for r in sws[i].routes} - {fid_of.get(k)}
                own = [(c, kk) for c, kk in centres if fid_of.get(kk) not in mates]
                inz = np.array([z == key for z in zk], bool)
                keep_z = frog_mask(rail_xy, k, own)
                m = sw_meshes.setdefault(key, Mesh(origin))
                _rail_runs(m, np.flatnonzero(keep_z & _grow(inz)), pts, nrm, tl, lat0, lat1)
        _sleepers(vis, pts, nrm, H, tl)
        _ballast(vis, pts, nrm, br == 1, tl, ground, room,
                 pier_avoid() + [(c, PIER_TRACK_M) for c, kk in centres if kk != k] if (br == 1).any() else ())
        _ballast_collision(col, pts[ck], nrm[ck], br[ck] == 1, tl[ck], (room[0][ck], room[1][ck]))
        if k in electrified:
            _catenary(vis, pts, nrm, br, tl, [c for c, kk in centres if kk != k], arc, (x0, y0, x1, y1))
    if platforms:                                   # the stations' platforms beside the track (nrails.stations)
        from nrails import stations
        own = [(k, p, b) for k, p, b in heavy]
        stations.add_platforms(vis, col, own, platforms)
    tun = None                                      # the tunnels' tubes (roadmesh.tunnel's, "railtun")
    import roads as _roads                          # (the tile's own square: its box has the roads' 2 m overlap)
    tubes = tile_tubes(pm, index, near, _roads.tile_bbox(tx, ty), ground)
    if tubes:
        import roadmesh
        tun = roadmesh.tunnel(tube_chunks(tubes), origin)
    # level crossings whose centre is in this tile: one platform per road over its parallel tracks
    for x in found:
        if not (x0 <= x["at"][0] < x1 and y0 <= x["at"][1] < y1):
            continue
        others = [o for o in found if o is not x and o["road"] == x["road"] and o["k"] != x["k"]
                  and np.hypot(*(np.asarray(o["at"]) - np.asarray(x["at"]))) <= X_CLUSTER_M + X_HALF_MAX_M]
        try:                                        # (one crossing's slab never costs the tile its track)
            _platform(x, others, vis, col, inner, _track_near(pm.get(x["fid"], ()), x["at"], x["half"]),
                      [np.asarray(pp)[:, :2] for f, parts in pm.items() if f != x["fid"] and f in index
                       for pp, _kd in parts])
        except Exception as e:      # noqa: BLE001
            _log_once(f"level crossing slab: {type(e).__name__}: {e}")
            continue
        xpts.append([round(float(x["at"][0]), 2), round(float(x["at"][1]), 2), round(x["z"], 2)])
        bar = crossing_bar(x, others)
        if bar is not None:
            xbars.append(bar)
        r = x["half"] + 1.0
        xboxes.append([round(float(x["at"][0]) - r, 1), round(float(x["at"][1]) - r, 1), round(x["z"] - 1.0, 1),
                       round(float(x["at"][0]) + r, 1), round(float(x["at"][1]) + r, 1), round(x["z"] + 1.5, 1)])
    for k, pts, _ in trams:                         # grooved rail heads flush with the street, render-only
        nrm = normals(pts[:, :2])
        for sgn in (-1.0, 1.0):
            c0 = sgn * (GAUGE_M / 2 + C / 2)
            _sweep(vis, pts, nrm, [(c0 - C / 2, 0.0), (c0 - C / 2, -0.03), (c0 + C / 2, -0.03), (c0 + C / 2, 0.0)],
                   MAT_TRAM, closed=True)
    whats, sw_keep, n = {}, [], 0
    for key in sorted(sw_meshes):                   # the turnouts' routes: one collision shape each ("nrailswN")
        m = sw_meshes[key]
        if m.empty():
            continue
        if n >= SW_SHAPES_MAX:                      # (past the mod's list: always solid in the track's collision,
            col.extend(m)                           # as before turnouts were set, rather than no rail there)
            continue
        n += 1
        whats[key] = f"nrailsw{n}"
        sw_keep.append((whats[key], m.arrays()))
    ct_keep, ct_rows = [], []
    for k in sorted(ct_meshes, key=lambda q: str(q)):     # the contacts: one collision shape per track ("nrailctN")
        m, mask, cpts = ct_meshes[k]
        if m.empty():
            continue
        if len(ct_keep) >= CT_SHAPES_MAX:
            col.extend(m)                           # (past the mod's list: always solid, as before)
            continue
        what = f"nrailct{len(ct_keep) + 1}"
        ct_keep.append((what, m.arrays()))
        ct_rows.append({"what": what, "lines": contact_line(cpts, mask)})
    if n >= SW_SHAPES_MAX and len(sw_meshes) > n:
        _log_once(f"turnouts: {len(sw_meshes)} zone shapes in a tile, {SW_SHAPES_MAX} switched, the rest always solid")
    sig_rows = _signals(vis, sws, heavy, centres, (x0, y0, x1, y1)) if sws and _on("BNGE_RAIL_SIGNALS") else []
    rt = RailTile(vis.parts(), col.parts(COL_MAX_VERTS), None if inner.empty() else inner.arrays(), xpts,
                  {"nrailx": xboxes} if xboxes else {}, [(k, p) for k, p, _ in heavy], tun)
    rt.sig_rows = sig_rows
    rt.xbar_rows = xbars
    rt.ct_shapes, rt.ct_rows = ct_keep, ct_rows
    if sws:
        rt.sw_shapes = sw_keep
        rt.sw_rows = swmod.mod_rows(sws, whats)
        rt.sw_need = swmod.shape_rows(sws, whats)
    return rt


# Light signals before the turnouts (the user's runs, 2026-10-26: "rajoute les signalisations lumineuses", then
# "je ne sais pas s'ils sont fideles a la vraie vie, peut-etre diversifier"), after the French railway's (SNCF) lights:
#   - a protection signal ("kind": "main") SIGNAL_BACK_M back along each turnout's trunk, on a mast SIGNAL_H_M high:
#     green (voie libre) the main line set; two yellow lights one over the other (rappel de ralentissement, RR30;
#     flashing RR60 on a gentle turnout) a diverging route; two red lights side by side (carre: stop) a vehicle on the
#     turnout;
#   - an advance signal ("adv") SIGNAL_ADV_M back where the trunk reaches that far: green; two yellow lights side by
#     side (ralentissement 30 / 60 flashing) a diverging route ahead; one yellow (avertissement) the turnout taken;
#   - on a yard's turnout (none of its routes a named line: rail_priority) a low shunting signal ("yard"), mast
#     SIGNAL_YARD_H_M: violet (carre violet: stop) a vehicle on it, white (manoeuvre allowed) else; no advance one.
# The mast SIGNAL_SIDE_M off the track on the side with room (no other track within SIGNAL_CLEAR_M), drawn only (a
# train beside never hits it); the head a target plate across the track facing the train. The lamps' place goes to
# the mod (data["railsig"]: id, kind, yard, lamp (the head's centre), face), which lights them (nrailsswitch.lamps,
# nrailsui.drawSignals). BNGE_RAIL_SIGNALS=off: none.
SIGNAL_BACK_M = 40.0
SIGNAL_ADV_M = 220.0
SIGNAL_SIDE_M = 2.6
SIGNAL_CLEAR_M = 3.4            # m from the mast to another track's centre line at least
SIGNAL_H_M = 4.2                # m: the head's centre over the rail top
SIGNAL_YARD_H_M = 1.1           # m: a shunting signal's
SIGNAL_HEAD = (0.06, 0.30, 0.55)    # m: the target's half depth, half width, half height
MAT_SIGNAL = 0                  # (MATERIALS[0]: the rails' steel)


def _signals(vis, sws, heavy, centres, box):
    """The masts of the turnouts' signals whose place is in box (into vis) and their rows for the mod: [{id, kind,
    yard, lamp: [x, y, z], face: [dx, dy]}] (face: the way a train coming toward the turnout looks at it)."""
    rows = []
    allc = [np.asarray(c, np.float64) for c, _k in centres]
    for sw in sws:
        if getattr(sw, "kind", "turnout") != "turnout" or sw.trunk is None or len(sw.trunk) < 2:
            continue
        tr = np.asarray(sw.trunk, np.float64)
        s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(tr, axis=0).T))]
        yard = all(float(getattr(r, "prio", 0.0) or 0.0) <= 0.0 for r in sw.routes)
        for kind, back in (("main", SIGNAL_BACK_M), ("adv", SIGNAL_ADV_M)):
            if kind == "adv" and yard:
                continue
            if s[-1] < back + 2.0:
                continue
            p = np.array([np.interp(back, s, tr[:, 0]), np.interp(back, s, tr[:, 1])])
            if not (box[0] <= p[0] < box[2] and box[1] <= p[1] < box[3]):
                continue
            q = np.array([np.interp(back + 2.0, s, tr[:, 0]), np.interp(back + 2.0, s, tr[:, 1])])
            face = p - q                            # (toward the turnout: the train's way)
            face = face / max(float(np.hypot(*face)), 1e-9)
            nrm = np.array([-face[1], face[0]])
            spot = None
            for sgn in (-1.0, 1.0):                 # (its right first, as most of the world's signals)
                c = p + sgn * nrm * SIGNAL_SIDE_M
                if all(len(cc) < 2 or float(np.min(np.hypot(cc[:, 0] - c[0], cc[:, 1] - c[1]))) >= SIGNAL_CLEAR_M - 0.01
                       or float(np.min(np.hypot(cc[:, 0] - p[0], cc[:, 1] - p[1]))) < 0.5 for cc in allc):
                    spot = c
                    break
            if spot is None:
                continue
            z = None                                # the rail top there: the nearest sample of the tile's tracks
            best = np.inf
            for _k, pts, _b in heavy:
                d = np.hypot(pts[:, 0] - p[0], pts[:, 1] - p[1])
                i = int(np.argmin(d))
                if d[i] < best:
                    best, z = float(d[i]), float(pts[i, 2])
            if z is None or best > 3.0:
                continue
            hd, hw, hh = SIGNAL_HEAD if not yard else (0.06, 0.18, 0.18)
            hz = z + (SIGNAL_YARD_H_M if yard else SIGNAL_H_M)
            _box(vis, spot, face, 0.09, 0.09, z - 1.0, hz - hh, MAT_SIGNAL)                # the mast
            _box(vis, spot, face, hd, hw, hz - hh, hz + hh, MAT_SIGNAL)                    # the target
            lamp = spot - face * (hd + 0.02)
            rows.append({"id": sw.id, "kind": kind, "yard": bool(yard),
                         "lamp": [round(float(lamp[0]), 2), round(float(lamp[1]), 2), round(hz, 2)],
                         "face": [round(float(face[0]), 3), round(float(face[1]), 3)]})
    return rows


def _box(mesh, c, face, hx, hy, z0, z1, mat):
    """A box centred at c (2,), its half sizes hx along face, hy across, from z0 to z1 (all six faces)."""
    a = np.asarray(face, np.float64)
    b = np.array([-a[1], a[0]])
    xy = [c + sx * hx * a + sy * hy * b for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    P = np.array([[*q, z1] for q in xy] + [[*q, z0] for q in xy])
    T = np.array([[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6], [0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2],
                  [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]])
    UV = np.array([[0, 0], [1, 0], [1, 1], [0, 1]] * 2, np.float64) * 0.3
    mesh.add(P, T, UV, mat, inside=np.repeat([[c[0], c[1], (z0 + z1) / 2]], len(T), axis=0))


def write(path, mesh, collision_only=False):
    import cdae
    P, T, UV, mats, M = mesh
    return cdae.write(path, P, T, uvs=UV, material=mats, tri_materials=M, object_name="rails",
                      collision_only=collision_only)
