"""geocode: the map's address search (Photon) request and response handling."""
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import geocode  # noqa: E402


class GeocodeTest(unittest.TestCase):
    def test_url_biased_to_the_player(self):
        q = parse_qs(urlparse(geocode.url(" fells point ", 39.28321, -76.59311)).query)
        self.assertEqual((q["q"], q["lat"], q["lon"]), (["fells point"], ["39.2832"], ["-76.5931"]))
        self.assertNotIn("lat", parse_qs(urlparse(geocode.url("x y z")).query))

    def test_parse_labels(self):
        data = {"features": [
            {"geometry": {"coordinates": [-76.5932, 39.2835]},
             "properties": {"name": "Fell's Point", "city": "Baltimore", "state": "Maryland", "country": "United States",
                            "osm_value": "neighbourhood"}},
            {"geometry": {"coordinates": [-77.0366, 38.8977]},
             "properties": {"housenumber": "1600", "street": "Pennsylvania Avenue Northwest", "city": "Washington"}},
            {"geometry": {"coordinates": [999, 0]}, "properties": {"name": "bad"}},
            {"properties": {"name": "no geometry"}}]}
        r = geocode.parse(data)
        self.assertEqual(len(r), 2)
        self.assertEqual((r[0]["name"], r[0]["detail"], r[0]["kind"]),
                         ("Fell's Point", "Baltimore, Maryland, United States", "neighbourhood"))
        self.assertEqual(r[1]["name"], "1600 Pennsylvania Avenue Northwest")
        self.assertEqual(r[1]["detail"], "Washington")

    def test_short_query_is_not_sent(self):
        class Boom:
            def get(self, *a, **k):
                raise AssertionError("no request for a short query")
        self.assertEqual(geocode.search("ab", net=Boom()), [])


if __name__ == "__main__":
    unittest.main()
