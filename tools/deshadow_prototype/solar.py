import numpy as np, sys
def sun(lat, doy, hsolar):
    dec = np.radians(23.44) * np.sin(2 * np.pi * (284 + doy) / 365)
    H = np.radians(15 * (hsolar - 12)); la = np.radians(lat)
    el = np.arcsin(np.sin(la) * np.sin(dec) + np.cos(la) * np.cos(dec) * np.cos(H))
    az = np.arctan2(-np.sin(H) * np.cos(dec), np.cos(la) * np.sin(dec) - np.sin(la) * np.cos(dec) * np.cos(H))
    return np.degrees(az) % 360, np.degrees(el)
lat, az0, el0 = float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
D, Hh = np.meshgrid(np.arange(1, 366), np.arange(5, 19, 0.05), indexing="ij")
az, el = sun(lat, D, Hh)
err = np.hypot((az - az0 + 180) % 360 - 180, el - el0)
import datetime
for k in np.argsort(err.ravel())[:400:40]:
    d, h = np.unravel_index(k, err.shape)
    dt = datetime.date(2022, 1, 1) + datetime.timedelta(int(D[d, h]) - 1)
    print(dt.strftime("%b %d"), f"{Hh[d,h]:.2f} solar  az {az[d,h]:.1f} el {el[d,h]:.1f}")
# what NAIP-plausible window gives (Jun-Aug, 9-15 solar)
m = (D >= 152) & (D <= 243) & (Hh >= 9) & (Hh <= 15)
print("summer 9-15 solar: el range", el[m].min().round(1), el[m].max().round(1))
m2 = (D >= 152) & (D <= 243) & (Hh >= 8) & (Hh <= 9)
print("summer 8-9 solar: az", az[m2].min().round(1), az[m2].max().round(1), "el", el[m2].min().round(1), el[m2].max().round(1))
