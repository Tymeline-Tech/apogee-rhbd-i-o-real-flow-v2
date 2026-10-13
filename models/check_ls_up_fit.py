#!/usr/bin/env python3
"""Verify LS_UP.va delay/current equations against Epic 1 extracted table."""

from __future__ import annotations

# Fitted coefficients (must match models/ls_up.va)
TPD_C = (-0.25351579, 1.24445053, -0.80139979, 0.02409569, -0.13101531, 0.17984842)
I0_A, I0_B = -0.0115, 0.008636
I1_A, I1_B = -0.0105, 0.009545
IL_K = 0.00091

# Epic 1 measurements (analog/sim/LS_UP.json, tt @ 27 C)
EPIC1 = [
    # vddl, vddh, tpd_ns, i_vddh0_nA, i_vddh1_nA, i_vddl1_nA
    (1.4, 3.3, 0.300, 0.017, 0.021, 0.001),
    (1.4, 5.5, 0.349, 0.036, 0.042, 0.001),
    (1.8, 3.3, 0.213, 0.017, 0.021, 0.002),
    (1.8, 5.5, 0.228, 0.036, 0.042, 0.002),
    (3.3, 3.3, 0.053, 0.017, 0.021, 0.003),
    (3.3, 5.5, 0.055, 0.036, 0.042, 0.003),
]


def tpd_ns(vddl: float, vddh: float) -> float:
    c0, c1, c2, c3, c4, c5 = TPD_C
    return (
        c0
        + c1 / vddl
        + c2 / (vddl * vddl)
        + c3 * vddh
        + c4 * vddh / vddl
        + c5 * vddh / (vddl * vddl)
    )


def main() -> int:
    ok = True
    print("LS_UP equation fit vs Epic 1")
    print(f"{'VDDL':>6} {'VDDH':>6} {'tpd_m':>8} {'tpd_f':>8} {'err':>8} "
          f"{'I0_m':>7} {'I0_f':>7} {'I1_m':>7} {'I1_f':>7}")
    for vddl, vddh, tpd_m, i0_m, i1_m, il_m in EPIC1:
        tpd_f = tpd_ns(vddl, vddh)
        i0_f = I0_A + I0_B * vddh
        i1_f = I1_A + I1_B * vddh
        il_f = IL_K * vddl
        terr = abs(tpd_f - tpd_m)
        print(
            f"{vddl:6.1f} {vddh:6.1f} {tpd_m:8.3f} {tpd_f:8.3f} {terr:8.3e} "
            f"{i0_m:7.3f} {i0_f:7.3f} {i1_m:7.3f} {i1_f:7.3f}"
        )
        if terr > 1e-6:
            ok = False
        if abs(i0_f - i0_m) > 0.002 or abs(i1_f - i1_m) > 0.002:
            ok = False
        if abs(il_f - il_m) > 0.0015:
            ok = False
    print("FIT_RESULT=" + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
