import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nrails import clearway  # noqa: E402


def track(z=100.0):
    xs = np.arange(-40.0, 40.1, 2.0)
    return [(0, np.c_[xs, np.zeros_like(xs), np.full_like(xs, z)])]


class ClearwayTest(unittest.TestCase):
    def test_props_on_track_gone(self):
        rows = [["deciduous", 3.0, 1.0, 100.1, 0, 1, 9.0, 0],      # on the track, at its level
                ["pole", 5.0, 6.0, 100.0, 0, 1, 8.5, 0],          # beside it
                ["lamp", 0.0, 1.5, 90.0, 0, 1, 7.0, 0],           # on a street 10 m under a viaduct
                ["lamp", 0.0, 0.5, 108.0, 0, 1, 7.0, 0]]          # up on a road bridge over it
        out = clearway.clear_props(rows, track())
        self.assertEqual([r[0] for r in out], ["pole", "lamp", "lamp"])

    def test_wire_through_track_gone(self):
        y = np.arange(-20.0, 20.1, 5.0)
        low = np.c_[np.full_like(y, 1.0), y, np.full_like(y, 101.5)]       # 1.5 m over the rails
        high = np.c_[np.full_like(y, 1.0), y, np.full_like(y, 109.0)]      # 9 m over: kept
        under = np.c_[np.full_like(y, 1.0), y, np.full_like(y, 95.0)]      # under a railway bridge: kept
        far = np.c_[np.full_like(y, 1.0) + 100, y, np.full_like(y, 101.0)]
        wires = [low, high, under, far]
        self.assertEqual(clearway.clear_wires(wires, track()), 1)
        self.assertEqual(len(wires), 3)
        self.assertFalse(any(w is low for w in wires))


class PierTest(unittest.TestCase):
    def test_pier_between_two_tracks_dropped(self):
        xs = np.arange(-40.0, 40.1, 2.0)
        lines = [(0, np.c_[xs, np.full_like(xs, -2.25), np.full_like(xs, 100.0)]),
                 (1, np.c_[xs, np.full_like(xs, 2.25), np.full_like(xs, 100.0)])]
        # a road deck along y over the two tracks (along x): its pier wall lies along x, between them
        between = (0.0, 0.0, 0.0, 1.0, 106.0, 98.0, 8.0)
        aside = (0.0, 15.0, 0.0, 1.0, 106.0, 98.0, 8.0)
        kept, n = clearway.clear_piers([between, aside], lines)
        self.assertEqual(n, 1)
        self.assertEqual(kept, [aside])

    def test_pier_far_under_a_viaduct_kept(self):
        xs = np.arange(-40.0, 40.1, 2.0)
        lines = [(0, np.c_[xs, np.zeros_like(xs), np.full_like(xs, 150.0)])]     # the track high on a viaduct
        p = (0.0, 0.0, 0.0, 1.0, 120.0, 98.0, 8.0)
        self.assertEqual(clearway.clear_piers([p], lines)[1], 0)


class WallTest(unittest.TestCase):
    def wall(self, top):
        y = np.arange(-20.0, 20.1, 2.0)
        k = len(y)
        return {"base": np.c_[np.full(k, 1.0), y], "top": np.full(k, top), "foot": np.full(k, 96.0),
                "toward": np.tile([1.0, 0.0], (k, 1)), "rock": False}

    def test_wall_across_track_cut(self):
        walls = [self.wall(100.2)]
        self.assertEqual(clearway.clear_walls(walls, track()), 1)
        self.assertEqual(len(walls), 2)
        for w in walls:
            self.assertTrue((np.abs(w["base"][:, 1]) >= clearway.WALL_CLEAR_M - 1.0).all())
            self.assertEqual(len(w["top"]), len(w["base"]))
            self.assertFalse(w["rock"])

    def test_wall_under_bridge_kept(self):
        walls = [self.wall(97.0)]
        self.assertEqual(clearway.clear_walls(walls, track()), 0)
        self.assertEqual(len(walls), 1)


if __name__ == "__main__":
    unittest.main()
