import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import pacer  # noqa: E402


class ForegroundTest(unittest.TestCase):
    def test_hold_waits_for_the_foreground(self):
        pacer.foreground_begin()
        done = []
        th = threading.Thread(target=lambda: (pacer.hold(5.0), done.append(time.monotonic())))
        th.start()
        time.sleep(0.2)
        self.assertEqual(done, [], "held while the foreground work runs")
        t_end = time.monotonic()
        pacer.foreground_end()
        th.join(2.0)
        self.assertEqual(len(done), 1)
        self.assertGreaterEqual(done[0], t_end)

    def test_hold_without_foreground_and_its_limit(self):
        t0 = time.monotonic()
        pacer.hold(5.0)
        self.assertLess(time.monotonic() - t0, 0.1)
        pacer.foreground_begin()
        try:
            t0 = time.monotonic()
            pacer.hold(0.2)
            self.assertGreaterEqual(time.monotonic() - t0, 0.19, "at most max_s")
        finally:
            pacer.foreground_end()


if __name__ == "__main__":
    unittest.main()
