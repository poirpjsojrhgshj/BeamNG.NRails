"""polygon.py: point-in-polygon in place of matplotlib's (the release install has no matplotlib)."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import polygon  # noqa: E402


def brute(ring, pts):
    """Even-odd ray casting, one point at a time."""
    out = []
    n = len(ring)
    for px, py in pts:
        c = False
        for i in range(n):
            x0, y0 = ring[i]
            x1, y1 = ring[(i + 1) % n]
            if (y0 <= py < y1 or y1 <= py < y0) and x0 + (py - y0) * (x1 - x0) / (y1 - y0) > px:
                c = not c
        out.append(c)
    return np.array(out)


class PolygonTest(unittest.TestCase):
    def test_square_and_hole_free_cases(self):
        sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
        got = polygon.Path(sq).contains_points([(5, 5), (15, 5), (-1, -1), (9.9, 0.1)])
        self.assertEqual(list(got), [True, False, False, True])
        closed = sq + [sq[0]]
        self.assertEqual(list(polygon.contains_points(closed, [(5, 5), (11, 5)])), [True, False])
        self.assertFalse(polygon.contains_points([(0, 0), (1, 1)], [(0.5, 0.5)]).any())
        self.assertEqual(len(polygon.contains_points(sq, np.zeros((0, 2)))), 0)

    def test_random_rings_match_brute_force(self):
        rng = np.random.default_rng(7)
        for k in range(40):
            n = int(rng.integers(3, 80))
            ang = np.sort(rng.uniform(0, 2 * np.pi, n))
            r = rng.uniform(5, 50, n)
            ring = np.c_[r * np.cos(ang), r * np.sin(ang)]
            if k % 4 == 0:
                ring = rng.uniform(-50, 50, (n, 2))        # self-intersecting: even-odd
            pts = rng.uniform(-60, 60, (300, 2))
            np.testing.assert_array_equal(polygon.contains_points(ring, pts), brute(ring, pts))


if __name__ == "__main__":
    unittest.main()
