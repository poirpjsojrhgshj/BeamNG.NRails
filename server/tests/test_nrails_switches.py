import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nrails import rails, switches  # noqa: E402
from test_nrails_rails import FlatGround  # noqa: E402


def turnout(side=1.0):
    main = ("main", "standard_gauge", np.array([[-200.0, 0.0], [200.0, 0.0]]), [])
    # a branch leaving at the node (0, 0) at ~1:9, to 4.5 m beside the main line, then parallel
    br = np.array([[0.0, 0.0], [20.0, side * 1.0], [40.0, side * 3.2], [60.0, side * 4.5], [200.0, side * 4.5]])
    return main, ("branch", "standard_gauge", br, [])


class FindTest(unittest.TestCase):
    def test_one_turnout_two_routes(self):
        main, br = turnout()
        sws = switches.find(switches.lines_of([main, br]), (-100, -100, 100, 100))
        self.assertEqual(len(sws), 1)
        sw = sws[0]
        self.assertEqual(len(sw.routes), 2)
        self.assertLess(np.hypot(*sw.at), 1.5)
        self.assertAlmostEqual(float(sw.dir[0]), 1.0, delta=0.05)
        self.assertEqual(sw.routes[0].fid, "branch")             # left first
        self.assertEqual(sw.routes[sw.default].fid, "main")      # the straight one by default
        for r in sw.routes:
            L = float(np.hypot(*np.diff(r.xy, axis=0).T).sum())
            self.assertTrue(20.0 < L <= switches.ZONE_MAX_M + 2, L)

    def test_parallel_tracks_and_a_crossing_are_no_turnouts(self):
        a = ("a", "standard_gauge", np.array([[-200.0, 0.0], [200.0, 0.0]]), [])
        b = ("b", "standard_gauge", np.array([[-200.0, 4.5], [200.0, 4.5]]), [])
        c = ("c", "standard_gauge", np.array([[0.0, -100.0], [0.0, 100.0]]), [])
        self.assertEqual(switches.find(switches.lines_of([a, b, c]), (-100, -100, 100, 100)), [])

    def test_the_main_line_by_default_and_the_trunk(self):
        """The named line (the main line, dark on OSM) is the default even where it is the diverging one; the trunk
        (the track behind the node) is found."""
        main = ("yard", "standard_gauge", np.array([[0.0, 0.0], [200.0, 0.0]]), [])
        trunk = ("line", "standard_gauge", np.array([[-200.0, 0.0], [0.0, 0.0]]), [])
        br = ("line2", "standard_gauge", np.array([[0.0, 0.0], [20.0, 1.0], [40.0, 3.2], [60.0, 4.5],
                                                   [200.0, 4.5]]), [])
        lines = switches.lines_of([main, trunk, br])
        sw = switches.find(lines, (-100, -100, 100, 100), {"line2": 1.0, "line": 1.0})[0]
        self.assertEqual(sw.routes[sw.default].fid, "line2")
        self.assertIsNotNone(sw.trunk)
        self.assertLess(float(sw.trunk[-1, 0]), -100.0)          # the trunk runs back along the line
        self.assertGreater(float(np.hypot(*np.diff(sw.routes[0].arm, axis=0).T).sum()), 150.0)

    def test_short_zones_end_where_the_gauges_part(self):
        main, br = turnout()
        sw = switches.find(switches.lines_of([main, br]), (-100, -100, 100, 100))[0]
        for r in sw.routes:
            other = [o for o in sw.routes if o is not r][0]
            d_end = switches._dist_to_line(r.xy[-1:], other.arm)[0]
            self.assertGreaterEqual(d_end, switches.SPLIT_M - 0.3)
            self.assertLess(d_end, switches.SPLIT_M + 1.0)

    def test_a_ladder_overlapping_zones(self):
        """Two turnouts 10 m apart on one track: the track's samples in both zones form a shape of their own, solid
        only with both turnouts set to the through route."""
        a = ("a", "standard_gauge", np.array([[-200.0, 0.0], [200.0, 0.0]]), [])
        b1 = ("b1", "standard_gauge", np.array([[0.0, 0.0], [20.0, -1.0], [40.0, -3.2], [60.0, -4.5],
                                                [200.0, -4.5]]), [])
        b2 = ("b2", "standard_gauge", np.array([[10.0, 0.0], [30.0, 1.0], [50.0, 3.2], [70.0, 4.5],
                                                [200.0, 4.5]]), [])
        lines = switches.lines_of([a, b1, b2])
        sws = switches.find(lines, (-100, -100, 100, 100))
        self.assertEqual(len(sws), 2)
        keys = switches.zone_keys(lines["a"], "a", sws)
        both = [k for k in keys if len(k) == 2]
        self.assertTrue(both, "samples of the main track in both zones")
        whats = {k: f"railsw{n + 1}" for n, k in enumerate(sorted(set(k for k in keys if k)))}
        rows = switches.shape_rows(sws, whats)
        two = [r for r in rows if len(r["need"]) == 2]
        self.assertTrue(two and {n[0] for n in two[0]["need"]} == {sws[0].id, sws[1].id})

    def test_a_diamond_crossing(self):
        """Two tracks crossing at 30 deg: a diamond, each track a route whose zone covers where the gauges overlap;
        no diamond where a branch leaves at a node (a turnout)."""
        a = ("a", "standard_gauge", np.array([[-200.0, 0.0], [200.0, 0.0]]), [])
        c = math.cos(math.radians(30)), math.sin(math.radians(30))
        b = ("b", "standard_gauge", np.array([[-200.0 * c[0], -200.0 * c[1]], [200.0 * c[0], 200.0 * c[1]]]), [])
        lines = switches.lines_of([a, b])
        ds = switches.find_diamonds(lines, (-100, -100, 100, 100), {"a": 1.0})
        self.assertEqual(len(ds), 1)
        d = ds[0]
        self.assertEqual(d.kind, "diamond")
        self.assertEqual(d.routes[d.default].fid, "a")
        for r in d.routes:
            L = float(np.hypot(*np.diff(r.xy, axis=0).T).sum())
            self.assertTrue(4.0 < L < 20.0, L)                   # ~ 2 x 1.9 / sin 30 + a sample
        main, br = turnout()
        self.assertEqual(switches.find_diamonds(switches.lines_of([main, br]), (-100, -100, 100, 100)), [])

    def test_long_lines_stay_small(self):
        """Two 40 km lines crossing (20 000 samples each): the diamond search looks at the stretch round the box
        only, in chunks (it once paired every segment of one with every segment of the other: tens of GB, the
        user's PC frozen, 2026-10-26)."""
        import time
        n = 20000
        a = np.c_[np.linspace(-20000.0, 20000.0, n), np.zeros(n)]
        b = np.c_[np.linspace(-20000.0, 20000.0, n) * 0.5, np.linspace(-20000.0, 20000.0, n)]
        t0 = time.perf_counter()
        ds = switches.find_diamonds({"a": a, "b": b}, (-128, -128, 128, 128))
        self.assertLess(time.perf_counter() - t0, 3.0)
        self.assertEqual(len(ds), 1)
        p = switches._seg_cross(a, b)
        self.assertEqual(len(p), 1)

    def test_same_in_every_tile(self):
        main, br = turnout()
        lines = switches.lines_of([main, br])
        a = switches.find(lines, (-50, -50, 10, 50))
        b = switches.find(lines, (10, -50, 80, 50))
        self.assertEqual([s.id for s in a], [s.id for s in b])


class BuildTest(unittest.TestCase):
    def test_zone_rails_in_their_own_shapes(self):
        main, br = turnout()
        cells = []
        orig = rails.rail_features
        rails.rail_features = lambda cells, frame, near: [main, br]
        try:
            import geodesy
            rt = rails.build(geodesy.EnuFrame(47.0, 7.0), 0, 0, cells, lambda la, lo: np.zeros(np.shape(la)),
                             with_crossings=False)
        finally:
            rails.rail_features = orig
        self.assertIsNotNone(rt)
        whats = [w for w, _m in rt.sw_shapes]
        self.assertEqual(len(whats), 2)                          # one shape per route
        self.assertEqual(len(rt.sw_rows), 1)
        row = rt.sw_rows[0]
        self.assertEqual(sorted(r["what"] for r in row["routes"]), sorted(whats))
        self.assertIn(row["def"], (0, 1))


if __name__ == "__main__":
    unittest.main()
