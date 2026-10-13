* =============================================================================
* POR SPICE behavioral twin of models/por.va
* Fitted Epic 1 release/reassert thresholds + I_VDD; hysteretic soft trip.
* =============================================================================

.subckt POR VDD VSS POR_N
+ vdd_nom=5.0 soft_gain=80 state_delay=1n
+ v_rel_c0=1.12741093 v_rel_c1=0.00340855
+ v_rea_c0=1.10641489 v_rea_c1=-0.00463183
+ i_c0=-1.48727856 i_c1=1.09580173 i_c2=1.13885518
+ process=0 temp_c=27
+ process_thresh_coeff=0.12 temp_thresh_coeff=-0.001
+ process_curr_coeff=0.35 temp_curr_coeff=0.005
+ seu=0 seu_time=150u seu_width=1u seu_amp=1.0

* PVT scales
Bpvt_t pvt_t 0
+ V = (1-process_thresh_coeff*process)*(1+temp_thresh_coeff*(temp_c-27))
Bpvt_c pvt_c 0
+ V = (1+process_curr_coeff*process)*(1+temp_curr_coeff*(temp_c-27))

* Fitted thresholds at vdd_nom
Bvr vrel 0 V = (v_rel_c0+v_rel_c1*vdd_nom)*v(pvt_t)
Bva vrea 0 V = (v_rea_c0+v_rea_c1*vdd_nom)*v(pvt_t)
Bhyst hyst 0 V = max(v(vrel)-v(vrea),1m)

* Delayed state via matched T-line (mirrors absdelay in por.va)
* Ideal trip target into delay line
Bst_i sti 0
+ V = 0.5*(1+tanh(soft_gain*(v(VDD,VSS)-(v(vrea)+v(hyst)*(1-v(state))))))
Ebuf n1 0 sti 0 1
Tdel n1 0 n2 0 Z0=50 TD={state_delay}
Rload n2 0 50
Estate state 0 n2 0 1

* SEU soft window (same continuous form as por.va)
Bseu seu_p 0
+ V = seu*0.25*(1+tanh(1e7*(time-seu_time)))*(1+tanh(1e7*(seu_time+seu_width-time)))

* Active-low POR_N with optional SEU assert pulse
Bout POR_N VSS
+ V = (1-v(seu_p))*v(state)*v(VDD,VSS) + v(seu_p)*v(VDD,VSS)*(1-seu_amp)

* Supply current (uA -> A)
Givdd VDD VSS
+ value={max((i_c0+i_c1*v(VDD,VSS)+i_c2*v(VDD,VSS)*v(VDD,VSS))*v(pvt_c),0)*1e-6}

.ends POR
