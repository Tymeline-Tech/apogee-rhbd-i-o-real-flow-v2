"""Pytest regression suite for the PVT/SEU characterization driver.

Invokes ``scripts/characterize.py`` across the project supply × corner ×
temperature × SEU grid, loads the generated CSV performance tables with
pandas, compares them to golden references (metric deviations ≤ 1 %), and
enforces ≥ 99 % functional coverage of the characterization parameter space.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

REPO_ROOT = Path(__file__).resolve().parents[1]
CHARACTERIZE_SCRIPT = REPO_ROOT / "scripts" / "characterize.py"
GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# Regression grid — matches golden references and project technical context.
REGRESSION_CELLS = ("POR", "LS_UP")
REGRESSION_SUPPLIES = (1.4, 1.8, 3.3, 5.5)
REGRESSION_CORNERS = ("ss", "tt", "ff")
REGRESSION_TEMPERATURES = (-55.0, 27.0, 125.0)
REGRESSION_SEU_STATES = (0, 1)

METRIC_RTOL = 0.01  # 1 % relative tolerance vs golden
COVERAGE_THRESHOLD = 0.99  # ≥ 99 % functional coverage

IDENTITY_COLS = ("cell", "supply_v", "corner", "temperature_c", "seu")
VOLATILE_COLS = ("raw_path", "log_path", "message")
CSV_NAMES = (
    "characterization_results.csv",
    "POR_performance.csv",
    "LS_UP_performance.csv",
)


def _expected_grid_size() -> int:
    return (
        len(REGRESSION_CELLS)
        * len(REGRESSION_SUPPLIES)
        * len(REGRESSION_CORNERS)
        * len(REGRESSION_TEMPERATURES)
        * len(REGRESSION_SEU_STATES)
    )


def _run_characterize(reports_dir: Path, sim_dir: Path, build_dir: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the characterization driver with the locked regression grid."""
    if not CHARACTERIZE_SCRIPT.is_file():  # pragma: no cover - repo layout invariant
        pytest.fail(f"characterization script missing: {CHARACTERIZE_SCRIPT}")

    cmd = [
        sys.executable,
        str(CHARACTERIZE_SCRIPT),
        "--use-builtin-probe",
        "--cells",
        ",".join(REGRESSION_CELLS),
        "--supplies",
        ",".join(str(v) for v in REGRESSION_SUPPLIES),
        "--corners",
        ",".join(REGRESSION_CORNERS),
        f"--temperatures={','.join(str(t) for t in REGRESSION_TEMPERATURES)}",
        "--seu-states",
        ",".join(str(s) for s in REGRESSION_SEU_STATES),
        "--reports-dir",
        str(reports_dir),
        "--sim-dir",
        str(sim_dir),
        "--build-dir",
        str(build_dir),
    ]
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


def _load_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():  # pragma: no cover - guarded by characterization fixture
        pytest.fail(f"expected CSV not found: {path}")
    return pd.read_csv(path)


def _prepare_for_compare(df: pd.DataFrame) -> pd.DataFrame:
    """Drop volatile path columns and sort by identity keys for stable compares."""
    out = df.drop(columns=[c for c in VOLATILE_COLS if c in df.columns], errors="ignore")
    sort_cols = [c for c in IDENTITY_COLS if c in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols).reset_index(drop=True)
    else:
        out = out.reset_index(drop=True)
    return out


def _align_frames(actual: pd.DataFrame, golden: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Align column sets so assert_frame_equal compares the shared schema."""
    shared = [c for c in golden.columns if c in actual.columns]
    missing = [c for c in golden.columns if c not in actual.columns]
    if missing:
        pytest.fail(f"generated CSV missing golden columns: {missing}")
    return actual[shared].copy(), golden[shared].copy()


def compute_functional_coverage(df: pd.DataFrame, expected_points: int) -> float:
    """Fraction of the characterization grid that produced a passing result.

    Functional coverage here is the share of supply × PVT × SEU corner points
    with ``status == "pass"``. A later story may replace this with a richer
    coverage model; the ≥ 99 % gate remains the same.
    """
    if expected_points <= 0:
        return 0.0
    if "status" not in df.columns:
        return 0.0
    n_pass = int((df["status"].astype(str) == "pass").sum())
    return n_pass / float(expected_points)


def _assert_metric_deviation_within_tol(
    actual: pd.DataFrame,
    golden: pd.DataFrame,
    rtol: float = METRIC_RTOL,
) -> None:
    """Explicitly assert every numeric metric is within ``rtol`` of golden."""
    skip = set(IDENTITY_COLS) | {"status", "tag"}
    numeric_cols = [
        c
        for c in golden.columns
        if c not in skip and c in actual.columns and pd.api.types.is_numeric_dtype(golden[c])
    ]
    violations: list[str] = []
    for col in numeric_cols:
        g = golden[col].to_numpy(dtype=float)
        a = actual[col].to_numpy(dtype=float)
        for idx, (gv, av) in enumerate(zip(g, a)):
            if math.isnan(gv) and math.isnan(av):
                continue
            denom = max(abs(gv), 1e-30)
            rel = abs(av - gv) / denom
            if rel > rtol:
                tag = (
                    actual["tag"].iloc[idx]
                    if "tag" in actual.columns
                    else f"row:{idx}"
                )
                violations.append(
                    f"{tag}.{col}: rel={rel:.4e} (actual={av}, golden={gv}, rtol={rtol})"
                )
    if violations:
        preview = "\n  ".join(violations[:20])
        more = f"\n  ... and {len(violations) - 20} more" if len(violations) > 20 else ""
        pytest.fail(
            f"{len(violations)} metric deviation(s) exceed {rtol * 100:.0f} %:\n  {preview}{more}"
        )


@pytest.fixture(scope="module")
def characterization_reports(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Run characterization once per test module; return the reports directory."""
    root = tmp_path_factory.mktemp("characterize_regression")
    reports_dir = root / "reports"
    sim_dir = root / "sim"
    build_dir = root / "build"

    proc = _run_characterize(reports_dir, sim_dir, build_dir)
    if proc.returncode != 0:  # pragma: no cover - exercised when ngspice/driver fails
        pytest.fail(
            "characterization script failed "
            f"(exit {proc.returncode})\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    summary = reports_dir / "characterization_results.csv"
    if not summary.is_file():  # pragma: no cover - driver contract
        pytest.fail(
            "characterization did not write characterization_results.csv\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    return reports_dir


@pytest.mark.verification
def test_expected_grid_size_matches_project_context() -> None:
    """Locked regression grid size is cells × supplies × corners × temps × SEU."""
    assert _expected_grid_size() == (
        len(REGRESSION_CELLS)
        * len(REGRESSION_SUPPLIES)
        * len(REGRESSION_CORNERS)
        * len(REGRESSION_TEMPERATURES)
        * len(REGRESSION_SEU_STATES)
    )


@pytest.mark.verification
def test_prepare_for_compare_without_identity_columns() -> None:
    """Volatile path columns are dropped even when identity keys are absent."""
    df = pd.DataFrame(
        {
            "metric": [2.0, 1.0],
            "raw_path": ["/tmp/a.raw", "/tmp/b.raw"],
            "log_path": ["/tmp/a.log", "/tmp/b.log"],
            "message": ["", ""],
        }
    )
    out = _prepare_for_compare(df)
    assert list(out.columns) == ["metric"]
    assert list(out["metric"]) == [2.0, 1.0]


@pytest.mark.verification
def test_align_frames_reports_missing_golden_columns() -> None:
    """Aligner fails fast when the generated CSV lacks golden columns."""
    actual = pd.DataFrame({"a": [1.0]})
    golden = pd.DataFrame({"a": [1.0], "b": [2.0]})
    with pytest.raises(pytest.fail.Exception, match="missing golden columns"):
        _align_frames(actual, golden)


@pytest.mark.verification
def test_compute_functional_coverage_edge_cases() -> None:
    """Coverage helper returns 0.0 for empty grids or missing status column."""
    assert compute_functional_coverage(pd.DataFrame(), 0) == 0.0
    assert compute_functional_coverage(pd.DataFrame({"x": [1]}), 4) == 0.0
    df = pd.DataFrame({"status": ["pass", "fail", "pass"]})
    assert compute_functional_coverage(df, 3) == pytest.approx(2.0 / 3.0)


@pytest.mark.verification
def test_metric_deviation_nan_match_and_violation() -> None:
    """NaN pairs are ignored; deviations beyond rtol raise with a clear message."""
    matched = pd.DataFrame({"tpd_ns": [float("nan")], "tag": ["t0"]})
    _assert_metric_deviation_within_tol(matched, matched)

    actual = pd.DataFrame({"tpd_ns": [2.0]})
    golden = pd.DataFrame({"tpd_ns": [1.0]})
    with pytest.raises(pytest.fail.Exception, match="metric deviation"):
        _assert_metric_deviation_within_tol(actual, golden, rtol=0.01)

    tagged = pd.DataFrame({"tpd_ns": [2.0], "tag": ["POR_tt"]})
    golden_tagged = pd.DataFrame({"tpd_ns": [1.0], "tag": ["POR_tt"]})
    with pytest.raises(pytest.fail.Exception, match="POR_tt.tpd_ns"):
        _assert_metric_deviation_within_tol(tagged, golden_tagged, rtol=0.01)


@pytest.mark.verification
def test_metric_deviation_many_violations_truncates_preview() -> None:
    """When many metrics diverge, the failure message notes remaining count."""
    n = 25
    actual = pd.DataFrame({"tpd_ns": [2.0] * n, "tag": [f"r{i}" for i in range(n)]})
    golden = pd.DataFrame({"tpd_ns": [1.0] * n, "tag": [f"r{i}" for i in range(n)]})
    with pytest.raises(pytest.fail.Exception, match="and 5 more"):
        _assert_metric_deviation_within_tol(actual, golden, rtol=0.01)


@pytest.mark.verification
@pytest.mark.parametrize("csv_name", CSV_NAMES)
def test_characterization_csv_matches_golden(
    characterization_reports: Path,
    csv_name: str,
) -> None:
    """Generated CSVs must match golden references within 1 % on all metrics."""
    golden_path = GOLDEN_DIR / csv_name
    if not golden_path.is_file():  # pragma: no cover - golden fixtures are checked in
        pytest.fail(f"golden reference missing: {golden_path}")

    actual = _prepare_for_compare(_load_csv(characterization_reports / csv_name))
    golden = _prepare_for_compare(_load_csv(golden_path))
    actual, golden = _align_frames(actual, golden)

    assert len(actual) == len(golden), (
        f"{csv_name}: row count mismatch actual={len(actual)} golden={len(golden)}"
    )

    _assert_metric_deviation_within_tol(actual, golden, rtol=METRIC_RTOL)

    # Primary contract: pandas frame equality at 1 % relative tolerance.
    assert_frame_equal(
        actual,
        golden,
        rtol=METRIC_RTOL,
        atol=0.0,
        check_dtype=False,
        check_exact=False,
    )


@pytest.mark.verification
def test_characterization_functional_coverage(
    characterization_reports: Path,
) -> None:
    """Overall functional coverage of the PVT/SEU grid must be ≥ 99 %."""
    results = _load_csv(characterization_reports / "characterization_results.csv")
    expected = _expected_grid_size()
    coverage = compute_functional_coverage(results, expected)

    assert len(results) == expected, (
        f"grid size mismatch: got {len(results)} rows, expected {expected}"
    )
    assert coverage >= COVERAGE_THRESHOLD, (
        f"functional coverage {coverage * 100:.2f} % "
        f"is below the {COVERAGE_THRESHOLD * 100:.0f} % gate "
        f"(pass={(results['status'] == 'pass').sum()}/{expected})"
    )
