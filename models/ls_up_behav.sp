* =============================================================================
* LS_UP SPICE behavioral twin of models/ls_up.va
* Fitted Epic 1 VTC + leakage; delay via buffered lossless T-line.
* =============================================================================

.subckt LS_UP IN OUT VDDL VDDH VSS
+ td=0.228n
+ vin_thresh=0.5 soft_gain=40
+ i_vddh0_a=-0.0115 i_vddh0_b=0.008636
+ i_vddh1_a=-0.0105 i_vddh1_b=0.009545 i_vddl1_k=0.00091
+ process=0 temp_c=27
+ process_leak_coeff=0.20 temp_leak_coeff=0.01

* Soft VDDL->VDDH voltage-transfer target
Bvtc tgt 0
+ V = v(VDDH,VSS)*0.5*(1+tanh(soft_gain*(v(IN,VSS)/max(v(VDDL,VSS),1m)-vin_thresh)))

* Ideal buffer into matched T-line (no resistive divider)
Ebuf n1 0 tgt 0 1
Tdel n1 0 n2 0 Z0=50 TD={td}
Rload n2 0 50
Eout OUT VSS n2 0 1

* Soft VTC state for leakage blend
Bs vtc_s 0
+ V = 0.5*(1+tanh(soft_gain*(v(IN,VSS)/max(v(VDDL,VSS),1m)-vin_thresh)))
Bpvt pvt_l 0 V = (1+process_leak_coeff*process)*(1+temp_leak_coeff*(temp_c-27))

Givddh VDDH VSS
+ value={( (i_vddh0_a+i_vddh0_b*v(VDDH,VSS))*(1-v(vtc_s))
+         +(i_vddh1_a+i_vddh1_b*v(VDDH,VSS))*v(vtc_s) )
+         *v(pvt_l)*1e-9}
Givddl VDDL VSS
+ value={(i_vddl1_k*v(VDDL,VSS))*v(vtc_s)*v(pvt_l)*1e-9}

.ends LS_UP
