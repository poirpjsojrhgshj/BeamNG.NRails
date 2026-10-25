"""One process does a piece of work while the server's other processes wait for its result (2026-10-23).

The server's processes (the main one, the two terrain-block processes, the far-tile, road-tile and far-building
workers) all start on a new place at once and need the same things: a fresh place's network log on a PC showed 51 %
of the Overture requests and 72 % of the OpenStreetMap ones repeated by another process within ~0.1 s (146 of ~400 MB),
and every process planned the same road cells (plancache.py). The in-process locks (threads) never saw each other.

once(lock, ready, ...) before such a piece of work, whose result lands in a file: ready() returns the result when the
file is there. A lock file (O_EXCL) says who does it; the others poll ready() while it exists. The lock holds how
urgent its holder is (the request kind's rank, then the process's PRIORITY, the niceness the server gave it): a
process waits only for a holder at least as urgent as itself, so the terrain block under the car never waits behind
a background fetch or a road tile's process below it. A lock older than STALE_S (its process died) is taken over; a
wait longer than wait_s does the work itself.
"""
import os
import time

STALE_S = 120.0
POLL_S = 0.05
PRIORITY = 0                # this process's niceness above the server's (blockworker.init's nice)
KIND_RANK = {"urgent": 0, "demand": 1, "prefetch": 2, "background": 3, "predownload": 4}


def _rank(kind):
    return KIND_RANK.get(kind, 1), int(PRIORITY)


def take(lock, kind="demand"):
    """True when this process now holds lock (or no lock file can be made: then it does the work unlocked); False
    when another process holds it (a stale lock is taken over)."""
    for _ in range(2):
        try:
            os.makedirs(os.path.dirname(lock), exist_ok=True)
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock) > STALE_S:
                    os.remove(lock)         # its process died doing it
                    continue
            except OSError:
                continue                    # (released meanwhile)
            return False
        except OSError:
            return True
        try:
            os.write(fd, ("%d %d" % _rank(kind)).encode())
        finally:
            os.close(fd)
        return True
    return False


def _less_urgent(lock, kind):
    """Whether lock's holder is less urgent than this process asking for kind."""
    try:
        with open(lock, "rb") as fh:
            held = fh.read().split()
        return (int(held[0]), int(held[1])) > _rank(kind)
    except (OSError, ValueError, IndexError):
        return False                        # (released, or being written)


def once(lock, ready, wait_s, kind="demand", on_wait=None):
    """(result, False): ready() gave it (at once or after waiting for another process); (None, True): this process
    does the work (release(lock) after the result is written); (None, False): do it without the lock (a wait past
    wait_s, or a less urgent holder). on_wait(): called once when this process starts waiting."""
    got = ready()
    if got is not None:
        return got, False
    t0 = time.monotonic()
    waited = False
    while True:
        if take(lock, kind):
            got = ready()                   # (written by the process whose lock we just followed)
            if got is not None:
                release(lock)
                return got, False
            return None, True
        if _less_urgent(lock, kind):
            return None, False              # do it here, not wait
        if not waited:
            waited = True
            if on_wait is not None:
                on_wait()
        if time.monotonic() - t0 > wait_s:
            return None, False
        time.sleep(POLL_S)
        got = ready()
        if got is not None:
            return got, False


def release(lock):
    try:
        os.remove(lock)
    except OSError:
        pass
