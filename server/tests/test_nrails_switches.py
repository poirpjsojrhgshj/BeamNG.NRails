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
