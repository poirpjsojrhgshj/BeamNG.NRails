#!/usr/bin/env python3
"""Drive OBS Studio (the Flatpak) over obs-websocket 5, so recordings start and stop without opening and closing OBS.

  python3 tools/obsctl.py up             # OBS running, minimized to the tray (started when it is not)
  python3 tools/obsctl.py start          # start recording
  python3 tools/obsctl.py stop           # stop; prints the recording's path
  python3 tools/obsctl.py status

The websocket server and its password are in OBS's own config (plugin_config/obs-websocket/config.json, read here;
the password is never printed). Only the Python standard library: a minimal RFC 6455 client for the few requests.
"""
import base64
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import time

OBS_APP = "com.obsproject.Studio"
CONFIG = os.path.expanduser(f"~/.var/app/{OBS_APP}/config/obs-studio/plugin_config/obs-websocket/config.json")
HOST = "127.0.0.1"


class ObsError(RuntimeError):
    pass


def _config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


class Obs:
    """One obs-websocket 5 session (identified, requests answered in order)."""

    def __init__(self, timeout=5.0):
        cfg = _config()
        self.sock = socket.create_connection((HOST, int(cfg.get("server_port", 4455))), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET / HTTP/1.1\r\nHost: {HOST}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
                           "Sec-WebSocket-Protocol: obswebsocket.json\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ObsError("websocket handshake: connection closed")
            head += chunk
        head, self._buf = head.split(b"\r\n\r\n", 1)
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ObsError("websocket handshake refused")
        hello = self._recv()["d"]
        ident = {"rpcVersion": 1, "eventSubscriptions": 0}
        auth = hello.get("authentication")
        if auth:
            pw = cfg.get("server_password", "")
            secret = base64.b64encode(hashlib.sha256((pw + auth["salt"]).encode()).digest()).decode()
            ident["authentication"] = base64.b64encode(
                hashlib.sha256((secret + auth["challenge"]).encode()).digest()).decode()
        self._send({"op": 1, "d": ident})
        if self._recv().get("op") != 2:
            raise ObsError("obs-websocket did not identify us (password?)")
        self._n = 0

    def _send(self, msg):
        data = json.dumps(msg).encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                                bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        while len(self._buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ObsError("websocket closed")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _recv(self):
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            op = b0 & 0x0F
            if op == 8:
                raise ObsError(f"websocket closed by OBS: {payload[2:].decode(errors='replace')}")
            if op == 1:
                return json.loads(payload)

    def request(self, kind, data=None):
        self._n += 1
        rid = str(self._n)
        self._send({"op": 6, "d": {"requestType": kind, "requestId": rid, "requestData": data or {}}})
        while True:
            m = self._recv()
            if m.get("op") == 7 and m["d"].get("requestId") == rid:
                st = m["d"]["requestStatus"]
                if not st.get("result"):
                    raise ObsError(f"{kind}: {st.get('comment') or st.get('code')}")
                return m["d"].get("responseData") or {}

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def running():
    r = subprocess.run(["pgrep", "-x", "obs"], capture_output=True, text=True)
    return bool(r.stdout.split())


def connect(wait_s=0.0):
    """An Obs session, retrying for wait_s seconds while OBS starts."""
    end = time.time() + wait_s
    while True:
        try:
            return Obs()
        except (OSError, ObsError):
            if time.time() >= end:
                raise
            time.sleep(1)


def up(wait_s=30.0):
    """OBS running with its websocket answering (started minimized to the tray when it is not running)."""
    if not running():
        subprocess.Popen(["flatpak", "run", OBS_APP, "--minimize-to-tray", "--disable-shutdown-check"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                         start_new_session=True)
    return connect(wait_s)


def start():
    o = up()
    try:
        if not o.request("GetRecordStatus").get("outputActive"):
            o.request("StartRecord")
        return True
    finally:
        o.close()


def stop():
    """Stop recording; the recording's path (None when nothing was recording)."""
    o = connect()
    try:
        if not o.request("GetRecordStatus").get("outputActive"):
            return None
        return o.request("StopRecord").get("outputPath")
    finally:
        o.close()


def status():
    o = connect()
    try:
        return o.request("GetRecordStatus")
    finally:
        o.close()


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    if cmd == "up":
        up().close()
        print("OBS up")
    elif cmd == "start":
        start()
        print("recording")
    elif cmd == "stop":
        print(stop() or "not recording")
    elif cmd == "status":
        print(json.dumps(status()))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
