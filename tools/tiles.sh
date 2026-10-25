#!/bin/sh
# tiles.sh <step> [from] [count]
cd "$(dirname "$0")/.."
python3 - "$@" <<'PY'
import sys, subprocess
a = sys.argv[1:] + ['0', '1']
code = f"PROBE_STEP='{a[0]}'; PROBE_FROM={a[1]}; PROBE_COUNT={a[2]}\n" + open('probes/p4_tiles.lua').read()
subprocess.run(['python3', 'tools/mcp.py', 'lua', code])
PY
