#!/usr/bin/env python3
"""Record the game's own frames to a video, without screen capture (2026-10-15: on the user's KDE Wayland
desktop every screen capture, OBS included, needs a permission dialog answered at the screen, and the game is a
native Wayland window, so nothing can grab it unattended).

The game takes a screenshot (createScreenshot2, half resolution, JPEG) every 1/fps s of wall time into its
temp folder, stamping each; stop() turns them into an H.264 video with each frame shown for its real duration
(ffmpeg's concat demuxer), so the video runs at real speed. Capturing costs the game ~15 ms a frame at 15 fps:
frame times measured while recording are not the game's (record visual runs, not performance runs).

    import gamerec
    rec = gamerec.start(fps=15)          # needs the game's MCP server (tools/mcp.py)
    ...
    video = rec.stop("out/drive.mp4")    # the file, or None

    python3 tools/gamerec.py --out ~/Videos/BeamNG.Earth/run1 --seconds 60    # record for a while
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp  # noqa: E402

USER_DIR = os.path.expanduser("~/.local/share/BeamNG/BeamNG.drive/current")
VFS_ROOT = "/temp/bngerec"

START_LUA = r"""
if BNGE_GREC and BNGE_GREC.proxy then pcall(function() BNGE_GREC.proxy:submitEventSinks({}, {}) end) end
BNGE_GREC = { n = 0, last = -1, t = {}, dir = %(dir)s, every = %(every)f, scale = %(scale)f, on = true }
local P = BNGE_GREC
FS:directoryCreate(P.dir)
-- our jobs are not the screenshot module's: its callbacks logged "unknown job id" three times a frame (thousands
-- of log lines, the log's 15000 were full before a drive ended); those of our ids are dropped while recording
P.ids = {}
if screenshot and not BNGE_GREC_ORIG then
  BNGE_GREC_ORIG = { screenshot.screenshotTaken, screenshot.screenshotProgress, screenshot.screenshotSaved }
  local names = { 'screenshotTaken', 'screenshotProgress', 'screenshotSaved' }
  for k, name in ipairs(names) do
    local orig = BNGE_GREC_ORIG[k]
    screenshot[name] = function(id, ...)
      local R = BNGE_GREC
      if R and R.ids[id] then return end
      return orig(id, ...)
    end
  end
end
local sink = {}
function sink:onPreRender()
  if not P.on then return end
  local t = os.clockhp()
  if t - P.last < P.every then return end
  P.last = t
  P.n = P.n + 1
  P.t[P.n] = t
  local id = createScreenshot2({ filename = string.format('%%s/f_%%06d', P.dir, P.n), writeJPG = true, superSampling = 1,
    tiles = 1, overlap = 0, rescaleFactor = P.scale, bufferType = 'color', objectTypeWhitelistMask = 0,
    objectTypeBlacklistMask = 0, shadowCasterObjectTypeWhitelistMask = 0, shadowCasterObjectTypeBlacklistMask = 0 })
  if id then P.ids[id] = true end
end
P.proxy = newExtensionProxy(nil, 'bngeGameRec')
P.proxy:submitEventSinks({ sink }, {})
return 'recording'
"""

STOP_LUA = r"""
local P = BNGE_GREC
if not P then return '[]' end
P.on = false
pcall(function() P.proxy:submitEventSinks({}, {}) end)
P.proxy = nil
return jsonEncode(P.t)
"""


class Recording:
    def __init__(self, run, fps):
        self.run, self.fps = run, fps
        self.dir = os.path.join(USER_DIR, VFS_ROOT.lstrip("/"), run)

    def stop(self, out_path, keep_frames=False):
        """Stop capturing and write the video to out_path (mp4). Returns out_path, or None without frames."""
        raw = mcp.call("run_lua", {"code": STOP_LUA}).strip()
        try:
            stamps = json.loads(raw)
        except ValueError:
            stamps = []
        if isinstance(stamps, dict):            # (a Lua array of one element can come back as an object)
            stamps = [stamps[k] for k in sorted(stamps, key=int)]
        time.sleep(2.0)                         # the last screenshots are written asynchronously
        frames = []
        for i, t in enumerate(stamps, 1):
            f = os.path.join(self.dir, f"f_{i:06d}.jpg")
            if os.path.exists(f):
                frames.append((f, float(t)))
        if len(frames) < 2:
            return None
        lst = os.path.join(self.dir, "frames.txt")
        with open(lst, "w") as fh:
            for k, (f, t) in enumerate(frames):
                d = (frames[k + 1][1] - t) if k + 1 < len(frames) else 1.0 / self.fps
                fh.write(f"file '{f}'\nduration {max(d, 0.001):.4f}\n")
            fh.write(f"file '{frames[-1][0]}'\n")        # (the concat demuxer drops the last duration otherwise)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        subprocess.run(["nice", "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-vf", "fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast",
                        "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path], check=True)
        if not keep_frames:
            shutil.rmtree(self.dir, ignore_errors=True)
        return out_path


def start(fps=15.0, scale=0.5, run=None):
    """Start capturing the game's frames (fps per second of wall time, at scale of the window's size)."""
    run = run or time.strftime("%Y%m%d-%H%M%S")
    mcp.quiet_ui()
    res = mcp.call("run_lua", {"code": START_LUA % {"dir": json.dumps(f"{VFS_ROOT}/{run}"), "every": 1.0 / fps,
                                                   "scale": scale}})
    if "recording" not in res:
        raise RuntimeError(f"game recorder did not start: {res[:200]}")
    return Recording(run, fps)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, help="folder: drive.mp4 (and drive_small.mp4) go there")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--fps", type=float, default=15.0)
    a = ap.parse_args()
    rec = start(a.fps)
    time.sleep(a.seconds)
    video = rec.stop(os.path.join(a.out, "drive.mp4"))
    print("video:", video)


if __name__ == "__main__":
    main()
