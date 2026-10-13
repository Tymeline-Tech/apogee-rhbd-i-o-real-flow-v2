"""Shared pytest fixtures for the Apogee RHBD I/O regression suite."""

from __future__ import annotations

from pathlib import Path


def pytest_configure(config) -> None:  # noqa: ANN001 — pytest hook signature
    """Ensure the coverage XML output directory exists before pytest-cov writes."""
    reports = Path(__file__).resolve().parents[1] / "reports"
    reports.mkdir(parents=True, exist_ok=True)
