"""Screen-space LOD (farfield.View in select): a node whose built tile's split would pop more than tau px on screen
splits beyond the distance rule (within SSE_REACH of it); smooth or unknown nodes keep the distance rule."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import farfield as ff  # noqa: E402

LAY = ff.LAYOUTS[64] if hasattr(ff, "LAYOUTS") else None


def pick(errs, cx=0.0, cy=0.0, prev=frozenset(), dz=0.0):
    view = ff.View(cx, cy, dz, 1440 / (2 * math.tan(math.radians(65) / 2)), lambda n: errs.get(n), tau=2.0, cap=1e9)
    return ff.select(0.0, 0.0, prev_refined=prev, radius=20000, view=view)


class SseTest(unittest.TestCase):
    def setUp(self):
        self.base, self.base_ref = ff.select(0.0, 0.0, radius=20000)
        # an L3 node just past its distance-rule switch distance
        lim = ff.switch_distance(3)
        s = ff.level_size(3)
        i = int(math.ceil(lim * 1.2 / s))
        self.node = (3, i, 0)
        self.assertIn(ff.Tile(*self.node).key, self.base)

    def test_rough_tile_splits(self):
        out, ref = pick({self.node: 400.0})            # a cliff: 400 m pop
        self.assertNotIn(ff.Tile(*self.node).key, out)
        self.assertIn(self.node, ref)

    def test_smooth_or_unknown_keeps_distance_rule(self):
        for errs in ({self.node: 0.5}, {}):
            out, _ = pick(errs)
            self.assertIn(ff.Tile(*self.node).key, out)

    def test_hysteresis(self):
        lvl, i, j = self.node
        x0 = i * ff.level_size(lvl)
        d = x0
        ppr = 1440 / (2 * math.tan(math.radians(65) / 2))
        e = 1.5 * d / ppr               # 1.5 px: under tau (2), over tau / 1.5
        out, _ = pick({self.node: e})
        self.assertIn(ff.Tile(*self.node).key, out)                 # not split from scratch
        out, _ = pick({self.node: e}, prev=frozenset({self.node}))
        self.assertNotIn(ff.Tile(*self.node).key, out)              # kept split

    def test_reach_caps_the_extra_refinement(self):
        view = ff.View(0.0, 0.0, 0.0, 2000.0, lambda n: 5000.0, reach=1.0, tau=2.0)    # every tile a cliff, no reach
        out, _ = ff.select(0.0, 0.0, radius=20000, view=view)
        self.assertEqual(set(out), set(self.base))
        view = ff.View(0.0, 0.0, 0.0, 2000.0, lambda n: 5000.0, tau=2.0)       # default reach: ~2 levels more
        out, _ = ff.select(0.0, 0.0, radius=20000, view=view)
        self.assertGreater(len(out), len(self.base))
        self.assertLess(len(out), 40 * len(self.base))


class ViewOrderTest(unittest.TestCase):
    def test_in_view_tiles_first(self):
        cone = ff.view_cone({"x": 0, "y": 0, "fx": 0, "fy": 1, "fovDeg": 65})       # looking north
        ahead, behind = ff.Tile(1, 0, 4), ff.Tile(1, 0, -5)
        self.assertAlmostEqual(ff.view_distance(ahead, cone, 0, 0), ahead.distance(0, 0))
        self.assertAlmostEqual(ff.view_distance(behind, cone, 0, 0), ff.VIEW_PENALTY * behind.distance(0, 0))
        self.assertLess(ff.view_distance(ahead, cone, 0, 0), ff.view_distance(behind, cone, 0, 0))

    def test_no_heading_no_penalty(self):
        self.assertIsNone(ff.view_cone({"x": 0, "y": 0, "fx": 0, "fy": 0.05, "fovDeg": 65}))     # looking down
        self.assertIsNone(ff.view_cone({"x": 0}))
        t = ff.Tile(1, 0, -5)
        self.assertEqual(ff.view_distance(t, None, 0, 0), t.distance(0, 0))


if __name__ == "__main__":
    unittest.main()
