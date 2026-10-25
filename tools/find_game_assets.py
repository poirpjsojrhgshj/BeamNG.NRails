#!/usr/bin/env python3
"""EarthNRails dev tool: list texture paths inside the game's content zips whose path matches a regex.

    .venv\\Scripts\\python.exe tools\\find_game_assets.py "assets/materials/.*(gravel|ballast)" [game dir]
"""
import glob
import os
import re
import sys
import zipfile

pat = re.compile(sys.argv[1], re.I)
game = sys.argv[2] if len(sys.argv) > 2 else r"E:\Games\BeamNG.drive"
seen = set()
for zp in sorted(glob.glob(os.path.join(game, "content", "**", "*.zip"), recursive=True)):
    try:
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():
                if pat.search(n) and n not in seen:
                    seen.add(n)
                    print(f"{os.path.relpath(zp, game)} :: /{n}")
    except (OSError, zipfile.BadZipFile):
        pass
