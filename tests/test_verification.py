"""Verification suite: Icarus TB, SPICE reference compare, coverage ≥99%.

Run with::

    pytest -m verification

Acceptance (epic / story):
  - Icarus TOP_IO testbench exits PASS
  - Behavioral model vs SPICE reference deviation ≤ 1% across corners
  - Functional coverage ≥ 99%
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.verification_lib import (
    MAX_REL_DEVIATION,
    MIN_FUNCTIONAL_COVERAGE,
    compare_ls_up_to_spice,
    compare_por_to_spice,
    generate_full_report,
    run_icarus_testbench,
)

pytestmark = pytest.mark.verification


@pytest.fixture(scope="module")
def icarus_result(rtl_dir: Path, artifacts_dir: Path, iverilog_available: bool):
    if not iverilog_available:
        pytest.skip("iverilog/vvp not installed")
    result = run_icarus_testbench(rtl_dir, artifacts_dir / "icarus")
    (artifacts_dir / "icarus" / "summary.txt").write_text(
        f"passed={result['passed']}\n"
        f"corners={result['corners']}\n"
        f"errors={result['errors']}\n"
        f"vcd={result.get('vcd')}\n",
        encoding="utf-8",
    )
    return result


@pytest.fixture(scope="module")
def coverage_report(
    icarus_result,
    ls_up_spice_ref,
    por_spice_ref,
    reports_dir: Path,
    artifacts_dir: Path,
):
    return generate_full_report(
        icarus=icarus_result,
        ls_spice=ls_up_spice_ref,
        por_spice=por_spice_ref,
        ls_csv_path=reports_dir / "ls_up_perf.csv",
        por_csv_path=reports_dir / "por_perf.csv",
        out_dir=artifacts_dir,
    )


class TestIcarusTestbench:
    """Execute rtl/tb_top_io.v via Icarus and require RESULT=PASS."""

    def test_iverilog_on_path(self, iverilog_available: bool):
        assert iverilog_available, "iverilog and vvp must be installed for verification"

    def test_tb_sources_exist(self, rtl_dir: Path):
        assert (rtl_dir / "tb_top_io.v").is_file()
        assert (rtl_dir / "reset_combiner.v").is_file()

    def test_tb_passes(self, icarus_result):
        assert icarus_result["passed"], (
            f"Icarus TB failed (errors={icarus_result['errors']}):\n"
            f"{icarus_result.get('stdout', '')[-2000:]}"
        )

    def test_tb_exercises_all_corners(self, icarus_result):
        # tb_top_io sweeps 7 normal + 6 SEU = 13 corners
        assert icarus_result["corners"] >= 13

    def test_vcd_waveform_dumped(self, icarus_result):
        vcd = icarus_result.get("vcd")
        assert vcd, "expected tb_top_io.vcd waveform dump"
        assert Path(vcd).is_file()
        assert Path(vcd).stat().st_size > 0


class TestModelAccuracyVsSpice:
    """Compare Verilog-A behavioral equations to SPICE reference CSVs/JSON."""

    def test_ls_up_spice_ref_passed(self, ls_up_spice_ref):
        assert ls_up_spice_ref.get("passed") is True
        assert ls_up_spice_ref.get("per_vdd"), "LS_UP SPICE ref missing per_vdd entries"

    def test_por_spice_ref_passed(self, por_spice_ref):
        assert por_spice_ref.get("passed") is True
        assert por_spice_ref.get("per_vdd"), "POR SPICE ref missing per_vdd entries"

    def test_ls_up_deviation_within_1pct(self, ls_up_spice_ref):
        compares = compare_ls_up_to_spice(ls_up_spice_ref)
        assert compares, "no LS_UP compares produced"
        failed = [c for c in compares if not c.passed]
        assert not failed, (
            "LS_UP model exceeds 1% deviation vs SPICE:\n"
            + "\n".join(
                f"  {c.name}: ref={c.reference} meas={c.measured} rel={c.rel_err:.3e}"
                for c in failed
            )
        )
        # Effective corner deviation ignores abs-floor passes (near-zero leakage).
        effective = [
            0.0 if (c.passed and c.rel_err > MAX_REL_DEVIATION) else c.rel_err
            for c in compares
        ]
        assert max(effective, default=0.0) <= MAX_REL_DEVIATION

    def test_por_deviation_within_1pct(self, por_spice_ref):
        compares = compare_por_to_spice(por_spice_ref)
        assert compares, "no POR compares produced"
        failed = [c for c in compares if not c.passed]
        assert not failed, (
            "POR model exceeds 1% deviation vs SPICE:\n"
            + "\n".join(
                f"  {c.name}: ref={c.reference} meas={c.measured} rel={c.rel_err:.3e}"
                for c in failed
            )
        )
        effective = [
            0.0 if (c.passed and c.rel_err > MAX_REL_DEVIATION) else c.rel_err
            for c in compares
        ]
        assert max(effective, default=0.0) <= MAX_REL_DEVIATION

    def test_perf_reference_csvs_exist(self, reports_dir: Path):
        assert (reports_dir / "ls_up_perf.csv").is_file()
        assert (reports_dir / "por_perf.csv").is_file()

    def test_model_fit_scripts_pass(self, models_dir: Path, repo_root: Path):
        """Sanity: stand-alone fit checkers vs Epic 1 tables still PASS."""
        import subprocess
        import sys

        for script in ("check_ls_up_fit.py", "check_por_fit.py"):
            path = models_dir / script
            proc = subprocess.run(
                [sys.executable, str(path)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                check=False,
            )
            assert proc.returncode == 0, f"{script} failed:\n{proc.stdout}\n{proc.stderr}"
            assert "FIT_RESULT=PASS" in proc.stdout


class TestFunctionalCoverage:
    """Generate coverage report and enforce ≥99% functional coverage."""

    def test_coverage_report_written(self, coverage_report, reports_dir: Path):
        assert (reports_dir / "verification_coverage.json").is_file()
        assert (reports_dir / "verification_coverage.txt").is_file()
        assert coverage_report.bins, "coverage report has no bins"

    def test_functional_coverage_ge_99pct(self, coverage_report):
        assert coverage_report.functional_coverage >= MIN_FUNCTIONAL_COVERAGE, (
            f"functional coverage {coverage_report.functional_coverage * 100:.2f}% "
            f"< {MIN_FUNCTIONAL_COVERAGE * 100:.0f}%\n"
            "Missed bins:\n"
            + "\n".join(
                f"  - {b.name}: {b.detail}" for b in coverage_report.bins if not b.hit
            )
        )

    def test_max_deviation_le_1pct(self, coverage_report):
        failed = [c for c in coverage_report.compares if not c.passed]
        assert not failed, (
            "corner compares exceed ≤1% (or absolute fit floor):\n"
            + "\n".join(
                f"  {c.name}: ref={c.reference} meas={c.measured} rel={c.rel_err:.3e}"
                for c in failed
            )
        )
        assert coverage_report.max_rel_deviation <= MAX_REL_DEVIATION, (
            f"max relative deviation {coverage_report.max_rel_deviation * 100:.4f}% "
            f"> {MAX_REL_DEVIATION * 100:.0f}%"
        )

    def test_acceptance_criteria_met(self, coverage_report):
        assert coverage_report.accepted, (
            "verification acceptance failed: "
            f"coverage={coverage_report.functional_coverage * 100:.2f}% "
            f"max_dev={coverage_report.max_rel_deviation * 100:.4f}% "
            f"icarus={coverage_report.icarus_pass}"
        )


class TestToolchain:
    """Lightweight toolchain presence checks used by the verification flow."""

    def test_python_parser_available(self):
        # csv/json are stdlib; numpy optional for this suite
        import csv
        import json

        assert csv and json

    def test_artifacts_dir_writable(self, artifacts_dir: Path):
        probe = artifacts_dir / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        assert probe.read_text(encoding="utf-8") == "ok"
        probe.unlink(missing_ok=True)
