#!/usr/bin/env python3
"""Run a command while OBS records the screen (tools/autodrive_perf.py's OBS handling: only when OBS is not already
open, only our own instance stopped, audio dropped, a small copy for sending). The video lands in --out.

  python3 tools/record.py --out ~/Videos/BeamNG.Earth/run1 -- python3 tools/drive.py --out ... --speed 45 --km 15
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import autodrive_perf as ad  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    os.makedirs(a.out, exist_ok=True)
    started = ad.obs_start()
    try:
        rc = subprocess.call(cmd)
    finally:
        video = ad.obs_stop(started, os.path.join(a.out, "drive.mp4")) if started else None
        if video:
            print("video:", video, "small:", ad.share_copy(video))
    sys.exit(rc)


if __name__ == "__main__":
    main()
