"""rockface.py: steep ground in the far tiles' photos drawn as rock."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import geodesy  # noqa: E402
import rockface  # noqa: E402


class RockFaceTest(unittest.TestCase):
    def setUp(self):
        self.frame = geodesy.EnuFrame(46.59, 7.91, 0.0)

    def test_flat_ground_unchanged(self):
        rgb = np.full((64, 64, 3), (60, 140, 50), np.uint8)
        U = np.zeros((9, 9), np.float32)
        out = rockface.rock(rgb, self.frame, 0.0, 0.0, 256.0, U, 0.0, 0.0, 32.0)
        self.assertIs(out, rgb)

    def test_cliff_turns_to_rock_and_varies(self):
        """A wall in the middle of the tile: its texels lose the photo's green, the flat parts keep it."""
        rgb = np.full((128, 128, 3), (60, 140, 50), np.uint8)
        x = np.arange(9) * 32.0
        U = np.tile(np.where(x < 112, 0.0, 300.0), (9, 1)).astype(np.float32)      # a 300 m step at x ~ 128
        U[:, 4] = 150.0
        out = rockface.rock(rgb, self.frame, 0.0, 0.0, 256.0, U, 0.0, 0.0, 32.0)
        wall = out[:, 60:68].reshape(-1, 3).astype(int)
        flat = out[:, 5:10].reshape(-1, 3).astype(int)
        self.assertTrue((flat == (60, 140, 50)).all())
        self.assertLess(np.mean(wall[:, 1] - wall[:, 0]), 40, "the wall's green mostly gone")
        self.assertGreater(wall.std(), 0.0, "not one flat colour")

    def test_deterministic_and_smooth(self):
        """The same wall gives the same rock every time, varied but without texel-to-texel jumps."""
        rgb = np.full((64, 64, 3), (60, 140, 50), np.uint8)
        U = np.tile(np.linspace(0.0, 400.0, 9), (9, 1))
        a = rockface.rock(rgb, self.frame, 0.0, 0.0, 256.0, U, 0.0, 0.0, 32.0)
        b = rockface.rock(rgb, self.frame, 0.0, 0.0, 256.0, U, 0.0, 0.0, 32.0)
        np.testing.assert_array_equal(a, b)
        self.assertGreater(np.abs(np.diff(a.astype(int), axis=1)).max(), 0, "the noise varies")
        self.assertLess(np.abs(np.diff(a.astype(int), axis=1)).mean(), 20, "and is smooth")


if __name__ == "__main__":
    unittest.main()
