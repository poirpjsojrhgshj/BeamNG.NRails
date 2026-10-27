"""NRails: OpenStreetMap's railways round the player, for the map's Rails tab, its itineraries and the level crossings'
barriers (the user, 2026-10-27: "tu connais openstreetmap, tu sais que tu peux extraire des donnees de rails, extrait
les, met les sur la map, s'il y a trop a charger, charge les 100 km autour uniquement accessibles depuis notre voie";
"creer des barrieres de passages a niveau la ou il y en a dans la vraie vie").

Overture (the roads' source) has the railways' lines but none of OSM's railway tags or nodes: no level crossing's
crossing:barrier / crossing:light, no shared node ids to tell a junction from two lines passing over each other. The
Overpass API has them. Its rules (docs/research/2026-10-10-rate-limits.md, Overpass: "never at runtime" for streaming;
"if ever used: 1 concurrent, <= 100/day, pause 30 s on 429") are kept: never streamed nor prefetched, only asked for
the player's own area when the mod asks (a session's first track, the map's Rails tab), one request at a time, at most
DAILY_MAX a day, each TILE_DEG square kept on disk CACHE_DAYS (a 100 km round needs 4 to 12 of them, once a month).

Pure but for OsmRail (the requests and the cache): parse, graph, reachable, simplify, route.
"""
import gzip
import heapq
import json
import logging
import math
import os
import threading
import time
import urllib.parse
import urllib.request

log = logging.getLogger("earthd.nrails")

URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter")
USER_AGENT = "BeamNG.NRails (BeamNG.Earth fork; railways for the in-game map; github.com/poirpjsojrhgshj/BeamNG.NRails)"
TILE_DEG = 1.0              # the cache's squares (1 deg: 111 x ~75 km at 47 N)
CACHE_DAYS = 30
DAILY_MAX = 90              # requests a day at most (the rules: <= 100; a first 200 km area: ~35)
PAUSE_429_S = 60.0          # a 429 / 504: the server left alone this long
RETRY_S = 3600.0            # a failed square asked again after this long
TIMEOUT_S = 240
RADIUS_KM = 100.0
MAIN_RADIUS_KM = 200.0      # the main lines and branches only from RADIUS_KM out to this (their own squares)
SIMPLIFY_M = 8.0            # m the map's lines keep to the ways (Douglas-Peucker)
KINDS = ("rail", "light_rail", "narrow_gauge")
KEEP_TAGS = ("railway", "usage", "service", "maxspeed", "electrified", "gauge", "bridge", "tunnel", "name", "ref")
REVERSE_DEG = 100.0         # a route never turns more than this at a node (no reversing at a junction)
R_EARTH = 6371008.8


def query(s, w, n, e, main_only=False):
    """The Overpass query of one square: its railways (ways, their node ids and geometry, a few tags) and its level
    crossings (nodes, their tags); main_only: the main lines and branches alone (usage main / branch), no crossing."""
    kinds = "|".join(KINDS)
    bb = f"{s:.4f},{w:.4f},{n:.4f},{e:.4f}"
    if main_only:
        return (f'[out:json][timeout:{TIMEOUT_S - 20}];way["railway"~"^({kinds})$"]["usage"~"^(main|branch)$"]({bb});'
                f'out body geom qt;')
    return (f'[out:json][timeout:{TIMEOUT_S - 20}];(way["railway"~"^({kinds})$"]({bb});'
            f'node["railway"="level_crossing"]({bb}););out body geom qt;')


def parse(doc):
    """Overpass JSON -> {"ways": [[id, [node ids], [[lat, lon], ...], {tags}], ...], "xings": [[id, lat, lon,
    barrier, light, bell], ...]}."""
    ways, xings = [], []
    for el in (doc or {}).get("elements", ()):
        tags = el.get("tags") or {}
        if el.get("type") == "way" and el.get("geometry") and el.get("nodes"):
            geo = [[round(g["lat"], 7), round(g["lon"], 7)] for g in el["geometry"] if g]
            if len(geo) == len(el["nodes"]) and len(geo) >= 2:
                ways.append([el["id"], el["nodes"], geo, {k: tags[k] for k in KEEP_TAGS if k in tags}])
        elif el.get("type") == "node" and tags.get("railway") == "level_crossing":
            xings.append([el["id"], round(el["lat"], 7), round(el["lon"], 7), tags.get("crossing:barrier"),
                          tags.get("crossing:light"), tags.get("crossing:bell")])
    return {"ways": ways, "xings": xings}


def squares(lat, lon, r_km):
    """The TILE_DEG squares (south-west corners) touching the r_km round (lat, lon), nearest first."""
    dlat = r_km / 111.2
    dlon = r_km / (111.2 * max(math.cos(math.radians(lat)), 0.05))
    out = []
    a = math.floor((lat - dlat) / TILE_DEG)
    while a * TILE_DEG <= lat + dlat:
        b = math.floor((lon - dlon) / TILE_DEG)
        while b * TILE_DEG <= lon + dlon:
            cs, cw = a * TILE_DEG, b * TILE_DEG
            ny = min(max(lat, cs), cs + TILE_DEG)
            nx = min(max(lon, cw), cw + TILE_DEG)
            out.append((dist_m(lat, lon, ny, nx), round(cs, 4), round(cw, 4)))
            b += 1
        a += 1
    return [(s, w) for _d, s, w in sorted(out)]


def dist_m(la0, lo0, la1, lo1):
    p0, p1 = math.radians(la0), math.radians(la1)
    dp, dl = p1 - p0, math.radians(lo1 - lo0)
    h = math.sin(dp / 2) ** 2 + math.cos(p0) * math.cos(p1) * math.sin(dl / 2) ** 2
    return 2 * R_EARTH * math.asin(min(1.0, math.sqrt(h)))


class Graph:
    """The railways of some squares merged (a way across two squares comes in both: kept once): nodes {id: (lat,
    lon)}, adjacency {id: set(ids)}, the ways {id: (nodes, tags)} and the crossings {id: row}."""

    def __init__(self):
        self.pos, self.adj, self.ways, self.xings = {}, {}, {}, {}
        self.node_ways = {}     # node id -> [way ids] (a level crossing's line: its speed)

    def add(self, data):
        for wid, nodes, geo, tags in data.get("ways", ()):
            if wid in self.ways:
                continue
            self.ways[wid] = (nodes, tags)
            for nid, (la, lo) in zip(nodes, geo):
                self.pos[nid] = (la, lo)
                self.node_ways.setdefault(nid, []).append(wid)
            for a, b in zip(nodes, nodes[1:]):
                if a != b:
                    self.adj.setdefault(a, set()).add(b)
                    self.adj.setdefault(b, set()).add(a)
        for row in data.get("xings", ()):
            self.xings[row[0]] = row

    def nearest(self, lat, lon, max_m=500.0):
        """The node nearest (lat, lon), within max_m, or None (a linear pass: called a few times a request)."""
        best, bd = None, max_m
        k = math.cos(math.radians(lat))
        for nid, (la, lo) in self.pos.items():
            dy, dx = (la - lat) * 111200.0, (lo - lon) * 111200.0 * k
            if abs(dy) < bd and abs(dx) < bd:
                d = math.hypot(dx, dy)
                if d < bd:
                    best, bd = nid, d
        return best

    def reachable(self, start, lat, lon, r_m):
        """The node ids reached from `start` along the tracks, never past r_m from (lat, lon)."""
        if start is None:
            return set()
        seen, todo = {start}, [start]
        while todo:
            n = todo.pop()
            for m in self.adj.get(n, ()):
                if m not in seen:
                    la, lo = self.pos[m]
                    if dist_m(lat, lon, la, lo) <= r_m:
                        seen.add(m)
                        todo.append(m)
        return seen

    def lines(self, nodes, simplify_m=SIMPLIFY_M):
        """The map's lines of the ways with a node in `nodes`: [{"id", "pts": [[lat, lon], ...], "k": kind}], each
        cut to its runs inside `nodes` and simplified."""
        out = []
        for wid, (wn, tags) in self.ways.items():
            run = []
            for nid in wn + [None]:
                if nid is not None and nid in nodes:
                    run.append(self.pos[nid])
                    continue
                if len(run) >= 2:
                    out.append({"id": wid, "pts": [[round(a, 6), round(b, 6)] for a, b in simplify(run, simplify_m)],
                                "k": kind_of(tags)})
                run = []
        return out

    def route(self, a, b, max_turn_deg=REVERSE_DEG):
        """The shortest way from node a to node b along the tracks, never turning more than max_turn_deg at a node
        (a train does not reverse at a junction): ([node ids], metres) or (None, inf). Dijkstra over (node, came
        from) states."""
        if a is None or b is None or a not in self.adj or b not in self.adj:
            return None, math.inf
        cos_max = math.cos(math.radians(max_turn_deg))
        k = math.cos(math.radians(self.pos[a][0]))

        def vec(p, q):
            (la0, lo0), (la1, lo1) = self.pos[p], self.pos[q]
            return ((lo1 - lo0) * k, la1 - la0)

        best = {(a, None): 0.0}
        prev = {}
        heap = [(0.0, a, None)]
        while heap:
            d, n, f = heapq.heappop(heap)
            if d > best.get((n, f), math.inf):
                continue
            if n == b:
                path, st = [n], (n, f)
                while st in prev:
                    st = prev[st]
                    path.append(st[0])
                return path[::-1], d
            vin = vec(f, n) if f is not None else None
            for m in self.adj.get(n, ()):
                if m == f:
                    continue
                if vin is not None:
                    vout = vec(n, m)
                    li, lo = math.hypot(*vin), math.hypot(*vout)
                    if li > 0 and lo > 0 and (vin[0] * vout[0] + vin[1] * vout[1]) / (li * lo) < cos_max:
                        continue
                nd = d + dist_m(*self.pos[n], *self.pos[m])
                if nd < best.get((m, n), math.inf):
                    best[(m, n)] = nd
                    prev[(m, n)] = (n, f)
                    heapq.heappush(heap, (nd, m, n))
        return None, math.inf


def speed_of(tags):
    """A way's maxspeed in km/h (OSM's "120", "120 mph", "FR:rail"...), or None."""
    v = str(tags.get("maxspeed") or "").strip().lower()
    num = ""
    for ch in v:
        if ch.isdigit() or ch == ".":
            num += ch
        elif num:
            break
    if not num:
        return None
    try:
        s = float(num)
    except ValueError:
        return None
    return s * 1.609344 if "mph" in v else s


def node_speed(g, nid):
    """The highest maxspeed (km/h) of the ways through node nid, or None."""
    best = None
    for wid in g.node_ways.get(nid, ()):
        s = speed_of(g.ways[wid][1])
        if s is not None and (best is None or s > best):
            best = s
    return best


def kind_of(tags):
    """The map's line kind: "main" (a line), "branch", "service" (sidings, yards, spurs), "light"."""
    if tags.get("railway") in ("light_rail", "narrow_gauge"):
        return "light"
    if tags.get("service"):
        return "service"
    return "main" if tags.get("usage") == "main" else "branch"


def simplify(pts, tol_m):
    """Douglas-Peucker over [(lat, lon)] in metres (an equirectangular frame at the first point). Pure."""
    if len(pts) < 3:
        return list(pts)
    k = math.cos(math.radians(pts[0][0])) * 111200.0
    xy = [((lo - pts[0][1]) * k, (la - pts[0][0]) * 111200.0) for la, lo in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        ax, ay = xy[i]
        bx, by = xy[j]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        dmax, imax = -1.0, -1
        for m in range(i + 1, j):
            px, py = xy[m]
            d = abs((px - ax) * ey - (py - ay) * ex) / L if L > 1e-9 else math.hypot(px - ax, py - ay)
            if d > dmax:
                dmax, imax = d, m
        if imax > 0 and dmax > tol_m:
            keep[imax] = True
            stack += [(i, imax), (imax, j)]
    return [p for p, k_ in zip(pts, keep) if k_]


class OsmRail:
    """The squares on disk (<cache>/nrails/osm/rail_<s>_<w>.json.gz) and the requests (one at a time)."""

    def __init__(self, cache_dir, fetch=None, clock=time.time):
        self.dir = os.path.join(cache_dir, "nrails", "osm")
        self.fetch = fetch or _fetch
        self.clock = clock
        self.lock = threading.Lock()
        self.failed = {}
        self.paused_until = 0.0
        self.graph = Graph()
        self.loaded = set()

    def _path(self, s, w, main_only=False):
        return os.path.join(self.dir, f"rail{'m' if main_only else ''}_{s:+08.3f}_{w:+09.3f}.json.gz")

    def _day(self):
        p = os.path.join(self.dir, "requests.json")
        today = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            d = {}
        return p, today, (d.get("n", 0) if d.get("day") == today else 0)

    def square(self, s, w, main_only=False):
        """One square's data: from the disk when fresh, else asked (None: not now; the rules or the network)."""
        if main_only:                               # (a whole square on disk already holds its main lines)
            full = self._path(s, w)
            try:
                if self.clock() - os.path.getmtime(full) < CACHE_DAYS * 86400:
                    main_only = False
            except OSError:
                pass
        p = self._path(s, w, main_only)
        try:
            if self.clock() - os.path.getmtime(p) < CACHE_DAYS * 86400:
                with gzip.open(p, "rt", encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, ValueError):
            pass
        stale = None
        try:
            with gzip.open(p, "rt", encoding="utf-8") as f:
                stale = json.load(f)             # (an old copy: used when the server cannot be asked)
        except (OSError, ValueError):
            pass
        now = self.clock()
        if now < self.paused_until or now - self.failed.get((s, w, main_only), -1e18) < RETRY_S:
            return stale
        dp, today, n = self._day()
        if n >= DAILY_MAX:
            return stale
        os.makedirs(self.dir, exist_ok=True)
        with open(dp, "w", encoding="utf-8") as f:
            json.dump({"day": today, "n": n + 1}, f)
        try:
            doc = self.fetch(query(s, w, s + TILE_DEG, w + TILE_DEG, main_only))
        except RateLimited:
            self.paused_until = self.clock() + PAUSE_429_S
            self.failed[(s, w, main_only)] = self.clock()
            return stale
        except Exception as e:      # noqa: BLE001 - offline, timeout: the stale copy or nothing
            log.info("nrails osm: square %s,%s: %s", s, w, e)
            self.failed[(s, w, main_only)] = self.clock()
            return stale
        data = parse(doc)
        tmp = p + ".tmp"
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
        os.replace(tmp, p)
        return data

    def area(self, lat, lon, r_km=RADIUS_KM, on_progress=None, main_km=None):
        """The squares round (lat, lon) loaded into the graph, nearest first (on_progress(done, total) after each):
        whole within r_km, their main lines only out to main_km; the number missing."""
        with self.lock:
            inner = set(squares(lat, lon, r_km))
            sq = squares(lat, lon, max(r_km, main_km or 0))
            missing = 0
            for i, (s, w) in enumerate(sq):
                main_only = (s, w) not in inner
                if (s, w, False) not in self.loaded and (not main_only or (s, w, True) not in self.loaded):
                    data = self.square(s, w, main_only)
                    if data is None:
                        missing += 1
                    else:
                        self.graph.add(data)
                        self.loaded.add((s, w, main_only))
                if on_progress:
                    on_progress(i + 1, len(sq))
            return missing


class RateLimited(Exception):
    pass


def _fetch(q):
    import ssl
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    last = None
    for url in URLS:
        req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": q}).encode(),
                                     headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return json.loads(body)
        except urllib.error.HTTPError as e:
            if e.code in (429, 504):
                raise RateLimited(str(e.code)) from e
            last = e
        except Exception as e:      # noqa: BLE001 - the next mirror
            last = e
    raise last or OSError("overpass unreachable")
