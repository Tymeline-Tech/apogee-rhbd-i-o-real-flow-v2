# POR Simulation Results

## Measured Performance
*Status: simulated functional*

Simulation of POR power‑on‑reset across supply voltages (corner tt, 27 °C) passed all checks.
Measured performance:
- VDD=1.4 V: supply current I_VDD_max=2.279 µA, release threshold V_release=1.132 V, release time t_release=80.83 µs, re‑assert threshold V_reassert=1.100 V, hysteresis ΔV=0.032 V
- VDD=3.3 V: I_VDD_max=14.531 µA, V_release=1.139 V, t_release=34.53 µs, V_reassert=1.091 V, ΔV=0.048 V
- VDD=5.5 V: I_VDD_max=38.990 µA, V_release=1.146 V, t_release=20.83 µs, V_reassert=1.081 V, ΔV=0.065 V

## Facts from the design database (generated, not written by the assistant)

**POR** - kind `por`, source: reference por.sp:POR
- Contents: 8 transistor(s) directly; ports VDD, VSS, POR_N
- Testbench checks: assert/release/re-assert on a supply ramp, threshold and hysteresis
- Functional simulation: 1.4V pass, 3.3V pass, 5.5V pass (generic models)
- Layout: not generated
