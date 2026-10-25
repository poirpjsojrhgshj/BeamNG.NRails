"""NRails: server/rails.py (track geometry, profile, turnouts, level crossings)."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from nrails import rails  # noqa: E402


class FlatGround:
    """rails.Ground stand-in: z = f(x, y)."""

    def __init__(self, f=lambda x, y: np.zeros_like(x)):
        self.f = f

    def z(self, x, y):
        x = np.asarray(x, np.float64).ravel()
        y = np.asarray(y, np.float64).ravel()
        return self.f(x, y)


def outward_ok(mesh, inside_point):
    """Share of triangles whose normal points away from inside_point."""
    P, T = np.concatenate(mesh.P), np.concatenate(mesh.T)
    V = P[T]
    n = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
    return float(((n * (V.mean(1) - inside_point)).sum(1) > 0).mean())


class TestHelpers(unittest.TestCase):
    def test_chaikin_keeps_ends_and_rounds(self):
        p = np.array([[0, 0], [100, 0], [100, 100]], float)
        q = rails.chaikin(p)
        self.assertTrue(np.allclose(q[0], p[0]) and np.allclose(q[-1], p[-1]))
        self.assertGreater(len(q), len(p))
        self.assertGreater(np.hypot(*(q - [100, 0]).T).min(), 5.0)     # the corner is cut

    def test_resample_step(self):
        xy, s = rails.resample(np.array([[0, 0], [10, 0]], float), 2.0)
        self.assertEqual(len(xy), 6)
        self.assertAlmostEqual(s[-1], 10.0)

    def test_maxfilter_and_smooth(self):
        v = np.zeros(50)
        v[25] = 1.0
        self.assertEqual(rails.maxfilter(v, 2)[23:28].tolist(), [1, 1, 1, 1, 1])
        self.assertAlmostEqual(float(rails.gsmooth(np.ones(20), 3).mean()), 1.0)

    def test_rail_section_is_closed_ccw(self):
        sec = rails.rail_section(rails.PROFILES["uic60"])
        self.assertGreater(rails.signed_area(sec), 0)
        self.assertAlmostEqual(sec[:, 1].min(), -0.172)
        self.assertAlmostEqual(sec[:, 0].max() - sec[:, 0].min(), 0.150)


class TestSweep(unittest.TestCase):
    def test_box_faces_outward_both_orientations(self):
        pts = np.c_[np.linspace(0, 20, 11), np.zeros(11), np.zeros(11)]
        nrm = rails.normals(pts[:, :2])
        for prof in ([(-1, 0), (-1, -1), (1, -1), (1, 0)], [(1, 0), (1, -1), (-1, -1), (-1, 0)]):
            m = rails.Mesh((0, 0, 0))
            rails._sweep(m, pts, nrm, prof, 0, closed=True, caps=True)
            self.assertEqual(outward_ok(m, np.array([10.0, 0.0, -0.5])), 1.0)

    def test_ballast_top_faces_up(self):
        pts = np.c_[np.linspace(0, 20, 11), np.zeros(11), np.zeros(11)]
        m = rails.Mesh((0, 0, 0))
        rails._ballast(m, pts, rails.normals(pts[:, :2]), np.zeros(11, bool))
        P, T = np.concatenate(m.P), np.concatenate(m.T)
        V = P[T]
        n = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
        self.assertTrue((n[:, 2] > 0).all())

    def test_ballast_collides_below_the_flange_discs(self):
        self.assertGreater(rails.BALLAST_COL_TOP_M, rails.CLEAR_UNDER_M)     # discs: 0.155-0.18 m under the rail top
        pts = np.c_[np.linspace(0, 20, 11), np.zeros(11), np.zeros(11)]
        m = rails.Mesh((0, 0, 0))
        br = np.zeros(11, bool)
        br[4:8] = True
        rails._ballast_collision(m, pts, rails.normals(pts[:, :2]), br)
        P = np.concatenate(m.P)
        gauge = np.abs(P[:, 1]) < rails.BALLAST_HALF_M + 0.05              # (the bridges' parapets stand outside)
        self.assertLessEqual(P[gauge, 2].max(), -rails.CLEAR_UNDER_M)      # nothing up into the discs' room
        self.assertGreater(P[:, 2].max(), 0.5, "a bridge's parapets")
        T = np.concatenate(m.T)
        V = P[T]
        n = np.cross(V[:, 1] - V[:, 0], V[:, 2] - V[:, 0])
        top = np.abs(V[:, :, 2].mean(1) + rails.BALLAST_COL_TOP_M) < 1e-6
        self.assertTrue((n[top][:, 2] > 0).all())                           # the crest faces up

    def test_sleepers_spacing(self):
        pts = np.c_[np.linspace(0, 60, 31), np.zeros(31), np.zeros(31)]
        m = rails.Mesh((0, 0, 0))
        rails._sleepers(m, pts, rails.normals(pts[:, :2]), 0.172)
        self.assertEqual(m.nv // 8, 100)
        self.assertEqual(outward_ok(m, np.array([30.0, 0.0, -0.5])) > 0.45, True)


class TestProfile(unittest.TestCase):
    def test_flat_ground_clearance(self):
        g = FlatGround()
        out = rails.track_profile(g, np.array([[0, 0], [300, 0]], float), [])
        self.assertEqual(len(out), 1)
        pts, br = out[0]
        self.assertFalse(br.any())
        self.assertTrue(np.allclose(pts[:, 2], rails.FORMATION_M, atol=1e-6))

    def test_short_bump_is_not_the_ground(self):
        """A bump shorter than 2 ROBUST_M (a tree, a house, a bridge's ramp in the elevation data): the track stays at
        the ground's level (the corridor cuts the bump away: nrails.corridor), no hump."""
        g = FlatGround(lambda x, y: np.where(np.abs(x - 150) < 3, 1.0, 0.0))
        pts, _ = rails.track_profile(g, np.array([[0, 0], [300, 0]], float), [])[0]
        self.assertLess(np.abs(pts[:, 2] - rails.FORMATION_M).max(), 0.05)

    def test_wide_bump_is_cleared_and_smoothed(self):
        g = FlatGround(lambda x, y: np.where(np.abs(x - 150) < 30, 1.0, 0.0))
        pts, _ = rails.track_profile(g, np.array([[0, 0], [300, 0]], float), [])[0]
        at = np.argmin(np.abs(pts[:, 0] - 150))
        self.assertGreaterEqual(pts[at, 2], 1.0 + rails.MIN_CLEAR_M - 1e-9)
        self.assertLess(np.abs(np.diff(pts[:, 2])).max(), 0.2)     # no step

    def test_bridge_is_straight(self):
        valley = FlatGround(lambda x, y: np.where((x > 100) & (x < 200), -30.0, 0.0))
        pts, kind = rails.track_profile(valley, np.array([[0, 0], [300, 0]], float), [(0.3, 0.7, "bridge")])[0]
        br = kind == 1
        self.assertTrue(br.any())
        self.assertGreater(pts[br][:, 2].min(), -1.0)              # not down in the valley

    def test_tunnel_runs_straight_from_portal_to_portal(self):
        """A hill with a tunnel through it: the track goes on through it, straight in profile between the portals,
        never up over the hill."""
        hill = FlatGround(lambda x, y: 0.004 * x + 60.0 * np.clip(1 - np.abs(x - 500) / 300.0, 0, 1))
        pts, kind = rails.track_profile(hill, np.array([[0, 0], [1000, 0]], float), [(0.3, 0.7, "tunnel")])[0]
        tun = kind == 2
        self.assertTrue(tun.any() and (kind[:10] == 0).all())
        x, z = pts[tun][:, 0], pts[tun][:, 2]
        line = np.polyfit(x, z, 1)
        self.assertLess(np.abs(np.polyval(line, x) - z).max(), 0.02, "straight")
        self.assertLess(z.max(), 24.0, "through the hill (62 m at its top), not over it: the portals at ~21-23 m")
        self.assertLess(np.abs(np.diff(pts[:, 2])).max(), 0.2, "no step at the portals")

    def test_a_cliff_at_a_portal_is_not_the_tunnels_level(self):
        """A tunnel coming out of a cliff onto the valley floor (the a main line by a village): the first sample in
        the open still reads the cliff 25 m up; the portal stays at the valley's level, no 5 % ramp down from it."""
        cliff = FlatGround(lambda x, y: np.where(np.asarray(x, float) < 503.0, 40.0, 0.0))
        pts, kind = rails.track_profile(cliff, np.array([[0, 0], [1000, 0]], float), [(0.0, 0.5, "tunnel")])[0]
        out = (kind == 0) & (pts[:, 0] > 505)
        self.assertTrue(out.any())
        self.assertLess(pts[out][:, 2].max(), 1.5, "the open track on the valley floor from the portal on")
        p = pts[pts[:, 0] > 480]
        ds = np.hypot(*np.diff(p[:, :2], axis=0).T)
        self.assertLess((np.abs(np.diff(p[:, 2])) / np.maximum(ds, 1e-9)).max(), 0.02, "no ramp at the portal")

    def test_a_tunnel_mapped_as_three_segments(self):
        """A long tunnel mapped as three segments (portal, all-tunnel, portal): one straight line from portal to
        portal, the same heights at the two inner nodes, whatever the window (a window over the middle only reads
        the whole chain: _tunnel_forced)."""
        hill = FlatGround(lambda x, y: 0.002 * x + 80.0 * np.clip(1 - np.abs(x - 1500) / 1000.0, 0, 1))
        segs = [("a", np.array([[0, 0], [800, 0]], float), [(0.5, 1.0, "tunnel")]),
                ("b", np.array([[800, 0], [2200, 0]], float), [(0.0, 1.0, "tunnel")]),
                ("c", np.array([[2200, 0], [3000, 0]], float), [(0.0, 0.5, "tunnel")])]
        whole = rails.profile_network(hill, segs)
        a, b, c = whole["a"][0][0], whole["b"][0][0], whole["c"][0][0]
        self.assertAlmostEqual(a[-1, 2], b[0, 2], places=3)
        self.assertAlmostEqual(b[-1, 2], c[0, 2], places=3)
        self.assertLess(b[:, 2].max(), 30.0, "deep under the hill (between the portals' heights)")
        slope = np.diff(b[:, 2]) / np.diff(b[:, 0])
        self.assertLess(slope.max() - slope.min(), 1e-6, "one grade along the chain")
        mid = rails.profile_network(hill, segs, near=(1400, -100, 1600, 100))
        bm = mid["b"][0][0]
        zb = np.interp(1500.0, b[:, 0], b[:, 2])
        self.assertAlmostEqual(np.interp(1500.0, bm[:, 0], bm[:, 2]), zb, places=3)

    def test_tubes_portals_and_twins(self):
        x = np.linspace(0, 200, 101)
        kind = np.where((x > 50) & (x < 150), 2, 0)
        a = (0, np.c_[x, np.zeros_like(x), np.full_like(x, 10.0)], kind)
        b = (1, np.c_[x, np.full_like(x, 4.5), np.full_like(x, 10.0)], kind)
        tubes = rails.tunnel_tubes([a, b], (-100, -100, 300, 100))
        self.assertEqual(len(tubes), 1, "two tracks 4.5 m apart: one tube round both")
        t = tubes[0]
        self.assertAlmostEqual(float(np.median(t["xy"][:, 1])), 2.25)
        self.assertAlmostEqual(t["w"], rails.TUNNEL_TRACK_W + 4.5)
        self.assertEqual(t["portal"], (True, True))
        self.assertAlmostEqual(float(t["z"][0]), 10.0 - rails.TUNNEL_FLOOR_M)
        cut = rails.tunnel_tubes([a], (-100, -100, 100.5, 100))      # the tile ends inside the tunnel
        clipped = [(0, a[1][x <= 102], kind[x <= 102])]
        cut = rails.tunnel_tubes(clipped, (-100, -100, 100.5, 100))
        self.assertEqual(cut[0]["portal"], (True, False), "no portal where the tile cuts the tube")
        import roadmesh
        mesh = roadmesh.tunnel(rails.tube_chunks(tubes), (0.0, 0.0, 0.0))
        self.assertIsNotNone(mesh)
        P = mesh[0]
        self.assertGreater(P[:, 2].max(), 10.0 + rails.TUNNEL_H - 1.0, "a vault over the tracks")

    def test_hole_mask_at_the_portals_only(self):
        n, sq = 128, 2.0
        cx = cy = 0.0
        half = n * sq / 2
        gx = -half + np.arange(n) * sq
        X, _Y = np.meshgrid(gx, gx)
        u = 10.0 + 40.0 * np.clip(1 - np.abs(X) / 60.0, 0, 1)       # a ridge along y, 50 m high at x = 0
        xs = np.linspace(-100, 100, 101)
        tube = {"xy": np.c_[xs, np.zeros_like(xs)], "z": np.full(len(xs), 10.0), "w": rails.TUNNEL_TRACK_W,
                "portal": (True, True), "up": (None, None)}
        mask = rails.tunnel_hole_mask([tube], u, cx, cy, sq)
        self.assertTrue(mask.any(), "the portals cut")
        ix = np.abs(gx).argmin()
        iy = np.abs(gx).argmin()
        self.assertFalse(mask[iy, ix], "the ground over the middle of the tube stays")

    def test_ground_read_near_the_tile_only(self):
        """A long segment is profiled around the tile only: its ground (and map cells) far away are never read."""
        seen = []

        class Spy(FlatGround):
            def z(self, x, y):
                seen.append(np.asarray(x).ravel().copy())
                return super().z(x, y)
        line = np.array([[-20000, 0], [20000, 0]], float)
        out = rails.track_profile(Spy(), line, [], near=(-300, -300, 300, 300))
        xs = np.concatenate(seen)
        self.assertLessEqual(np.abs(xs).max(), 300 + rails.PIN_R_M + 1)
        self.assertEqual(len(out), 1)
        pts, _ = out[0]
        self.assertTrue(np.allclose(pts[:, 2], rails.FORMATION_M, atol=1e-6))   # cut ends: no pin, same level
        # the same window from two tiles gives the same heights where they overlap
        a = rails.track_profile(FlatGround(lambda x, y: 0.002 * x), line, [], near=(-300, -300, 300, 300))[0][0]
        b = rails.track_profile(FlatGround(lambda x, y: 0.002 * x), line, [], near=(-100, -300, 500, 300))[0][0]
        common = np.intersect1d(np.round(a[:, 0], 3), np.round(b[:, 0], 3))
        mid = common[(common > -50) & (common < 150)]
        za = np.interp(mid, a[:, 0], a[:, 2])
        zb = np.interp(mid, b[:, 0], b[:, 2])
        self.assertLess(np.abs(za - zb).max(), 0.01)

    def test_long_bridge_kept_whole(self):
        valley = FlatGround(lambda x, y: np.where(np.abs(x) < 400, -40.0, 0.0))
        line = np.array([[-2000, 0], [2000, 0]], float)
        out = rails.track_profile(valley, line, [(0.4, 0.6, "bridge")], near=(-100, -100, 100, 100))
        pts, kind = out[0]
        br = kind == 1
        self.assertTrue(br.any())
        self.assertGreater(pts[br][:, 2].min(), -1.0)              # straight between the abutments, not in the valley

    def test_segments_meet_at_one_height(self):
        """Two mapped segments end to end on a slope: one height at their node, no step."""
        g = FlatGround(lambda x, y: 0.01 * x + np.where((x > 90) & (x < 110), 0.8, 0.0))
        out = rails.profile_network(g, [("a", np.array([[0, 0], [100, 0]], float), []),
                                        ("b", np.array([[100, 0], [200, 30]], float), [])])
        a, b = out["a"][0][0], out["b"][0][0]
        self.assertAlmostEqual(a[-1, 2], b[0, 2], places=6)

    def test_branch_meets_the_main_line(self):
        """A siding leaving a main line mid-segment starts at the main line's height (the main line not split there)."""
        g = FlatGround(lambda x, y: 0.02 * x + 3.0 * np.exp(-((y - 60) / 25.0) ** 2))   # a mound beside the main
        main = ("main", np.array([[0, 0], [400, 0]], float), [])
        branch = ("branch", np.array([[200, 0], [300, 40], [400, 60]], float), [])
        out = rails.profile_network(g, [main, branch])
        m, b = out["main"][0][0], out["branch"][0][0]
        zm = np.interp(200.0, m[:, 0], m[:, 2])
        self.assertLess(abs(b[0, 2] - zm), 0.01)

    def test_grade_capped(self):
        """A 6 m / 20 m mound 60 m long (wider than the median's 2 ROBUST_M: ground, not a tree): an embankment no
        steeper than MAX_GRADE, never a dip under the ground."""
        # (within GRADE_REACH_M: a mound up to MAX_GRADE x GRADE_REACH_M high at MAX_GRADE, a higher one steeper,
        # never a step)
        for h, lim in ((6.0, rails.MAX_GRADE * 1.15), (20.0, 0.12)):
            spike = FlatGround(lambda x, y, h=h: np.where(np.abs(x - 300) < 30, h, 0.0))
            pts = rails.track_profile(spike, np.array([[0, 0], [600, 0]], float), [])[0][0]
            grade = np.abs(np.diff(pts[:, 2]) / np.diff(pts[:, 0]))
            self.assertLess(grade.max(), lim)
            self.assertGreaterEqual(pts[np.argmin(np.abs(pts[:, 0] - 300)), 2], h + rails.MIN_CLEAR_M - 1e-6)


class TestTurnoutsAndCrossings(unittest.TestCase):
    def test_frog_mask_drops_rail_inside_other_gauge(self):
        main = np.c_[np.linspace(0, 100, 51), np.zeros(51)]
        branch = np.c_[np.linspace(0, 100, 51), np.linspace(0, 10, 51)]
        rail = branch + [0, -(rails.GAUGE_M / 2 + 0.036)]          # the branch's right rail
        keep = rails.frog_mask(rail, 1, [(main, 0), (branch, 1)])
        self.assertFalse(keep.all())
        self.assertTrue(keep[-1])

    def test_crossing_found_once_per_road(self):
        xy, s = rails.resample(np.array([[0, 0], [100, 0]], float))
        road = ("r1", np.array([[50, -20], [50, 0], [50, 20]], float), 3.5)
        x = rails.crossings_on(xy, s, [road])
        self.assertEqual(len(x), 1)
        self.assertAlmostEqual(x[0]["s"], 50.0)
        self.assertAlmostEqual(x[0]["half"], 3.5 + rails.X_END_M)
        along = ("r2", np.array([[10, 0.5], [90, 0.5]], float), 3.0)      # a road along the track: no crossing
        self.assertEqual(rails.crossings_on(xy, s, [along]), [])

    def test_track_eases_to_the_road_at_a_crossing(self):
        high = FlatGround(lambda x, y: 2.0 * np.clip(np.abs(x - 300) / 80.0, 0, 1))   # a road down in a hollow
        road = ("r1", np.array([[300, -30], [300, 30]], float), 3.0)
        found = []
        pts, _ = rails.track_profile(high, np.array([[0, 0], [600, 0]], float), [], None, [road], found)[0]
        self.assertEqual(len(found), 1)
        at = np.argmin(np.abs(pts[:, 0] - 300))
        # eased down to the road (+ X_RISE_M) as far as the ground beside it lets the track (never into its gauge)
        self.assertGreaterEqual(pts[at, 2], rails.X_RISE_M - 1e-6)
        self.assertLess(pts[at, 2], 1.0)            # (the grade cap keeps the descent to 3.5 %: a little higher)
        g = 2.0 * np.clip(np.abs(pts[:, 0] - 300) / 80.0, 0, 1)
        self.assertTrue((pts[:, 2] >= g + rails.X_RISE_M - 1e-6).all())
        self.assertAlmostEqual(found[0]["z"], pts[at, 2], places=6)
        flat = FlatGround()                                                       # on flat ground: exactly 0.25
        pts2 = rails.track_profile(flat, np.array([[0, 0], [600, 0]], float), [], None, [road], [])[0][0]
        self.assertAlmostEqual(pts2[np.argmin(np.abs(pts2[:, 0] - 300)), 2], rails.X_RISE_M, places=6)
        self.assertAlmostEqual(found[0]["z_road"], 0.0, places=6)
        far = np.argmin(np.abs(pts[:, 0] - 150))
        self.assertGreater(pts[far, 2], 2.0 + rails.MIN_CLEAR_M - 1e-6)        # back on its formation away from it
        self.assertLess(np.abs(np.diff(pts[:, 2])).max(), 0.2)                   # eased, no step

    def test_crossing_inner_slab_leaves_flangeways(self):
        x = {"at": [0.0, 0.0], "z": 0.5, "z_road": 0.25, "half": 5.0, "t": np.array([1.0, 0.0]),
             "n": np.array([0.0, 1.0])}
        vis, col, inner = rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0))
        rails._platform(x, [], vis, col, inner)
        P = np.concatenate(inner.P)
        self.assertAlmostEqual(np.abs(P[:, 1]).max(), rails.GAUGE_M / 2 - rails.X_FLANGEWAY_M)
        self.assertFalse(col.empty())

    def test_crossing_slabs_follow_a_curved_climbing_track(self):
        """A crossing on a 250 m curve climbing at 1 %: the slabs follow the track, never over its rail top (the
        straight strip at the centre's height stood 0.18 m over it at its ends, under a WLD FS30-2's snowplow) and
        never into the gauge on the curve's inside."""
        R = 250.0
        a = np.linspace(-0.08, 0.08, 81)
        xy = np.c_[R * np.sin(a), R - R * np.cos(a)]
        s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        z = 0.5 + 0.01 * (s - s[40])
        track = np.c_[xy, z]
        x = {"at": xy[40], "z": 0.5, "z_road": 0.25, "half": 18.0, "t": np.array([1.0, 0.0]),
             "n": np.array([0.0, 1.0])}
        vis, col, inner = rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0))
        tr = rails._track_near([(track, np.zeros(len(track), np.int8))], x["at"], x["half"])
        self.assertIsNotNone(tr)
        rails._platform(x, [], vis, col, inner, tr)
        for m in (col, inner):
            P = np.concatenate(m.P)
            d = np.hypot(P[:, 0] - xy[:, None, 0], P[:, 1] - xy[:, None, 1])
            j = np.argmin(d, axis=0)                            # each vertex's nearest track sample
            self.assertLess((P[:, 2] - z[j]).max(), 0.02, "no slab over the rail top")
        C = np.concatenate(col.P)
        r = np.hypot(C[:, 0], C[:, 1] - R)                      # distance from the curve's centre
        lateral = np.abs(R - r)
        self.assertGreater(lateral[C[:, 2] > z.min() - 0.05].min(), rails.GAUGE_M / 2, "outer slabs off the gauge")

    def test_no_cant_at_a_turnouts_zone(self):
        """A canted curve with a turnout zone's points on it (the clear points): no cant within CANT_X_CLEAR_M of
        them, full cant again 2 CANT_X_CLEAR_M away."""
        if not rails.CANT_ON:
            self.skipTest("cant off")
        R = 400.0
        a = np.linspace(0.0, 1.0, 201)
        xy = np.c_[R * np.sin(a), R - R * np.cos(a)]
        full = rails.cant_tilt(xy)
        zone = [xy[i] for i in range(95, 106, 2)]                # ~20 m of a route's centre line
        t = rails.cant_tilt(xy, zone)
        self.assertGreater(np.abs(full[100]), 0.01)
        self.assertAlmostEqual(float(t[100]), 0.0)
        self.assertAlmostEqual(float(t[170]), float(full[170]))

    def test_parallel_tracks_share_one_platform(self):
        """Four tracks 4.5 m apart: the slabs meet half way between them, ramps only on the two outer sides."""
        xs = [{"at": [0.0, 4.5 * i], "z": 0.5, "z_road": 0.25, "half": 5.0, "t": np.array([1.0, 0.0]),
               "n": np.array([0.0, 1.0]), "road": "r", "k": i} for i in range(4)]
        tops = []
        for x in xs:
            vis, col, inner = rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0))
            rails._platform(x, [o for o in xs if o is not x], vis, col, inner)
            P = np.concatenate(col.P)
            tops.append((P[:, 1].min(), P[:, 1].max(), P[:, 2].min()))
        self.assertAlmostEqual(tops[1][0], 4.5 - 2.25)          # inner tracks: slab to half way, no ramp
        self.assertAlmostEqual(tops[1][1], 4.5 + 2.25)
        self.assertGreater(tops[1][2], 0.5 - rails.X_SLAB_DEPTH_M - 1e-6)
        self.assertLess(tops[0][0], -2.0)                      # the outer side of the first track: its ramp
        self.assertGreater(tops[3][1], 13.5 + 2.0)


if __name__ == "__main__":
    unittest.main()
