#!/usr/bin/env python3
"""NRails: check the Windows/Linux runtime the companion server will use. Read-only; changes nothing.

    .venv\\Scripts\\python.exe tools\\check_env.py      (the interpreter start.py really uses)
    py tools\\check_env.py                               (any other interpreter, for comparison)

Checks: interpreter (version, 64-bit), server packages (numpy, Pillow+WebP, duckdb, fsspec, certifi), the native
module earthfast (.pyd/.so, loaded from server/ exactly as fast.py does), the .venv, the BeamNG user folder, the mod
copies in mods/db.json (upstream beamng_earth vs this fork), the cache junction and free disk space.
"""
import importlib
import importlib.util
import json
import os
import platform
import shutil
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "server")
sys.path.insert(0, ROOT)
sys.path.insert(0, SERVER)

OK, WARN, BAD = "[ OK ]", "[WARN]", "[FAIL]"
problems = []


def line(tag, msg):
    print(f"{tag} {msg}")
    if tag == BAD:
        problems.append(msg)


def section(t):
    print("\n== " + t + " " + "=" * max(0, 70 - len(t)))


section("Interpreter")
bits = struct.calcsize("P") * 8
line(OK if sys.version_info >= (3, 10) else BAD, f"Python {sys.version.split()[0]} ({bits}-bit) at {sys.executable}")
if bits != 64:
    line(BAD, "earthfast.pyd is 64-bit: a 32-bit Python cannot load it")
in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
line(OK if in_venv else WARN, f"virtual environment: {'yes, ' + sys.prefix if in_venv else 'no (system Python)'}")

section("Server packages (server/requirements.txt)")
REQ = [("numpy", True), ("PIL", True), ("duckdb", True), ("fsspec", True), ("certifi", False)]
for mod, needed in REQ:
    if importlib.util.find_spec(mod) is None:
        why = {"duckdb": "no Overture map data -> NO roads, NO rails, NO buildings (mapdata/overture.py)",
               "fsspec": "DuckDB cannot read remote parquet (rangeread.NetfetchFS)"}.get(mod, "required")
        line(BAD if needed else WARN, f"{mod}: MISSING - {why}")
        continue
    try:
        m = importlib.import_module(mod)
        line(OK, f"{mod} {getattr(m, '__version__', '?')}")
    except Exception as e:  # noqa: BLE001 - report any import failure
        line(BAD, f"{mod}: import error {type(e).__name__}: {e}")
try:
    from PIL import features
    line(OK if features.check("webp") else BAD, f"Pillow WebP support: {features.check('webp')}")
except Exception as e:  # noqa: BLE001
    line(WARN, f"Pillow features check failed: {e}")

section("Native module earthfast (native/earthfast -> server/earthfast.pyd|.abi3.so)")
try:
    import earthfast
    line(OK, f"earthfast {getattr(earthfast, 'VERSION', '?')} from {earthfast.__file__}")
    try:
        import fast  # the server's own wrapper (server/fast.py)
        line(OK, f"server/fast.py imports ({os.path.basename(fast.__file__)})")
    except Exception as e:  # noqa: BLE001
        line(BAD, f"server/fast.py does not import: {type(e).__name__}: {e}")
except Exception as e:  # noqa: BLE001
    line(BAD, f"earthfast does not load: {type(e).__name__}: {e}  (rebuild: python tools/build_native.py)")

section("Server modules the rail work will touch")
for name in ("cdae", "roads", "roadmesh", "mapdata", "overture", "navgraph"):
    try:
        importlib.import_module(name)
        line(OK, f"server/{name}.py imports")
    except Exception as e:  # noqa: BLE001
        line(BAD, f"server/{name}.py: {type(e).__name__}: {e}")

section("Fork install state")
try:
    import install
    venv_py = install.venv_python()
    line(OK if os.path.isfile(venv_py) else BAD, f".venv python: {venv_py} ({'present' if os.path.isfile(venv_py) else 'MISSING - run install.py'})")
    cfg = install.load_config()
    user_dir = cfg.get("user_dir")
    if not user_dir:
        found = install.candidate_user_dirs()
        user_dir = found[0] if found else None
        line(WARN, f"no {os.path.basename(install.CONFIG)} yet (install.py not run); detected user folder: {user_dir}")
    else:
        line(OK, f"user folder (from config): {user_dir}")
    if user_dir:
        try:
            with open(os.path.join(user_dir, "mods", "db.json"), encoding="utf-8") as f:
                mods = json.load(f).get("mods", {})
        except (OSError, ValueError):
            mods = {}
        up = mods.get(install.UPSTREAM_MOD_NAME, {})
        me = mods.get(install.MOD_NAME, {})
        up_on, me_on = up.get("active") is True, me.get("active") is True
        line(OK, f"mods/db.json: upstream '{install.UPSTREAM_MOD_NAME}' active={up.get('active')}, "
                 f"fork '{install.MOD_NAME}' active={me.get('active')}")
        if up_on and me_on:
            line(BAD, "both mods are active: they share /levels/beamng_earth and lua/ge/extensions/beamngEarth")
        mod_dir = os.path.join(user_dir, "mods", "unpacked", install.MOD_NAME)
        line(OK if os.path.isdir(mod_dir) else WARN, f"fork mod copy: {mod_dir} ({'present' if os.path.isdir(mod_dir) else 'not installed yet'})")
except Exception as e:  # noqa: BLE001
    line(WARN, f"install.py state not readable: {e}")

section("Cache & disk")
from nrails import paths  # noqa: E402  (server/paths.py: the one default the server, mapdata, airports and gravity use)
cache = paths.default_cache_dir()
if os.path.isdir(cache):
    real = os.path.realpath(cache)
    line(OK if os.path.splitdrive(real)[0].upper() != "C:" else WARN,
         f"active cache {cache} -> {real}" + ("" if real != cache else " (no junction: on this drive)"))
else:
    line(WARN, f"no cache folder yet at {cache}")
legacy = os.path.join(os.path.expanduser("~"), ".cache", "beamng-earth")
if os.path.normcase(legacy) != os.path.normcase(cache) and os.path.isdir(legacy):
    same = os.path.normcase(os.path.realpath(legacy)) == os.path.normcase(os.path.realpath(cache))
    line(OK if same else WARN, f"legacy path {legacy} -> {os.path.realpath(legacy)}"
         + (" (same target: one cache)" if same else " (a SECOND cache: no longer used by the fork)"))
for d in ("C:\\", os.path.splitdrive(ROOT)[0] + "\\") if os.name == "nt" else ("/",):
    try:
        free = shutil.disk_usage(d).free / 2**30
        line(OK if free > 20 else WARN, f"free space on {d}: {free:.1f} GiB")
    except OSError:
        pass

section("Summary")
print(f"{platform.system()} {platform.release()} | {len(problems)} blocking problem(s)")
for p in problems:
    print("  - " + p)
sys.exit(1 if problems else 0)
