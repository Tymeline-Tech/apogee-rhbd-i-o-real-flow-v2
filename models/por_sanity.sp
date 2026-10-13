* =============================================================================
* Local ngspice sanity check for POR behavioral equations (Epic 1 fit)
* Nominal case VDD ramp 0 -> 3.3 V in 100 us (measured V_release = 1.139 V)
* =============================================================================

.include por_behav.sp

Vss  VSS  0  DC 0
* Ramp 0->3.3 V in 100 us, hold to 200 us, ramp down by 300 us
Vdd  VDD  0  PWL(0 0 100u 3.3 200u 3.3 300u 0)

* vdd_nom=3.3 selects Epic 1 thresholds for the 3.3 V row
* SEU pulse at 150 us during hold (seu_amp=1 forces temporary assert)
Xpor VDD VSS POR_N POR
+ vdd_nom=3.3 process=0 temp_c=27
+ seu=1 seu_time=150u seu_width=1u seu_amp=1.0

.control
  set noaskquit
  option reltol=1e-3
  let pass = 1

  * -------- Transient: assert / release / SEU / re-assert --------
  tran 0.05u 300u

  * Asserted near VDD=0.8 V (t ≈ 24.24 us)
  meas tran v_at_0p8 FIND v(POR_N) AT=24.24u
  * Released through hold (before SEU)
  meas tran v_hold FIND v(POR_N) AT=140u
  * Release: POR_N crosses 0.5 V while snapping toward VDD
  meas tran t_rel when v(POR_N)=0.5 rise=1
  * Re-assert on ramp-down (exclude SEU fall at ~150 us)
  meas tran t_rea when v(POR_N)=0.5 fall=1 from=200u to=300u
  * Supply current during hold (pre-SEU window)
  meas tran i_vmax AVG i(Vdd) from=120u to=140u
  * SEU assert pulse and recovery
  meas tran v_seu FIND v(POR_N) AT=150.5u
  meas tran v_seu_rec FIND v(POR_N) AT=160u

  let vdd_at_rel = 3.3 * t_rel / 100u
  * Ramp-down: VDD = 3.3 * (300u - t) / 100u for t in [200u, 300u]
  let vdd_at_rea = 3.3 * (300u - t_rea) / 100u
  let i_hold = -i_vmax

  echo CASE_TRAN_3.3
  print v_at_0p8
  print v_hold
  print vdd_at_rel
  print vdd_at_rea
  print i_hold
  echo CASE_SEU
  print v_seu
  print v_seu_rec

  if v_at_0p8 > 0.3
    let pass = 0
  end
  if v_hold < 3.0
    let pass = 0
  end
  * Release threshold ~1.139 V (allow soft-trip window)
  if vdd_at_rel < 1.05
    let pass = 0
  end
  if vdd_at_rel > 1.22
    let pass = 0
  end
  * Re-assert threshold ~1.091 V
  if vdd_at_rea < 1.00
    let pass = 0
  end
  if vdd_at_rea > 1.18
    let pass = 0
  end
  * Supply current ~14.531 uA at 3.3 V
  if i_hold < 10u
    let pass = 0
  end
  if i_hold > 20u
    let pass = 0
  end
  * SEU forces assert then recovery
  if v_seu > 1.0
    let pass = 0
  end
  if v_seu_rec < 3.0
    let pass = 0
  end

  print pass
  if pass eq 1
    echo SANITY_RESULT=PASS
  else
    echo SANITY_RESULT=FAIL
  end
  quit
.endc

.end
