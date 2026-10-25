"""Synthetic OurAirports files for the airport tests (no network): the real column sets, rows built
from runway geometry given in metres."""
import csv
import io
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import airports  # noqa: E402

AIRPORT_COLS = ["id", "ident", "type", "name", "latitude_deg", "longitude_deg", "elevation_ft", "continent",
                "iso_country", "iso_region", "municipality", "scheduled_service", "icao_code", "iata_code",
                "gps_code", "local_code", "home_link", "wikipedia_link", "keywords"]
RUNWAY_COLS = ["id", "airport_ref", "airport_ident", "length_ft", "width_ft", "surface", "lighted", "closed",
               "le_ident", "le_latitude_deg", "le_longitude_deg", "le_elevation_ft", "le_heading_degT",
               "le_displaced_threshold_ft", "he_ident", "he_latitude_deg", "he_longitude_deg", "he_elevation_ft",
               "he_heading_degT", "he_displaced_threshold_ft"]
FT = airports.FT


def airport(id, ident, lat, lon, elev_ft=100, type="medium_airport", country="US", name=None):
    return {"id": str(id), "ident": ident, "type": type, "name": name or f"{ident} Airport", "latitude_deg": f"{lat:.6f}",
            "longitude_deg": f"{lon:.6f}", "elevation_ft": "" if elev_ft is None else str(elev_ft),
            "continent": "NA", "iso_country": country, "iso_region": f"{country}-X", "municipality": "Town",
            "scheduled_service": "no", "icao_code": ident, "iata_code": "", "gps_code": ident, "local_code": "",
            "home_link": "", "wikipedia_link": "", "keywords": ""}


def runway(id, ap, lat, lon, heading, length_m, width_m=45.72, surface="ASP", lighted=1, closed=0,
           le="09", he="27", le_elev_ft=100, he_elev_ft=100, le_disp_ft=None, he_disp_ft=None,
           ends=("le", "he"), headings=True, length_ft=None, width_ft=None):
    """A runways.csv row: le end at (lat, lon), the he end `length_m` along the true `heading`."""
    hlat, hlon = airports._offset(lat, lon, heading, length_m)
    r = {"id": str(id), "airport_ref": ap["id"], "airport_ident": ap["ident"],
         "length_ft": f"{length_m / FT:.0f}" if length_ft is None else str(length_ft),
         "width_ft": f"{width_m / FT:.0f}" if width_ft is None else str(width_ft),
         "surface": surface, "lighted": str(lighted), "closed": str(closed),
         "le_ident": le, "le_latitude_deg": "", "le_longitude_deg": "",
         "le_elevation_ft": "" if le_elev_ft is None else str(le_elev_ft),
         "le_heading_degT": f"{heading:.1f}" if headings else "",
         "le_displaced_threshold_ft": "" if le_disp_ft is None else str(le_disp_ft),
         "he_ident": he, "he_latitude_deg": "", "he_longitude_deg": "",
         "he_elevation_ft": "" if he_elev_ft is None else str(he_elev_ft),
         "he_heading_degT": f"{(heading + 180) % 360:.1f}" if headings else "",
         "he_displaced_threshold_ft": "" if he_disp_ft is None else str(he_disp_ft)}
    if "le" in ends:
        r["le_latitude_deg"], r["le_longitude_deg"] = f"{lat:.8f}", f"{lon:.8f}"
    if "he" in ends:
        r["he_latitude_deg"], r["he_longitude_deg"] = f"{hlat:.8f}", f"{hlon:.8f}"
    return r


def helipad(id, ap, lat=None, lon=None, ident="H1"):
    return {"id": str(id), "airport_ref": ap["id"], "airport_ident": ap["ident"], "length_ft": "50",
            "width_ft": "50", "surface": "CON", "lighted": "1", "closed": "0", "le_ident": ident,
            "le_latitude_deg": "" if lat is None else f"{lat:.6f}", "le_longitude_deg": "" if lon is None else f"{lon:.6f}",
            "le_elevation_ft": "", "le_heading_degT": "", "le_displaced_threshold_ft": "", "he_ident": "",
            "he_latitude_deg": "", "he_longitude_deg": "", "he_elevation_ft": "", "he_heading_degT": "",
            "he_displaced_threshold_ft": ""}


def to_csv(rows, cols):
    out = io.StringIO(newline="")
    w = csv.DictWriter(out, fieldnames=cols, lineterminator="\n", quoting=csv.QUOTE_NONNUMERIC)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return out.getvalue().encode("utf-8")


def world():
    """A small world: a two-runway airport with a crossing runway, a grass strip, special cases.
    Returns (airports_csv, runways_csv, the airport rows by ident)."""
    A = airport(1, "KTST", 45.0, 7.0, 330)
    B = airport(2, "GRAS", 45.05, 7.05, 500, type="small_airport", country="GB")
    C = airport(3, "SKEW", 45.10, 7.10, 600, type="small_airport", country="FR")
    H = airport(4, "HELI", 45.0, 7.02, 300, type="heliport")
    X = airport(5, "GONE", 45.2, 7.2, 300, type="closed")
    M = airport(6, "MISS", 45.3, 7.3, 300, type="small_airport")
    S = airport(7, "STEP", 45.4, 7.4, 6000, type="small_airport", country="FR")
    aps = [A, B, C, H, X, M, S]
    rws = [
        runway(101, A, 45.0, 6.99, 90.0, 3000.0, le="09", he="27", le_elev_ft=330, he_elev_ft=300, le_disp_ft=600),
        runway(102, A, 44.995, 7.005, 0.0, 2200.0, width_m=45.72, le="18", he="36", surface="CONC-G"),
        runway(103, A, 44.99, 7.02, 45.0, 1500.0, width_m=30.48, le="05", he="23", closed=1),
        runway(201, B, 45.05, 7.05, 60.0, 800.0, width_m=25.0, surface="GRS", lighted=0, le="06", he="24"),
        runway(301, C, 45.10, 7.10, 120.0, 900.0, surface="Asphalt", ends=("he",), le="12", he="30", lighted=0),
        runway(302, C, 45.10, 7.10, 30.0, 700.0, surface="", ends=(), le="03", he="21", lighted=0),   # 2nd runway: no arp
        helipad(401, H, 45.0, 7.02),
        helipad(402, H),
        runway(501, X, 45.2, 7.2, 90.0, 1000.0, surface="TURF", lighted=0),
        runway(601, M, 45.3, 7.3, 90.0, 1000.0, ends=(), surface="GVL", lighted=0, width_ft=""),       # arp
        runway(602, A, 45.0, 7.04, 90.0, 1000.0, ends=(), headings=False, le="N", he="S"),             # skipped
        runway(701, S, 45.4, 7.4, 45.0, 540.0, surface="Asphalt", le="04", he="22", le_elev_ft=6400, he_elev_ft=6600,
               width_m=40.0, lighted=0),
    ]
    return to_csv(aps, AIRPORT_COLS), to_csv(rws, RUNWAY_COLS), {a["ident"]: a for a in aps}


def db():
    a, r, _ = world()
    return airports.AirportDB.from_csv(a, r)


def plane(z0=100.0, gx=0.0, gy=0.0, lat0=45.0, lon0=7.0, bumps=0.0):
    """A synthetic DEM sampler: z0 + gx * east + gy * north (m) around (lat0, lon0), plus optional
    smooth bumps of amplitude `bumps` (m)."""
    k = 111320.0
    c = math.cos(math.radians(lat0))
    import numpy as np

    def fn(lat, lon):
        lat = np.asarray(lat, np.float64)
        lon = np.asarray(lon, np.float64)
        y = (lat - lat0) * k
        x = (lon - lon0) * k * c
        return z0 + gx * x + gy * y + bumps * np.sin(x / 97.0) * np.cos(y / 131.0)
    return fn
