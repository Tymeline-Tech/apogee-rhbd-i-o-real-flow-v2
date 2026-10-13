* =============================================================================
* Local ngspice sanity check for LS_UP behavioral equations (Epic 1 fit)
* Nominal case VDDL=1.8 V, VDDH=5.5 V (measured tpd_in_rise = 0.228 ns)
* =============================================================================

.include ls_up_behav.sp

Vss  VSS  0  DC 0
Vddl VDDL 0  DC 1.8
Vddh VDDH 0  DC 5.5
Vin  IN   0  PULSE(0 1.8 2n 0.05n 0.05n 20n 40n)

* td = 0.228 ns from Epic 1 / ls_up.va fit at 1.8/5.5
Xls IN OUT VDDL VDDH VSS LS_UP td=0.228n process=0 temp_c=27

.control
  set noaskquit
  option reltol=1e-3
  let pass = 1

  * -------- Transient: rail transfer + delay --------
  tran 0.01n 10n
  meas tran t_in_a when v(IN)=0.9 rise=1
  meas tran t_out_a when v(OUT)=2.75 rise=1
  meas tran vout_peak MAX v(OUT) from=3n to=9n
  meas tran i_vddh_hi_a AVG i(Vddh) from=5n to=9n
  let tpd_a = t_out_a - t_in_a
  let i_vddh_a = -i_vddh_hi_a
  echo CASE_TRAN_1.8_to_5.5
  print vout_peak
  print tpd_a
  print i_vddh_a

  if vout_peak < 5.0
    let pass = 0
  end
  if tpd_a < 150p
    let pass = 0
  end
  if tpd_a > 350p
    let pass = 0
  end
  if abs(i_vddh_a) > 1u
    let pass = 0
  end

  * -------- DC low (IN=0) --------
  alter Vin = 0
  op
  let vout_lo = v(OUT)
  let i_lo = -i(Vddh)
  echo CASE_DC_LO
  print vout_lo
  print i_lo
  if vout_lo > 0.3
    let pass = 0
  end
  if abs(i_lo) > 1n
    let pass = 0
  end
  if abs(i_lo) < 0.01n
    let pass = 0
  end

  * -------- DC high (IN=1.8) --------
  alter Vin = 1.8
  op
  let vout_hi_dc = v(OUT)
  let i_hi = -i(Vddh)
  echo CASE_DC_HI
  print vout_hi_dc
  print i_hi
  if vout_hi_dc < 5.0
    let pass = 0
  end
  if abs(i_hi) > 1n
    let pass = 0
  end
  if abs(i_hi) < 0.01n
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
