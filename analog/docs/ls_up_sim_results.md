# LS_UP Simulation Results

## Measured Performance
*Status: simulated functional*

Simulation of LS_UP level shifter across supply ranges (corner tt, 27 °C) passed all checks.
Measured static supply currents (nA) and input rise propagation delay (ns):
- VDDL=1.4 V, VDDH=3.3 V: I_VDDH_in0=0.017 nA, I_VDDH_in1=0.021 nA, I_VDDL_in1=0.001 nA, tpd_in_rise=0.30 ns
- VDDL=1.4 V, VDDH=5.5 V: I_VDDH_in0=0.036 nA, I_VDDH_in1=0.042 nA, I_VDDL_in1=0.001 nA, tpd_in_rise=0.35 ns
- VDDL=1.8 V, VDDH=3.3 V: I_VDDH_in0=0.017 nA, I_VDDH_in1=0.021 nA, I_VDDL_in1=0.002 nA, tpd_in_rise=0.21 ns
- VDDL=1.8 V, VDDH=5.5 V: I_VDDH_in0=0.036 nA, I_VDDH_in1=0.042 nA, I_VDDL_in1=0.002 nA, tpd_in_rise=0.23 ns
- VDDL=3.3 V, VDDH=3.3 V: I_VDDH_in0=0.017 nA, I_VDDH_in1=0.021 nA, I_VDDL_in1=0.003 nA, tpd_in_rise=0.053 ns
- VDDL=3.3 V, VDDH=5.5 V: I_VDDH_in0=0.036 nA, I_VDDH_in1=0.042 nA, I_VDDL_in1=0.003 nA, tpd_in_rise=0.055 ns

## Facts from the design database (generated, not written by the assistant)

**LS_UP** - kind `level_shifter`, source: reference level_shifter.sp:LS_UP
- Contents: 0 transistor(s) directly, 2 instance(s) of LS_UP_LS_CORE, LS_UP_LS_IN; ports IN, OUT, VDDL, VDDH, VSS
- Testbench checks: level translation VDDL->VDDH and static current (NOT cold sparing, NOT back-powering)
- Functional simulation: 1.4->3.3V pass, 1.4->5.5V pass, 1.8->3.3V pass, 1.8->5.5V pass, 3.3->3.3V pass, 3.3->5.5V pass (generic models)
- Layout: not generated
