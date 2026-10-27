"""NRails: one profile per map cell, shared by everything that needs the track's heights.

Every road tile profiled its own window (the tile + rails.NEAR_M) and every map cell's grading plan again its own
(nrails.grade): ~40 profiles of the same tracks per map cell, each its own window, so their heights met only within the
reach of the windows' margins (the user's run, 2026-10-25: loading and teleports "impitoyable", Calais never loaded;
steps between tiles and a 30 % ramp where a window cut a tunnel network). Now a map cell's tracks are profiled once
per process, in the cell's box + NEAR_M (rails.profile_network), and each sample belongs to the one cell it lies in:
a road tile, a terrain block's tunnel holes and the cell's grading plans all take the samples of the cells they cover,
so they agree everywhere by construction (two cells' samples meet where their windows overlap by NEAR_M).

The ground is the grader's own (the DEM at grading.PROFILE_ZOOM, the sea and lake floors carved by its wet(): the
Channel Tunnel's cover reads the sea floor), the same in every process: the cell's grading plan puts the terrain at
the bed right under the track the road tiles draw. Without a grader for the frame (grading off): the caller's elev.
"""
import threading
from collections import OrderedDict

import numpy as np

CACHE_CELLS = 64            # cell profiles kept per process (least recently used out)

_graders = {}               # frame key -> grading.Grader (grader_made)
_mem = OrderedDict()        # (frame key, cell key, elev id) -> CellProfile
_lock = threading.Lock()
_key_locks = {}


def frame_key(frame):
    return (round(float(frame.lat0), 9), round(float(frame.lon0), 9), round(float(getattr(frame, "h0", 0.0)), 3))


def grader_made(grader):
    """A grading.Grader made for an anchor's frame in this process (blockworker / earthd hooks): its ground is the
    profiles' (see above)."""
    if grader is not None:
        _graders[frame_key(grader.frame)] = grader


def canonical_elev(frame):
    """elev(lat, lon) of the profiles in this frame: the grader's DEM with the water floors carved; None without
    a grader."""
    g = _graders.get(frame_key(frame))
    if g is None:
        return None
    wet = getattr(g, "wet", None)

    def elev(la, lo):
        z = np.asarray(g.elev(np.asarray(la), np.asarray(lo)), np.float64)
        if wet is not None:
            try:
                d = np.asarray(wet(np.asarray(la), np.asarray(lo)), np.float64)
                z = z - np.maximum(np.nan_to_num(d), 0.0)
            except Exception:       # noqa: BLE001 - no water data at hand: the DEM
                pass
        return z
    elev.canonical = True
    return elev


class CellProfile:
    """parts: {fid: [(xyz (k, 3), kind (k,), arc (k,))]} the samples of the cell's own box (runs along the mapped
    segment, arc its length from the segment's start), found: the level crossings in it."""
    __slots__ = ("parts", "found")

    def __init__(self, parts, found):
        self.parts, self.found = parts, found


def _cell_box(frame, key):
    lon0, lat0, lon1, lat1 = key.bounds()
    e, n, _ = frame.geodetic_to_enu(np.array([lat0, lat0, lat1, lat1]), np.array([lon0, lon1, lon0, lon1]), 0.0)
    e, n = np.asarray(e, np.float64), np.asarray(n, np.float64)
    return float(e.min()), float(n.min()), float(e.max()), float(n.max())


def _owned(frame, key, xy):
    lon0, lat0, lon1, lat1 = key.bounds()
    la, lo, _ = frame.enu_to_geodetic(xy[:, 0], xy[:, 1], np.zeros(len(xy)))
    la, lo = np.asarray(la, np.float64), np.asarray(lo, np.float64)
    return (la >= lat0) & (la < lat1) & (lo >= lon0) & (lo < lon1)


# A map cell that could not be read while profiling (fetch_cell: asked CELL_RETRIES times): the profile made without
# it is used but never kept (the user's runs, 2026-10-27: "absence de terrain sous le ballast ... general ...
# reapparition du terrain apres rechargement": a cell missing once, the hole in the bed's grading stayed the whole run).
CELL_RETRIES = 3
CELL_WAIT_S = (1.0, 3.0, 6.0)
_tl = threading.local()


def note_miss():
    """A cell needed by the profile being made could not be read (this thread)."""
    _tl.miss = getattr(_tl, "miss", 0) + 1
    try:
        import revisit
        revisit.fault()             # (nothing made now is persisted: upstream's road tiles and plans alike)
    except Exception:       # noqa: BLE001
        pass


def misses():
    return getattr(_tl, "miss", 0)


def fetch_cell(cell_fn, k, log=None):
    """cell_fn(k), asked again CELL_RETRIES times after a failure (CELL_WAIT_S apart); None and note_miss() when it
    still fails."""
    import time
    last = None
    for i in range(CELL_RETRIES + 1):
        try:
            return cell_fn(k)
        except Exception as e:      # noqa: BLE001
            last = e
            if i < CELL_RETRIES:
                time.sleep(CELL_WAIT_S[min(i, len(CELL_WAIT_S) - 1)])
    if log is not None:
        log.info("NRails: map cell %s not at hand (%s: %s): its track left out this time", k, type(last).__name__, last)
    note_miss()
    return None


def cell_profile(frame, key, cell_fn, elev):
    """The CellProfile of map cell key (see above), cached. cell_fn(key): a cell's "roads" layer (None when not at
    hand); elev: the caller's, when there is no canonical one."""
    from nrails import rails
    ce = canonical_elev(frame)
    use = ce if ce is not None else elev
    ck = (frame_key(frame), str(key), "c" if ce is not None else id(elev))
    with _lock:
        got = _mem.get(ck)
        if got is not None:
            _mem.move_to_end(ck)
            return got
        kl = _key_locks.setdefault(ck, threading.Lock())
    with kl:
        with _lock:
            got = _mem.get(ck)
            if got is not None:
                return got
        path = _disk_path(frame, key) if ce is not None else None
        got = _load(path) if path else None
        if got is None:
            m0 = misses()
            got = _profile_cell(frame, key, cell_fn, use, rails)
            if misses() != m0:
                return got          # (a cell missing: used now, made again next time)
            if path:
                _store(path, got)
        with _lock:
            _mem[ck] = got
            while len(_mem) > CACHE_CELLS:
                old, _v = _mem.popitem(last=False)
                _key_locks.pop(old, None)
        return got


# The server's processes share each cell's profile through a file (one server run's own, as grading's plancache: the
# terrain blocks', the road tiles' and the grading's processes would each profile the same cells otherwise).
DISK_VERSION = 1


def _disk_path(frame, key):
    import os
    run = os.environ.get("BNGE_PLAN_RUN")
    if not run:
        return None
    from nrails import paths
    root = os.path.join(paths.default_cache_dir(), "nrails_profiles")
    if not _pruned:
        _pruned.append(True)
        _prune(root, run)
    return os.path.join(root, run, f"v{DISK_VERSION}_{frame.lat0:.9f}_{frame.lon0:.9f}",
                        str(key).replace("/", "_") + ".npz")


_pruned = []


def _prune(root, run, keep_s=6 * 3600.0):
    """Other runs' folders untouched for keep_s removed."""
    import os
    import shutil
    import time
    try:
        for name in os.listdir(root):
            p = os.path.join(root, name)
            if name != run and os.path.isdir(p) and time.time() - os.path.getmtime(p) > keep_s:
                shutil.rmtree(p, ignore_errors=True)
    except OSError:
        pass


def _load(path):
    import json
    import os
    if not os.path.exists(path):
        return None
    try:
        with np.load(path, allow_pickle=False) as f:
            meta = json.loads(str(f["meta"]))
            parts = {}
            for i, (fid, n) in enumerate(meta["parts"]):
                parts.setdefault(fid, []).append((f[f"p{i}"], f[f"k{i}"], f[f"a{i}"]))
            found = []
            for x in meta["found"]:             # (its vectors as arrays again, as profile_network made them)
                x = dict(x)
                for k in ("at", "t", "n"):
                    if k in x:
                        x[k] = np.asarray(x[k], np.float64)
                found.append(x)
            return CellProfile(parts, found)
    except Exception:       # noqa: BLE001 - unreadable: profiled again
        return None


def _store(path, cp):
    import json
    import os
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        arrays, plist = {}, []
        i = 0
        for fid, ps in cp.parts.items():
            for p, k, a in ps:
                arrays[f"p{i}"], arrays[f"k{i}"], arrays[f"a{i}"] = p, np.asarray(k), np.asarray(a)
                plist.append((fid, len(p)))
                i += 1

        arrays["meta"] = np.array(json.dumps({"parts": plist, "found": cp.found},
                                             default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
        tmp = f"{path}.{os.getpid()}.tmp.npz"
        np.savez(tmp, **arrays)
        os.replace(tmp, path)
    except Exception:       # noqa: BLE001 - not shared this time
        pass


def _profile_cell(frame, key, cell_fn, elev, rails):
    import mapcells
    own = _cell_box(frame, key)
    m = rails.NEAR_M
    near = (own[0] - m, own[1] - m, own[2] + m, own[3] + m)
    la, lo, _ = frame.enu_to_geodetic(np.array([near[0], near[2]]), np.array([near[1], near[3]]), 0.0)
    la, lo = np.asarray(la, np.float64), np.asarray(lo, np.float64)
    keys = mapcells.cells_for_bbox(float(la.min()), float(lo.min()), float(la.max()), float(lo.max()))
    own_feats = cell_fn(key)
    if own_feats is None or not rails.rail_features([own_feats], frame, own):
        return CellProfile({}, [])          # (most cells: no track in them, nothing more read)
    first = {k: (own_feats if str(k) == str(key) else cell_fn(k)) for k in keys}
    cells = list(rails.more_cells(keys, cell_fn, first).values())
    feats = rails.rail_features(cells, frame, rails._feature_box(near))
    segments = [(fid, xy, rg) for fid, cls, xy, rg in feats if cls in rails.HEAVY_CLASSES]
    if not segments:
        return CellProfile({}, [])
    with_x = rails._on("BNGE_RAIL_CROSSINGS")
    roads_near = rails.road_lines(cells, frame, near) if with_x else ()
    structs = rails.road_structs(cells, frame, near) if with_x else None
    found, arcs = [], {}
    prof = rails.profile_network(rails.Ground(frame, elev), segments, near, roads_near, found, arcs, structs,
                                 rails.rail_connectors(cells))
    parts = {}
    for fid, ps in prof.items():
        for (pts, kind), arc in zip(ps, arcs[fid]):
            mine = _owned(frame, key, pts[:, :2])
            for run in rails._runs(mine):
                if len(run):
                    parts.setdefault(fid, []).append((pts[run], np.asarray(kind)[run], np.asarray(arc)[run]))
    found = [x for x in found if _owned(frame, key, np.asarray([x["at"]], np.float64)[:, :2])[0]]
    return CellProfile(parts, found)


def profile_box(frame, box, cell_fn, elev):
    """The heavy tracks round box (x0, y0, x1, y1), from the profiles of the map cells it touches: ({fid: [(pts (k, 3),
    kind (k,))]}, found, arcs {fid: [arc (k,)]}) as rails.profile_network gives them (each fid's samples of the cells
    joined along its arc; a run per stretch without a gap)."""
    import mapcells
    from nrails import rails
    la, lo, _ = frame.enu_to_geodetic(np.array([box[0], box[2]]), np.array([box[1], box[3]]), 0.0)
    la, lo = np.asarray(la, np.float64), np.asarray(lo, np.float64)
    keys = mapcells.cells_for_bbox(float(la.min()), float(lo.min()), float(la.max()), float(lo.max()))
    by_fid, found = {}, []
    for k in keys:
        cp = cell_profile(frame, k, cell_fn, elev)
        found += cp.found
        for fid, ps in cp.parts.items():
            by_fid.setdefault(fid, []).extend(ps)
    prof, arcs = {}, {}
    gap = 1.6 * rails.STEP_M
    for fid, ps in by_fid.items():
        pts = np.concatenate([p for p, _k, _a in ps])
        kind = np.concatenate([k for _p, k, _a in ps])
        arc = np.concatenate([a for _p, _k, a in ps])
        o = np.argsort(arc, kind="stable")
        pts, kind, arc = pts[o], kind[o], arc[o]
        keep = np.r_[True, np.diff(arc) > 1e-6]
        pts, kind, arc = pts[keep], kind[keep], arc[keep]
        cuts = np.flatnonzero(np.diff(arc) > gap) + 1
        for a, b in zip(np.r_[0, cuts], np.r_[cuts, len(arc)]):
            if b - a >= 2:
                prof.setdefault(fid, []).append((pts[a:b], kind[a:b]))
                arcs.setdefault(fid, []).append(arc[a:b])
    return prof, found, arcs


def cached_box(frame, box):
    """Are the profiles of every map cell profile_box reads for box already made (in memory or this run's disk
    cache)? Never profiles anything. (nrails.hooks.rail_corridor_cached: a provisional block's corridor only then,
    the block itself must come in seconds.)"""
    import os
    import mapcells
    la, lo, _ = frame.enu_to_geodetic(np.array([box[0], box[2]]), np.array([box[1], box[3]]), 0.0)
    la, lo = np.asarray(la, np.float64), np.asarray(lo, np.float64)
    fk = frame_key(frame)
    for k in mapcells.cells_for_bbox(float(la.min()), float(lo.min()), float(la.max()), float(lo.max())):
        with _lock:
            if (fk, str(k), "c") in _mem:
                continue
        path = _disk_path(frame, k)
        if not path or not os.path.exists(path):
            return False
    return True


def covered_box(frame, box):
    """The union of the boxes of the map cells profile_box reads for box (where its pieces are cut)."""
    import mapcells
    la, lo, _ = frame.enu_to_geodetic(np.array([box[0], box[2]]), np.array([box[1], box[3]]), 0.0)
    la, lo = np.asarray(la, np.float64), np.asarray(lo, np.float64)
    bs = np.array([_cell_box(frame, k) for k in
                   mapcells.cells_for_bbox(float(la.min()), float(lo.min()), float(la.max()), float(lo.max()))])
    return float(bs[:, 0].min()), float(bs[:, 1].min()), float(bs[:, 2].max()), float(bs[:, 3].max())


def block_tubes(frame, cell_fn, elev, box):
    """rails.block_tubes from the cells' shared profiles: the rail tunnels' tubes round a terrain block's box."""
    from nrails import rails
    m = 50.0
    nbox = (box[0] - m, box[1] - m, box[2] + m, box[3] + m)
    pm, _found, _arcs = profile_box(frame, nbox, cell_fn, elev)
    heavy = [(fid, pts, kd) for fid, ps in pm.items() for pts, kd in ps]
    if not any((np.asarray(kd) == 2).any() for _f, _p, kd in heavy):
        return []
    return rails.tunnel_tubes(heavy, covered_box(frame, nbox))


def clear():
    with _lock:
        _mem.clear()
        _key_locks.clear()
