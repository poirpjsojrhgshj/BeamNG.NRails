"""tools/autodrive_perf.py: the crash / stop / off-route checks of a recorded drive."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "tools"))
import autodrive_perf as ad  # noqa: E402


def poll(t, v=10.0, damage=0.0, off=1.0, rem=2000.0, planning=False):
    return {"t": t, "x": t * v, "y": 0.0, "v": v, "damage": damage, "lat": 39.0, "lon": -76.0,
            "gps": {"remaining": rem, "off": off, "arrows": "r3", "planning": planning}}


class ChecksTest(unittest.TestCase):
    def run_polls(self, polls):
        shots = []
        c = ad.Checks(lambda n, ev: shots.append(ev["kind"]) or f"event_{n}.jpg")
        for p in polls:
            c.feed(p)
        return c.events, shots

    def test_a_crash_is_a_damage_jump(self):
        ev, shots = self.run_polls([poll(0), poll(1, damage=200), poll(2, v=0.1, damage=9000)])
        self.assertEqual([e["kind"] for e in ev], ["crash"])
        self.assertEqual(ev[0]["mph_before"], round(10 * 2.23694, 1))
        self.assertEqual(shots, ["crash"])

    def test_a_missed_damage_reading_is_no_crash(self):
        # (a run at Presov 2026-10-21: one poll read 0, the next the same damage again: two false crashes)
        ev, _ = self.run_polls([poll(0), poll(1, damage=4243), poll(2, damage=0), poll(3, damage=4243)])
        self.assertEqual([e["kind"] for e in ev], ["crash"])
        ev, _ = self.run_polls([poll(0, damage=4243), poll(1, damage=0), poll(2, damage=0), poll(3, damage=4000)])
        self.assertEqual([e["kind"] for e in ev], ["crash"], "a reset car's next crash")

    def test_a_scrape_is_not_a_crash(self):
        ev, _ = self.run_polls([poll(0), poll(1, damage=300), poll(2, damage=700)])
        self.assertEqual(ev, [])

    def test_a_stop_after_standing_long_once(self):
        polls = [poll(0)] + [poll(t, v=0.0) for t in range(1, 120)]
        ev, _ = self.run_polls(polls)
        self.assertEqual([e["kind"] for e in ev], ["stop"], "once, not every poll after")
        self.assertGreaterEqual(ev[0]["seconds"], ad.STOP_S)

    def test_a_red_light_planning_or_arrival_is_no_stop(self):
        ev, _ = self.run_polls([poll(t, v=0.0) for t in range(30)] + [poll(31)])
        self.assertEqual(ev, [], "30 s at a light")
        ev, _ = self.run_polls([poll(t, v=0.0, planning=True) for t in range(100)])
        self.assertEqual(ev, [], "waiting for the route")
        ev, _ = self.run_polls([poll(t, v=0.0, rem=20.0) for t in range(100)])
        self.assertEqual(ev, [], "arrived")

    def test_leaving_the_route_once_per_excursion(self):
        ev, _ = self.run_polls([poll(0), poll(1, off=40), poll(2, off=45), poll(3, off=2), poll(4, off=30)])
        self.assertEqual([e["kind"] for e in ev], ["off_route", "off_route"])


class HitchTest(unittest.TestCase):
    def test_causes(self):
        self.assertEqual(ad.hitch_cause({"ms": 80, "mod": {"roads": 60, "far": 3}, "engine": {"render": 10}}), "mod.roads")
        self.assertEqual(ad.hitch_cause({"ms": 80, "mod": {"roads": 5}, "engine": {"render": 60, "ui": 2}}),
                         "engine.render")
        rows = [{"hitches": [{"ms": 80, "mod": {"roads": 60}}, {"ms": 120, "mod": {"roads": 90}}]},
                {"hitches": {}}, {"hitches": [{"ms": 70, "engine": {"gfx": 50}}]}]
        self.assertEqual(ad._causes(rows), {"mod.roads": [2, 120], "engine.gfx": [1, 70]})


if __name__ == "__main__":
    unittest.main()
