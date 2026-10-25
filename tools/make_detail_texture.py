#!/usr/bin/env python3
"""Ground detail texture for the imagery tiles (v1.3): mod/beamng_earth/art/beamngEarth/detail_ground.dds

The engine's v1.0 material adds the detail map on top of the colour map with no distance fade
(shaders/common/material/shadergen/v0/defaultMatV0.hlsl:246: colour * saturate(map + detail*2-1)),
so a stock detail texture repeating every 2 m shows as a fabric-like pattern on hills hundreds
of metres away (seen in-game). Here the fade is built into the mip chain instead: the fine mips
carry the grain, the coarser ones blend to flat 0.5 grey (no change to the imagery), so the GPU's
own mip selection fades the detail with distance and viewing angle.

Procedural (no third-party content): periodic band-limited noise (FFT, so it tiles seamlessly)
plus sparse pebbles, zero mean. One repeat = 4 m (512 px = 7.8 mm per texel); level k has a
2^k times larger texel, and the fade runs over levels 2..5 (3-25 cm texels), i.e. roughly
10-80 m away head-on, nearer at grazing angles. Stored uncompressed (A8R8G8B8): DXT1's 5:6:5
endpoints tint near-grey grain green/magenta.

  python3 tools/make_detail_texture.py [out.dds]
"""
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "mod", "beamng_earth", "art", "beamngEarth", "detail_ground.dds")
N = 512
REPEAT_M = 4.0
AMPLITUDE = 0.03                   # std of level 0 around 0.5 (the shader adds 2x this to
                                   # imagery of ~0.3: 0.075 read as harsh salt-and-pepper in-game)
FADE = {0: 1.0, 1: 1.0, 2: 0.75, 3: 0.45, 4: 0.2}   # deeper levels: 0 (flat grey)


def grain(seed=7):
    rng = np.random.default_rng(seed)
    f = np.fft.fftfreq(N) * N / REPEAT_M                    # cycles per metre
    r = np.hypot(*np.meshgrid(f, f))
    # band 1.5 .. 60 cycles/m (67 cm .. 1.7 cm), pink-ish so it reads as gravel, not static
    band = np.where(r > 0, 1 / np.maximum(r, 1e-6) ** 0.6, 0) * (r > 1.5) * (r < 60)
    spec = np.fft.fft2(rng.standard_normal((N, N))) * band
    a = np.real(np.fft.ifft2(spec))
    a /= a.std()
    # sparse pebbles: small periodic blobs, light or dark
    yy, xx = np.mgrid[0:N, 0:N]
    for _ in range(400):
        cx, cy = rng.integers(0, N, 2)
        rad = rng.uniform(1.5, 5.0)                            # texels (1-4 cm)
        dx = (xx - cx + N // 2) % N - N // 2
        dy = (yy - cy + N // 2) % N - N // 2
        a += rng.choice((-1.6, 1.2)) * np.exp(-(dx * dx + dy * dy) / (2 * rad * rad))
    a -= a.mean()
    a /= a.std()
    return 0.5 + AMPLITUDE * a


def levels(img):
    out, cur, k = [], img, 0
    while True:
        out.append(0.5 + (cur - 0.5) * FADE.get(k, 0.0))
        if cur.shape[0] == 1:
            return out
        cur = cur.reshape(cur.shape[0] // 2, 2, cur.shape[1] // 2, 2).mean((1, 3))
        k += 1


def encode(levels_):
    DDSD = 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000         # caps, h, w, pitch, pixfmt, mipcount
    h, w = levels_[0].shape
    head = (b"DDS " + struct.pack("<7I", 124, DDSD, h, w, w * 4, 0, len(levels_))
            + struct.pack("<11I", *((0,) * 11))
            # DDPF_RGB | ALPHAPIXELS, R8G8B8A8 byte order: the game's DDS reader logs "only RGB
            # formats are supported!" for the A8R8G8B8 masks (it loads it anyway; in-game 2026-10-10)
            + struct.pack("<2I4s5I", 32, 0x41, b"\0\0\0\0", 32,
                          0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000)
            + struct.pack("<5I", 0x1000 | 0x400000 | 0x8, 0, 0, 0, 0))
    assert len(head) == 128
    body = []
    for lv in levels_:
        g = np.clip(np.rint(lv * 255), 0, 255).astype(np.uint8)
        rgba = np.stack([g, g, g, np.full_like(g, 255)], -1)
        body.append(rgba.tobytes())
    return head + b"".join(body)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else OUT
    os.makedirs(os.path.dirname(out), exist_ok=True)
    lv = levels(grain())
    data = encode(lv)
    with open(out, "wb") as f:
        f.write(data)
    print(out, len(data), "bytes;", len(lv), "levels; level means",
          [round(float(x.mean()), 4) for x in lv[:7]], "stds", [round(float(x.std()), 4) for x in lv[:7]])


if __name__ == "__main__":
    main()
