"""A sampling profiler for the running server (debugging): with BNGE_SAMPLE=<path> in the environment, a thread looks
at every other thread's Python stack every INTERVAL_S and, every DUMP_S, writes the most frequent functions (self, and
anywhere in the stack) per thread name to <path>. Cheap enough to leave on during a recorded session (~1 % of a core);
off without the variable. Wall-clock samples: a thread waiting on a lock or in C code that holds the GIL counts too.
"""
import collections
import os
import sys
import threading
import time

INTERVAL_S = 0.01
DUMP_S = 15.0
CPU_S = 1.0                 # the threads' CPU times read this often (a thread's last second before it ends is lost)
TOP = 120
IDLE_THREADS = ("malloc-trim", "watch-parent", "lag-watch", "parent-watch", "warm-read")   # (asleep in C)
IDLE = ("wait", "select", "poll", "_worker", "get", "acquire", "sleep", "accept", "recv", "read", "_run_once")


def _key(code):
    return f"{os.path.basename(code.co_filename)}:{code.co_name}"


def start(path):
    self_n = collections.Counter()
    cum_n = collections.Counter()
    by_thread = collections.Counter()
    cpu_by = collections.Counter()          # CPU seconds by thread name (the threads' own clocks, every CPU_S)
    cpu_last = {}
    names = {}

    tick = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100

    def thread_cpu():
        """Every live thread's CPU since the last call, by name (Linux: /proc/self/task/<tid>/stat)."""
        for th in threading.enumerate():
            nid = getattr(th, "native_id", None)
            try:
                with open(f"/proc/self/task/{nid}/stat") as f:
                    v = f.read().rsplit(")", 1)[1].split()
                c = (int(v[11]) + int(v[12])) / tick
            except (OSError, ValueError, IndexError):
                continue
            cpu_by[th.name.rstrip("0123456789_-")] += c - cpu_last.get(nid, 0.0)
            cpu_last[nid] = c

    def loop():
        last = last_cpu = time.monotonic()
        while True:
            time.sleep(INTERVAL_S)
            for tid, frame in sys._current_frames().items():
                if tid == threading.get_ident():     # (not the caller's: a worker's jobs run on its main thread)
                    continue
                if frame.f_code.co_name in IDLE and frame.f_back is not None and \
                        os.path.basename(frame.f_code.co_filename) in ("threading.py", "selectors.py", "queue.py",
                                                                       "thread.py", "base_events.py", "socket.py"):
                    continue                # an idle thread
                t = names.get(tid)
                if t is None:
                    t = names[tid] = next((th.name for th in threading.enumerate() if th.ident == tid), str(tid))
                tname = t.rstrip("0123456789_-")
                if tname in IDLE_THREADS:
                    continue
                by_thread[tname] += 1
                self_n[(tname, _key(frame.f_code))] += 1
                seen = set()
                f = frame
                while f is not None:
                    k = _key(f.f_code)
                    if k not in seen:
                        seen.add(k)
                        cum_n[(tname, k)] += 1
                    f = f.f_back
            now = time.monotonic()
            if now - last_cpu >= CPU_S:
                last_cpu = now
                thread_cpu()
            if now - last >= DUMP_S:
                last = now
                try:
                    with open(path + ".tmp", "w") as fh:
                        fh.write(f"CPU seconds by thread (process {time.process_time():.1f} s):\n")
                        for t, c in cpu_by.most_common():
                            if c >= 0.05:
                                fh.write(f"  {c:8.1f} s  {t}\n")
                        fh.write(f"\nsamples every {INTERVAL_S * 1000:.0f} ms; busy samples by thread:\n")
                        for t, n in by_thread.most_common():
                            fh.write(f"  {n * INTERVAL_S:8.1f} s  {t}\n")
                        fh.write("\nself (where the thread was):\n")
                        for (t, k), n in self_n.most_common(TOP):
                            fh.write(f"  {n * INTERVAL_S:8.1f} s  {t:12s} {k}\n")
                        fh.write("\ncumulative (anywhere in the stack):\n")
                        for (t, k), n in cum_n.most_common(TOP * 2):
                            fh.write(f"  {n * INTERVAL_S:8.1f} s  {t:12s} {k}\n")
                    os.replace(path + ".tmp", path)
                except OSError:
                    pass

    th = threading.Thread(target=loop, name="sampler", daemon=True)
    th.start()
    return th


def maybe_start(suffix=""):
    """suffix: added to the path (a worker process's own file: blockworker.init gives ".<pid>")."""
    path = os.environ.get("BNGE_SAMPLE")
    if path:
        start(path + suffix)
