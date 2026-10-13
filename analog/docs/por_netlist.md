# POR Power‑On‑Reset Netlist and Simulation Results

## Netlist
*Status: derived*

.subckt POR VDD VSS POR_N
MS B VDD VSS VSS nch W=0.9 L=4
ML0 VDD VDD B VSS nnat W=1 L=25
MH B VDD h VSS nch W=0.42 L=32
MHS h POR_N VSS VSS nch W=1 L=0.5
MCB VDD B VDD VDD pch W=2 L=2
MP2 POR_N B VDD VDD pch W=2 L=0.5
MN2 POR_N B VSS VSS nnat W=1 L=25
MCO VSS POR_N VSS VSS nch W=4 L=4
.ends

## Simulation Results (PVT Sweep)
*Status: simulated functional*

Supply sweep results (static supply current in µA, release threshold, release time, reassert threshold, hysteresis):
- VDD=1.4 V: I_VDD_max=2.279 µA, release_threshold=1.132 V, release_time=80.83 µs, reassert_threshold=1.100 V, hysteresis=0.032 V
- VDD=3.3 V: I_VDD_max=14.531 µA, release_threshold=1.139 V, release_time=34.53 µs, reassert_threshold=1.091 V, hysteresis=0.048 V
- VDD=5.5 V: I_VDD_max=38.990 µA, release_threshold=1.146 V, release_time=20.83 µs, reassert_threshold=1.081 V, hysteresis=0.065 V

## Facts from the design database (generated, not written by the assistant)

**POR** - kind `por`, source: reference por.sp:POR
- Contents: 8 transistor(s) directly; ports VDD, VSS, POR_N
- Testbench checks: assert/release/re-assert on a supply ramp, threshold and hysteresis
- Functional simulation: 1.4V pass, 3.3V pass, 5.5V pass (generic models)
- Layout: not generated
