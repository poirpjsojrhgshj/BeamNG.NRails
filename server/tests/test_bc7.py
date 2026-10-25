"""bc7.py: BC7 mode-6 blocks round-trip, the anchor rule, the DDS layout the game's terrain cache uses."""
import os
import struct
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bc7  # noqa: E402


class Bc7Test(unittest.TestCase):
    def test_round_trip(self):
        rng = np.random.default_rng(5)
        # photo-like: a smooth luminance field with a colour cast and a little per-channel noise
        lum = np.cumsum(np.cumsum(rng.normal(0, 1.0, (64, 64)), 0), 1)
        lum = (lum - lum.min()) / (np.ptp(lum) + 1e-9) * 180 + 40
        smooth = np.clip(lum[..., None] * np.array([1.0, 0.9, 0.75]) + rng.normal(0, 2, (64, 64, 3)), 0, 255).astype(np.uint8)
        dec = bc7.decode(bc7.encode(smooth), 64, 64)
        self.assertEqual(dec.shape, (64, 64, 4))
        err = np.abs(dec[..., :3].astype(int) - smooth).mean()
        self.assertLess(err, 3.0)
        self.assertTrue((dec[..., 3] == 255).all(), "opaque")
        flat = np.full((8, 8, 3), (10, 200, 77), np.uint8)
        self.assertLessEqual(np.abs(bc7.decode(bc7.encode(flat), 8, 8)[..., :3].astype(int) - flat).max(), 1)

    def test_anchor_and_size(self):
        img = np.zeros((4, 4, 3), np.uint8)
        img[0, 0] = 255                          # a bright texel 0: its index starts high, so the endpoints swap
        blk = bc7.encode(img)
        self.assertEqual(len(blk), 16)
        lo = struct.unpack("<Q", blk[:8])[0]
        self.assertEqual(lo & 0x7F, 1 << 6, "mode 6")
        dec = bc7.decode(blk, 4, 4)[..., :3]
        self.assertGreater(int(dec[0, 0].min()), 230)
        self.assertLess(int(dec[3, 3].max()), 25)
        odd = bc7.decode(bc7.encode(np.full((5, 7, 3), 50, np.uint8)), 7, 5)
        self.assertEqual(odd.shape, (5, 7, 4))

    def test_dds_layout(self):
        img = np.full((64, 64, 3), 99, np.uint8)
        d = bc7.dds(img)
        self.assertEqual(d[:4], b"DDS ")
        size, flags, h, w, linear, depth, mips = struct.unpack("<7I", d[4:32])
        self.assertEqual((size, h, w, linear, mips), (124, 64, 64, 64 * 64, 7))
        self.assertEqual(d[84:88], b"DX10")
        self.assertEqual(struct.unpack("<5I", d[128:148]), (bc7.DXGI_BC7_UNORM_SRGB, 3, 0, 1, 0))
        body = sum(max(1, (64 >> k) // 4) ** 2 * 16 for k in range(7))
        self.assertEqual(len(d), 148 + body)


class TerrainCacheKeyTest(unittest.TestCase):
    def test_xxh64_and_the_games_key(self):
        import terraincache
        self.assertEqual(terraincache.xxh64(b""), 0xEF46DB3751D8E999)
        # a cache miss in the game's log (2026-10-12): base colour = this path, ao = the level's flat map
        self.assertEqual(terraincache.base_key("/temp/beamngEarth/20261012-205217-e109/hm_3_0_0_base.dds",
                                               "/levels/beamng_earth/art/terrains/bngEarth_base_ao.png"),
                         "a85a55fd11d8c1f6")


if __name__ == "__main__":
    unittest.main()


class TerrainCacheMipsTest(unittest.TestCase):
    def test_rgba_mips_follow_the_photo(self):
        """GitHub #115: the terrain cache's RGBA (photo + AO) mips were read as RGB: grey under the top level, the
        distant ground striped (worst at Low texture quality, which draws the lower levels)."""
        import struct
        rng = np.random.default_rng(5)
        rgb = np.clip(np.array([180, 130, 80]) + rng.normal(0, 12, (256, 256, 3)), 0, 255).astype(np.uint8)
        rgba = np.concatenate([rgb, np.full((256, 256, 1), 251, np.uint8)], 2)
        d = bc7.dds(rgba)
        h, w, mips = struct.unpack_from("<2I", d, 12) + (struct.unpack_from("<I", d, 28)[0],)
        off = 148
        for k in range(mips):
            lw, lh = max(1, w >> k), max(1, h >> k)
            n = max(1, (lw + 3) // 4) * max(1, (lh + 3) // 4) * 16
            lv = bc7.decode(d[off:off + n], lw, lh)
            off += n
            mean = lv[..., :3].reshape(-1, 3).mean(0)
            self.assertLess(np.abs(mean - [180, 130, 80]).max(), 12, f"level {k}: {mean}")
            self.assertTrue(np.all(np.abs(lv[..., 3].astype(int) - 251) <= 2), f"level {k}: alpha")
        self.assertEqual(off, len(d))
