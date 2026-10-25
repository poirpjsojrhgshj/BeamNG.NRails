#!/bin/sh
# BeamNG.EarthNRails Hub (Linux): install, start the server, start the game, settings.
cd "$(dirname "$0")" || exit 1
if [ -x .venv/bin/python ]; then exec .venv/bin/python hub.py "$@"; fi
exec python3 hub.py "$@"
