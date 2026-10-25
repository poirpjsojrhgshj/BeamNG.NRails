"""mapgeom.Features.outer_centres: the prefilter tile_buildings uses (close to each first ring's mean)."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import geodesy  # noqa: E402
import mapgeom  # noqa: E402


class OuterCentresTest(unittest.TestCase):
    def test_close_to_the_ring_means(self):
        rng = np.random.default_rng(3)
        lonlat, part_off, ring_off, coord_off = [], [0], [0], [0]
        for i in range(300):
            if i % 37 == 0:                                 # a feature without parts
                part_off.append(part_off[-1])
                continue
            k = int(rng.integers(1, 9))                     # some rings too short to count
            c = np.array([-76.6, 39.28]) + rng.normal(0, 0.02, 2)
            ring = c + rng.normal(0, 1e-4, (k, 2))
            ring = np.vstack([ring, ring[:1]])
            lonlat.append(ring)
            coord_off.append(coord_off[-1] + len(ring))
            ring_off.append(ring_off[-1] + 1)
            part_off.append(part_off[-1] + 1)
        f = mapgeom.Features(layer="b", ids=np.array([f"{i:04d}" for i in range(300)]), kind=np.full(300, 3, np.uint8),
                             part_off=np.array(part_off), ring_off=np.array(ring_off), coord_off=np.array(coord_off),
                             lonlat=np.vstack(lonlat))
        fr = geodesy.EnuFrame(39.28, -76.6, 0.0)
        cx, cy = f.outer_centres(fr)
        checked = 0
        for i in range(300):
            parts = f.parts(i)
            if not parts or not parts[0] or len(parts[0][0]) < 4:
                self.assertTrue(np.isnan(cx[i]) and np.isnan(cy[i]), i)
                continue
            e, n = mapgeom.enu_xy(f, fr, parts[0][0])
            self.assertAlmostEqual(cx[i], e[:-1].mean(), delta=1e-6)
            self.assertAlmostEqual(cy[i], n[:-1].mean(), delta=1e-6)
            checked += 1
        self.assertGreater(checked, 100)
        self.assertIs(f.outer_centres(fr)[0], cx)           # kept per frame


class BoxesTest(unittest.TestCase):
    def test_exact_boxes_of_all_coordinates(self):
        # features of several parts and rings, some without any: each box is the min / max of xy_in over all of
        # the feature's coordinates, exactly (the far buildings' road_lines test uses them in its place)
        rng = np.random.default_rng(5)
        lonlat, part_off, ring_off, coord_off = [], [0], [0], [0]
        for i in range(200):
            nparts = 0 if i % 23 == 0 else int(rng.integers(1, 4))
            for _ in range(nparts):
                for _ in range(int(rng.integers(1, 3))):
                    k = int(rng.integers(1, 7))
                    lonlat.append(np.array([-76.6, 39.28]) + rng.normal(0, 0.01, (k, 2)))
                    coord_off.append(coord_off[-1] + k)
                    ring_off.append(ring_off[-1] + 1)
            part_off.append(len(ring_off) - 1)
        f = mapgeom.Features(layer="r", ids=np.array([f"{i:04d}" for i in range(200)]), kind=np.full(200, 2, np.uint8),
                             part_off=np.array(part_off), ring_off=np.array(ring_off), coord_off=np.array(coord_off),
                             lonlat=np.vstack(lonlat))
        fr = geodesy.EnuFrame(39.28, -76.6, 0.0)
        bb = f.boxes(fr)
        xy = f.xy_in(fr)
        for i in range(200):
            a = f.coord_off[f.ring_off[f.part_off[i]]]
            b = f.coord_off[f.ring_off[f.part_off[i + 1]]]
            if b == a:
                self.assertTrue(np.isinf(bb[i]).all(), i)
                continue
            want = [xy[a:b, 0].min(), xy[a:b, 1].min(), xy[a:b, 0].max(), xy[a:b, 1].max()]
            self.assertEqual(bb[i].tolist(), want, i)
        self.assertIs(f.boxes(fr), bb, "kept per frame")


if __name__ == "__main__":
    unittest.main()
