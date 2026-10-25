"""Runway grading (server/runwaygeom.py) on synthetic DEMs: the frame, the zones, the profile against
the design limits (radius, grade, pinned ends), data end elevations against the DEM, steep and relaxed
runways, a coarse DEM, crossing runways, continuity (no steps), untouched terrain outside, the
footprint, determinism, and the drop-in elev_fn through heightmap.grid_u. No network."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import airportfixtures as af  # noqa: E402
import airports  # noqa: E402
import geodesy  # noqa: E402
import heightmap  # noqa: E402
import runwaygeom as rg  # noqa: E402

LAT0, LON0 = 45.0, 7.0


def make(id=1, lat=LAT0, lon=LON0, heading=90.0, length=2000.0, width=45.0, paved=True, le_elev=None,
         he_elev=None, closed=False, center=True):
    """An airports.Runway centred on (lat, lon) (or starting there with center=False)."""
    if center:
        lat, lon = airports._offset(lat, lon, (heading + 180) % 360, length / 2)
    hlat, hlon = airports._offset(lat, lon, heading, length)

    def end(ident, la, lo, e, h):
        return airports.RunwayEnd(ident, la, lo, e, "data" if e is not None else "none", h, 0.0, "data")
    cls = "asphalt" if paved else "grass"
    return airports.Runway(id=id, airport_id=1, airport_ident="T", airport_type="medium_airport", airport_name="T",
                           country="FR", le=end("09", lat, lon, le_elev, heading),
                           he=end("27", hlat, hlon, he_elev, (heading + 180) % 360), length_m=length, width_m=width,
                           width_source="data", surface_raw=cls, surface=cls, condition=None,
                           ground_model="ASPHALT" if paved else "GRASS", paved=paved, surface_known=True,
                           lighted=paved, closed=closed, quality="surveyed", length_data_m=length)


def along(rw, frac=0.5):
    return rg.geometry(rw).latlon(np.array([frac * rw.length_m]), np.array([0.0]))


def surface(p, s, t):
    """The paved surface height of plan p at runway-local (s, t)."""
    return rg._core(p, np.asarray(s, float), np.asarray(t, float))


class FrameTest(unittest.TestCase):
    def test_st_roundtrip(self):
        rw = make(heading=37.0, length=1800.0)
        g = rg.geometry(rw)
        self.assertAlmostEqual(g.length, 1800.0, delta=0.01)
        s = np.array([0.0, 900.0, 1800.0, -50.0, 333.3])
        t = np.array([0.0, 10.0, -20.0, 5.0, 100.0])
        lat, lon = g.latlon(s, t)
        s2, t2 = g.st(lat, lon)
        np.testing.assert_allclose(s2, s, atol=2e-3)
        np.testing.assert_allclose(t2, t, atol=2e-3)
        # s = 0 is the le end, t > 0 to the left (north when heading east)
        s3, t3 = rg.geometry(make(heading=90.0)).st(np.array([LAT0 + 0.0001]), np.array([LON0]))
        self.assertGreater(t3[0], 0)
        self.assertAlmostEqual(s3[0], 1000.0, delta=0.01)

    def test_limits_by_code(self):
        self.assertEqual([rg.runway_code(x) for x in (500, 800, 1199, 1200, 1799, 1800, 4000)], [1, 2, 2, 3, 3, 4, 4])
        self.assertEqual(rg.geometry(make(length=3000)).strip_half, 75.0)
        self.assertEqual(rg.geometry(make(length=600, width=18, paved=False)).strip_half, 30.0)
        self.assertEqual(rg.geometry(make(length=600, width=18, paved=False)).shoulder, 0.0)
        self.assertEqual(rg.geometry(make(width=45)).shoulder, 7.5)


class FlatTest(unittest.TestCase):
    def setUp(self):
        self.rw = make(length=2000.0, width=45.0)
        self.dem = af.plane(100.0)
        self.p = rg.plan(self.rw, self.dem)
        self.c = rg.CROWN_PAVED * (math.sqrt(11.25 ** 2 + 1) - 1)

    def test_profile_flat(self):
        # each cross-section sample implies a centreline height with this runway's crown: on a flat DEM
        # (no crown in it) the median is the one at W/4, so the cross-section keeps the DEM's level
        np.testing.assert_allclose(self.p.z, 100.0 + self.c, atol=1e-9)
        self.assertEqual(self.p.blend, rg.B_MIN)
        self.assertFalse(self.p.steep)

    def test_cross_section_and_zones(self):
        g = self.p.geom
        t = np.array([0.0, 10.0, 22.4, 26.0, 29.9, 60.0, 74.9, 80.0, 94.0, 96.0, 200.0])
        lat, lon = g.latlon(np.full(t.shape, 1000.0), t)
        z, w, zone = rg.apply([self.p], lat, lon, self.dem(lat, lon))
        crown = rg.CROWN_PAVED * (math.sqrt(22.5 ** 2 + 1) - 1)
        crown_224 = rg.CROWN_PAVED * (math.sqrt(22.4 ** 2 + 1) - 1)
        c = 100.0 + self.c
        self.assertAlmostEqual(z[0], c, places=6)
        self.assertAlmostEqual(z[2], c - crown_224, places=5)
        self.assertAlmostEqual(z[4], c - crown - rg.SHOULDER_SLOPE * 7.4, places=5)   # near the shoulder edge
        self.assertLess(abs(np.mean(z[:3]) - 100.0), 0.1)
        self.assertEqual(list(zone), [4, 4, 4, 3, 3, 2, 2, 1, 1, 0, 0])
        np.testing.assert_allclose(z[5:], 100.0, atol=1e-6)     # the strip follows the (flat) terrain
        self.assertEqual(list(w[:7]), [1.0] * 7)
        self.assertEqual(w[-1], 0.0)

    def test_untouched_outside_bitwise(self):
        lat = np.linspace(LAT0 - 0.02, LAT0 + 0.02, 201)
        lon = np.full(lat.shape, LON0 + 0.03)                   # 2.4 km east of the middle: outside
        e = self.dem(lat, lon) + np.linspace(0, 1, lat.size)
        z, w, zone = rg.apply([self.p], lat, lon, e)
        self.assertTrue(np.array_equal(z, e))
        self.assertFalse(w.any() or zone.any())


class ProfileTest(unittest.TestCase):
    def test_follows_a_gentle_slope(self):
        dem = af.plane(100.0, 0.005, 0.0)                       # 0.5 % rising east, along the runway
        p = rg.plan(make(length=3000.0), dem)
        self.assertEqual(p.target_source, "dem (no data ends)")
        self.assertLess(p.stats["dem_rmse_m"], 0.01)
        self.assertAlmostEqual(p.stats["overall_grade_pct"], 0.5, delta=0.01)

    def test_limits_on_a_bumpy_dem(self):
        dem = af.plane(100.0, 0.0, 0.0, bumps=3.0)              # +-3 m waves of ~600 m
        for length, paved in ((3200.0, True), (1500.0, True), (900.0, True)):
            p = rg.plan(make(length=length), dem)
            lim = p.geom.limits
            ds = p.s[1] - p.s[0]
            curv = np.abs(np.diff(p.z, 2)) / ds ** 2
            grade = np.abs(np.diff(p.z)) / ds
            self.assertLessEqual(curv.max(), 1 / lim.min_radius + 1e-12, length)
            self.assertLessEqual(grade.max(), max(lim.max_grade, abs(p.stats["overall_grade_pct"]) / 100
                                                  + rg.GRADE_MARGIN) + 1e-12)
            self.assertAlmostEqual(p.z[0], p.targets[0], places=9)      # ends pinned
            self.assertAlmostEqual(p.z[-1], p.targets[1], places=9)
            self.assertGreater(p.stats["dem_rmse_m"], 0.0)

    def test_data_ends_give_the_gradient_dem_the_level(self):
        dem = af.plane(100.0, 0.001, 0.0)                        # DEM: +2 m over 2 km
        rw = make(length=2000.0, le_elev=150.0, he_elev=154.0)   # data: +4 m, 51-52 m above the DEM
        p = rg.plan(rw, dem)
        self.assertEqual(p.target_source, "data")
        self.assertAlmostEqual(p.targets[1] - p.targets[0], 4.0, delta=1e-6)
        dem_mid = (p.dem[0] + p.dem[-1]) / 2
        self.assertAlmostEqual((p.targets[0] + p.targets[1]) / 2, dem_mid, delta=0.2)

    def test_data_ends_disagreeing_are_ignored(self):
        dem = af.plane(100.0, 0.0, 0.0)
        p = rg.plan(make(length=1000.0, le_elev=100.0, he_elev=130.0), dem)     # 30 m: > max(10, 3 % L)
        self.assertEqual(p.target_source, "dem (data ends disagree)")
        p = rg.plan(make(length=1000.0, le_elev=300.0, he_elev=300.0), dem)     # 200 m off: datum / data error
        self.assertEqual(p.target_source, "dem (data offset)")
        np.testing.assert_allclose(p.targets, (100.0 + p.dem[0] - 100.0,) * 2, atol=1e-6)
        np.testing.assert_allclose(p.dem, p.dem[0], atol=1e-9)

    def test_steep_runway_keeps_its_shape(self):
        # an altiport: 12 % overall, steepening towards le (a convex knee), data ends agree
        k = 111320.0 * math.cos(math.radians(LAT0))

        def dem(lat, lon):
            x = (np.asarray(lon) - LON0) * k + 270.0             # 0 at the le end, east along the runway
            return 2000.0 + 0.12 * x + 15.0 * np.exp(-((x - 120.0) / 60.0) ** 2)
        rw = make(length=540.0, width=40.0, le_elev=2000.0, he_elev=2064.8)
        p = rg.plan(rw, dem)
        self.assertTrue(p.steep)
        self.assertEqual(p.geom.strip_half, p.geom.paved_half + rg.STEEP_STRIP)
        self.assertEqual(p.geom.strip_end, rg.STEEP_STRIP_END)
        ds = p.s[1] - p.s[0]
        self.assertLessEqual((np.abs(np.diff(p.z, 2)) / ds ** 2).max(), 1 / rg.STEEP_RADIUS + 1e-12)
        self.assertGreater(p.stats["max_grade_pct"], 13.0)       # the bump survives (not a straight line)
        self.assertLess(p.stats["dem_rmse_m"], 3.0)
        coarse = rg.plan(rw, dem, dem_res=30.0)
        self.assertEqual(coarse.stats["limit_min_radius_m"], 1500.0)
        self.assertGreater(coarse.stats["dem_rmse_m"], p.stats["dem_rmse_m"])
        # the strip beyond the ends continues the end grade: no wall at the top of the slope
        lat, lon = p.geom.latlon(np.array([p.geom.length + 10.0]), np.array([0.0]))
        z = rg.apply([p], lat, lon, dem(lat, lon))[0]
        self.assertAlmostEqual(z[0], float(dem(lat, lon)[0]), delta=1.0)

    def test_unpaved_strip_relaxed(self):
        k = 111320.0 * math.cos(math.radians(LAT0))

        def dem(lat, lon):                                      # 1 % then 5 % over the last 200 m
            x = (np.asarray(lon) - LON0) * k + 500.0
            return 1500.0 + 0.01 * x + 0.04 * np.maximum(x - 800.0, 0.0)
        paved = rg.plan(make(length=1000.0, paved=True), dem)
        grass = rg.plan(make(length=1000.0, paved=False, width=30.0), dem)
        self.assertFalse(paved.stats["relaxed"])
        self.assertTrue(grass.stats["relaxed"])
        self.assertLess(grass.stats["dem_max_dev_m"], paved.stats["dem_max_dev_m"])


class FieldTest(unittest.TestCase):
    def test_no_steps(self):
        dem = af.plane(300.0, 0.03, -0.02, bumps=4.0)            # a tilted, wavy hillside
        rws = [make(1, length=1600.0, heading=70.0), make(2, length=900.0, heading=160.0, paved=False, width=25.0)]
        plans = rg.plan_group(rws, dem)
        g = plans[0].geom
        for t0 in (0.0, 30.0, 90.0):
            s = np.arange(-400.0, 2000.0, 0.25)
            lat, lon = g.latlon(s, np.full(s.shape, t0))
            z = rg.apply(plans, lat, lon, dem(lat, lon))[0]
            self.assertLess(np.abs(np.diff(z)).max(), 0.25 * 0.5, t0)          # < 50 % slope: no step
        for s0 in (-30.0, 200.0, 800.0, 1650.0):
            t = np.arange(-400.0, 400.0, 0.25)
            lat, lon = g.latlon(np.full(t.shape, s0), t)
            z = rg.apply(plans, lat, lon, dem(lat, lon))[0]
            self.assertLess(np.abs(np.diff(z)).max(), 0.25 * 0.5, s0)

    def test_blend_and_footprint(self):
        dem = af.plane(100.0, 0.0, 0.08)                         # 8 % across the runway: big cut and fill
        rw = make(length=1500.0, width=30.0)
        p = rg.plan(rw, dem)
        self.assertTrue(rg.B_MIN <= p.blend <= rg.B_MAX)
        self.assertGreater(p.blend, rg.B_MIN)
        g = p.geom
        lat = np.linspace(LAT0 - 0.01, LAT0 + 0.01, 401)
        lon = np.linspace(LON0 - 0.015, LON0 + 0.015, 401)
        LA, LO = np.meshgrid(lat, lon, indexing="ij")
        z, w, zone = rg.apply([p], LA, LO, dem(LA, LO))
        s, t = g.st(LA[w > 0], LO[w > 0])
        s0, s1, th = g.reach_rect(p.blend)
        self.assertTrue(((s >= s0 - 1e-6) & (s <= s1 + 1e-6) & (np.abs(t) <= th + 1e-6)).all())
        f = geodesy.EnuFrame(LAT0, LON0)
        poly = rg.footprint_polygon(rw, f)
        e, n, _ = f.geodetic_to_enu(LA[w > 0], LO[w > 0], 0.0)
        self.assertTrue(airports._convex_overlap(poly, np.stack([e, n], 1)[:3]))
        # the added slope in the blend stays within BLEND_SLOPE plus what the strip's clamp band adds
        # (the terrain's cross slope minus the strip slope: 8 - 2.5 %)
        tt = np.arange(g.strip_half, g.strip_half + p.blend, 0.5)
        la2, lo2 = g.latlon(np.full(tt.shape, 700.0), tt)
        d = rg.apply([p], la2, lo2, dem(la2, lo2))[0] - dem(la2, lo2)
        self.assertLessEqual(np.abs(np.diff(d)).max() / 0.5, rg.BLEND_SLOPE + 0.08 - 0.025 + 1e-6)

    def test_crossing_runways(self):
        dem = af.plane(100.0, 0.004, 0.003, bumps=1.0)
        a = make(1, length=3000.0, heading=90.0)
        b = make(2, length=2000.0, heading=30.0)
        plans = rg.plan_group([b, a], dem)
        self.assertEqual([p.key for p in plans], ["oa:1", "oa:2"])          # longest first
        lat, lon = np.array([LAT0]), np.array([LON0])                        # both centres meet here
        z = rg.apply(plans, lat, lon, dem(lat, lon))[0]
        za = rg.apply(plans[:1], lat, lon, dem(lat, lon))[0]
        self.assertEqual(z[0], za[0])                                        # the main runway's surface
        gb = plans[1].geom                                                   # far from the crossing: b's own
        la, lo = gb.latlon(np.array([150.0]), np.array([0.0]))
        z = rg.apply(plans, la, lo, dem(la, lo))[0]
        self.assertAlmostEqual(z[0], float(surface(plans[1], 150.0, 0.0)), places=6)
        # the second plan was fitted on the field the first one made
        self.assertEqual(rg.groups([a, b]), [[a, b]])
        self.assertEqual(rg.groups([a, make(3, lat=LAT0 + 0.1, length=800)]), [[a], [make(3, lat=LAT0 + 0.1, length=800)]])

    def test_deterministic(self):
        dem = af.plane(200.0, 0.01, 0.0, bumps=2.0)
        rws = [make(1, length=2500.0, heading=80.0), make(2, length=1200.0, heading=10.0)]
        p1 = rg.plan_group(rws, dem)
        p2 = rg.plan_group(list(reversed(rws)), dem)
        for a, b in zip(p1, p2):
            self.assertTrue(np.array_equal(a.z, b.z))
            self.assertEqual(a.blend, b.blend)
        rng = np.random.default_rng(5)
        lat = LAT0 + rng.uniform(-0.01, 0.01, 4000)
        lon = LON0 + rng.uniform(-0.02, 0.02, 4000)
        z = rg.apply(p1, lat, lon, dem(lat, lon))[0]
        perm = rng.permutation(4000)
        z2 = rg.apply(p1, lat[perm], lon[perm], dem(lat[perm], lon[perm]))[0]
        self.assertTrue(np.array_equal(z[perm], z2))
        z3 = np.concatenate([rg.apply(p1, lat[i:i + 333], lon[i:i + 333], dem(lat[i:i + 333], lon[i:i + 333]))[0]
                             for i in range(0, 4000, 333)])
        self.assertTrue(np.array_equal(z, z3))
        self.assertTrue(np.array_equal(rg.graded_elev_fn(dem, p1)(lat, lon), z))

    def test_heightmap_dropin(self):
        dem = af.plane(150.0, 0.002, 0.001, bumps=1.0)
        rw = make(length=1500.0, heading=90.0)
        plans = rg.plan_group([rw], dem)
        lat_c, lon_c = rg.geometry(rw).lat_c, rg.geometry(rw).lon_c
        frame = geodesy.EnuFrame(lat_c, lon_c, 0.0)
        u0 = heightmap.grid_u(frame, dem, 0.0, 0.0, size=256)
        u1 = heightmap.grid_u(frame, rg.graded_elev_fn(dem, plans), 0.0, 0.0, size=256)
        changed = np.abs(u1 - u0) > 0
        self.assertTrue(changed.any())
        xs, ys = heightmap.sample_coords(0.0, 0.0, 256)
        # the sample at the runway's middle (0, 0) is the graded centreline height (minus the curvature)
        j, i = int(np.searchsorted(ys, 0.0)), int(np.searchsorted(xs, 0.0))
        self.assertAlmostEqual(u1[j, i], plans[0].profile(np.array([750.0]))[0], delta=0.01)
        E, N = np.meshgrid(xs, ys)
        far = np.hypot(E, N) > 760 + 75 + plans[0].blend + 5
        self.assertFalse(changed[far & (np.abs(N) > 75 + plans[0].blend + 5)].any())


if __name__ == "__main__":
    unittest.main()
