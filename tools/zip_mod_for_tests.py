#!/usr/bin/env python3
"""NRails dev tool: zip mod/ (Lua sources + tests, no art) to build/mod_lua.zip, for running the Lua tests
under luajit on another machine. Read-only on the sources."""
import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
out = os.path.join(ROOT, "build", "mod_lua.zip")
os.makedirs(os.path.dirname(out), exist_ok=True)
n = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for dirpath, _, names in os.walk(os.path.join(ROOT, "mod")):
        for name in names:
            if name.endswith((".lua", ".mjs", ".js", ".json")) and "art" not in dirpath.split(os.sep):
                p = os.path.join(dirpath, name)
                z.write(p, os.path.relpath(p, ROOT))
                n += 1
print(out, n, "files")
