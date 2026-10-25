"""EarthNRails Hub helpers (no window): the rails settings to the server's environment, the rail vehicle list file."""
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import hub  # noqa: E402
from nrails import rails  # noqa: E402


class HubRailsTest(unittest.TestCase):
    def test_rails_settings_reach_the_server(self):
        s = hub.load_settings()
        s["rails"].update({"catenary": False, "cant": True, "max_grade": 25})
        env = hub.server_env(s)
        self.assertEqual(env["BNGE_RAIL_CATENARY"], "off")
        self.assertEqual(env["BNGE_RAIL_CANT"], "on")
        self.assertEqual(env["BNGE_RAIL_MAX_GRADE"], "25")

    def test_max_grade_from_the_environment(self):
        keep = os.environ.get("BNGE_RAIL_MAX_GRADE")
        try:
            os.environ["BNGE_RAIL_MAX_GRADE"] = "25"
            self.assertAlmostEqual(rails.max_grade(), 0.025)
            os.environ["BNGE_RAIL_MAX_GRADE"] = "500"           # clamped
            self.assertAlmostEqual(rails.max_grade(), 0.080)
            os.environ["BNGE_RAIL_MAX_GRADE"] = "steep"         # the default
            self.assertAlmostEqual(rails.max_grade(), 0.035)
        finally:
            if keep is None:
                os.environ.pop("BNGE_RAIL_MAX_GRADE", None)
            else:
                os.environ["BNGE_RAIL_MAX_GRADE"] = keep

    def test_the_vehicle_list_file_the_mod_reads(self):
        names = hub.parse_vehicles("my_loco, wagon2;my_loco\nrailcar")
        self.assertEqual(names, ["my_loco", "wagon2", "railcar"])
        with tempfile.TemporaryDirectory() as d:
            path = hub.write_vehicle_list(d, names)
            self.assertEqual(path, os.path.join(d, "settings", "beamngEarth", "nrails_vehicles.json"))
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"vehicles": names})
        self.assertIsNone(hub.write_vehicle_list("", names))


if __name__ == "__main__":
    unittest.main()
