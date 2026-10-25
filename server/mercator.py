"""Web-Mercator limits shared by the tiled sources (imagery, its shadow and colour fixes, the DEM, the map cells).

Web Mercator stops at +-MAX_LAT (85.05 deg): beyond it there are no tiles, and near it a fixed ground distance spans
ever more tiles (1 / cos(lat) of them; at the poles, every column). Loops over the tiles around a point use columns():
at most one turn of the globe, each column once.
"""
import math

MAX_LAT = 85.0511287798066


def columns(x, rpx, tile, n):
    """The tile columns (wrapped into [0, n)) of the pixel span x +- rpx, each once and at most n of them."""
    c0, c1 = int(math.floor((x - rpx) / tile)), int(math.floor((x + rpx) / tile))
    if c1 - c0 + 1 >= n:
        return range(n)
    return [c % n for c in range(c0, c1 + 1)]
