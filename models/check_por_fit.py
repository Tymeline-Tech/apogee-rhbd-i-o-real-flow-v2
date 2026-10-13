#!/usr/bin/env python3
"""Verify POR.va threshold/current equations against Epic 1 extracted table."""

from __future__ import annotations

# Fitted coefficients (must match models/por.va)
V_REL_C0, V_REL_C1 = 1.12741093, 0.00340855
V_REA_C0, V_REA_C1 = 1.10641489, -0.00463183
I_C0, I_C1, I_C2 = -1.48727856, 1.09580173, 1.13885518

# Epic 1 measurements (analog/sim/por.json, tt @ 27 C)
EPIC1 = [
    # vdd, v_release, v_reassert, hyst, i_uA, t_release_us
    (1.4, 1.132, 1.100, 0.032, 2.279, 80.83),
    (3.3, 1.139, 1.091, 0.048, 14.531, 34.53),
    (5.5, 1.146, 1.081, 0.065, 38.990, 20.83),
]


def main() -> int:
    ok = True
    print("POR equation fit vs Epic 1")
    print(
        f"{'VDD':>6} {'Vrel_m':>8} {'Vrel_f':>8} {'Vrea_m':>8} {'Vrea_f':>8} "
        f"{'I_m':>8} {'I_f':>8} {'errV':>8} {'errI':>8}"
    )
    for vdd, vrel_m, vrea_m, hyst_m, i_m, _t in EPIC1:
        vrel_f = V_REL_C0 + V_REL_C1 * vdd
        vrea_f = V_REA_C0 + V_REA_C1 * vdd
        i_f = I_C0 + I_C1 * vdd + I_C2 * vdd * vdd
        hyst_f = vrel_f - vrea_f
        err_v = max(abs(vrel_f - vrel_m), abs(vrea_f - vrea_m))
        err_i = abs(i_f - i_m)
        print(
            f"{vdd:6.1f} {vrel_m:8.3f} {vrel_f:8.3f} {vrea_m:8.3f} {vrea_f:8.3f} "
            f"{i_m:8.3f} {i_f:8.3f} {err_v:8.3e} {err_i:8.3e}"
        )
        if err_v > 1e-3:
            ok = False
        if err_i > 1e-3:
            ok = False
        if abs(hyst_f - hyst_m) > 2e-3:
            ok = False
        # Release time on a 0->VDD / 100 us ramp is Vrel/VDD * 100 us
        t_pred = 100.0 * vrel_m / vdd
        if abs(t_pred - _t) > 1.0:
            ok = False
    print("FIT_RESULT=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
