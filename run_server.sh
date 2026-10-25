#!/usr/bin/env bash
# BeamNG.Earth: start the world server with the recommended options.
# Run it, then start BeamNG.drive. Keep this terminal open while you play.
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    echo "The server is not installed yet. Running the installer first..."
    python3 install.py || exit 1
fi
exec .venv/bin/python start.py "$@"
