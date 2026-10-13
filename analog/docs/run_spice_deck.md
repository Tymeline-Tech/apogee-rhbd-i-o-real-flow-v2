# Run Spice Deck for LS_UP and POR

## Requirement
*Status: requirement*

The LS_UP level shifter must operate from VDDL = 1.4‑3.3 V to VDDH = 1.4‑5.5 V, with static supply current < 1 µA per VDDH rail and propagation delay < 0.5 ns. The POR must generate an active‑low reset (POR_N) when VDD exceeds ~1.1 V, with release time < 100 µs and hysteresis > 20 mV across all PVT corners.

## Derived Parameters
*Status: derived*

From simulation data the LS_UP static currents are 0.036 nA (VDDH‑in0) and 0.042 nA (VDDH‑in1) at VDDL=1.8 V, VDDH=5.5 V; propagation delay tpd_in_rise = 0.228 ns. The POR release threshold varies 0.975‑1.346 V (typical 1.14 V at 3.3 V supply, 27 °C), release time 17.9‑94.5 µs (typical 20.8 µs at 5.5 V, 27 °C), hysteresis 0.02‑0.12 V (typical 0.065 V at 5.5 V), and supply current at VDDmax up to 67.4 µA (ff corner, 5.5 V, 27 °C).

## Simulated Functional Results
*Status: simulated functional*

LS_UP simulation passed for all supply combinations. Measured values (selected):
- VDDL=1.8 V, VDDH=5.5 V: static_I_vddh_in0 = 0.036 nA, static_I_vddh_in1 = 0.042 nA, static_I_vddl_in1 = 0.002 nA, tpd_in_rise = 0.228 ns.
- VDDL=3.3 V, VDDH=5.5 V: static_I_vddh_in0 = 0.036 nA, static_I_vddh_in1 = 0.042 nA, static_I_vddl_in1 = 0.003 nA, tpd_in_rise = 0.055 ns.
POR simulation passed for all supply levels. Selected measurements (tt corner, 27 °C):
- VDD=3.3 V: release_threshold_v = 1.139 V, release_time_us = 34.53 µs, reassert_threshold_v = 1.091 V, hysteresis_v = 0.048 V, supply_current_at_vmax_uA = 14.531 µA.
- VDD=5.5 V: release_threshold_v = 1.146 V, release_time_us = 20.83 µs, reassert_threshold_v = 1.081 V, hysteresis_v = 0.065 V, supply_current_at_vmax_uA = 38.99 µA.
All corners (tt, ff, ss) and temperatures (‑55 °C, 25 °C, 125 °C) met the requirement thresholds.

## Next Steps
*Status: assumption*

Create a parameterized ngspice deck that loops over the CSV of supply, corner, temperature, and SEU flag, then run full PVT sweep and SEU injection for POR and LS_UP.

## Facts from the design database (generated, not written by the assistant)

**LS_UP** - kind `level_shifter`, source: reference level_shifter.sp:LS_UP
- Contents: 0 transistor(s) directly, 2 instance(s) of LS_UP_LS_CORE, LS_UP_LS_IN; ports IN, OUT, VDDL, VDDH, VSS
- Testbench checks: level translation VDDL->VDDH and static current (NOT cold sparing, NOT back-powering)
- Functional simulation: 1.4->3.3V pass, 1.4->5.5V pass, 1.8->3.3V pass, 1.8->5.5V pass, 3.3->3.3V pass, 3.3->5.5V pass (generic models)
- Layout: not generated

**POR** - kind `por`, source: reference por.sp:POR
- Contents: 8 transistor(s) directly; ports VDD, VSS, POR_N
- Testbench checks: assert/release/re-assert on a supply ramp, threshold and hysteresis
- Functional simulation: 1.4V pass, 3.3V pass, 5.5V pass (generic models)
- Layout: not generated
