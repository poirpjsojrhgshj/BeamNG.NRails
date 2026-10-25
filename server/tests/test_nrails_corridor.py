import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from nrails import corridor, rails  # noqa: E402


class CeilingTest(unittest.TestCase):
    def setUp(self):
        x = np.arange(-50.0, 50.1, 2.0)
        self.pts = np.c_[x, np.zeros_like(x), np.full_like(x, 100.0)]
        self.c = corridor.Ceiling((-60, -60, 60, 60))
        self.c.stamp(self.pts)

    def test_bed_level_within_half(self):
        z = self.c.at(np.array([0.0, 10.0, -20.0]), np.array([0.0, 3.0, -3.0]))
        np.testing.assert_allclose(z, 100.0 - corridor.BED_M, atol=0.05)

    def test_slope_beyond(self):
        z = self.c.at(np.array([0.0]), np.array([corridor.CUT_HALF_M + 5.0]))
        self.assertAlmostEqual(float(z[0]), 100.0 - corridor.BED_M + 5.0 * corridor.CUT_SLOPE, delta=0.3)

    def test_no_limit_far(self):
        z = self.c.at(np.array([0.0, 0.0]), np.array([40.0, 59.0]))
        self.assertTrue(np.isinf(z).all())

    def test_open_samples_skip_bridges_crossings(self):
        kind = np.zeros(len(self.pts), np.int8)
        kind[:5] = 1
        found = [{"at": np.array([20.0, 0.0]), "half": 5.0}]
        p = corridor.open_samples({"a": [(self.pts, kind)]}, found)
        self.assertFalse(((p[:, 0] > 20 - 5 - corridor.X_KEEP_M + 0.1) & (p[:, 0] < 20 + 9 - 0.1)).any())
        self.assertFalse((p[:, 0] < -50 + 9).any())
        self.assertTrue(len(p) > 20)

    def test_cut_only_lowers(self):
        class Frame:
            def geodetic_to_enu(self, la, lo, z):
                return np.asarray(lo, float), np.asarray(la, float), np.asarray(z, float)
        gen = lambda la, lo: np.full(np.shape(la), 103.0)  # noqa: E731
        f = corridor.cut(gen, Frame(), self.c)
        z = f(np.array([0.0, 2.0, 50.0]), np.array([0.0, 0.0, 0.0]))
        self.assertAlmostEqual(float(z[0]), 100.0 - corridor.BED_M, delta=0.05)
        self.assertAlmostEqual(float(z[2]), 103.0)
        low = corridor.cut(lambda la, lo: np.full(np.shape(la), 90.0), Frame(), self.c)
        self.assertTrue((low(np.array([0.0]), np.array([0.0])) == 90.0).all())


class ClassesTest(unittest.TestCase):
    def test_abandoned_not_heavy(self):
        self.assertNotIn("unknown", rails.HEAVY_CLASSES)
        self.assertIn("narrow_gauge", rails.HEAVY_CLASSES)


if __name__ == "__main__":
    unittest.main()
