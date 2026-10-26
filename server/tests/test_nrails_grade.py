import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import grading  # noqa: E402
from nrails import grade, rails  # noqa: E402


class UnderBridgeTest(unittest.TestCase):
    def test_bed_kept_off_a_road_under_a_short_bridge(self):
        """A track on an embankment 5 m over a street, its bridge mapped 7 m long over a 7 m wide road: the rail
        bed's plan stops RAIL_BED_HALF_M + UNDER_GAP_M off the road's carriageway on both sides (its core imposed the
        embankment's level on the road's edges)."""
        x = np.arange(-60.0, 60.1, rails.STEP_M)
        pts = np.c_[x, np.zeros(len(x)), np.full(len(x), 5.6)]
        kind = np.where(np.abs(x) <= 3.5, 1, 0).astype(np.int8)
        road = ("r", np.array([[0.0, -50.0], [0.0, 50.0]]), 3.5)
        own = (-100.0, -100.0, 100.0, 100.0)
        plans = grade._plans({"t": [(pts, kind)]}, [], own, grading, rails, [road])
        self.assertTrue(plans)
        for _fid, p in plans:
            self.assertGreater(np.abs(p.xy[:, 0]).min(), 3.5 + grade.RAIL_BED_HALF_M + grade.UNDER_GAP_M - 1e-6)
        before = grade._plans({"t": [(pts, kind)]}, [], own, grading, rails, ())
        self.assertLess(min(np.abs(p.xy[:, 0]).min() for _f, p in before), 5.0, "(it reached the road before)")

    def test_no_road_under_it_no_trim(self):
        x = np.arange(-60.0, 60.1, rails.STEP_M)
        pts = np.c_[x, np.zeros(len(x)), np.full(len(x), 5.6)]
        kind = np.where(np.abs(x) <= 3.5, 1, 0).astype(np.int8)
        road = ("r", np.array([[30.0, 20.0], [30.0, 50.0]]), 3.5)       # (beside, not under it)
        plans = grade._plans({"t": [(pts, kind)]}, [], (-100.0, -100.0, 100.0, 100.0), grading, rails, [road])
        self.assertLess(min(np.abs(p.xy[:, 0]).min() for _f, p in plans), 5.0)


if __name__ == "__main__":
    unittest.main()
