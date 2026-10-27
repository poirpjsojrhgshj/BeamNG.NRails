"""NRails: server/nrails/osmrail.py and osmmsg.py (OpenStreetMap's railways: the graph, reach, routes, the cache)."""
import gzip
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from nrails import osmmsg, osmrail  # noqa: E402

D = 0.001       # deg: ~111 m north, ~75 m east at 47 N


def doc():
    """A main line west-east (nodes 1..5), a branch leaving it at node 3 to the north-east (6, 7), a line elsewhere
    (20, 21: not connected), a crossing on node 2."""
    def way(wid, nodes, pts, **tags):
        return {"type": "way", "id": wid, "nodes": nodes, "geometry": [{"lat": a, "lon": b} for a, b in pts],
                "tags": dict(railway="rail", **tags)}
    lat = 47.0
    main = way(100, [1, 2, 3, 4, 5], [(lat, 7.0 + i * D) for i in range(5)], usage="main")
    branch = way(101, [3, 6, 7], [(lat, 7.0 + 2 * D), (lat + D, 7.0 + 3 * D), (lat + 2 * D, 7.0 + 4 * D)],
                 service="siding")
    other = way(102, [20, 21], [(lat + 0.01, 7.0), (lat + 0.01, 7.0 + D)])
    xing = {"type": "node", "id": 2, "lat": lat, "lon": 7.0 + D,
            "tags": {"railway": "level_crossing", "crossing:barrier": "half", "crossing:light": "yes"}}
    return {"elements": [main, branch, other, xing, {"type": "node", "id": 9, "lat": 0, "lon": 0}]}


class TestGraph(unittest.TestCase):
    def setUp(self):
        self.g = osmrail.Graph()
        self.g.add(osmrail.parse(doc()))

    def test_parse(self):
        d = osmrail.parse(doc())
        self.assertEqual(len(d["ways"]), 3)
        self.assertEqual(d["xings"], [[2, 47.0, 7.001, "half", "yes", None]])

    def test_a_way_in_two_squares_kept_once(self):
        self.g.add(osmrail.parse(doc()))
        self.assertEqual(len(self.g.ways), 3)

    def test_reachable_from_the_track_only(self):
        n = self.g.reachable(self.g.nearest(47.0, 7.0), 47.0, 7.0, 10000)
        self.assertEqual(n, {1, 2, 3, 4, 5, 6, 7})
        near = self.g.reachable(1, 47.0, 7.0, 180)          # (the round cuts the line)
        self.assertEqual(near, {1, 2, 3})

    def test_snapshot(self):
        s = osmmsg.snapshot(self.g, 47.0, 7.0, 47.0, 7.0, 10)
        self.assertTrue(s["reach"])
        self.assertEqual({l["id"] for l in s["lines"]}, {100, 101})
        self.assertEqual(s["xings"], [[47.0, 7.001, "half", "yes"]])
        self.assertEqual({l["k"] for l in s["lines"]}, {"main", "service"})
        far = osmmsg.snapshot(self.g, 47.0, 7.0, 46.0, 7.0, 10)  # (not on a track: everything in the round)
        self.assertFalse(far["reach"])
        self.assertEqual(len(far["lines"]), 3)

    def test_route_and_no_reversing(self):
        path, d = self.g.route(1, 7)
        self.assertEqual(path, [1, 2, 3, 6, 7])
        self.assertGreater(d, 200)
        path, _ = self.g.route(5, 7)                        # from the east: the branch faces away (a reversal)
        self.assertIsNone(path)
        self.assertEqual(self.g.route(1, 20)[0], None)

    def test_simplify(self):
        pts = [(47.0, 7.0 + i * 1e-5) for i in range(50)]
        self.assertEqual(len(osmrail.simplify(pts, 1.0)), 2)

    def test_squares_nearest_first(self):
        sq = osmrail.squares(47.6, 6.9, 100)
        self.assertEqual(sq[0], (47.0, 6.0))
        self.assertTrue(4 <= len(sq) <= 12)


class TestCache(unittest.TestCase):
    def test_asked_once_then_from_disk_and_daily_cap(self):
        calls = []

        def fetch(q):
            calls.append(q)
            return doc()
        with tempfile.TemporaryDirectory() as d:
            o = osmrail.OsmRail(d, fetch=fetch)
            self.assertEqual(o.area(47.0, 7.0, 10), 0)
            n = len(calls)
            self.assertGreater(n, 0)
            o2 = osmrail.OsmRail(d, fetch=fetch)
            o2.area(47.0, 7.0, 10)
            self.assertEqual(len(calls), n)                 # (the disk)
            self.assertEqual(len(o2.graph.ways), 3)
            with open(os.path.join(d, "nrails", "osm", "requests.json"), "w") as f:
                json.dump({"day": "2000-01-01", "n": 999}, f)
            for f in os.listdir(os.path.join(d, "nrails", "osm")):
                if f.endswith(".gz"):
                    os.utime(os.path.join(d, "nrails", "osm", f), (0, 0))   # (stale)
            o3 = osmrail.OsmRail(d, fetch=fetch)
            self.assertEqual(o3.area(47.0, 7.0, 10), 0)
            self.assertEqual(len(o3.graph.ways), 3)         # (a new day: asked again, the stale copy meanwhile)

    def test_rate_limited_pauses_and_keeps_the_stale_copy(self):
        def fetch(q):
            raise osmrail.RateLimited("429")
        with tempfile.TemporaryDirectory() as d:
            o = osmrail.OsmRail(d, fetch=fetch)
            self.assertGreater(o.area(47.0, 7.0, 10), 0)
            self.assertGreater(o.paused_until, 0)


if __name__ == "__main__":
    unittest.main()
