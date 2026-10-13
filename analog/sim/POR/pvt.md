# POR: PVT check

**Result: PASS** at 9 corner/temperature point(s).

Models: sky130A 5 V devices (g5v0d10v5, Magic PCells)

## Supply sweep (nominal corner)

| Run | Supply (V) | Result | Measurements |
|---|---|---|---|
| por@1.4V | 1.4 | pass | hysteresis_v=0.032, reassert_threshold_v=1.1, release_threshold_v=1.13, release_time_us=80.8 |
| por@3.3V | 3.3 | pass | hysteresis_v=0.048, reassert_threshold_v=1.09, release_threshold_v=1.14, release_time_us=34.5 |
| por@5.5V | 5.5 | pass | hysteresis_v=0.065, reassert_threshold_v=1.08, release_threshold_v=1.15, release_time_us=20.8 |

## Corners

| Corner | Temp (C) | 1.4 V | 3.3 V | 5.5 V | Result |
|---|---|---|---|---|---|
| tt | -55 | pass | pass | pass | pass |
| tt | 25 | pass | pass | pass | pass |
| tt | 125 | pass | pass | pass | pass |
| ff | -55 | pass | pass | pass | pass |
| ff | 25 | pass | pass | pass | pass |
| ff | 125 | pass | pass | pass | pass |
| ss | -55 | pass | pass | pass | pass |
| ss | 25 | pass | pass | pass | pass |
| ss | 125 | pass | pass | pass | pass |

_Run 2026-10-13 11:34:30._
