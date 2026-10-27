#!/usr/bin/env python3
"""NRails dev tool: where the fork touches upstream's files, for merging a new BeamNG.Earth release.

Everything the fork adds lives in its own files (server/nrails/, mod .../beamngEarth/nrails.lua, the nrails_*.py
launchers, the Hub, the fork's key map and docs). Upstream's files only carry single lines marked "NRails hook".
This lists them, and with --check compares every upstream file with the `upstream` branch (the unmodified release):
any changed line in it that is not a hook line is reported (a change that would be lost or conflict at the next
merge), and the exit status is 1.

    python tools/nrails_hooks.py            the hook lines, by file
    python tools/nrails_hooks.py --check    ... and the upstream files' other changes (against branch `upstream`)

Merging a new release: commit it unmodified on branch `upstream` (git checkout upstream; copy the release over;
git commit), then `git checkout main; git merge upstream`; conflicts can only be on hook lines; run --check and the
tests (tools/run_tests.py, tools/run_lua_tests.py).
"""
import argparse
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MARK = "NRails hook"
# the fork's own files (paths relative to ROOT, prefixes): not upstream's, free to change
OWN = ("server/nrails/", "server/tests/test_nrails_", "mod/tests/test_nrails", "tools/", "build/", ".github/README.md",
       "mod/beamng_earth/lua/ge/extensions/beamngEarth/nrails",       # (nrails*.lua: every NRails game module)
       "mod/beamng_earth/lua/vehicle/extensions/nrails",              # (the rail guidance's vehicle side)
       "mod/beamng_earth/ui/ui-vue/mods/beamngEarth/NRails",          # (the map's railway parts)
       "mod/beamng_earth/ui/ui-vue/mods/beamngEarth/nrailsMap",
       "mod/beamng_earth/lua/ge/extensions/beamngEarth/nrails.lua",
       "mod/beamng_earth/lua/ge/extensions/beamngEarth/nrailsload.lua",
       "mod/beamng_earth/lua/ge/extensions/beamngEarth/nrailsswitch.lua",
       "mod/beamng_earth/lua/ge/extensions/beamngEarth/nrailsroute.lua",
       "mod/beamng_earth/lua/ge/extensions/beamngEarth/nrailsui.lua",
       "mod/beamng_earth/settings/inputmaps/keyboard_nrails.json",
       "mod/beamng_earth/lua/ge/extensions/core/input/actions/nrails.json",
       "mod/beamng_earth/core/input/actions/nrails.json",
       "mod/beamng_earth/levels/beamng_earth/art/shapes/beamngEarth/rails.materials.json",
       ".gitignore",           # (+ the Hub's settings file; no comment syntax for a mark there)
       "hub.py", "run_hub.bat", "run_hub.sh", "nrails_install.py", "nrails_launcher.py", "NRAILS.md", ".beamng_earthnrails.json",
       "NRAILS_VERSION", "LICENSE.NRails", "RELEASE_NOTES_NRAILS.md")


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout


def own(path):
    return any(path == o or path.startswith(o) for o in OWN)


def hook_lines():
    out = {}
    for line in git("grep", "-n", "-I", MARK, "--", ".").splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        path, n, text = parts
        if not own(path):
            out.setdefault(path, []).append((int(n), text.strip()))
    return out


def _block_lines(path):
    """Line numbers (1-based) of the file's "NRails hook begin" .. "NRails hook end" blocks (both included)."""
    out, inside = set(), False
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8", errors="replace") as f:
            for n, line in enumerate(f, 1):
                if MARK + " begin" in line:
                    inside = True
                if inside or MARK in line:
                    out.add(n)
                if MARK + " end" in line:
                    inside = False
    except OSError:
        pass
    return out


def stray_changes(base="upstream"):
    """{path: [diff lines]}: the lines of upstream's files (against base) changed outside the hooks: an added line
    must be a hook line (or in a hook block); a removed line only goes in a hunk that adds hook lines (the original a
    hook line replaced), at most as many as those."""
    out = {}
    for path in git("diff", "--name-only", base, "--").splitlines():
        if own(path):
            continue
        diff = git("diff", "-U0", base, "--", path).splitlines()
        if diff and not any(d.startswith("+++ ") for d in diff):
            out[path] = ["(binary or mode change)"]
            continue
        hooked = _block_lines(path)
        bad, hunk = [], None

        def close(h):
            if h is not None and len(h["minus"]) > h["hooks"]:
                bad.extend(h["minus"][h["hooks"]:] if h["hooks"] else h["minus"])
        for d in diff:
            if d.startswith("@@"):
                close(hunk)
                m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", d)
                hunk = {"n": int(m.group(1)) if m else 0, "hooks": 0, "minus": []}
            elif hunk is None or d.startswith("+++") or d.startswith("---"):
                continue
            elif d.startswith("+"):
                if hunk["n"] in hooked or MARK in d:
                    hunk["hooks"] += 1
                elif d[1:].strip():
                    bad.append(d)
                hunk["n"] += 1
            elif d.startswith("-") and d[1:].strip():
                hunk["minus"].append(d)
        close(hunk)
        if bad:
            out[path] = bad
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--base", default="upstream")
    a = ap.parse_args()
    hooks = hook_lines()
    n = sum(len(v) for v in hooks.values())
    print(f"{n} hook lines in {len(hooks)} upstream files")
    for path in sorted(hooks):
        print(path)
        for ln, text in hooks[path]:
            print(f"  {ln:5d}  {text[:150]}")
    if not a.check:
        return 0
    stray = stray_changes(a.base)
    if not stray:
        print(f"\nupstream files differ from '{a.base}' in hook lines only")
        return 0
    print(f"\n{len(stray)} upstream files with other changes (against '{a.base}'):")
    for path in sorted(stray):
        print(path)
        for d in stray[path][:20]:
            print(f"  {d[:150]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
