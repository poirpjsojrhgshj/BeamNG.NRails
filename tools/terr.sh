#!/bin/sh
cd "$(dirname "$0")/.."
python3 - "$@" <<'PY'
import sys, subprocess
code = f"PROBE_STEP='{sys.argv[1]}'; PROBE_N={sys.argv[2] if len(sys.argv)>2 else 256}\n" + open('probes/p7_terrain.lua').read()
subprocess.run(['timeout', '90', 'python3', 'tools/mcp.py', 'lua', code])
PY
