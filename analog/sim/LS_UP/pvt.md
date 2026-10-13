# LS_UP: PVT check

**Result: PASS** at 9 corner/temperature point(s).

Models: sky130A 5 V devices (g5v0d10v5, Magic PCells)

## Supply sweep (nominal corner)

| Run | Supply (V) | Result | Measurements |
|---|---|---|---|
| level_shifter@1.4->3.3V | 3.3 | pass | static_I_vddh_in0_nA=0.017, static_I_vddh_in1_nA=0.021, static_I_vddl_in1_nA=0.001, tpd_in_rise_ns=0.3 |
| level_shifter@1.4->5.5V | 5.5 | pass | static_I_vddh_in0_nA=0.036, static_I_vddh_in1_nA=0.042, static_I_vddl_in1_nA=0.001, tpd_in_rise_ns=0.349 |
| level_shifter@1.8->3.3V | 3.3 | pass | static_I_vddh_in0_nA=0.017, static_I_vddh_in1_nA=0.021, static_I_vddl_in1_nA=0.002, tpd_in_rise_ns=0.213 |
| level_shifter@1.8->5.5V | 5.5 | pass | static_I_vddh_in0_nA=0.036, static_I_vddh_in1_nA=0.042, static_I_vddl_in1_nA=0.002, tpd_in_rise_ns=0.228 |
| level_shifter@3.3->3.3V | 3.3 | pass | static_I_vddh_in0_nA=0.017, static_I_vddh_in1_nA=0.021, static_I_vddl_in1_nA=0.003, tpd_in_rise_ns=0.053 |
| level_shifter@3.3->5.5V | 5.5 | pass | static_I_vddh_in0_nA=0.036, static_I_vddh_in1_nA=0.042, static_I_vddl_in1_nA=0.003, tpd_in_rise_ns=0.055 |

## Corners

| Corner | Temp (C) | 3.3 V | 5.5 V | Result |
|---|---|---|---|---|
| tt | -55 | pass | pass | pass |
| tt | 25 | pass | pass | pass |
| tt | 125 | pass | pass | pass |
| ff | -55 | pass | pass | pass |
| ff | 25 | pass | pass | pass |
| ff | 125 | pass | pass | pass |
| ss | -55 | pass | pass | pass |
| ss | 25 | pass | pass | pass |
| ss | 125 | pass | pass | pass |

_Run 2026-10-13 11:44:01._
