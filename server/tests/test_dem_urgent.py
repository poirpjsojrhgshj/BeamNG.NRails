"""Dem.urgent(): tiles asked for in it skip the queue of the shared fetch pool."""
import os
import sys
import tempfile
import threading
import time
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import dem as demmod  # noqa: E402


class UrgentTest(unittest.TestCase):
    def test_urgent_skips_the_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = demmod.Dem(tmp, fetch_workers=1)
            gate = threading.Event()

            def load(k):
                if k[0] == 9:           # the queued, slow ones
                    gate.wait(10)
                return np.zeros((demmod.TILE, demmod.TILE), np.float32)
            d._load_tile = load
            # the shared pool's one worker busy, its queue full - including the tile the urgent caller needs
            blockers = [threading.Thread(target=d.tiles, args=([(9, i, 0)],)) for i in range(4)]
            for b in blockers:
                b.start()
            time.sleep(0.1)
            queued = threading.Thread(target=d.tiles, args=([(10, 1, 1)],))
            queued.start()
            time.sleep(0.1)
            t = time.monotonic()
            with d.urgent():
                got = d.tiles([(10, 1, 1), (10, 2, 2)])
            self.assertLess(time.monotonic() - t, 2.0)
            self.assertEqual(len(got), 2)
            gate.set()
            for b in blockers + [queued]:
                b.join(10)


if __name__ == "__main__":
    unittest.main()
