"""Runway markings as geometry (docs/research/2026-10-11-airports.md §4): threshold stripes,
designation numbers and letters, centreline dashes, aiming point, touchdown zone, side stripes,
displaced-threshold bar and arrows, closed-runway crosses. Pure: no engine calls.

Every mark is a list of Strokes: a segment (s0, t0) -> (s1, t1) in the runway-local frame of
runwaygeom (s from the low-numbered end along the runway, t to the left looking from le to he) with
a width; the painted area is the rectangle around the segment (butt ends). A stroke maps 1:1 to a
2-node DecalRoad (nodes = the segment's ends, width = the stroke width) or to one rectangle in a
baked texture, which is how the design doc paints them (DecalRoads on the hidden physics block:
probes P1-P3 of docs/research/2026-10-11-engine-probes.md).

Standards: FAA AC 150/5340-1M ("faa": the US and its territories, by the airport's country) or ICAO
Annex 14 Vol I §5.2 ("icao": everywhere else), dimensions in STYLES (from those documents as cited
in the design doc; verify before relying on single values). Which elements a runway gets (its
marking class) follows the data, since OurAirports does not say whether a runway has an instrument
approach:
  closed       only the closed-runway crosses (at both ends and every <= 300 m)
  unpaved      nothing (turf, gravel, dirt strips carry cones or boards, not paint: props later)
  precision    lighted, paved, length >= 1800 m, at a large or medium airport: threshold, designation,
               centreline 0.9 m, aiming point, touchdown zone, side stripes
  nonprecision lighted and paved, length >= 1200 m: threshold, designation, centreline 0.45 m,
               aiming point
  visual       other paved runways: designation, centreline 0.3 m, threshold from 1200 m (code 3),
               aiming point from 1200 m (FAA: visual runways >= 4000 ft used by jets)
Displaced thresholds move the threshold stripes, designation, aiming point and touchdown zone; the
displaced part gets a threshold bar and centreline arrows instead of dashes.
Deterministic: a pure function of the runway's data.
"""
import math
import re
from dataclasses import dataclass

import numpy as np

import runwaygeom

FAA_COUNTRIES = ("US", "PR", "VI", "GU", "AS", "MP", "UM")
WHITE, YELLOW = "white", "yellow"


@dataclass(frozen=True)
class Style:
    name: str
    thr_offset: float           # threshold stripes start this far after the threshold (m)
    thr_length: float           # stripe length (m)
    thr_width: float            # stripe width = gap; the centre gap is double (m)
    thr_edge: float             # stripes stay this far inside the runway edges (m)
    desig_gap: float            # designation starts this far after the threshold stripes (m)
    desig_height: float         # character height (m) on runways >= 30 m wide
    desig_height_narrow: float  # ... narrower runways
    cl_stripe: float            # centreline stripe and gap (m)
    cl_gap: float
    cl_after_desig: float       # centreline starts this far after the designation (m)
    tdz_step: float             # touchdown zone pairs every this many m from the threshold
    tdz_length: float
    tdz_width: float
    tdz_spacing: float          # between the stripes of one group (m)
    bar_width: float            # displaced-threshold bar (m)
    closed_color: str
    leading_zero: bool          # "09" (ICAO) or "9" (FAA)


STYLES = {
    # FAA AC 150/5340-1M: threshold 150 ft x 5.75 ft from 20 ft; numbers 60 ft high 40 ft past the
    # threshold bars; centreline 120 ft stripes / 80 ft gaps; TDZ 75 ft x 6 ft bars, 5 ft apart, every
    # 500 ft; displaced threshold bar 10 ft; closed runways yellow crosses.
    "faa": Style("faa", 6.1, 45.7, 1.75, 3.0, 12.2, 18.3, 12.2, 36.6, 24.4, 12.2, 152.4, 22.9, 1.83, 1.52,
                 3.05, YELLOW, False),
    # ICAO Annex 14 5.2.4-5.2.6: threshold stripes >= 30 m long, ~1.8 m wide, from 6 m; numbers 9 m high
    # 12 m past them; centreline 30 m / 20 m; TDZ pairs every 150 m, >= 22.5 m x 3 m; closed: white crosses.
    "icao": Style("icao", 6.0, 30.0, 1.8, 3.0, 12.0, 9.0, 9.0, 30.0, 20.0, 12.0, 150.0, 22.5, 3.0, 1.5,
                  3.0, WHITE, True),
}
# Threshold stripes by runway width (both standards): <23 m 4, <30 m 6, <45 m 8, <60 m 12, else 16.
THR_STRIPES = ((23.0, 4), (30.0, 6), (45.0, 8), (60.0, 12), (math.inf, 16))
# Aiming point by landing distance (ICAO table 5-1): (LDA below, distance from threshold, length,
# width, gap between the inner sides).
AIMING = ((800.0, 150.0, 30.0, 4.0, 6.0), (1200.0, 250.0, 30.0, 6.0, 9.0),
          (2400.0, 300.0, 45.0, 6.0, 18.0), (math.inf, 400.0, 45.0, 6.0, 18.0))
AIMING_FAA = (310.9, 45.7, 9.1, 21.9)           # 1020 ft, 150 ft, 30 ft, 72 ft between inner edges
# Touchdown zone pairs (ICAO 5.2.6.3 by LDA; FAA: up to 6 at 500 ft steps): stripes per side at
# steps 1..6 (step 2 is the aiming point's place: a pair overlapping the aiming point is left out).
TDZ_PAIRS = ((900.0, 1), (1200.0, 2), (1500.0, 3), (2400.0, 4), (math.inf, 6))
TDZ_STRIPES = (3, 3, 2, 2, 1, 1)
CL_WIDTH = {"precision": 0.9, "nonprecision": 0.45, "visual": 0.3}
EDGE_WIDTH = (0.9, 0.45)        # side stripes: W >= 30 m, narrower
CLOSED_ARM, CLOSED_WIDTH, CLOSED_EVERY = 36.0, 1.8, 300.0

# A seven-segment stroke font in a unit box (x right, y up, as the pilot on the approach reads it),
# plus the side letters.
_SEG = {"a": ((0, 1), (1, 1)), "b": ((1, 1), (1, .5)), "c": ((1, .5), (1, 0)), "d": ((0, 0), (1, 0)),
        "e": ((0, 0), (0, .5)), "f": ((0, .5), (0, 1)), "g": ((0, .5), (1, .5))}
_DIGITS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc", "5": "afgcd", "6": "afgedc",
           "7": "abc", "8": "abcdefg", "9": "abcdfg"}
GLYPHS = {k: tuple(_SEG[c] for c in v) for k, v in _DIGITS.items()}
GLYPHS["L"] = (((0, 1), (0, 0)), ((0, 0), (1, 0)))
GLYPHS["C"] = (((1, 1), (0, 1)), ((0, 1), (0, 0)), ((0, 0), (1, 0)))
GLYPHS["R"] = (((0, 0), (0, 1)), ((0, 1), (1, 1)), ((1, 1), (1, .5)), ((1, .5), (0, .5)), ((.3, .5), (1, 0)))


@dataclass(frozen=True)
class Stroke:
    kind: str                   # threshold / designation / centreline / aiming / tdz / edge / bar / arrow / closed
    end: str | None             # "le" / "he" / None (both)
    color: str
    s0: float
    t0: float
    s1: float
    t1: float
    width: float

    @property
    def length(self):
        return math.hypot(self.s1 - self.s0, self.t1 - self.t0)

    def polygon(self):
        """The 4 corners ((4, 2) s/t) of the painted rectangle."""
        ds, dt = self.s1 - self.s0, self.t1 - self.t0
        ln = math.hypot(ds, dt) or 1.0
        ns, nt = -dt / ln * self.width / 2, ds / ln * self.width / 2
        return np.array([(self.s0 + ns, self.t0 + nt), (self.s1 + ns, self.t1 + nt),
                         (self.s1 - ns, self.t1 - nt), (self.s0 - ns, self.t0 - nt)])


@dataclass(frozen=True)
class Markings:
    style: str
    mclass: str                 # closed / unpaved / precision / nonprecision / visual
    strokes: tuple
    designators: tuple          # ("10", "28") as painted (with the side letter)
    notes: tuple = ()

    def by_kind(self):
        out = {}
        for s in self.strokes:
            out[s.kind] = out.get(s.kind, 0) + 1
        return out


def style_for(rw):
    return "faa" if getattr(rw, "country", "") in FAA_COUNTRIES else "icao"


def marking_class(rw):
    """The marking class of a runway (see the module docstring)."""
    if rw.closed:
        return "closed"
    if not rw.paved:
        return "unpaved"
    if rw.lighted and rw.length_m >= 1800 and rw.airport_type in ("large_airport", "medium_airport"):
        return "precision"
    if rw.lighted and rw.length_m >= 1200:
        return "nonprecision"
    return "visual"


def designation_text(ident, heading, style):
    """(text as painted, from_heading): number (with a leading zero in ICAO style) and side letter."""
    num, side, guessed = _designator(ident, heading)
    txt = (f"{num:02d}" if style.leading_zero else str(num)) + side
    return txt, guessed


def _designator(ident, heading):
    m = re.match(r"^(0?[1-9]|[12][0-9]|3[0-6])([LCR]?)$", (ident or "").strip().upper())
    if m:
        return int(m.group(1)), m.group(2), False
    n = int(math.floor(heading / 10.0 + 0.5)) % 36
    return (36 if n == 0 else n), "", True


def _thr_stripes(width):
    for w, n in THR_STRIPES:
        if width < w:
            return n
    return 16


def _glyph_strokes(ch, x0, y0, w, h, sw):
    """Strokes of one character in pilot coordinates (x right, y up); the box's lower left at (x0, y0)."""
    out = []
    ix, iy = w - sw, h - sw                         # stroke centre lines run inside the box
    for (ax, ay), (bx, by) in GLYPHS[ch]:
        p = (x0 + sw / 2 + ax * ix, y0 + sw / 2 + ay * iy)
        q = (x0 + sw / 2 + bx * ix, y0 + sw / 2 + by * iy)
        ln = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
        ex, ey = (q[0] - p[0]) / ln * sw / 2, (q[1] - p[1]) / ln * sw / 2
        out.append(((p[0] - ex, p[1] - ey), (q[0] + ex, q[1] + ey)))   # square ends close the corners
    return out


class _End:
    """Maps the end's pilot frame (x right, y forward from the threshold) to runway s, t."""

    def __init__(self, name, length, s_thr):
        self.name, self.length, self.s_thr = name, length, s_thr

    def st(self, x, y):
        if self.name == "le":
            return self.s_thr + y, -x
        return self.s_thr - y, x

    def stroke(self, kind, color, x0, y0, x1, y1, width):
        s0, t0 = self.st(x0, y0)
        s1, t1 = self.st(x1, y1)
        return Stroke(kind, self.name, color, round(s0, 4), round(t0, 4), round(s1, 4), round(t1, 4),
                      round(width, 4))


def markings(rw, style=None):
    """The Markings of an airports.Runway (style: "faa" / "icao"; default from its country)."""
    st = STYLES[style or style_for(rw)]
    mclass = marking_class(rw)
    L, W = float(rw.length_m), float(rw.width_m)
    notes = []
    strokes = []
    desigs = []
    if mclass == "closed":
        arm = min(CLOSED_ARM, 0.4 * L)
        span = min(W - 4.0, arm * 0.5)
        n = max(2, int(math.ceil((L - arm) / CLOSED_EVERY)) + 1)
        for i in range(n):
            sc = arm / 2 + 2.0 + (L - arm - 4.0) * i / (n - 1)
            for sgn in (-1, 1):
                strokes.append(Stroke("closed", None, st.closed_color, round(sc - arm / 2, 4), round(-sgn * span / 2, 4),
                                      round(sc + arm / 2, 4), round(sgn * span / 2, 4), CLOSED_WIDTH))
        return Markings(st.name, mclass, tuple(strokes), (), tuple(notes))
    if mclass == "unpaved":
        return Markings(st.name, mclass, (), (), ("unpaved: no painted markings",))
    disp = {}
    for name, e in (("le", rw.le), ("he", rw.he)):
        d = e.displaced_m
        if d > 0.4 * L:
            notes.append(f"{name} displaced threshold {d:.0f} m ignored (> 40 % of the runway)")
            d = 0.0
        disp[name] = d
    ends = [_End("le", L, disp["le"]), _End("he", L, L - disp["he"])]
    lda = {e.name: L - disp[e.name] for e in ends}   # landing distance from each threshold (to the far end)
    cl_w = CL_WIDTH.get(mclass, 0.3)
    code = runwaygeom.runway_code(L)
    want_thr = mclass in ("precision", "nonprecision") or code >= 3
    want_aim = mclass in ("precision", "nonprecision") or (L >= 1200 and code >= 3)
    want_tdz = mclass == "precision"
    cl_from = {}                                    # y (from the threshold) where the centreline may start
    for e in ends:
        other = "he" if e.name == "le" else "le"
        y = st.thr_offset
        # displaced part: bar at the threshold, arrows along the centreline
        if disp[e.name] > 0:
            strokes.append(e.stroke("bar", WHITE, -W / 2 + 1.0, -st.bar_width / 2, W / 2 - 1.0, -st.bar_width / 2,
                                    st.bar_width))
            for y0 in np.arange(-disp[e.name] + 10.0, -15.0, 50.0):
                y1 = min(y0 + 30.0, -8.0)
                if y1 - y0 < 10:
                    continue
                strokes.append(e.stroke("arrow", WHITE, 0.0, y0, 0.0, y1 - 4.0, cl_w))
                for sgn in (-1, 1):
                    strokes.append(e.stroke("arrow", WHITE, sgn * 2.5, y1 - 6.0, 0.0, y1, 0.6))
        # threshold stripes
        if want_thr:
            n = _thr_stripes(W)
            sw = min(st.thr_width, (W - 2 * st.thr_edge) / (2 * n))
            x = -n * sw                             # 2n widths: n stripes, n-2 gaps, a double centre gap
            ln = min(st.thr_length, 0.1 * L)
            for i in range(n):
                xc = x + sw / 2 + 2 * i * sw + (sw if i >= n // 2 else 0.0)
                strokes.append(e.stroke("threshold", WHITE, xc, y, xc, y + ln, sw))
            y += ln + st.desig_gap
        else:
            y += 6.0
        # designation: the side letter nearest the threshold, the number beyond
        ident = rw.le.ident if e.name == "le" else rw.he.ident
        heading = rw.le.heading if e.name == "le" else rw.he.heading
        txt, guessed = designation_text(ident, heading, st)
        if guessed:
            notes.append(f"{e.name} designator {txt} from the true heading (ident {ident!r})")
        desigs.append(txt)
        h = st.desig_height if W >= 30 else st.desig_height_narrow
        num, side = txt.rstrip("LCR"), txt[len(txt.rstrip("LCR")):]
        cw, gap = h / 3.0, h / 6.0
        avail = W - 4.0
        need = len(num) * cw + (len(num) - 1) * gap
        if need > avail:                            # a narrow runway: smaller characters
            k = avail / need
            h, cw, gap = h * k, cw * k, gap * k
        sw = h / 12.0
        rows = ([side] if side else []) + [num]
        for row in rows:
            rw_w = len(row) * cw + (len(row) - 1) * gap
            x0 = -rw_w / 2
            for ch in row:
                for (ax, ay), (bx, by) in _glyph_strokes(ch, x0, y, cw, h, sw):
                    strokes.append(e.stroke("designation", WHITE, ax, ay, bx, by, sw))
                x0 += cw + gap
            y += h + gap * 2
        cl_from[e.name] = y - gap * 2 + st.cl_after_desig
        # aiming point
        aim = None
        if want_aim:
            if st.name == "faa":
                a_d, a_len, a_w, a_gap = AIMING_FAA
            else:
                a_d, a_len, a_w, a_gap = next(r[1:] for r in AIMING if lda[e.name] < r[0])
            a_gap = min(a_gap, 0.45 * W)
            a_w = min(a_w, W / 2 - a_gap / 2 - 1.5)
            if a_w >= 1.0 and a_d + a_len < lda[e.name] / 2:
                aim = (a_d, a_d + a_len)
                for sgn in (-1, 1):
                    xc = sgn * (a_gap / 2 + a_w / 2)
                    strokes.append(e.stroke("aiming", WHITE, xc, a_d, xc, a_d + a_len, a_w))
            else:
                notes.append(f"{e.name} aiming point left out (runway too short or narrow)")
        # touchdown zone
        if want_tdz:
            pairs = next(n for lim, n in TDZ_PAIRS if lda[e.name] < lim)
            gap_c = min(AIMING_FAA[3] if st.name == "faa" else 18.0, 0.45 * W)
            for k in range(pairs):
                y0 = st.tdz_step * (k + 1)
                y1 = y0 + st.tdz_length
                if aim and not (y1 <= aim[0] or y0 >= aim[1]):
                    continue                        # the aiming point's place
                if y1 > lda[e.name] / 2 - 30.0:
                    break
                nst = TDZ_STRIPES[k]
                for sgn in (-1, 1):
                    for j in range(nst):
                        xc = sgn * (gap_c / 2 + st.tdz_width / 2 + j * (st.tdz_width + st.tdz_spacing))
                        if abs(xc) + st.tdz_width / 2 > W / 2 - 1.0:
                            continue
                        strokes.append(e.stroke("tdz", WHITE, xc, y0, xc, y1, st.tdz_width))
    # centreline dashes between the two designations, laid out symmetrically
    s_a = ends[0].s_thr + cl_from["le"]
    s_b = ends[1].s_thr - cl_from["he"]
    pitch = st.cl_stripe + st.cl_gap
    if s_b - s_a >= st.cl_stripe:
        n = int((s_b - s_a + st.cl_gap) // pitch)
        used = n * st.cl_stripe + (n - 1) * st.cl_gap
        s = s_a + (s_b - s_a - used) / 2
        for _ in range(n):
            strokes.append(Stroke("centreline", None, WHITE, round(s, 4), 0.0, round(s + st.cl_stripe, 4), 0.0, cl_w))
            s += pitch
    else:
        notes.append("no room for centreline dashes")
    # side stripes: the full length, outer edge on the runway edge (or 30 m out on wider runways)
    if mclass == "precision":
        ew = EDGE_WIDTH[0] if W >= 30 else EDGE_WIDTH[1]
        tt = min(W / 2, 30.0) - ew / 2
        for sgn in (-1, 1):
            strokes.append(Stroke("edge", None, WHITE, 0.5, round(sgn * tt, 4), round(L - 0.5, 4), round(sgn * tt, 4), ew))
    return Markings(st.name, mclass, tuple(strokes), tuple(desigs), tuple(notes))


def to_world(geom, strokes):
    """[(lat0, lon0, lat1, lon1, width, kind, color)] for runwaygeom.Geometry `geom`: the DecalRoad
    form (two nodes and a width; the engine drapes them on the terrain, P1)."""
    if not strokes:
        return []
    s = np.array([[k.s0, k.s1] for k in strokes]).ravel()
    t = np.array([[k.t0, k.t1] for k in strokes]).ravel()
    lat, lon = geom.latlon(s, t)
    lat, lon = lat.reshape(-1, 2), lon.reshape(-1, 2)
    return [(float(a[0]), float(b[0]), float(a[1]), float(b[1]), k.width, k.kind, k.color)
            for a, b, k in zip(lat, lon, strokes)]
