#!/bin/sh
# probe.sh <N> <step>  -> runs probes/p3_procmesh.lua with params
cd "$(dirname "$0")/.."
python3 - "$@" <<'PY'
import sys, subprocess
n, step = sys.argv[1], sys.argv[2]
code = f"PROBE_N={n}; PROBE_STEP='{step}'\n" + open('probes/p3_procmesh.lua').read()
subprocess.run(['python3', 'tools/mcp.py', 'lua', code])
PY
