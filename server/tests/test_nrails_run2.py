"""NRails, the user's second run (2026-10-24): tracks side by side at one level, grade-separated crossings, the
collision's coarser line, viaduct sides, stations, deck junctions."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from nrails import decks, rails, stations  # noqa: E402
from test_nrails_rails import FlatGround  # noqa: E402


class ParallelTest(unittest.TestCase):
    def test_double_track_on_a_side_hill_at_one_level(self):
        hill = FlatGround(lambda x, y: 0.4 * y + 0.001 * x)         # rises 40 cm per m to the north (y)
        segs = [("a", np.array([[0, 0], [600, 0]], float), []), ("b", np.array([[0, 4.5], [600, 4.5]], float), [])]
        keep = os.environ.pop("BNGE_RAIL_PARALLEL", None)
        try:
            out = rails.profile_network(hill, segs)
            os.environ["BNGE_RAIL_PARALLEL"] = "off"
            alone = rails.profile_network(hill, segs)
        finally:
            os.environ.pop("BNGE_RAIL_PARALLEL", None)
            if keep is not None:
                os.environ["BNGE_RAIL_PARALLEL"] = keep
        a, b = out["a"][0][0], out["b"][0][0]
        mid = slice(len(a) // 4, 3 * len(a) // 4)
        self.assertGreater(float(np.abs(alone["a"][0][0][mid, 2] - alone["b"][0][0][mid, 2]).max()), 1.0)
        self.assertLess(float(np.abs(a[mid, 2] - b[mid, 2]).max()), 0.02)
        self.assertTrue((a[:, 2] >= alone["a"][0][0][:, 2] - 1e-9).all())       # raised only
        g = np.abs(np.diff(a[:, 2])) / np.hypot(*np.diff(a[:, :2], axis=0).T)
        self.assertLess(float(g.max()), rails.MAX_GRADE + 0.005)

    def test_a_siding_ends_without_a_step_in_the_main_line(self):
        g = FlatGround(lambda x, y: np.where(y > 2.0, 1.0, 0.0))     # the siding's strip 1 m higher
        segs = [("main", np.array([[0, 0], [800, 0]], float), []),
                ("siding", np.array([[300, 4.5], [500, 4.5]], float), [])]
        main = rails.profile_network(g, segs)["main"][0][0]
        gr = np.abs(np.diff(main[:, 2])) / np.hypot(*np.diff(main[:, :2], axis=0).T)
        self.assertLess(float(gr.max()), 2 * rails.PAR_GRADE + 0.001)     # (eased in and out: no step)
        self.assertGreater(float(main[:, 2].max()), 0.9)                  # beside the siding: at its level


class SeparationTest(unittest.TestCase):
    def setUp(self):
        # the track along x; a road across it at x = 300 over a 6 m embankment (unflagged): the ground's bump
        self.g = FlatGround(lambda x, y: np.where(np.abs(x - 300) < 15, 6.0, 0.0))
        self.track = ("t", np.array([[0, 0], [600, 0]], float), [])
        self.road = ("r", np.array([[300, -50], [300, 50]], float), 4.0)

    def structs(self, conns=frozenset()):
        return {"r": {"cls": "secondary", "layer": 0.0, "conns": set(conns),
                      "parts": [("ground", self.road[1], 4.0)]}}

    def test_an_overpass_without_a_shared_node_does_not_lift_the_track(self):
        found = []
        out = rails.profile_network(self.g, [self.track], None, [self.road], found, None, self.structs(),
                                    {"t": {"c1", "c2"}})
        pts = out["t"][0][0]
        z_at = float(np.interp(300, pts[:, 0], pts[:, 2]))
        self.assertEqual(found, [])                     # no level crossing
        self.assertLess(z_at, 1.0)                      # the track straight through, at its level

    def test_a_shared_node_is_a_level_crossing(self):
        found = []
        rails.profile_network(self.g, [self.track], None, [self.road], found, None, self.structs({"c1"}),
                              {"t": {"c1", "c2"}})
        self.assertEqual(len(found), 1)

    def test_without_structs_every_crossing_is_level(self):
        found = []
        rails.profile_network(self.g, [self.track], None, [self.road], found)
        self.assertEqual(len(found), 1)


class CollisionLineTest(unittest.TestCase):
    def test_a_straight_track_keeps_few_samples(self):
        pts = np.c_[np.arange(0, 200, 2.0), np.zeros(100), np.full(100, 5.0)]
        k = rails.simplify_keep(pts)
        self.assertEqual(k[0], 0)
        self.assertEqual(k[-1], 99)
        self.assertLessEqual(len(k), 12)                # every COL_MAX_SEG_M at most
        seg = np.diff(pts[k, 0])
        self.assertLessEqual(float(seg.max()), rails.COL_MAX_SEG_M)

    def test_a_curve_keeps_its_shape(self):
        a = np.linspace(0, np.pi / 2, 80)
        pts = np.c_[300 * np.cos(a), 300 * np.sin(a), np.zeros(80)]
        k = rails.simplify_keep(pts)
        for i, j in zip(k[:-1], k[1:]):                 # every sample within COL_TOL_M of its chord
            p, q = pts[i, :2], pts[j, :2]
            mid = pts[i:j + 1, :2]
            t = np.clip(((mid - p) @ (q - p)) / max(float((q - p) @ (q - p)), 1e-12), 0, 1)
            d = np.hypot(*(mid - (p + t[:, None] * (q - p))).T)
            self.assertLessEqual(float(d.max()), rails.COL_TOL_M + 1e-9)


class ViaductSidesTest(unittest.TestCase):
    def test_no_parapet_toward_the_next_track(self):
        pts = np.c_[np.linspace(0, 60, 31), np.zeros(31), np.full(31, 10.0)]
        nrm = rails.normals(pts[:, :2])
        other = np.c_[np.linspace(0, 60, 31), np.full(31, 4.5)]          # the next track 4.5 m to the left
        room = rails.side_room(pts, nrm, [other])
        self.assertTrue(np.allclose(room[0], 4.5))
        self.assertTrue(np.isinf(room[1]).all())
        m = rails.Mesh((0, 0, 0))
        rails._ballast_collision(m, pts, nrm, np.ones(31, bool), None, room)
        P = np.concatenate(m.P)
        top = 10.0 - rails.BALLAST_TOP_M + rails.BRIDGE_PARAPET[1]
        high = P[np.isclose(P[:, 2], top)]
        self.assertTrue(len(high))                      # a parapet ...
        self.assertTrue((high[:, 1] < 0).all())         # ... on the right only
        self.assertGreater(float(P[:, 1].max()), 2.2)   # the slab on to half way (2.25 m)


class StationsTest(unittest.TestCase):
    def test_points_in_ring(self):
        ring = np.array([[0, 0], [10, 0], [10, 10], [0, 10]], float)
        inside = stations.points_in_ring(np.array([[5, 5], [15, 5], [-1, -1]], float), ring)
        self.assertEqual(inside.tolist(), [True, False, False])

    def test_a_platform_beside_the_track(self):
        pts = np.c_[np.linspace(0, 100, 51), np.zeros(51), np.full(51, 2.0)]
        ring = np.array([[10, 1.8], [90, 1.8], [90, 8.0], [10, 8.0]], float)     # left of the track, 6 m wide
        vis, col = rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0))
        self.assertEqual(stations.add_platforms(vis, col, [(0, pts, np.zeros(51, np.int8))], [ring]), 1)
        P = np.concatenate(vis.P)
        self.assertAlmostEqual(float(P[:, 2].max()), 2.0 + stations.PLATFORM_H_M)
        self.assertAlmostEqual(float(P[:, 1].min()), stations.PLATFORM_EDGE_M, places=3)
        self.assertGreater(float(P[:, 1].max()), 7.0)

    def test_a_platform_outline_over_two_tracks_stops_before_the_next(self):
        # one outline mapped round two tracks 10 m apart: the slab between them stops 1.65 m short of each
        pts = np.c_[np.linspace(0, 100, 51), np.zeros(51), np.full(51, 2.0)]
        other = pts + [0, 10.0, 0]
        ring = np.array([[10, -6], [90, -6], [90, 16], [10, 16]], float)
        vis, col = rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0))
        stations.add_platforms(vis, col, [(0, pts, np.zeros(51, np.int8)), (1, other, np.zeros(51, np.int8))],
                               [ring])
        P = np.concatenate(vis.P)
        between = P[(P[:, 1] > 0) & (P[:, 1] < 10)]
        self.assertGreater(len(between), 0)
        self.assertLessEqual(float(between[:, 1].max()), 10 - stations.PLATFORM_EDGE_M + 1e-6)
        self.assertGreaterEqual(float(between[:, 1].min()), stations.PLATFORM_EDGE_M - 1e-6)

    def test_a_footbridge_across_the_tracks_is_lifted_a_kiosk_on_them_dropped(self):
        track = np.c_[np.linspace(0, 100, 101), np.zeros(101)]
        across = np.array([[48, -15], [52, -15], [52, 15], [48, 15]], float)     # a passerelle over the line
        on = np.array([[95, -1], [100.5, -1], [100.5, 1], [95, 1]], float)        # the line ends in it
        beside = np.array([[40, 5], [60, 5], [60, 12], [40, 12]], float)
        self.assertEqual(stations.track_relation(across, [track]), "across")
        self.assertEqual(stations.track_relation(on, [track]), "on")
        self.assertIsNone(stations.track_relation(beside, [track]))


class MouthCutTest(unittest.TestCase):
    """A tube running into a 1:1 hillside from x = 0: the mouth is cut until the ground stands 2 m over the vault."""

    def setUp(self):
        n, sq = 64, 2.0
        self.cx = self.cy = 0.0
        x = -n * sq / 2 + np.arange(n) * sq
        X, _Y = np.meshgrid(x, x)
        self.u = np.maximum(0.0, X)                     # flat in front of the portal, then 1:1 up
        xs = np.arange(0.0, 60.0, 2.0)
        self.tube = {"xy": np.c_[xs, np.zeros(len(xs))], "z": np.full(len(xs), -0.5), "w": 4.0,
                     "portal": (True, False), "up": (None, None)}

    def test_reach(self):
        r = rails.mouth_reach(self.tube, 0, self.u, -64.0, -64.0, 2.0)
        self.assertAlmostEqual(r, 8.5 + 2.0, delta=1.01)   # vault -0.5 + 7, + 2 m soil: x = 8.5, a grid step more

    def test_the_square_over_the_vault_is_cut(self):
        ix = int((8.0 + 64.0) / 2.0)                    # x = 8 m: ground 8 m, the vault at 6.5 m
        iy = 32
        os.environ["BNGE_RAIL_MOUTH_CUT"] = "off"
        try:
            off = rails.tunnel_hole_mask([self.tube], self.u, self.cx, self.cy, 2.0)
        finally:
            os.environ.pop("BNGE_RAIL_MOUTH_CUT")
        on = rails.tunnel_hole_mask([self.tube], self.u, self.cx, self.cy, 2.0)
        self.assertFalse(off[iy, ix])
        self.assertTrue(on[iy, ix])
        self.assertFalse(on[iy, int((30.0 + 64.0) / 2.0)])      # deep in the hill the ground stays


class UnderSeaTest(unittest.TestCase):
    def test_a_tunnel_dives_under_the_sea_floor(self):
        # the track at 20 m either side, the hills its portals open into at 35 m, a sea floor 40 m down between the
        # shores, the tunnel from 1000 to 21000: 7 km from its portals to the shores, it dives at the tunnel grade;
        # shores 3 km from them (too close for 1.25 %): at the line's steepest
        for shore, grade in ((8000.0, rails.TUNNEL_DIVE_GRADE), (4000.0, rails.MAX_GRADE)):
            floor = FlatGround(lambda x, y, a=shore: np.where((x > a) & (x < 22000 - a), -40.0,
                                                               np.where((x > 1000) & (x < 21000), 35.0, 20.0)) + 0 * y)
            segs = [("t", np.array([[0, 0], [22000, 0]], float), [(1000 / 22000, 21000 / 22000, "tunnel")])]
            pts, kind = rails.profile_network(floor, segs)["t"][0]
            tun = kind == 2
            x, z = pts[tun][:, 0], pts[tun][:, 2]
            mid = (x > shore + 300) & (x < 22000 - shore - 300)
            vault = z[mid] + rails.TUNNEL_H - rails.TUNNEL_FLOOR_M
            self.assertLess(vault.max(), -40.0 + 0.5, "the tube under the sea floor, not in the water")
            g = np.abs(np.diff(z) / np.diff(x))
            self.assertLess(g.max(), grade + 0.003)
            self.assertGreater(z[:3].min(), 15.0, "the portals stay at the land's level")


class TunnelNetworkTest(unittest.TestCase):
    def test_a_branch_inside_a_tunnel_meets_the_bore_at_one_level_in_every_window(self):
        # a bore from x = 0 (portal at 10 m) to x = 4000 (portal at 50 m) under a hill, mapped as two segments meeting
        # at x = 1000; a branch from that node to its own portal at (1000, 800) (ground 30 m there)
        hill = FlatGround(lambda x, y: np.where((x > 0) & (x < 4000) & (y < 780), 120.0,
                                                10.0 + 40.0 * np.clip(x / 4000.0, 0, 1) + 20.0 * (y > 780)))
        segs = [("m1", np.array([[-300, 0], [1000, 0]], float), [(300 / 1300, 1.0, "tunnel")]),
                ("m2", np.array([[1000, 0], [4300, 0]], float), [(0.0, 3000 / 3300, "tunnel")]),
                ("br", np.array([[1000, 0], [1000, 1100]], float), [(0.0, 800 / 1100, "tunnel")])]
        whole = rails.profile_network(hill, segs)
        ends = [whole["m1"][0][0][-1, 2], whole["m2"][0][0][0, 2], whole["br"][0][0][0, 2]]
        self.assertLess(max(ends) - min(ends), 0.01, f"one level at the node: {ends}")
        near = (1500, -100, 1700, 100)               # a window away from the node
        part = rails.profile_network(hill, segs, near=near)
        zw = np.interp(1600.0, whole["m2"][0][0][:, 0], whole["m2"][0][0][:, 2])
        zp = np.interp(1600.0, part["m2"][0][0][:, 0], part["m2"][0][0][:, 2])
        self.assertAlmostEqual(zw, zp, places=2)


class CanonCacheTest(unittest.TestCase):
    def test_a_cell_profile_round_trips_through_its_file(self):
        import tempfile
        from nrails import canon
        pts = np.c_[np.arange(5.0), np.zeros(5), np.full(5, 3.0)]
        cp = canon.CellProfile({"a": [(pts, np.zeros(5, np.int8), np.arange(5.0) * 2)]},
                               [{"at": np.array([1.0, 0.0]), "s": np.float64(2.0), "z": 3.5, "half": 4.0, "fid": "a",
                                 "t": np.array([1.0, 0.0]), "n": np.array([0.0, 1.0]), "z_road": 3.2, "road": "r"}])
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x", "c.npz")
            canon._store(p, cp)
            back = canon._load(p)
        self.assertIsNotNone(back)
        self.assertTrue(np.allclose(back.parts["a"][0][0], pts))
        x = back.found[0]
        for k in ("at", "t", "n"):          # (arrays again: as lists they broke the crossing's slab, whole tiles' tracks)
            self.assertIsInstance(x[k], np.ndarray)
        rails._platform(x, [], rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0)))

    def test_a_crossing_from_the_disk_cache_as_lists_is_still_built(self):
        x = {"at": [1.0, 0.0], "t": [1.0, 0.0], "n": [0.0, 1.0], "z": 3.5, "z_road": 3.2, "half": 4.0}
        m = rails.Mesh((0, 0, 0))
        rails._platform(x, [], m, rails.Mesh((0, 0, 0)), rails.Mesh((0, 0, 0)))
        self.assertFalse(m.empty())

    def test_profile_box_joins_the_cells_samples_along_the_arc(self):
        from nrails import canon
        import mapcells
        a = canon.CellProfile({"t": [(np.c_[np.arange(0, 10.0, 2), np.zeros(5), np.ones(5)], np.zeros(5),
                                      np.arange(0, 10.0, 2))]}, [])
        b = canon.CellProfile({"t": [(np.c_[np.arange(10, 20.0, 2), np.zeros(5), np.ones(5)], np.zeros(5),
                                      np.arange(10, 20.0, 2))]}, [])
        keys = ["k1", "k2"]
        orig_cells, orig_cp = mapcells.cells_for_bbox, canon.cell_profile
        mapcells.cells_for_bbox = lambda *a, **k: keys
        canon.cell_profile = lambda frame, k, cf, el: a if k == "k1" else b
        try:
            import geodesy
            prof, found, arcs = canon.profile_box(geodesy.EnuFrame(47.0, 7.0), (0, -5, 20, 5), None, None)
        finally:
            mapcells.cells_for_bbox, canon.cell_profile = orig_cells, orig_cp
        self.assertEqual(len(prof["t"]), 1)                 # one run across the two cells
        self.assertEqual(len(prof["t"][0][0]), 10)


class DeckJunctionTest(unittest.TestCase):
    def test_a_road_that_does_not_meet_the_deck_keeps_its_clearance(self):
        import roads
        flat = lambda xy: np.full(len(xy), 100.0)          # noqa: E731
        deck = [np.c_[np.linspace(0, 60, 31), np.zeros(31)]]
        ground = {("under", "g"): [np.array([[5.0, -20], [5.0, 20]])]}
        decks.CONNS.update({"deck": frozenset({"a", "b"}), "under": frozenset({"c"})})
        out = decks.deck_crossings([(0, 5.0, 100.0)], deck, [("deck", 0)], ground, flat)
        self.assertEqual(len(out[0]), 4)                # a clearance: never a junction at grade
        decks.CONNS["under"] = frozenset({"a"})         # the map joins them: a junction
        out = decks.deck_crossings([(0, 5.0, 100.0)], deck, [("deck", 0)], ground, flat)
        self.assertEqual(len(out[0]), 3)
        self.assertEqual(roads.AT_GRADE_REACH_M > 5.0, True)


if __name__ == "__main__":
    unittest.main()
