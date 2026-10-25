"""polardem.py: the polar caps' DEM (Copernicus GLO-30 past Web Mercator's limit): file names, levels, the global
pixel grid, sampling across files, the antimeridian and the pole, missing files as sea level."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import polardem  # noqa: E402


class FakeCog:
    """A file of the caps at a level: heights as a function of the pixel centres' lat / lon."""

    def __init__(self, lat_sw, lon_sw, level, fn):
        f = 1 << level
        cpd = polardem.band_cols(lat_sw)
        self.width, self.height = cpd // f, polardem.ROWS_PER_DEG // f
        rows = np.arange(self.height) * f + (f - 1) / 2.0
        cols = np.arange(self.width) * f + (f - 1) / 2.0
        lat = lat_sw + 1 - rows / polardem.ROWS_PER_DEG
        lon = lon_sw + cols / cpd
        self.grid = fn(lat[:, None], lon[None, :]).astype(np.float32)

    def read_window(self, col0, row0, w, h):
        return self.grid[row0:row0 + h, col0:col0 + w]


class Fake(polardem.PolarDem):
    def __init__(self, fn, existing):
        super().__init__("/nonexistent", None)
        self.fn, self._files, self.opened = fn, set(existing), []

    def _cog(self, name, level, cpd):
        parts = name.split("_")
        lat = int(parts[4][1:]) * (1 if parts[4][0] == "N" else -1)
        lon = int(parts[6][1:]) * (1 if parts[6][0] == "E" else -1)
        self.opened.append((name, level))
        c = FakeCog(lat, lon, level, self.fn)
        assert c.width * (1 << level) == cpd
        return c


def plane(lat, lon):
    return 2000.0 + (lat + 90.0) * 100.0 + np.cos(np.radians(lon)) * 0.0


class PolarDemTest(unittest.TestCase):
    def test_names_and_levels(self):
        self.assertEqual(polardem.file_name(-90, 0), "Copernicus_DSM_COG_10_S90_00_E000_00_DEM")
        self.assertEqual(polardem.file_name(86, -1), "Copernicus_DSM_COG_10_N86_00_W001_00_DEM")
        self.assertEqual(polardem.level_for(10), 0)
        self.assertEqual(polardem.level_for(70), 1)
        self.assertEqual(polardem.level_for(5000), polardem.LEVELS - 1)

    def test_global_grid(self):
        gx, gy = polardem.global_px(-89.0, 0.0, 0)
        self.assertEqual((gx, gy), (180 * 360, 179 * 3600))           # a file's north-west pixel centre
        gx3, gy3 = polardem.global_px(-89.0, 0.0, 3)
        self.assertAlmostEqual(gy3 * 8 + 3.5, gy)                      # overview pixel j: full j * 8 + 3.5

    def all_files(self):
        return {polardem.file_name(a, o) for a in range(-90, -84) for o in range(-180, 180)}

    def test_bands(self):
        self.assertEqual([polardem.band_cols(a) for a in (89, 85, 84, 80, -81, -85, -86, -90)],
                         [360, 360, 720, 720, 720, 720, 360, 360])
        self.assertEqual(polardem.file_lat(np.array([85.0, 85.0001, -85.0, -84.9999, -90.0])).tolist(),
                         [84, 85, -86, -85, -90])     # 85.0 N: N84's top row; 85.0 S: S86's

    def test_across_the_bands(self):
        """Points either side of 85 S (5" columns north of it, 10" south): one smooth surface, no step."""
        d = Fake(plane, self.all_files())
        lat = np.linspace(-84.95, -85.05, 41)
        lon = np.full(41, -175.37)
        np.testing.assert_allclose(d.sample(lat, lon, 30), plane(lat, lon), atol=1e-3)

    def test_sample_across_files_and_pole(self):
        d = Fake(plane, self.all_files())
        lat = np.array([-86.5, -86.0, -87.9999, -89.995, -90.0])
        lon = np.array([10.0, 179.9995, -180.0, 45.0, 0.0])
        want = plane(np.maximum(lat, -90 + 1 / 3600), lon)            # the pole: the grid's last row (1" short)
        np.testing.assert_allclose(d.sample(lat, lon, 30), want, atol=1e-3)
        ring = np.linspace(-180, 180, 37)
        h = d.sample(np.full(37, -89.9), ring, 30)                     # round the pole: every file
        np.testing.assert_allclose(h, plane(-89.9, 0), atol=0.05)
        self.assertTrue(all(level == polardem.LEVELS - 1 for _, level in d.opened[-36:]), "the coarsest level")

    def test_missing_files_are_sea_level(self):
        d = Fake(plane, set())
        np.testing.assert_array_equal(d.sample(np.array([89.99, 87.0]), np.array([0.0, 20.0]), 30), [0.0, 0.0])
        self.assertFalse(d.covers([89.9], [0.0]))
        self.assertTrue(Fake(plane, self.all_files()).covers([-89.9], [0.0]))


if __name__ == "__main__":
    unittest.main()
