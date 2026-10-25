"""groundahead.py: the highest ground near the player's straight path (the mod's altitude rule)."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geodesy as g  # noqa: E402
import groundahead as ga  # noqa: E402

LAT0, LON0 = 39.28, -76.59


class FakeDem:
    """A peak of `top` m at frame point (px, py) with radius r, 10 m elsewhere."""

    def __init__(self, frame, px, py, top, r=100.0):
        self.frame, self.px, self.py, self.top, self.r = frame, px, py, top, r
        self.zooms = []

    def sample(self, lat, lon, zoom):
        self.zooms.append(zoom)
        e, n, _ = self.frame.geodetic_to_enu(lat, lon, np.zeros_like(lat))
        return np.where(np.hypot(e - self.px, n - self.py) < self.r, self.top, 10.0)


class GroundAheadTest(unittest.TestCase):
    def setUp(self):
        self.frame = g.EnuFrame(LAT0, LON0)

    def test_flat(self):
        z = ga.highest(FakeDem(self.frame, 1e6, 0, 0), self.frame, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(z, 10.0 + ga.MARGIN, delta=0.1)

    def test_peak_ahead_on_the_path(self):
        # 900 m ahead at 100 m/s: within AHEAD_S (10 s); to the side within RADIUS
        dem = FakeDem(self.frame, 900.0, 200.0, 900.0)
        self.assertAlmostEqual(ga.highest(dem, self.frame, 0.0, 0.0, 100.0, 0.0), 900.0 + ga.MARGIN, delta=1.0)
        self.assertEqual(set(dem.zooms), {ga.ZOOM})

    def test_peak_behind_or_too_far(self):
        behind = FakeDem(self.frame, -2000.0, 0.0, 900.0)
        self.assertLess(ga.highest(behind, self.frame, 0.0, 0.0, 100.0, 0.0), 100.0)
        far = FakeDem(self.frame, 5000.0, 0.0, 900.0)     # beyond MAX_PATH at 300 m/s
        self.assertLess(ga.highest(far, self.frame, 0.0, 0.0, 300.0, 0.0), 100.0)

    def test_curvature(self):
        # flat sea-level ground 3 km away lies below the frame's z = 0 plane (d^2 / 2R ~ 0.7 m)
        dem = FakeDem(self.frame, 1e6, 0, 0)
        dem.sample = lambda lat, lon, zoom: np.zeros_like(lat)
        z = ga.highest(dem, self.frame, 3000.0, 0.0, 0.0, 0.0)
        self.assertLess(z - ga.MARGIN, -0.5)


if __name__ == "__main__":
    unittest.main()
