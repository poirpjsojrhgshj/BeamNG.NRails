"""Runway markings (server/runwaymarks.py): the marking class from the data, threshold stripes per
width, designators (data ident, ICAO leading zero, FAA without, the heading guess), what each class
gets, every stroke on the pavement, the two ends mirror images, no two elements overlapping, displaced
thresholds, closed runways, the world (DecalRoad) form, determinism. Pure: no engine."""
import itertools
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import airports  # noqa: E402
import runwaygeom as rg  # noqa: E402
import runwaymarks as rm  # noqa: E402
import test_runwaygeom as trg  # noqa: E402


def rw(length=3000.0, width=45.0, country="US", type="large_airport", lighted=True, paved=True, closed=False,
       le="09", he="27", heading=90.0, le_disp=0.0, he_disp=0.0):
    r = trg.make(length=length, width=width, paved=paved, closed=closed, heading=heading)
    return replace(r, country=country, airport_type=type, lighted=lighted,
                   le=replace(r.le, ident=le, displaced_m=le_disp), he=replace(r.he, ident=he, displaced_m=he_disp))


def overlap(a, b):
    return airports._convex_overlap(a.polygon(), b.polygon())


class ClassTest(unittest.TestCase):
    def test_classes(self):
        self.assertEqual(rm.marking_class(rw()), "precision")
        self.assertEqual(rm.marking_class(rw(type="small_airport")), "nonprecision")
        self.assertEqual(rm.marking_class(rw(length=1000.0)), "visual")
        self.assertEqual(rm.marking_class(rw(lighted=False)), "visual")
        self.assertEqual(rm.marking_class(rw(paved=False)), "unpaved")
        self.assertEqual(rm.marking_class(rw(closed=True)), "closed")
        self.assertEqual(rm.style_for(rw(country="US")), "faa")
        self.assertEqual(rm.style_for(rw(country="GB")), "icao")

    def test_kinds_per_class(self):
        k = rm.markings(rw()).by_kind()
        self.assertTrue({"threshold", "designation", "centreline", "aiming", "tdz", "edge"} <= set(k))
        k = rm.markings(rw(type="small_airport")).by_kind()
        self.assertTrue({"threshold", "designation", "centreline", "aiming"} <= set(k))
        self.assertFalse({"tdz", "edge"} & set(k))
        k = rm.markings(rw(length=700.0, width=18.0, lighted=False)).by_kind()
        self.assertEqual(set(k), {"designation", "centreline"})
        self.assertEqual(rm.markings(rw(paved=False)).strokes, ())


class StripeTest(unittest.TestCase):
    def test_threshold_count_by_width(self):
        for width, n in ((18.0, 4), (23.0, 6), (30.0, 8), (45.0, 12), (60.0, 16)):
            m = rm.markings(rw(width=width, type="small_airport"))
            self.assertEqual(m.by_kind()["threshold"], 2 * n, width)
            le = sorted(s.t0 for s in m.strokes if s.kind == "threshold" and s.end == "le")
            gaps = np.diff(le)
            self.assertAlmostEqual(max(gaps), 1.5 * min(gaps), places=3)       # the double centre gap
            self.assertAlmostEqual(sum(le), 0.0, places=6)                     # symmetric about the centreline

    def test_designators(self):
        self.assertEqual(rm.markings(rw(country="US", le="09", he="27")).designators, ("9", "27"))
        self.assertEqual(rm.markings(rw(country="FR", le="09", he="27")).designators, ("09", "27"))
        self.assertEqual(rm.markings(rw(country="FR", le="15L", he="33R")).designators, ("15L", "33R"))
        m = rm.markings(rw(country="FR", le="N", he="S", heading=4.0))
        self.assertEqual(m.designators, ("36", "18"))
        self.assertTrue(any("from the true heading" in n for n in m.notes))

    def test_tdz_pairs_and_halfway(self):
        m = rm.markings(rw(length=3000.0))
        for e in ("le", "he"):
            ys = [abs(s.s0 - (0 if e == "le" else 3000)) for s in m.strokes if s.kind == "tdz" and s.end == e]
            self.assertTrue(ys)
            self.assertLess(max(ys), 1500.0)
        short = rm.markings(rw(length=1850.0))
        self.assertLess(short.by_kind().get("tdz", 0), m.by_kind()["tdz"])


class LayoutTest(unittest.TestCase):
    CASES = [dict(), dict(country="GB"), dict(type="small_airport"), dict(length=1000.0, width=23.0),
             dict(width=60.0, le="07R", he="25L"), dict(le_disp=300.0, he_disp=150.0), dict(width=18.0, length=1300.0)]

    def test_on_the_pavement(self):
        for c in self.CASES:
            r = rw(**c)
            for s in rm.markings(r).strokes:
                p = s.polygon()
                self.assertTrue((p[:, 0] >= -1e-6).all() and (p[:, 0] <= r.length_m + 1e-6).all(), (c, s))
                self.assertTrue((np.abs(p[:, 1]) <= r.width_m / 2 + 1e-6).all(), (c, s))

    def test_elements_do_not_overlap(self):
        allowed = {frozenset(("arrow",)), frozenset(("designation",)), frozenset(("closed",))}
        for c in self.CASES:
            st = rm.markings(rw(**c)).strokes
            for a, b in itertools.combinations(st, 2):
                if a.kind == b.kind and frozenset((a.kind,)) in allowed:
                    continue                                     # strokes of one glyph / arrow / cross meet
                self.assertFalse(overlap(a, b), (c, a, b))

    def test_ends_mirror(self):
        r = rw(country="GB", le="09", he="09")                   # same text at both ends: exact mirror images
        m = rm.markings(r)
        L = r.length_m
        le = sorted((round(s.s0, 3), round(s.t0, 3), round(s.s1, 3), round(s.t1, 3), s.kind)
                    for s in m.strokes if s.end == "le")
        he = sorted((round(L - s.s0, 3), round(-s.t0, 3), round(L - s.s1, 3), round(-s.t1, 3), s.kind)
                    for s in m.strokes if s.end == "he")
        self.assertEqual(le, he)
        cl = [s for s in m.strokes if s.kind == "centreline"]
        self.assertAlmostEqual(cl[0].s0, L - cl[-1].s1, places=3)

    def test_displaced_threshold(self):
        m = rm.markings(rw(le_disp=300.0))
        thr = [s.s0 for s in m.strokes if s.kind == "threshold" and s.end == "le"]
        self.assertTrue(all(abs(x - 306.1) < 1e-6 for x in thr))
        self.assertEqual(sum(1 for s in m.strokes if s.kind == "bar"), 1)
        arrows = [s for s in m.strokes if s.kind == "arrow"]
        self.assertTrue(arrows and all(s.s1 < 300.0 for s in arrows))
        self.assertTrue(all(s.s0 > 300.0 for s in m.strokes if s.kind == "centreline"))
        m = rm.markings(rw(le_disp=2000.0))                      # implausible: ignored with a note
        self.assertTrue(any("ignored" in n for n in m.notes))
        self.assertFalse(any(s.kind == "bar" for s in m.strokes))

    def test_closed(self):
        m = rm.markings(rw(closed=True))
        self.assertEqual(set(m.by_kind()), {"closed"})
        self.assertEqual({s.color for s in m.strokes}, {"yellow"})
        self.assertEqual({s.color for s in rm.markings(rw(closed=True, country="DE")).strokes}, {"white"})
        centres = sorted({round((s.s0 + s.s1) / 2, 3) for s in m.strokes})
        self.assertLessEqual(max(np.diff(centres)), rm.CLOSED_EVERY + 1e-6)

    def test_world_form_and_determinism(self):
        r = rw()
        m1, m2 = rm.markings(r), rm.markings(r)
        self.assertEqual(m1, m2)
        g = rg.geometry(r)
        w = rm.to_world(g, m1.strokes)
        self.assertEqual(len(w), len(m1.strokes))
        lat0, lon0, lat1, lon1, width, kind, color = w[0]
        s, t = g.st(np.array([lat0, lat1]), np.array([lon0, lon1]))
        np.testing.assert_allclose(s, [m1.strokes[0].s0, m1.strokes[0].s1], atol=2e-3)
        np.testing.assert_allclose(t, [m1.strokes[0].t0, m1.strokes[0].t1], atol=2e-3)
        self.assertEqual(rm.to_world(g, ()), [])


if __name__ == "__main__":
    unittest.main()
