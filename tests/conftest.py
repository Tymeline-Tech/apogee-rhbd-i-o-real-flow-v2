"""Shared fixtures for Apogee RHBD I/O verification tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RTL_DIR = REPO_ROOT / "rtl"
MODELS_DIR = REPO_ROOT / "models"
REPORTS_DIR = REPO_ROOT / "reports"
SIM_DIR = REPO_ROOT / "analog" / "sim"
ARTIFACTS_DIR = REPO_ROOT / "reports" / "verification_artifacts"


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def rtl_dir() -> Path:
    return RTL_DIR


@pytest.fixture(scope="session")
def models_dir() -> Path:
    return MODELS_DIR


@pytest.fixture(scope="session")
def reports_dir() -> Path:
    return REPORTS_DIR


@pytest.fixture(scope="session")
def sim_dir() -> Path:
    return SIM_DIR


@pytest.fixture(scope="session")
def artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


@pytest.fixture(scope="session")
def iverilog_available() -> bool:
    return shutil.which("iverilog") is not None and shutil.which("vvp") is not None


@pytest.fixture(scope="session")
def ls_up_spice_ref(sim_dir: Path) -> dict:
    path = sim_dir / "LS_UP.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def por_spice_ref(sim_dir: Path) -> dict:
    # Prefer canonical uppercase artifact; fall back to lowercase if needed.
    for name in ("POR.json", "por.json"):
        path = sim_dir / name
        if path.is_file():
            with path.open(encoding="utf-8") as fh:
                return json.load(fh)
    raise FileNotFoundError("POR SPICE reference JSON not found under analog/sim")
