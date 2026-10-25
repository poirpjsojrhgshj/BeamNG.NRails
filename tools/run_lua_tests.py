#!/usr/bin/env python3
"""NRails: run the mod's Lua tests (mod/tests/test_*.lua, written for `luajit mod/tests/test_x.lua`) under the
LuaJIT that the `lupa` package bundles, for Windows machines without a luajit binary.

    python -m pip install --target build\\pylibs lupa        (once)
    .venv\\Scripts\\python.exe tools\\run_lua_tests.py [test_roads ...]

Each file runs in a fresh LuaRuntime with arg[0] set to its path; os.exit(code) ends that file only.
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "build", "pylibs"))
try:
    from lupa import luajit21 as lupa_rt
except ImportError:
    try:
        import lupa as lupa_rt
    except ImportError:
        sys.exit("lupa is missing: python -m pip install --target build\\pylibs lupa")


class _Exit(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


EXIT = "__nrails_exit__:"


def run(path):
    lua = lupa_rt.LuaRuntime(unpack_returned_tuples=True)
    # os.exit ends this file only: an error carrying the code, caught below
    lua.execute("os.exit = function(c) if c == nil or c == true then c = 0 elseif c == false then c = 1 end "
                f"error('{EXIT}' .. tostring(c), 0) end")
    lua.execute(f"arg = {{ [0] = [[{path}]] }}")
    # a wall clock for stopwatch.lua (it falls back to os.clock: process CPU time, ~16 ms steps on Windows, which made
    # the tests that wait "more than 0 ms" flaky): socket.gettime as plain luajit with LuaSocket has it
    import time
    lua.globals().package.preload["socket"] = lua.eval("function(f) return function() return { gettime = f } end end")(
        time.perf_counter)
    try:
        lua.execute(f"dofile([[{path}]])")
        return 0
    except lupa_rt.LuaError as e:
        msg = str(e)
        if EXIT in msg:
            return int(msg.split(EXIT, 1)[1].split()[0])
        print(f"ERROR {os.path.basename(path)}: {msg[:400]}")
        return 2


def main():
    args = sys.argv[1:]
    root = ROOT
    if args[:1] == ["--root"]:
        root, args = args[1], args[2:]
    want = set(args)
    files = sorted(glob.glob(os.path.join(root, "mod", "tests", "test_*.lua")))
    failed = []
    for p in files:
        name = os.path.splitext(os.path.basename(p))[0]
        if want and name not in want:
            continue
        code = run(p.replace("\\", "/"))
        if code != 0:
            failed.append(name)
    print(f"\n{len(failed)} failing file(s)" + (": " + ", ".join(failed) if failed else ""))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
