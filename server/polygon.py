"""Point-in-polygon for numpy arrays (even-odd rule), in place of matplotlib.path.Path.contains_points:
the server used matplotlib for nothing else, and the players' install (install.py: server/requirements.txt)
did not have it, so the server did not start from the release zip (2026-10-15).

    Path(ring).contains_points(pts) -> bool array    ring: (N, 2) vertices, open or closed; pts: (M, 2)
"""
import numpy as np

import fast


def contains_points(ring, pts):
    """Which of pts (M, 2) lie inside the polygon ring (N, 2) (even-odd crossings of a ray toward +x)."""
    ring = np.asarray(ring, np.float64).reshape(-1, 2)
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    fast.require(0, "contains_points")       # the Rust loop: crossings in horizontal bands of the ring's edges
    return np.asarray(fast._ef.contains_points(np.ascontiguousarray(ring), np.ascontiguousarray(pts)))


class Path:
    """The part of matplotlib.path.Path the server uses."""

    def __init__(self, vertices):
        self.vertices = np.asarray(vertices, np.float64).reshape(-1, 2)

    def contains_points(self, pts):
        return contains_points(self.vertices, pts)
