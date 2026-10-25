# Ball-drive findings (2026-10-10, v1.3.1, tools/ball_drive.py)

Real-physics test: the stock `ball` vehicle pushed toward a target velocity (40 m/s^2 max), the
user's car frozen meanwhile. The ball tops out ~40 m/s (rolling/air drag vs the push rate of
~4 pushes/s from Python), so "134 m/s" runs actually ran at ~38 m/s.

| run | where | speed | under L-2 | queue max | fps mean | min sim ratio | frames >50 ms |
|---|---|---|---|---|---|---|---|
| ball_40 | Kern River hills, uphill | 17.8 m/s mean | 100 % | 22 | 86 | 0.984 | 20 |
| ball_134 | Central Valley floor (35.40, -119.20), north | 38.2 m/s mean | **55.6 %** | **1725** | 65 | **0.756** | 99 |

ball_134 timeline: the import queue grows from the start (241 at 17 s, 645 at 33 s, ~1000 at
145 s, 1723 at 383 s) and never drains; from ~160 s the tile under the ball is L3/L4 (1-4 km
tiles) for long stretches (L3 457 samples, L4 259, L2 117), i.e. the visible ground is coarse
under the vehicle even though peekImport imports nearest-to-camera first. Likely cause: a swap
group runs only when ALL its adds are loaded, and a group replacing a coarse tile around the
player includes many far adds, so near L-2 tiles sit loaded-but-hidden behind them; plus the
supply/demand gap (~10 textured imports/s vs > 14/s needed at ~38 m/s on this flat farmland).
At ~18 m/s everything keeps up. So the v1.4 throughput work is needed already at highway speeds,
not only at 300 mph.

Other: after the rebase (t = 384 s) the queue restarts from ~800 with 502 old tiles kept; the
mod's status line showed a stale "Far field 50/50" (fixed in the server, not yet deployed).
