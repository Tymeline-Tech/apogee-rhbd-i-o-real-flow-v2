# Apogee RHBD I/O — test / verification targets
.PHONY: test verification clean-verification

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest

# Default: full verification marker suite (Icarus + SPICE compare + coverage)
test: verification

verification:
	$(PYTEST) -m verification

clean-verification:
	rm -rf reports/verification_artifacts reports/verification_coverage.json \
		reports/verification_coverage.txt rtl/tb_top_io.vvp rtl/tb_top_io.vcd
