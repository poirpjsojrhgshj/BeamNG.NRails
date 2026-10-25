"""NRails: a road's class bounds its profile, as the design rules of real roads do (France's ICTAAL / ARP: a
motorway climbs 5-6 % at most, an expressway 7-8 %, with long vertical curves). The elevation data does not know
that: a motorway in a cutting or on an embankment took the hillside's bumps (the user, 2026-10-24: "une autoroute ne va
jamais avoir un trou au milieu ni un mur"). Its profile is smoothed longer, then held to its grade by cut and fill
(grade_limit). A profile already within the grade is left as it is; the plan's ends keep their heights.

Called by grading._plan (NRails hook: nrails.hooks.road_profile). BNE_CLASS_PROFILE=off turns it off.
"""
import os

import numpy as np

ON = os.environ.get("BNE_CLASS_PROFILE", "on") != "off"
CLASS_SIGMA_M = {"motorway": 30.0, "trunk": 22.0, "motorway_link": 16.0, "trunk_link": 16.0, "primary": 16.0}
CLASS_MAX_GRADE = {"motorway": 0.06, "trunk": 0.08, "primary": 0.10, "motorway_link": 0.08, "trunk_link": 0.09}
GRADE_END_BLEND_M = 60.0    # m over which a grade-limited profile goes back to its own ends' heights
GRADE_REACH_M = 60.0        # m a bump is looked at round each point (local: every cell planning a road agrees)
GRADE_MAX_DEV_M = 2.5       # m a profile is cut or filled at most by its grade limit
GRADE_ROUND_M = 6.0         # m: the grade-limited profile's corners smoothed this much


def sigma_for(cls, default):
    """The profile smoothing (m) of a built road of class cls (upstream's grading.SIGMA_M otherwise)."""
    return CLASS_SIGMA_M.get(cls, default) if ON else default


def road_profile(z, raw, step, spec, smooth):
    """The profile of a built road of spec.cls: z (upstream's, smoothed with SIGMA_M) taken again from raw with
    the class's own smoothing, then held to the class's grade. smooth(z, step, sigma): grading.smooth_profile. Pure."""
    if not ON or spec.cls not in CLASS_SIGMA_M and spec.cls not in CLASS_MAX_GRADE:
        return z
    if spec.cls in CLASS_SIGMA_M:
        z = smooth(raw, step, CLASS_SIGMA_M[spec.cls])
    if spec.cls in CLASS_MAX_GRADE:
        gl = grade_limit(z, step, CLASS_MAX_GRADE[spec.cls])
        if gl is not z:             # (the envelopes' corners rounded)
            z = smooth(gl, step, GRADE_ROUND_M)
    return z


def grade_limit(z, step, grade, end_blend=GRADE_END_BLEND_M, reach=GRADE_REACH_M, max_dev=GRADE_MAX_DEV_M):
    """The profile z (sampled every `step` m) held to |dz/ds| <= grade over bumps: the mean of its windowed
    `grade`-Lipschitz minorant (lo_i = min of z_j + grade |s_i - s_j| over |s_i - s_j| <= reach: the peaks cut down)
    and majorant (the valleys filled): a balanced cut and fill, at most max_dev m, equal to z wherever z already keeps
    the grade. A steady climb steeper than the grade stays as the data has it (its two envelopes are symmetric round
    it): only humps and dips go. Local (reach), so the cells that plan a road's pieces agree. Eased back to z over
    end_blend m at both ends (the junctions there keep their heights). Pure; returns z itself when nothing changes."""
    z = np.asarray(z, np.float64)
    n = len(z)
    if n < 3 or grade <= 0:
        return z
    d = grade * step
    lo, hi = z.copy(), z.copy()
    for k in range(1, min(n, int(round(reach / step)) + 1)):
        lo[k:] = np.minimum(lo[k:], z[:-k] + k * d)
        lo[:-k] = np.minimum(lo[:-k], z[k:] + k * d)
        hi[k:] = np.maximum(hi[k:], z[:-k] - k * d)
        hi[:-k] = np.maximum(hi[:-k], z[k:] - k * d)
    out = np.clip((lo + hi) / 2, z - max_dev, z + max_dev)
    if np.allclose(out, z, atol=1e-6):
        return z
    s = np.arange(n) * step
    L = s[-1]
    eb = min(end_blend, L / 2)
    if eb > 0:
        w = np.clip(np.minimum(s, L - s) / eb, 0.0, 1.0)
        w = 0.5 - 0.5 * np.cos(np.pi * w)       # 0 at the ends, 1 from eb on
        out = z + (out - z) * w
    return out
