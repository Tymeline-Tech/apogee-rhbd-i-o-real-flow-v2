#!/usr/bin/env python3
"""Post-process ngspice .raw outputs for LS_UP and POR characterization.

Loads voltage/timing waveforms from ngspice raw files, computes per-corner
performance metrics with NumPy, and returns a pandas DataFrame.

Metrics
-------
- gain                 : large-signal |ΔVout/ΔVin| (LS_UP) or trip-region
                         |dPOR_N/dVDD| (POR)
- prop_delay_s         : IN→OUT 50% propagation delay (LS_UP); NaN for POR
- reset_time_s         : POR_N release time from t=0 (POR); NaN for LS_UP
- seu_upset_tolerance  : 1.0 if output recovers after an SEU pulse within
                         the post-pulse window, else 0.0 (NaN if no SEU)

Dependencies: numpy, pandas. Optionally uses PySpice's RawFile when installed;
otherwise a built-in ngspice ASCII/binary .raw parser is used.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Optional, Sequence

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Raw-file I/O
# ---------------------------------------------------------------------------

_VARIABLE_RE = re.compile(
    r"^\s*(\d+)\s+(\S+)\s+(\S+)(?:\s+(.*))?$"
)


@dataclass
class RawWaveforms:
    """Waveforms extracted from one ngspice .raw plot."""

    path: Path
    title: str = ""
    date: str = ""
    plotname: str = ""
    flags: str = ""
    variables: list[str] = field(default_factory=list)
    units: list[str] = field(default_factory=list)
    data: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def time(self) -> Optional[np.ndarray]:
        for key in ("time", "TIME", "t", "frequency", "FREQUENCY"):
            if key in self.data:
                return np.asarray(self.data[key], dtype=float)
        # First variable is conventionally the sweep axis.
        if self.variables:
            return np.asarray(self.data[self.variables[0]], dtype=float)
        return None

    def get(self, *names: str) -> Optional[np.ndarray]:
        """Return the first matching vector (case-insensitive, v(name) aware)."""
        lowered = {k.lower(): k for k in self.data}
        for name in names:
            key = name.lower()
            if key in lowered:
                return np.asarray(self.data[lowered[key]], dtype=float)
            # Match v(name) / i(name) forms against bare names and vice versa.
            bare = key
            for prefix in ("v(", "i(", "v", "i"):
                if bare.startswith(prefix) and bare.endswith(")"):
                    bare = bare[len(prefix) : -1]
                    break
            candidates = [
                bare,
                f"v({bare})",
                f"i({bare})",
                f"v{bare}",
                f"i{bare}",
            ]
            for cand in candidates:
                if cand in lowered:
                    return np.asarray(self.data[lowered[cand]], dtype=float)
        # Fuzzy: any variable whose bare node equals the request.
        for name in names:
            target = name.lower().strip()
            for raw_name, arr in self.data.items():
                token = raw_name.lower()
                m = re.match(r"^[vi]\((.+)\)$", token)
                node = m.group(1) if m else token
                if node == target or token == target:
                    return np.asarray(arr, dtype=float)
        return None


def _parse_header_lines(lines: Sequence[str]) -> tuple[dict[str, Any], int]:
    """Parse ngspice raw header; return metadata and index of data start line."""
    meta: dict[str, Any] = {
        "title": "",
        "date": "",
        "plotname": "",
        "flags": "",
        "n_variables": 0,
        "n_points": 0,
        "variables": [],
        "units": [],
        "binary": False,
    }
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i].rstrip("\n")
        lower = line.lower()
        if lower.startswith("title:"):
            meta["title"] = line.split(":", 1)[1].strip()
        elif lower.startswith("date:"):
            meta["date"] = line.split(":", 1)[1].strip()
        elif lower.startswith("plotname:"):
            meta["plotname"] = line.split(":", 1)[1].strip()
        elif lower.startswith("flags:"):
            meta["flags"] = line.split(":", 1)[1].strip().lower()
        elif lower.startswith("no. variables:"):
            meta["n_variables"] = int(line.split(":", 1)[1].strip())
        elif lower.startswith("no. points:"):
            meta["n_points"] = int(line.split(":", 1)[1].strip())
        elif lower.startswith("variables:"):
            i += 1
            while i < n and len(meta["variables"]) < meta["n_variables"]:
                m = _VARIABLE_RE.match(lines[i].rstrip("\n"))
                if not m:
                    break
                meta["variables"].append(m.group(2))
                meta["units"].append(m.group(3))
                i += 1
            continue
        elif lower.startswith("binary:"):
            meta["binary"] = True
            return meta, i + 1
        elif lower.startswith("values:"):
            meta["binary"] = False
            return meta, i + 1
        i += 1
    raise ValueError("ngspice raw header missing Binary:/Values: section")


def _read_raw_builtin(path: Path) -> RawWaveforms:
    """Parse an ngspice .raw file (ASCII or binary) without PySpice."""
    raw_bytes = path.read_bytes()
    # Header is always ASCII up to Binary:/Values:
    # Split on first Binary:/Values: marker in bytes to keep binary payload intact.
    header_end = None
    binary = False
    for marker, is_bin in ((b"Binary:\n", True), (b"Binary:\r\n", True),
                           (b"Values:\n", False), (b"Values:\r\n", False)):
        idx = raw_bytes.find(marker)
        if idx >= 0:
            header_end = idx + len(marker)
            binary = is_bin
            break
    if header_end is None:
        raise ValueError(f"{path}: not a recognizable ngspice .raw file")

    header_text = raw_bytes[:header_end].decode("ascii", errors="replace")
    header_lines = header_text.splitlines()
    meta, _ = _parse_header_lines(header_lines)
    meta["binary"] = binary
    n_vars = int(meta["n_variables"])
    n_pts = int(meta["n_points"])
    var_names = list(meta["variables"])

    if binary:
        payload = raw_bytes[header_end:]
        flags = meta["flags"]
        complex_data = "complex" in flags
        # ngspice "short" → float32, else float64
        fmt = "<f" if "short" in flags else "<d"
        width = 4 if "short" in flags else 8
        values_per_sample = 2 if complex_data else 1
        expected = n_vars * n_pts * values_per_sample * width
        if len(payload) < expected:
            raise ValueError(
                f"{path}: binary payload too short "
                f"({len(payload)} < {expected} bytes)"
            )
        flat = np.asarray(
            struct.unpack(f"<{n_vars * n_pts * values_per_sample}{fmt[-1]}",
                          payload[:expected]),
            dtype=float,
        )
        if complex_data:
            flat = flat.reshape(n_pts, n_vars, 2)[:, :, 0]
        else:
            flat = flat.reshape(n_pts, n_vars)
        arrays = {name: flat[:, i].copy() for i, name in enumerate(var_names)}
    else:
        # ASCII Values: each point starts with "<index>\t<v0>" then indented values.
        text = raw_bytes[header_end:].decode("ascii", errors="replace")
        tokens: list[float] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.replace(",", " ").split()
            # First token on a point line may be the integer index.
            start = 0
            if parts and parts[0].isdigit() and "." not in parts[0] and "e" not in parts[0].lower():
                # Could be index only, or index + first value.
                if len(parts) == 1:
                    continue
                start = 1
            for p in parts[start:]:
                # Complex: real,imag
                if "," in p:
                    p = p.split(",", 1)[0]
                tokens.append(float(p))
        needed = n_vars * n_pts
        if len(tokens) < needed:
            raise ValueError(
                f"{path}: ASCII payload has {len(tokens)} values, need {needed}"
            )
        flat = np.asarray(tokens[:needed], dtype=float).reshape(n_pts, n_vars)
        arrays = {name: flat[:, i].copy() for i, name in enumerate(var_names)}

    # ngspice often stores the sweep axis with a negative sign in binary mode;
    # take absolute value for time/frequency so metrics stay positive.
    scale = var_names[0] if var_names else None
    if scale is not None and scale.lower() in {"time", "frequency"}:
        arrays[scale] = np.abs(arrays[scale])

    return RawWaveforms(
        path=path,
        title=meta["title"],
        date=meta["date"],
        plotname=meta["plotname"],
        flags=meta["flags"],
        variables=var_names,
        units=list(meta["units"]),
        data=arrays,
    )


def _read_raw_pyspice(path: Path) -> RawWaveforms:
    """Load .raw via PySpice when available."""
    from PySpice.Probe.RawFile import RawFile  # type: ignore

    raw = RawFile(str(path))
    variables: list[str] = []
    units: list[str] = []
    data: dict[str, np.ndarray] = {}
    # PySpice exposes .variables and per-variable .node / .name
    for var in raw.variables:
        name = getattr(var, "name", None) or str(var)
        variables.append(name)
        units.append(getattr(var, "unit", "") or "")
        data[name] = np.asarray(np.array(var), dtype=float)
    return RawWaveforms(
        path=path,
        title=getattr(raw, "title", "") or "",
        date=getattr(raw, "date", "") or "",
        plotname=getattr(raw, "plot_name", "") or getattr(raw, "plotname", "") or "",
        flags="",
        variables=variables,
        units=units,
        data=data,
    )


def load_raw(path: Path | str) -> RawWaveforms:
    """Load waveforms from an ngspice .raw file (PySpice or built-in parser)."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    try:
        import PySpice  # noqa: F401

        return _read_raw_pyspice(path)
    except Exception:
        return _read_raw_builtin(path)


def write_raw_ascii(
    path: Path | str,
    *,
    time: np.ndarray,
    vectors: Mapping[str, np.ndarray],
    title: str = "postprocess synthetic",
    plotname: str = "Transient Analysis",
) -> Path:
    """Write a minimal ASCII ngspice .raw file (useful for tests / fixtures)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ["time", *vectors.keys()]
    arrays = [np.asarray(time, dtype=float), *[np.asarray(vectors[k], dtype=float) for k in vectors]]
    n_pts = len(arrays[0])
    for a in arrays[1:]:
        if len(a) != n_pts:
            raise ValueError("all vectors must share the time axis length")
    lines = [
        f"Title: {title}",
        "Date: synthetic",
        f"Plotname: {plotname}",
        "Flags: real",
        f"No. Variables: {len(names)}",
        f"No. Points: {n_pts}",
        "Variables:",
    ]
    for i, name in enumerate(names):
        unit = "time" if name == "time" else "voltage"
        lines.append(f"\t{i}\t{name}\t{unit}")
    lines.append("Values:")
    for p in range(n_pts):
        lines.append(f" {p}\t{arrays[0][p]:.12e}")
        for a in arrays[1:]:
            lines.append(f"\t{a[p]:.12e}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    return path


# ---------------------------------------------------------------------------
# Metric calculations (NumPy)
# ---------------------------------------------------------------------------

def _crossings(time: np.ndarray, signal: np.ndarray, threshold: float, edge: str) -> np.ndarray:
    """Return times where signal crosses threshold on rising or falling edges."""
    s = np.asarray(signal, dtype=float)
    t = np.asarray(time, dtype=float)
    if edge == "rise":
        mask = (s[:-1] < threshold) & (s[1:] >= threshold)
    else:
        mask = (s[:-1] > threshold) & (s[1:] <= threshold)
    idxs = np.nonzero(mask)[0]
    times = []
    for i in idxs:
        dy = s[i + 1] - s[i]
        if dy == 0:
            times.append(float(t[i]))
        else:
            frac = (threshold - s[i]) / dy
            times.append(float(t[i] + frac * (t[i + 1] - t[i])))
    return np.asarray(times, dtype=float)


def compute_gain(
    vin: np.ndarray,
    vout: np.ndarray,
    *,
    mode: str = "large_signal",
) -> float:
    """Voltage gain from input/output waveforms.

    large_signal: |ΔVout| / |ΔVin| over the full sweep (LS_UP rail transfer).
    small_signal: max |dVout/dVin| along the trajectory (POR trip sharpness).
    """
    vin = np.asarray(vin, dtype=float)
    vout = np.asarray(vout, dtype=float)
    if vin.size < 2 or vout.size < 2:
        return float("nan")
    if mode == "large_signal":
        dvin = float(np.nanmax(vin) - np.nanmin(vin))
        dvout = float(np.nanmax(vout) - np.nanmin(vout))
        if dvin <= 0:
            return float("nan")
        return abs(dvout / dvin)
    # small-signal / trip-region peak slope
    dvin = np.gradient(vin)
    dvout = np.gradient(vout)
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = np.where(np.abs(dvin) > 1e-15, dvout / dvin, 0.0)
    return float(np.nanmax(np.abs(slope)))


def compute_propagation_delay(
    time: np.ndarray,
    vin: np.ndarray,
    vout: np.ndarray,
    *,
    vin_thresh: Optional[float] = None,
    vout_thresh: Optional[float] = None,
    edge: str = "rise",
) -> float:
    """Propagation delay between matching IN/OUT threshold crossings."""
    time = np.asarray(time, dtype=float)
    vin = np.asarray(vin, dtype=float)
    vout = np.asarray(vout, dtype=float)
    if vin_thresh is None:
        vin_thresh = 0.5 * (float(np.nanmax(vin)) + float(np.nanmin(vin)))
    if vout_thresh is None:
        vout_thresh = 0.5 * (float(np.nanmax(vout)) + float(np.nanmin(vout)))
    t_in = _crossings(time, vin, vin_thresh, edge)
    t_out = _crossings(time, vout, vout_thresh, edge)
    if t_in.size == 0 or t_out.size == 0:
        return float("nan")
    # Pair first OUT crossing that occurs at/after the first IN crossing.
    t0 = t_in[0]
    later = t_out[t_out >= t0 - 1e-18]
    if later.size == 0:
        return float("nan")
    return float(later[0] - t0)


def compute_reset_time(
    time: np.ndarray,
    por_n: np.ndarray,
    *,
    release_thresh: Optional[float] = None,
    vdd: Optional[np.ndarray] = None,
) -> float:
    """POR release (reset de-assert) time: first rise of POR_N through threshold.

    Default threshold is 0.5 V (matches the Epic 1 / por_sanity.sp meas), not
    mid-rail of VDD — POR_N tracks VDD at release, so a mid-rail threshold
    would report the later time when the supply itself crosses mid-rail.
    """
    time = np.asarray(time, dtype=float)
    por_n = np.asarray(por_n, dtype=float)
    if release_thresh is None:
        # Prefer a fixed logic-low threshold; fall back to 10% of peak if the
        # supply is sub-1 V (unusual for this project).
        peak = float(np.nanmax(por_n))
        release_thresh = 0.5 if peak >= 1.0 else 0.1 * peak
    t_rel = _crossings(time, por_n, release_thresh, "rise")
    if t_rel.size == 0:
        return float("nan")
    return float(t_rel[0])


def compute_seu_upset_tolerance(
    time: np.ndarray,
    signal: np.ndarray,
    *,
    expected_high: Optional[float] = None,
    upset_level_frac: float = 0.5,
    recovery_window_s: Optional[float] = None,
) -> dict[str, float]:
    """Quantify SEU upset tolerance from a transient that includes an SEU pulse.

    Only high→low→high excursions count as upsets (ignores power-up low and
    intentional reset-assert intervals).

    Returns
    -------
    seu_upset_tolerance : 1.0 if the signal recovers to the expected rail after
        an upset excursion, else 0.0. NaN if no upset excursion is detected.
    seu_upset_duration_s : contiguous time spent below the upset threshold.
    seu_recovery_time_s  : time from the end of the upset window to re-crossing
        the recovery threshold (NaN if never recovered).
    """
    nan_result = {
        "seu_upset_tolerance": float("nan"),
        "seu_upset_duration_s": float("nan"),
        "seu_recovery_time_s": float("nan"),
        "seu_upset_start_s": float("nan"),
        "seu_upset_end_s": float("nan"),
    }
    time = np.asarray(time, dtype=float)
    signal = np.asarray(signal, dtype=float)
    if expected_high is None:
        expected_high = float(np.nanmax(signal))
    if expected_high <= 0 or time.size < 3:
        return nan_result

    low_thresh = upset_level_frac * expected_high
    high_thresh = 0.8 * expected_high
    is_high = signal >= high_thresh
    is_low = signal < low_thresh

    # Upset = low interval preceded by a high sample (settled state).
    # Prefer intervals that later recover high — this distinguishes an SEU
    # pulse from a POR ramp-down re-assert (which stays low).
    padded_low = np.concatenate([[False], is_low, [False]])
    edges = np.diff(padded_low.astype(int))
    starts = np.nonzero(edges == 1)[0]
    ends = np.nonzero(edges == -1)[0]

    recovering: list[tuple[float, float, float, float]] = []
    failing: list[tuple[float, float, float]] = []
    for s, e in zip(starts, ends):
        if s == 0:
            continue  # ignore initial low (power-up / pre-release)
        if not bool(np.any(is_high[:s])):
            continue
        t_start = float(time[s])
        end_idx = min(e - 1, len(time) - 1)
        t_end = float(time[end_idx])
        duration = t_end - t_start
        post_high = is_high[end_idx + 1 :] if end_idx + 1 < len(is_high) else np.array([])
        if post_high.size and bool(np.any(post_high)):
            # Recovery time: first sample index after upset that is high.
            rel = int(np.argmax(post_high))
            t_rec = float(time[end_idx + 1 + rel])
            recovering.append((duration, t_start, t_end, t_rec - t_end))
        else:
            failing.append((duration, t_start, t_end))

    if recovering:
        # SEU pulses are typically short; pick the longest recovering upset.
        upset_duration, t_start, t_end, recovery_time = max(
            recovering, key=lambda c: c[0]
        )
        recovered = True
        if recovery_window_s is not None:
            recovered = recovery_time <= recovery_window_s
        return {
            "seu_upset_tolerance": 1.0 if recovered else 0.0,
            "seu_upset_duration_s": float(upset_duration),
            "seu_recovery_time_s": float(recovery_time),
            "seu_upset_start_s": t_start,
            "seu_upset_end_s": t_end,
        }

    if failing:
        # Observed a high→low that never recovered (hard fail / stuck upset).
        upset_duration, t_start, t_end = max(failing, key=lambda c: c[0])
        return {
            "seu_upset_tolerance": 0.0,
            "seu_upset_duration_s": float(upset_duration),
            "seu_recovery_time_s": float("nan"),
            "seu_upset_start_s": t_start,
            "seu_upset_end_s": t_end,
        }

    return nan_result


# ---------------------------------------------------------------------------
# Corner / path metadata
# ---------------------------------------------------------------------------

_CORNER_RE = re.compile(r"(?:^|[_\-/])(tt|ss|ff)(?:[_\-/]|$)", re.I)
_TEMP_RE = re.compile(
    r"(?:^|[_\-/])(?:temp[_-]?)?([mM]-?\d+|-?\d+)[cC](?:[_\-/]|$)"
)
_SEU_RE = re.compile(r"(?:^|[_\-/])seu(?:[_\-/]|$)", re.I)
_BLOCK_RE = re.compile(r"(ls_up|por)", re.I)
_VDDL_RE = re.compile(r"vddl[_-]?(\d+(?:\.\d+)?)", re.I)
_VDDH_RE = re.compile(r"vddh[_-]?(\d+(?:\.\d+)?)", re.I)
_VDD_RE = re.compile(r"(?:^|[_\-/])vdd[_-]?(\d+(?:\.\d+)?)(?:[_\-/]|$)", re.I)
# Patterns like 1.8_5.5 or 1.8-5.5 near the end of the stem
_PAIR_RE = re.compile(r"(\d+(?:\.\d+)?)[_-](\d+(?:\.\d+)?)(?:_seu)?$", re.I)
_SINGLE_V_RE = re.compile(r"(?:^|[_\-/])(\d+(?:\.\d+)?)V?(?:_seu)?$", re.I)


def _parse_temp_token(token: str) -> float:
    token = token.replace("m", "-").replace("M", "-")
    return float(token)


def parse_corner_metadata(path: Path | str) -> dict[str, Any]:
    """Infer block / PVT / supply / SEU flags from a .raw path or filename."""
    path = Path(path)
    # Use full path with normalized separators so nested dirs contribute.
    text = str(path.with_suffix("")).replace("\\", "/")
    stem = path.stem

    meta: dict[str, Any] = {
        "file": str(path),
        "block": None,
        "corner": None,
        "temp_c": None,
        "vddl": None,
        "vddh": None,
        "vdd": None,
        "seu": False,
    }

    m = _BLOCK_RE.search(text)
    if m:
        meta["block"] = "LS_UP" if m.group(1).lower() == "ls_up" else "POR"

    m = _CORNER_RE.search(text)
    if m:
        meta["corner"] = m.group(1).lower()

    m = _TEMP_RE.search(text)
    if m:
        meta["temp_c"] = _parse_temp_token(m.group(1))

    meta["seu"] = bool(_SEU_RE.search(text))

    m = _VDDL_RE.search(text)
    if m:
        meta["vddl"] = float(m.group(1))
    m = _VDDH_RE.search(text)
    if m:
        meta["vddh"] = float(m.group(1))
    m = _VDD_RE.search(text)
    if m:
        meta["vdd"] = float(m.group(1))

    if meta["vddl"] is None or meta["vddh"] is None:
        m = _PAIR_RE.search(stem)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            # Convention: lower/core first for LS_UP (vddl, vddh)
            meta["vddl"] = meta["vddl"] if meta["vddl"] is not None else a
            meta["vddh"] = meta["vddh"] if meta["vddh"] is not None else b

    if meta["vdd"] is None and meta["block"] == "POR":
        m = _SINGLE_V_RE.search(stem)
        if m:
            meta["vdd"] = float(m.group(1))
        elif meta["vddh"] is not None:
            meta["vdd"] = meta["vddh"]

    return meta


# ---------------------------------------------------------------------------
# Per-file / batch processing → DataFrame
# ---------------------------------------------------------------------------

RESULT_COLUMNS = [
    "file",
    "block",
    "corner",
    "temp_c",
    "vddl",
    "vddh",
    "vdd",
    "seu",
    "gain",
    "prop_delay_s",
    "prop_delay_ns",
    "reset_time_s",
    "reset_time_us",
    "seu_upset_tolerance",
    "seu_upset_duration_s",
    "seu_recovery_time_s",
]


def process_raw_file(
    path: Path | str,
    *,
    meta: Optional[Mapping[str, Any]] = None,
    recovery_window_s: Optional[float] = None,
) -> dict[str, Any]:
    """Load one .raw file and compute characterization metrics."""
    path = Path(path)
    info = parse_corner_metadata(path)
    if meta:
        info.update({k: v for k, v in meta.items() if v is not None})

    wf = load_raw(path)
    time = wf.time
    if time is None:
        raise ValueError(f"{path}: no time/frequency axis in raw file")

    block = (info.get("block") or "").upper()
    # Auto-detect block from available signals when path lacks it.
    if not block:
        if wf.get("OUT", "out") is not None and wf.get("IN", "in") is not None:
            block = "LS_UP"
        elif wf.get("POR_N", "por_n") is not None:
            block = "POR"
        info["block"] = block

    result: dict[str, Any] = {c: info.get(c) for c in RESULT_COLUMNS}
    result["file"] = str(path)
    result["block"] = block
    result["seu"] = bool(info.get("seu", False))
    result["gain"] = float("nan")
    result["prop_delay_s"] = float("nan")
    result["prop_delay_ns"] = float("nan")
    result["reset_time_s"] = float("nan")
    result["reset_time_us"] = float("nan")
    result["seu_upset_tolerance"] = float("nan")
    result["seu_upset_duration_s"] = float("nan")
    result["seu_recovery_time_s"] = float("nan")

    if block == "LS_UP":
        vin = wf.get("IN", "in", "vin")
        vout = wf.get("OUT", "out", "vout")
        if vin is None or vout is None:
            raise ValueError(f"{path}: LS_UP raw missing IN/OUT vectors")
        vddl = info.get("vddl")
        vddh = info.get("vddh")
        if vddl is None:
            vddl = float(np.nanmax(vin))
            result["vddl"] = vddl
        if vddh is None:
            vddh = float(np.nanmax(vout))
            result["vddh"] = vddh

        result["gain"] = compute_gain(vin, vout, mode="large_signal")
        tpd = compute_propagation_delay(
            time,
            vin,
            vout,
            vin_thresh=0.5 * float(vddl),
            vout_thresh=0.5 * float(vddh),
            edge="rise",
        )
        result["prop_delay_s"] = tpd
        result["prop_delay_ns"] = tpd * 1e9 if np.isfinite(tpd) else float("nan")

        _apply_seu_metrics(
            result,
            compute_seu_upset_tolerance(
                time,
                vout,
                expected_high=float(vddh),
                recovery_window_s=recovery_window_s,
            ),
        )

    elif block == "POR":
        por_n = wf.get("POR_N", "por_n", "por")
        vdd = wf.get("VDD", "vdd")
        if por_n is None:
            raise ValueError(f"{path}: POR raw missing POR_N vector")
        if vdd is None:
            # Fall back to reconstructing a monotonic ramp proxy from time.
            vdd_nom = info.get("vdd") or float(np.nanmax(por_n))
            vdd = np.full_like(por_n, float(vdd_nom))
        if info.get("vdd") is None:
            result["vdd"] = float(np.nanmax(vdd))

        result["gain"] = compute_gain(vdd, por_n, mode="small_signal")
        t_reset = compute_reset_time(time, por_n, vdd=vdd)
        result["reset_time_s"] = t_reset
        result["reset_time_us"] = (
            t_reset * 1e6 if np.isfinite(t_reset) else float("nan")
        )

        _apply_seu_metrics(
            result,
            compute_seu_upset_tolerance(
                time,
                por_n,
                expected_high=float(np.nanmax(vdd)),
                recovery_window_s=(
                    recovery_window_s if recovery_window_s is not None else 50e-6
                ),
            ),
        )
    else:
        raise ValueError(f"{path}: unable to determine block type (LS_UP/POR)")

    return result


def _apply_seu_metrics(
    result: MutableMapping[str, Any], seu: Mapping[str, float]
) -> None:
    """Attach SEU columns.

    - SEU-tagged runs always record the measured tolerance (NaN → 0.0 fail).
    - Untagged runs only auto-attach when a recovering upset is observed, so
      POR ramp-down re-assert is not mistaken for an SEU event.
    """
    tol = seu.get("seu_upset_tolerance", float("nan"))
    if result.get("seu"):
        result["seu_upset_tolerance"] = 0.0 if not np.isfinite(tol) else float(tol)
        result["seu_upset_duration_s"] = seu.get(
            "seu_upset_duration_s", float("nan")
        )
        result["seu_recovery_time_s"] = seu.get(
            "seu_recovery_time_s", float("nan")
        )
    elif np.isfinite(tol) and float(tol) == 1.0:
        result["seu_upset_tolerance"] = 1.0
        result["seu_upset_duration_s"] = seu.get(
            "seu_upset_duration_s", float("nan")
        )
        result["seu_recovery_time_s"] = seu.get(
            "seu_recovery_time_s", float("nan")
        )


def find_raw_files(root: Path | str) -> list[Path]:
    """Recursively discover .raw files under *root*."""
    root = Path(root)
    if root.is_file() and root.suffix.lower() == ".raw":
        return [root]
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.raw") if p.is_file())


def process_simulations(
    raw_root: Path | str,
    *,
    recovery_window_s: Optional[float] = None,
) -> pd.DataFrame:
    """Process all .raw files under *raw_root* into a metrics DataFrame."""
    paths = find_raw_files(raw_root)
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in paths:
        try:
            rows.append(
                process_raw_file(path, recovery_window_s=recovery_window_s)
            )
        except Exception as exc:  # keep batch robust; report later
            errors.append(f"{path}: {exc}")
    df = pd.DataFrame(rows, columns=RESULT_COLUMNS)
    if errors and df.empty:
        raise RuntimeError(
            "failed to process any raw files:\n" + "\n".join(errors)
        )
    df.attrs["errors"] = errors
    return df


def results_to_dataframe(rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
    """Build a typed metrics DataFrame from an iterable of result dicts."""
    return pd.DataFrame(list(rows), columns=RESULT_COLUMNS)


# ---------------------------------------------------------------------------
# Synthetic fixtures (smoke / unit testing without a live ngspice run)
# ---------------------------------------------------------------------------

def generate_ls_up_fixture_waveforms(
    *,
    vddl: float = 1.8,
    vddh: float = 5.5,
    tpd_s: float = 0.228e-9,
    seu: bool = False,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Synthesize LS_UP IN/OUT waveforms with known delay and optional SEU."""
    t = np.linspace(0.0, 10e-9, 2001)
    t_rise = 2e-9
    vin = np.where(t < t_rise, 0.0, vddl)
    # Soften edges slightly for crossing interpolation.
    vin = vddl * (0.5 * (1.0 + np.tanh((t - t_rise) / 20e-12)))
    vout = vddh * (0.5 * (1.0 + np.tanh((t - (t_rise + tpd_s)) / 20e-12)))
    if seu:
        # Force OUT low during a 1 ns SEU window mid-pulse, then recover.
        seu_t0, seu_w = 5e-9, 1e-9
        upset = (t >= seu_t0) & (t < seu_t0 + seu_w)
        vout = np.where(upset, 0.0, vout)
    return t, {"v(in)": vin, "v(out)": vout}


def generate_por_fixture_waveforms(
    *,
    vdd_nom: float = 3.3,
    v_release: float = 1.139,
    ramp_s: float = 100e-6,
    seu: bool = False,
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Synthesize POR VDD/POR_N waveforms with known release time + optional SEU."""
    t = np.linspace(0.0, 300e-6, 6001)
    # Ramp 0→VDD in ramp_s, hold to 200 us, ramp down by 300 us.
    vdd = np.zeros_like(t)
    hold_end = 200e-6
    total_end = 300e-6
    for i, ti in enumerate(t):
        if ti <= ramp_s:
            vdd[i] = vdd_nom * (ti / ramp_s)
        elif ti <= hold_end:
            vdd[i] = vdd_nom
        else:
            vdd[i] = max(vdd_nom * (total_end - ti) / ramp_s, 0.0)

    t_release = ramp_s * (v_release / vdd_nom)
    v_reassert = v_release - 0.048
    # Active-low POR_N: asserted (0) until VDD crosses v_release, tracks VDD
    # while released, re-asserts when VDD falls through v_reassert.
    por = np.zeros_like(t)
    released = False
    for i, (ti, vv) in enumerate(zip(t, vdd)):
        if not released and ti >= t_release:
            released = True
        if released and ti > hold_end and vv <= v_reassert:
            released = False
        por[i] = vv if released else 0.0
    if seu:
        seu_t0, seu_w = 150e-6, 1e-6
        upset = (t >= seu_t0) & (t < seu_t0 + seu_w)
        por = np.where(upset, 0.0, por)
    return t, {"v(vdd)": vdd, "v(por_n)": por}


def write_fixture_raw_tree(root: Path | str) -> list[Path]:
    """Write a small PVT-like .raw tree for LS_UP and POR (with/without SEU)."""
    root = Path(root)
    written: list[Path] = []
    corners = [("tt", 27.0), ("ss", -55.0), ("ff", 125.0)]
    for corner, temp in corners:
        t, vecs = generate_ls_up_fixture_waveforms(seu=False)
        p = root / "LS_UP" / corner / f"LS_UP_{corner}_{temp:.0f}C_vddl1.8_vddh5.5.raw"
        write_raw_ascii(p, time=t, vectors=vecs, title=f"LS_UP {corner} {temp}C")
        written.append(p)

        t, vecs = generate_ls_up_fixture_waveforms(seu=True)
        p = root / "LS_UP" / corner / f"LS_UP_{corner}_{temp:.0f}C_vddl1.8_vddh5.5_seu.raw"
        write_raw_ascii(p, time=t, vectors=vecs, title=f"LS_UP SEU {corner}")
        written.append(p)

        t, vecs = generate_por_fixture_waveforms(seu=False)
        p = root / "POR" / corner / f"POR_{corner}_{temp:.0f}C_vdd3.3.raw"
        write_raw_ascii(p, time=t, vectors=vecs, title=f"POR {corner} {temp}C")
        written.append(p)

        t, vecs = generate_por_fixture_waveforms(seu=True)
        p = root / "POR" / corner / f"POR_{corner}_{temp:.0f}C_vdd3.3_seu.raw"
        write_raw_ascii(p, time=t, vectors=vecs, title=f"POR SEU {corner}")
        written.append(p)
    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Post-process ngspice .raw files for LS_UP / POR metrics."
    )
    p.add_argument(
        "raw_root",
        nargs="?",
        default="analog/sim",
        help="directory (or single .raw) to process (default: analog/sim)",
    )
    p.add_argument(
        "--write-fixtures",
        metavar="DIR",
        help="write synthetic LS_UP/POR .raw fixtures under DIR and exit",
    )
    p.add_argument(
        "--smoke",
        action="store_true",
        help="write temp fixtures, process them, print the DataFrame, and exit",
    )
    p.add_argument(
        "-o",
        "--output",
        help="optional CSV path to dump the metrics DataFrame "
        "(CSV generation story owns production tables; this is for debug)",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    if args.write_fixtures:
        paths = write_fixture_raw_tree(args.write_fixtures)
        print(f"wrote {len(paths)} fixture .raw files under {args.write_fixtures}")
        return 0

    if args.smoke:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="postprocess_smoke_") as tmp:
            write_fixture_raw_tree(tmp)
            df = process_simulations(tmp)
            print(df.to_string(index=False))
            print(f"\nrows={len(df)} columns={list(df.columns)}")
            # Basic sanity on known fixture metrics
            ls = df[(df["block"] == "LS_UP") & (~df["seu"])]
            por = df[(df["block"] == "POR") & (~df["seu"])]
            ls_seu = df[(df["block"] == "LS_UP") & (df["seu"])]
            por_seu = df[(df["block"] == "POR") & (df["seu"])]
            assert not ls.empty and not por.empty
            assert np.allclose(ls["prop_delay_ns"].median(), 0.228, atol=0.05)
            assert np.allclose(ls["gain"].median(), 5.5 / 1.8, rtol=0.05)
            assert np.allclose(por["reset_time_us"].median(), 34.5, atol=1.0)
            assert (ls_seu["seu_upset_tolerance"] == 1.0).all()
            assert (por_seu["seu_upset_tolerance"] == 1.0).all()
            print("SMOKE_RESULT=PASS")
        return 0

    root = Path(args.raw_root)
    if not root.exists():
        print(f"raw root not found: {root}", file=sys.stderr)
        print("hint: pass --smoke to validate against synthetic fixtures", file=sys.stderr)
        return 1

    df = process_simulations(root)
    if df.empty:
        print(f"no .raw files found under {root}", file=sys.stderr)
        errs = df.attrs.get("errors") or []
        for e in errs:
            print(f"  error: {e}", file=sys.stderr)
        return 1

    print(df.to_string(index=False))
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out, index=False)
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
