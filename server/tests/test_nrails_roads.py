"""EarthNRails: what the fork changes in BeamNG.Earth's roads (nrails.bridges, nrails.profile, nrails.hooks)."""
import json
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import grading  # noqa: E402
import roadmesh  # noqa: E402
import roads  # noqa: E402
from nrails import bridges, decks, hooks, profile, rails  # noqa: E402
from test_roads import features, LON  # noqa: E402


class ApproachSlabTest(unittest.TestCase):
    # the terrain grid's post nearest an abutment stood down the embankment, a 0.75 m slot before a motorway deck at
    # a test town; each abutment end goes on as a slab, flat then sinking

    def lines(self):
        x = np.arange(0.0, 161.0, 4.0)
        a = np.c_[x, np.zeros_like(x), 22.0 + 0.01 * x]
        b = np.c_[np.arange(160.0, 241.0, 4.0), np.zeros(21), np.full(21, 23.6)]   # the chain's next part: a joint
        return [(a, 12.0), (b, 12.0)]

    def test_one_slab_per_abutment(self):
        slabs = bridges.abutment_slabs(self.lines())
        self.assertEqual(len(slabs), 2, "x 0 and x 240; none at the joint (x 160)")
        lo, hi = sorted((s for _i, s in slabs), key=lambda s: s[:, 0].mean())
        self.assertAlmostEqual(lo[0, 0], 0.0)
        self.assertAlmostEqual(lo[0, 2], 22.0, msg="it starts at the deck end's height")
        self.assertAlmostEqual(lo[1, 0], -bridges.FLAT_M)
        self.assertAlmostEqual(lo[1, 2], 22.0, msg="flat over the grid's first squares")
        self.assertAlmostEqual(lo[2, 0], -(bridges.FLAT_M + bridges.RAMP_M))
        self.assertAlmostEqual(lo[2, 2], 22.0 - bridges.SINK_M, msg="then sinks under it")
        self.assertAlmostEqual(hi[0, 0], 240.0)

    def test_ends_cut_by_the_context_box_are_no_abutments(self):
        slabs = bridges.abutment_slabs(self.lines(), box=(-50.0, -50.0, 240.2, 50.0))
        self.assertEqual(len(slabs), 1, "x 240 lies on the box's edge: the part goes on beyond it")

    def test_slab_mesh_joins_the_deck_mesh(self):
        ctx = []
        for pts, w in self.lines():
            ch = roads._chunk(roads.DECK, w, pts)
            ch.update(fixed=True, deck=True, ctx=True)
            ctx.append(ch)
        sc = bridges.slab_chunks(ctx, (-50.0, -50.0, 300.0, 50.0), (-80.0, -80.0, 330.0, 80.0))
        self.assertTrue(sc and all(c["deck"] and c["fixed"] and c["tunnel"] for c in sc))
        slab = roadmesh.deck(sc, (0.0, 0.0, 0.0))
        self.assertIsNotNone(slab, "its concrete made (the slab alone: no parapet, no girders)")
        deck = roadmesh.deck(ctx, (0.0, 0.0, 0.0))
        merged = bridges.merge_meshes(deck, slab)
        self.assertEqual(len(merged[0]), len(deck[0]) + len(slab[0]))
        self.assertEqual(len(merged[1]), len(deck[1]) + len(slab[1]))
        self.assertTrue(int(np.max(merged[1])) < len(merged[0]))


class GradeLimitTest(unittest.TestCase):
    """A road's class bounds its profile's grade (nrails.profile)."""

    def test_a_hump_is_cut_and_filled_to_the_grade(self):
        s = np.arange(0, 600, 2.0)
        z = 100.0 + 2.0 * np.exp(-((s - 300.0) / 12.0) ** 2)      # a 2 m hump over ~40 m: up to 13 %
        g = profile.grade_limit(z, 2.0, 0.06)
        self.assertLess(np.abs(np.diff(g) / 2.0).max(), 0.06 + 1e-9, "within 6 %")
        self.assertLess(g.max(), z.max(), "the peak cut")
        self.assertGreater(g[140], z[140] + 0.05, "its foot filled")
        self.assertTrue(np.allclose(g[:20], z[:20]) and np.allclose(g[-20:], z[-20:]), "the ends kept")

    def test_a_steady_climb_and_a_gentle_profile_stay(self):
        s = np.arange(0, 600, 2.0)
        climb = 0.09 * s                    # steeper than the grade, steady: as the data has it
        got = profile.grade_limit(climb, 2.0, 0.06)
        self.assertLess(np.abs(got - climb)[30:-30].max(), 1e-6, "(past GRADE_REACH_M from the ends)")
        self.assertLess(np.abs(got - climb).max(), 0.5, "and little near them")
        gentle = 0.03 * s + 0.5 * np.sin(s / 80.0)
        self.assertIs(profile.grade_limit(gentle, 2.0, 0.06), gentle, "within the grade: untouched")

    def test_local_the_same_in_every_piece(self):
        s = np.arange(0, 2000, 2.0)
        z = 50.0 + 0.02 * s + 3.0 * np.exp(-((s - 1000.0) / 10.0) ** 2)
        whole = profile.grade_limit(z, 2.0, 0.06)
        piece = profile.grade_limit(z[300:700], 2.0, 0.06)
        self.assertLess(np.abs(whole[400:600] - piece[100:300]).max(), 1e-9)

    def test_the_motorway_plan_takes_it_through_the_hook(self):
        x = np.arange(0.0, 600.0, 2.0)
        xy = np.c_[x, np.zeros_like(x)]
        z = 100.0 + 2.5 * np.exp(-((x - 300.0) / 10.0) ** 2)
        mw = roads.road_specs(features([[(0, 0), (600, 0)]], ["motorway"]))[0]
        res = roads.road_specs(features([[(0, 0), (600, 0)]], ["residential"]))[0]
        gm = np.abs(np.diff(grading._plan(xy, z, mw).z) / grading.VERTEX_STEP).max()
        gr = np.abs(np.diff(grading._plan(xy, z, res).z) / grading.VERTEX_STEP).max()
        self.assertLess(gm, 0.065, "the motorway within its grade")
        self.assertGreater(gr, gm, "a street keeps more of the ground's shape")


class HooksTest(unittest.TestCase):
    def test_shape_files_name_the_track(self):
        names = roads.shape_files(1, 2, 3)
        for what in ("rail", "rail2", "railcol", "railcol4", "railx", "railtun"):
            self.assertIn(what, names)
        self.assertEqual(names["road"], "road_1_2_3.cdae", "upstream's kept")

    def test_boot_gives_a_cache_dir_only_when_none_is_named(self):
        self.assertEqual(hooks.boot(["--cache-dir", "X"]), ["--cache-dir", "X"])
        got = hooks.boot(["--port", "0"])
        self.assertEqual(got[:2], ["--port", "0"])
        self.assertEqual(got[2], "--cache-dir")
        self.assertTrue(os.path.isabs(got[3]))

    def test_write_tile_without_extras_is_upstream_s(self):
        with tempfile.TemporaryDirectory() as d:
            path, n = roads.write_tile(d, "/vfs", 1, 0, 0, [], nrails=None)
            with open(os.path.join(d, os.path.basename(path))) as f:
                data = json.load(f)
            self.assertFalse(any(k.startswith("rail") for k in data))

    def test_a_failing_hook_costs_only_its_part(self):
        class Bad:
            rail = object()         # no shapes(): the track's write fails, the tile is still written
        with tempfile.TemporaryDirectory() as d:
            path, _ = roads.write_tile(d, "/vfs", 1, 0, 0, [], nrails=Bad())
            self.assertTrue(os.path.exists(os.path.join(d, os.path.basename(path))))


class DeckOverRailTest(unittest.TestCase):
    """A road bridge 400 m long (room to climb at roads.DECK_MAX_GRADE) over flat ground at 100 m, a track on the ground across it."""
    flat = staticmethod(lambda xy: np.full(len(xy), 100.0))
    deck = [np.c_[np.linspace(-200, 200, 201), np.zeros(201)]]

    def ground(self, x):
        return {("r1", "g"): [np.array([[x + 3, -50.0], [x + 3, 50.0]])],
                ("t1", decks.RAIL_KEY): [np.array([[x, -50.0], [x, 50.0]])]}

    def test_the_crossing_has_the_railway_s_clearance(self):
        got = decks.deck_rail_crossings(self.deck, self.ground(0.0), self.flat)
        self.assertEqual(len(got), 3)           # its centre, and CLEAR_HALF_M either side along the deck
        self.assertEqual(sorted(round(g[1], 3) for g in got), [200 - decks.CLEAR_HALF_M, 200, 200 + decks.CLEAR_HALF_M])
        pi, arc, z, cl = got[0]
        self.assertEqual(pi, 0)
        self.assertAlmostEqual(arc, 200.0, places=3)
        self.assertAlmostEqual(z, 100.0 + rails.FORMATION_M)
        self.assertGreater(cl, decks.RAIL_FREE_M + roadmesh.DECK_DEPTH + roadmesh.GIRDER_D)     # + the smoothing's
        self.assertLess(cl, decks.RAIL_FREE_M + roadmesh.DECK_DEPTH + roadmesh.GIRDER_D + 1.0)
        self.assertTrue(hooks.is_rail_key(("t1", decks.RAIL_KEY)))
        self.assertFalse(hooks.is_rail_key(("r1", "g")))

    def test_the_deck_clears_the_rails_by_6_m(self):
        cr = decks.deck_rail_crossings(self.deck, self.ground(0.0), self.flat)
        z = roads.deck_profile(self.deck, self.flat, cr)[0]
        under = float(np.interp(0.0, self.deck[0][:, 0], z)) - roadmesh.DECK_DEPTH - roadmesh.GIRDER_D
        self.assertGreaterEqual(under - (100.0 + rails.FORMATION_M), decks.RAIL_FREE_M - 0.05)

    def test_a_road_under_a_railway_embankment_is_left_alone(self):
        bank = lambda xy: np.where(np.abs(np.asarray(xy)[:, 0]) < 12.0, 106.0, 100.0)    # the track 6 m up
        self.assertEqual(decks.deck_rail_crossings(self.deck, self.ground(0.0), bank), [])

    def test_a_track_by_an_abutment_is_no_junction_at_grade(self):
        # 8 m from the abutment: a road there would be met at grade; a railway never (the deck climbs as it can)
        ground = self.ground(-192.0)
        road = [(0, 8.0, 100.0)]
        z_road = roads.deck_profile(self.deck, self.flat, road)[0]
        z_rail = roads.deck_profile(self.deck, self.flat, decks.deck_rail_crossings(self.deck, ground, self.flat))[0]
        self.assertGreater(float(np.interp(-192.0, self.deck[0][:, 0], z_rail)),
                           float(np.interp(-192.0, self.deck[0][:, 0], z_road)) + 0.2)


if __name__ == "__main__":
    unittest.main()
