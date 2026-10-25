"""NAIP orthophoto (USGS National Agriculture Imagery Program, public domain; ~0.6 m) of a square
HALF_M around LAT LON, 1024 px wide (pixels square in degrees, so the box is exact; tools/ortho_overlay.py
squares it in metres). Fetched politely through the server's netfetch (project User-Agent).
    python3 tools/ortho_naip.py LAT LON HALF_M OUT.jpg"""
import sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'server'))
import netfetch
lat, lon, half, out = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
PX = int(sys.argv[5]) if len(sys.argv) > 5 else 1024
dlat = half / 111320.0; dlon = half / (111320.0 * math.cos(math.radians(lat)))
f = netfetch.Fetcher(stats_dir=os.path.join(os.path.expanduser('~/.cache/beamng-earth'), 'netstats'))
url = ("https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?"
       f"bbox={lon-dlon},{lat-dlat},{lon+dlon},{lat+dlat}&bboxSR=4326&imageSR=4326&size={PX},{int(round(PX * dlat / dlon))}&format=jpg&f=image")
r = f.get(url)
print(r.status, len(r.body), r.headers.get('content-type'))
open(out, 'wb').write(r.body)
