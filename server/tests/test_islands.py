"""islands: traffic islands inside small road loops (roundabouts, turnaround loops)."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import islands  # noqa: E402
import roads  # noqa: E402


def arc(r, a0, a1, n=12, cx=0.0, cy=0.0):
    t = np.linspace(a0, a1, n)
    return np.stack([cx + r * np.cos(t), cy + r * np.sin(t), np.zeros(n)], 1)


class IslandTest(unittest.TestCase):
    def test_roundabout_ring(self):
        ow = roads.Spec(6.0, "paved", True, "residential", True)
        two = roads.Spec(9.0, "paved", True, "residential", False)
        rs = [("r1", ow, arc(16, 0, math.pi), 0.0), ("r2", ow, arc(16, math.pi, 2 * math.pi), 0.0),
              ("app", two, np.array([(16.0, 0.0, 0.0), (80.0, 0.0, 0.0)]), 0.0)]
        f = islands.find(rs)
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["inner"], {"r1": 1, "r2": 1}, "counter-clockwise ring: the inside is its left")
        ring = f[0]["ring"]
        r = np.hypot(ring[:, 0], ring[:, 1])
        self.assertTrue(np.all(np.abs(r - 13.0) < 0.8), "the curb line is the ring inset by its half width")
        self.assertTrue(islands.in_island(f, (0.0, 0.0)) and not islands.in_island(f, (40.0, 0.0)))

    def test_a_road_through_the_loop_is_no_island(self):
        ow = roads.Spec(6.0, "paved", True, "residential", True)
        rs = [("r1", ow, arc(16, 0, math.pi), 0.0), ("r2", ow, arc(16, math.pi, 2 * math.pi), 0.0)]
        self.assertEqual(len(islands.find(rs)), 1)
        # a turn lane across it, joined to neither half at the loop's corners (Timisoara 2026-10-15)
        lane = ("lane", ow, np.array([(-30.0, 3.0, 0.0), (30.0, 3.0, 0.0)]), 0.0)
        self.assertEqual(islands.find(rs + [lane]), [])

    def test_turnaround_loop_with_a_two_way_link(self):
        ow = roads.Spec(5.8, "paved", True, "residential", True)
        two = roads.Spec(10.6, "paved", True, "residential", False)
        loop = arc(12, math.pi, 2 * math.pi, cy=0.0)                 # south half, west to east, one-way
        link = np.array([(12.0, 0.0, 0.0), (-12.0, 0.0, 0.0)])       # north side, two-way
        f = islands.find([("loop", ow, loop, 0.0), ("link", two, link, 0.0)])
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["inner"]["loop"], 1, "the loop runs anticlockwise: its left faces the island")
        self.assertEqual(f[0]["inner"]["link"], 1, "the link runs east to west: its left (south) faces it")

    def test_loop_round_a_building_is_a_block(self):
        ow = roads.Spec(6.0, "paved", True, "residential", True)
        rs = [("r1", ow, arc(16, 0, math.pi), 0.0), ("r2", ow, arc(16, math.pi, 2 * math.pi), 0.0)]
        self.assertEqual(islands.find(rs, structures=[(2.0, 1.0)]), [], "a building inside: not an island")

    def test_city_block_keeps_its_sidewalks(self):
        two = roads.Spec(9.0, "paved", True, "residential", False)
        sq = [((0, 0), (50, 0)), ((50, 0), (50, 50)), ((50, 50), (0, 50)), ((0, 50), (0, 0))]
        rs = [(f"s{i}", two, np.array([(a[0], a[1], 0.0), (b[0], b[1], 0.0)]), 0.0) for i, (a, b) in enumerate(sq)]
        self.assertEqual(islands.find(rs), [], "two-way streets round a block: not an island")


class RingTest(unittest.TestCase):
    def test_rings(self):
        two = roads.Spec(7.0, "paved", True, "tertiary", False)
        ow = roads.Spec(7.0, "paved", True, "primary", True, 2.5, 1)
        circle = [(f"c{k}", two, arc(14, k * math.pi / 3, (k + 1) * math.pi / 3, 4), 0.0) for k in range(6)]
        self.assertEqual(islands.ring_fids(circle), {f"c{k}" for k in range(6)}, "a round loop: a ring, oneway or not")
        sq = [((0, 0), (60, 0)), ((60, 0), (60, 60)), ((60, 60), (0, 60)), ((0, 60), (0, 0))]
        block = [(f"s{k}", ow, np.array([(*a, 0.0), (*b, 0.0)]), 0.0) for k, (a, b) in enumerate(sq)]
        self.assertEqual(islands.ring_fids(block), set(), "a block of one-way streets driven round: no ring")
        back = roads.Spec(7.0, "paved", True, "primary", True, 2.5, -1)
        pair = [("n", ow, np.array([(0.0, 0.0, 0.0), (0.0, 200.0, 0.0)]), 0.0),
                ("s", back, np.array([(12.0, 0.0, 0.0), (12.0, 200.0, 0.0)]), 0.0),
                ("j0", two, np.array([(0.0, 0.0, 0.0), (12.0, 0.0, 0.0)]), 0.0),
                ("j1", two, np.array([(0.0, 200.0, 0.0), (12.0, 200.0, 0.0)]), 0.0)]
        self.assertEqual(islands.ring_fids(pair), set(), "a divided road's carriageways: no ring")


if __name__ == "__main__":
    unittest.main()
