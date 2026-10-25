"""dsmground.py: buildings and small tree stands out of a surface model, hills kept."""
import os
import sys
import unittest

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dsmground as g  # noqa: E402

PX = 18.0   # m per pixel (a z12 tile at mid latitudes)


class DsmGroundTest(unittest.TestCase):
    def test_town_blocks_come_down_to_the_streets(self):
        """A gently sloping plain with 120 m blocks 12 m high between 20 m streets: the blocks go, the plain stays."""
        y, x = np.mgrid[0:200, 0:200].astype(np.float32)
        plain = 100.0 + 0.01 * x * PX
        town = plain.copy()
        period = int(140 / PX)
        blocks = ((x % period) < period - 1) & ((y % period) < period - 1) & (x > 50) & (x < 150) & (y > 50) & (y < 150)
        town[blocks] += 12.0
        out = g.ground(town, PX)
        self.assertLess(np.abs(out - plain)[60:140, 60:140].max(), 1.5)
        self.assertLess(np.abs(out - plain).mean(), 0.3)

    def test_hills_stay(self):
        """A 300 m wide, 120 m high hill and a 60 m high ridge stay as they are."""
        y, x = np.mgrid[0:200, 0:200].astype(np.float32)
        d = np.hypot(x - 100, y - 100) * PX
        hill = 50.0 + 120.0 * np.exp(-(d / 150.0) ** 2)
        np.testing.assert_allclose(g.ground(hill, PX), hill, atol=0.5)
        ridge = 50.0 + 60.0 * np.exp(-((x - 100) * PX / 120.0) ** 2) + 0.02 * y * PX
        # (the interior: the server crops the margin it filters with)
        np.testing.assert_allclose(g.ground(ridge, PX)[20:-20, 20:-20], ridge[20:-20, 20:-20], atol=0.5)

    def test_flat_ground_untouched(self):
        a = np.full((64, 64), 7.0, np.float32)
        np.testing.assert_array_equal(g.ground(a, PX), a)


if __name__ == "__main__":
    unittest.main()
