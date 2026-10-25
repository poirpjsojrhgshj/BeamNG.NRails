"""Blocking test client for earthd (framing from protocol.py)."""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import protocol  # noqa: E402


def stop_server(proc):
    """Stop an earthd a test started, its worker processes with it. On Windows terminate() kills the server alone:
    its spawned pool workers (each holds both ends of its task queue, so no EOF) lived on and kept earthfast.pyd
    locked. Safe to call twice (tearDown, then the cleanup a failed setUp leaves)."""
    kids = _children(proc.pid)
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            proc.terminate()
    try:
        proc.wait(10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    # its workers exit on their own within blockworker.PARENT_POLL_S, still writing to the session folder until then
    # (a test's temp folder removed under them: "Directory not empty", 1 run in 6)
    end = time.monotonic() + 10
    while kids and time.monotonic() < end:
        kids = [k for k in kids if os.path.exists(f"/proc/{k}")]
        if kids:
            time.sleep(0.1)


def _children(pid):
    """The pids of a process's children (Linux; [] elsewhere)."""
    try:
        with open(f"/proc/{pid}/task/{pid}/children") as f:
            return [int(k) for k in f.read().split()]
    except (OSError, ValueError):
        return []


class Client:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=5)
        self.dec = protocol.Decoder()
        self.pending = []
        self.log = []

    def close(self):
        self.sock.close()

    def send(self, msg):
        self.sock.sendall(protocol.encode(msg))

    def recv(self, timeout=60):
        end = time.monotonic() + timeout
        while not self.pending:
            left = end - time.monotonic()
            if left <= 0:
                raise TimeoutError("no message")
            self.sock.settimeout(left)
            data = self.sock.recv(65536)
            if not data:
                raise ConnectionError("server closed")
            self.pending += self.dec.feed(data)
        msg = self.pending.pop(0)
        self.log.append(msg)
        return msg

    def until(self, pred, timeout=120):
        """Receive until pred(msg); returns (match, everything received before it)."""
        seen, end = [], time.monotonic() + timeout
        while True:
            m = self.recv(max(0.1, end - time.monotonic()))
            if pred(m):
                return m, seen
            seen.append(m)

    def drain(self, quiet=0.3):
        """Everything that arrives until the server has been quiet for `quiet` s."""
        out = []
        while True:
            try:
                out.append(self.recv(quiet))
            except TimeoutError:
                return out


class FarState:
    """The mod's view of the far field (protocol 3), rebuilt from far_tile / far_swap / far_remove:
    a far_tile is held (loaded, hidden) until a far_swap shows it; far_remove evicts a held tile
    or removes a previous anchor's shown tile."""

    def __init__(self):
        self.tiles = {}     # (anchorId, key) -> far_tile msg, shown
        self.held = {}      # (anchorId, key) -> far_tile msg, sent but not swapped in yet
        self.order = []     # (kind, anchorId, key or far_swap msg) in arrival order
        self.swaps = []

    def switch(self, anchor_id):
        """commit_anchor: tiles held for another anchor are dropped."""
        self.held = {k: m for k, m in self.held.items() if k[0] == anchor_id}

    def apply(self, msgs):
        for m in msgs:
            t, aid = m["type"], m.get("anchorId")
            if t == "far_tile":
                ck = (aid, m["key"])
                assert ck not in self.tiles and ck not in self.held, m
                self.held[ck] = m
                self.order.append(("tile", aid, m["key"]))
            elif t == "far_swap":
                for k in m["remove"]:
                    assert (aid, k) in self.tiles, (m, k)
                    del self.tiles[(aid, k)]
                for k in m["add"]:
                    assert (aid, k) in self.held, (m, k)
                    self.tiles[(aid, k)] = self.held.pop((aid, k))
                self.order.append(("swap", aid, m))
                self.swaps.append(m)
            elif t == "far_retex":         # only for a tile shown or held (the server's rule)
                ck = (aid, m["key"])
                tile = self.tiles.get(ck) or self.held.get(ck)
                assert tile is not None, m
                tile["texture"] = m["texture"]
                self.order.append(("retex", aid, m["key"]))
            elif t == "far_remove":
                ck = (aid, m["key"])
                if ck in self.held:
                    del self.held[ck]
                    self.order.append(("evict", aid, m["key"]))
                else:
                    assert ck in self.tiles, m
                    del self.tiles[ck]
                    self.order.append(("remove", aid, m["key"]))

    def keys(self, anchor_id):
        return {k for a, k in self.tiles if a == anchor_id}
