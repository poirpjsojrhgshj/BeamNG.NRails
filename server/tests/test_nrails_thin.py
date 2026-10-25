import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import roadmesh  # noqa: E402
from nrails import thin  # noqa: E402


def deck_chunk(z, w=8.0):
    ys = np.arange(-20.0, 20.1, 4.0)
    return {"m": "road_asphalt_2lane", "w": w, "tl": 11.0, "p": 20, "fixed": True, "deck": True,
            "n": [[0.0, float(y), z] for y in ys]}


def track(z=100.0):
    xs = np.arange(-30.0, 30.1, 2.0)
    return [(0, np.c_[xs, np.zeros_like(xs), np.full_like(xs, z)])]


class ThinTest(unittest.TestCase):
    def test_low_deck_thin(self):
        c = deck_chunk(100.0 + 7.5)             # girders: 7.5 - 2.2 = 5.3 m over the rails
        self.assertEqual(thin.mark([c], track()), 1)
        self.assertEqual(c["thin"], thin.THIN_M)

    def test_high_deck_kept(self):
        c = deck_chunk(100.0 + 9.5)
        self.assertEqual(thin.mark([c], track()), 0)
        self.assertNotIn("thin", c)

    def test_deck_under_track_kept(self):
        c = deck_chunk(100.0 - 5.0)             # a road under the railway's bridge
        self.assertEqual(thin.mark([c], track()), 0)

    def test_far_track_kept(self):
        c = deck_chunk(100.0 + 7.5)
        far = [(0, np.c_[np.full(10, 200.0), np.arange(10.0), np.full(10, 100.0)])]
        self.assertEqual(thin.mark([c], far), 0)

    def test_mesh_thin_has_no_girders(self):
        thick, slab = deck_chunk(107.5), deck_chunk(107.5)
        slab["thin"] = thin.THIN_M
        mt = roadmesh.deck([thick], (0.0, 0.0, 0.0))
        ms = roadmesh.deck([slab], (0.0, 0.0, 0.0))
        self.assertAlmostEqual(float(mt[0][:, 2].min()), 107.5 - roadmesh.DECK_DEPTH - roadmesh.GIRDER_D, places=3)
        self.assertAlmostEqual(float(ms[0][:, 2].min()), 107.5 - thin.THIN_M, places=3)
        self.assertLess(len(ms[1]), len(mt[1]))
        self.assertGreater(float(ms[0][:, 2].max()), 107.5 + 0.5)     # (the parapets kept)

    def test_piers_raised(self):
        c = deck_chunk(107.5)
        c["thin"] = thin.THIN_M
        zt = 107.5 - roadmesh.DECK_DEPTH - roadmesh.GIRDER_D
        p = (0.0, 18.0, 0.0, 1.0, zt, 95.0, 8.0)
        far = (50.0, 18.0, 0.0, 1.0, zt, 95.0, 8.0)
        out = thin.raise_piers([p, far], [c])
        self.assertAlmostEqual(out[0][4], 107.5 - thin.THIN_M)
        self.assertAlmostEqual(out[1][4], zt)


if __name__ == "__main__":
    unittest.main()
