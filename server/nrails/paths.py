"""NRails: the one place that says where the download cache lives (standard library only).

Upstream's server takes its cache from --cache-dir (default ~/.cache/beamng-earth); nrails.hooks.boot hands it this
folder when the command line names none. Order:
  1. BNGE_CACHE_DIR (environment) - an explicit choice wins (e.g. a folder on another drive);
  2. Windows: %LOCALAPPDATA%\\beamng-earth (where the populated cache and launcher logs already are);
  3. elsewhere: ~/.cache/beamng-earth (upstream's default).
A junction/symlink at that path (to keep C: free) is resolved to its target once, here: on this PC (2026-10-24) every
os.replace through the %LOCALAPPDATA%\\beamng-earth junction failed with WinError 3 while the same rename on the target
(K:) or through ~/.cache's junction worked; the cache writes every file as tmp + os.replace (staging.py).
"""
import os

ENV = "BNGE_CACHE_DIR"


def default_cache_dir():
    env = os.environ.get(ENV, "").strip()
    if env:
        path = os.path.abspath(os.path.expanduser(env))
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        path = os.path.join(base, "beamng-earth")
    else:
        path = os.path.join(os.path.expanduser("~"), ".cache", "beamng-earth")
    return resolve(path)


def resolve(path):
    """path with its junctions / symlinks followed to the real folder. os.path.realpath alone is not enough: in the
    player's own desktop session it returned the %LOCALAPPDATA% junction unresolved (GetFinalPathNameByHandle failing on
    it, 2026-10-24: the server logged the junction path and wrote through it), so the links are read with readlink
    first, hop by hop."""
    p = os.path.abspath(path)
    for _ in range(16):                     # (a loop of links ends here)
        try:
            is_link = os.path.islink(p) or (hasattr(os.path, "isjunction") and os.path.isjunction(p))
            if not is_link:
                break
            target = os.readlink(p)
        except (OSError, ValueError):
            break
        if target.startswith("\\\\?\\UNC\\"):
            target = "\\\\" + target[8:]
        elif target.startswith("\\\\?\\") or target.startswith("\\??\\"):
            target = target[4:]
        p = os.path.normpath(target if os.path.isabs(target) else os.path.join(os.path.dirname(p), target))
    try:
        return os.path.realpath(p)
    except OSError:
        return p
