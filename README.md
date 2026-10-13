# apogee-rhbd-i-o-real-flow-v2

Apogee RHBD I/O — real flow v2 (sky130 g5v0d10v5 LS_UP / POR / TOP_IO).

## Verification

Requires Icarus Verilog (`iverilog` / `vvp`) and Python deps from
`requirements-dev.txt`.

```bash
pip install -r requirements-dev.txt
pytest -m verification
# or: make verification
```

The suite runs the Icarus `rtl/tb_top_io` testbench, compares behavioral
models to SPICE reference data (`analog/sim/*.json`, `reports/*_perf.csv`),
and writes coverage to `reports/verification_coverage.{json,txt}`
(≥99% functional coverage, ≤1% corner deviation).