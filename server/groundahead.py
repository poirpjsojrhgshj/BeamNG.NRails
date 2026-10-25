"""The highest ground near and ahead of the player, for the mod's altitude rule (2026-10-13).

High above the ground the physics block is not needed: the user flies, and at 300 m/s the block builds
could not keep up anyway (~1 s per answer). The mod stops moving the block while the player is far above
the ground (core.lua, FOLLOW_OFF_AGL) and takes it up again on the way down. The far tiles do not collide,
so the mod cannot measure that height itself: the server answers each pose with the highest ground within
RADIUS of the player's straight path over the next AHEAD_S seconds (a coarse DEM, so it adds MARGIN).
"""
import math

import numpy as np

ZOOM = 11           # ~60-75 m pixels at mid latitudes: a coarse, cheap look (bilinear smooths peaks: MARGIN)
AHEAD_S = 10.0      # s of straight flight looked at
STEP_S = 0.5
RADIUS = 250.0      # m around each point of the path
MARGIN = 30.0       # m added for what the coarse DEM smooths away
MAX_PATH = 4000.0   # m: the path looked at is at most this long


def points(x, y, vx, vy):
    """The (x, y) sample points: along the path, each with a 3x3 cross of +-RADIUS."""
    sp = math.hypot(vx, vy)
    t_max = AHEAD_S if sp * AHEAD_S <= MAX_PATH else MAX_PATH / sp
    ts = np.arange(0.0, t_max + 1e-9, STEP_S)
    px, py = x + vx * ts, y + vy * ts
    off = np.array([-RADIUS, 0.0, RADIUS])
    ox, oy = np.meshgrid(off, off)
    return (px[:, None] + ox.ravel()[None, :]).ravel(), (py[:, None] + oy.ravel()[None, :]).ravel()


def highest(dem, frame, x, y, vx, vy):
    """The highest ground (m, z of `frame`, curvature included) near the path, + MARGIN."""
    ex, ey = points(x, y, vx, vy)
    lat, lon, _ = frame.enu_to_geodetic(ex, ey, np.zeros_like(ex))
    h = dem.sample(lat, lon, ZOOM)
    _, _, z = frame.geodetic_to_enu(lat, lon, h)
    return float(np.max(z)) + MARGIN
