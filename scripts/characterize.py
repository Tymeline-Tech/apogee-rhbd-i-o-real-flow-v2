#!/usr/bin/env python3
"""Apogee RHBD I/O — PVT / SEU characterization driver.

Iterates over supply, process corner, temperature, and SEU injection states,
runs ngspice for each point, extracts key metrics from binary/ASCII .raw
files, and writes CSV performance tables plus PNG plots (pandas/matplotlib).

Default grid (sky130 g5v0d10v5 RHBD 5 V I/O):
  supply        1.4, 1.8, 3.3, 5.5 V
  corners       ss, tt, ff
  temperature   -55, 27, 125 °C
  SEU states    0 (nominal), 1 (injected)
"""

from __future__ import annotations

import argparse
import csv
import logging
import math
import os
import re
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

# ---------------------------------------------------------------------------
# Defaults aligned with project technical context
# ---------------------------------------------------------------------------
DEFAULT_SUPPLIES_V = (1.4, 1.8, 3.3, 5.5)
DEFAULT_CORNERS = ("ss", "tt", "ff")
DEFAULT_TEMPERATURES_C = (-55.0, 27.0, 125.0)
DEFAULT_SEU_STATES = (0, 1)
DEFAULT_DEVICE_CLASS = "g5v0d10v5"
DEFAULT_PDK = "sky130"
DEFAULT_CELLS = ("POR", "LS_UP")

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NETLIST_DIR = REPO_ROOT / "analog" / "netlists"
DEFAULT_SIM_DIR = REPO_ROOT / "analog" / "sim" / "characterize"
DEFAULT_REPORTS_DIR = REPO_ROOT / "reports" / "characterize"
DEFAULT_BUILD_DIR = REPO_ROOT / "build" / "characterize"

LOG = logging.getLogger("characterize")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CornerPoint:
    """One point in the supply × PVT × SEU characterization grid."""

    cell: str
    supply_v: float
    corner: str
    temperature_c: float
    seu: int

    @property
    def tag(self) -> str:
        seu_tag = f"seu{self.seu}"
        supply_tag = f"{self.supply_v:.2f}V".replace(".", "p")
        temp_tag = (
            f"m{abs(self.temperature_c):.0f}C"
            if self.temperature_c < 0
            else f"{self.temperature_c:.0f}C"
        )
        return f"{self.cell}_{supply_tag}_{self.corner}_{temp_tag}_{seu_tag}"


@dataclass
class RunResult:
    """Metrics and paths produced by one ngspice invocation."""

    point: CornerPoint
    status: str
    raw_path: Path | None = None
    log_path: Path | None = None
    deck_path: Path | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    message: str = ""

    def to_row(self) -> dict[str, Any]:
        row: dict[str, Any] = {
            "cell": self.point.cell,
            "supply_v": self.point.supply_v,
            "corner": self.point.corner,
            "temperature_c": self.point.temperature_c,
            "seu": self.point.seu,
            "status": self.status,
            "tag": self.point.tag,
            "raw_path": str(self.raw_path) if self.raw_path else "",
            "log_path": str(self.log_path) if self.log_path else "",
            "message": self.message,
        }
        # Metrics must not clobber identity / status columns.
        reserved = set(row)
        for key, value in self.metrics.items():
            if key not in reserved:
                row[key] = value
        return row


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_float_list(text: str) -> tuple[float, ...]:
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("expected at least one number")
    try:
        return tuple(float(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid float list: {text!r}") from exc


def _parse_str_list(text: str) -> tuple[str, ...]:
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("expected at least one token")
    return tuple(parts)


def _parse_int_list(text: str) -> tuple[int, ...]:
    parts = [p.strip() for p in text.replace(";", ",").split(",") if p.strip()]
    if not parts:
        raise argparse.ArgumentTypeError("expected at least one integer")
    try:
        return tuple(int(p) for p in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid int list: {text!r}") from exc


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Drive ngspice across supply / PVT / SEU corners for Apogee RHBD "
            "I/O cells, parse .raw results, and emit CSV tables + PNG plots."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "--cells",
        type=_parse_str_list,
        default=",".join(DEFAULT_CELLS),
        help="Comma-separated cell names to characterize",
    )
    parser.add_argument(
        "--supplies",
        type=_parse_float_list,
        default=",".join(str(v) for v in DEFAULT_SUPPLIES_V),
        help="Supply voltages in volts (1.4–5.5 V range)",
    )
    parser.add_argument(
        "--corners",
        type=_parse_str_list,
        default=",".join(DEFAULT_CORNERS),
        help="Process corners (ss, tt, ff)",
    )
    parser.add_argument(
        "--temperatures",
        type=_parse_float_list,
        default=",".join(str(t) for t in DEFAULT_TEMPERATURES_C),
        metavar="LIST",
        help=(
            "Temperatures in °C (comma-separated). "
            "Prefer --temperatures=-55,27,125 when the first value is negative."
        ),
    )
    parser.add_argument(
        "--seu-states",
        type=_parse_int_list,
        default=",".join(str(s) for s in DEFAULT_SEU_STATES),
        help="SEU injection flags (0=nominal, 1=injected)",
    )
    parser.add_argument(
        "--netlist-dir",
        type=Path,
        default=DEFAULT_NETLIST_DIR,
        help="Directory containing <cell>.sp netlists",
    )
    parser.add_argument(
        "--deck",
        type=Path,
        default=None,
        help=(
            "Optional parameterized SPICE deck template. Placeholders "
            "{{CELL}}, {{SUPPLY}}, {{CORNER}}, {{TEMP}}, {{SEU}}, "
            "{{NETLIST}}, {{RAW_PATH}}, {{DEVICE_CLASS}}, {{PDK}} are "
            "substituted. When omitted, a deck is generated per cell."
        ),
    )
    parser.add_argument(
        "--sim-dir",
        type=Path,
        default=DEFAULT_SIM_DIR,
        help="Directory for generated decks, logs, and .raw files",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=DEFAULT_REPORTS_DIR,
        help="Directory for CSV tables and PNG plots",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=DEFAULT_BUILD_DIR,
        help="Scratch build directory for intermediate artifacts",
    )
    parser.add_argument(
        "--ngspice",
        default=os.environ.get("NGSPICE", "ngspice"),
        help="ngspice executable",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Per-run ngspice timeout in seconds",
    )
    parser.add_argument(
        "--device-class",
        default=DEFAULT_DEVICE_CLASS,
        help="Device class tag written into decks and CSV metadata",
    )
    parser.add_argument(
        "--pdk",
        default=DEFAULT_PDK,
        help="PDK name written into decks and CSV metadata",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Enumerate the grid and write decks without invoking ngspice",
    )
    parser.add_argument(
        "--skip-missing-netlist",
        action="store_true",
        help="Skip cells whose netlist is absent instead of failing",
    )
    parser.add_argument(
        "--use-builtin-probe",
        action="store_true",
        help=(
            "Force the built-in RC probe deck (no PDK / netlist required). "
            "Useful for toolchain / pipeline smoke tests."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase logging verbosity (-v, -vv)",
    )
    return parser


def _preprocess_argv(argv: Sequence[str]) -> list[str]:
    """Merge flags whose values look like negative numbers into --opt=value.

    argparse otherwise treats ``--temperatures -55,27,125`` as an unknown
    option ``-55,27,125``.
    """
    sticky = {
        "--temperatures",
        "--supplies",
        "--seu-states",
        "--timeout",
    }
    out: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in sticky and i + 1 < len(argv):
            nxt = argv[i + 1]
            if nxt.startswith("-") and len(nxt) > 1 and (nxt[1].isdigit() or nxt[1] == "."):
                out.append(f"{tok}={nxt}")
                i += 2
                continue
        out.append(tok)
        i += 1
    return out


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_arg_parser()
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    args = parser.parse_args(_preprocess_argv(raw_argv))

    # Normalize list-typed defaults that argparse may leave as strings when
    # the default= path is used with type= converters inconsistently across
    # Python versions — coerce explicitly.
    if isinstance(args.cells, str):
        args.cells = _parse_str_list(args.cells)
    if isinstance(args.supplies, str):
        args.supplies = _parse_float_list(args.supplies)
    if isinstance(args.corners, str):
        args.corners = _parse_str_list(args.corners)
    if isinstance(args.temperatures, str):
        args.temperatures = _parse_float_list(args.temperatures)
    if isinstance(args.seu_states, str):
        args.seu_states = _parse_int_list(args.seu_states)

    for v in args.supplies:
        if not (1.4 - 1e-9 <= v <= 5.5 + 1e-9):
            parser.error(f"supply {v} V outside project range 1.4–5.5 V")
    for c in args.corners:
        if c.lower() not in {"ss", "tt", "ff"}:
            parser.error(f"unsupported corner {c!r}; expected ss, tt, or ff")
    args.corners = tuple(c.lower() for c in args.corners)
    for s in args.seu_states:
        if s not in (0, 1):
            parser.error(f"SEU state must be 0 or 1, got {s}")

    return args


# ---------------------------------------------------------------------------
# Parameter grid
# ---------------------------------------------------------------------------
def iter_parameter_grid(
    cells: Sequence[str],
    supplies: Sequence[float],
    corners: Sequence[str],
    temperatures: Sequence[float],
    seu_states: Sequence[int],
) -> Iterator[CornerPoint]:
    for cell in cells:
        for supply in supplies:
            for corner in corners:
                for temp in temperatures:
                    for seu in seu_states:
                        yield CornerPoint(
                            cell=cell,
                            supply_v=float(supply),
                            corner=str(corner),
                            temperature_c=float(temp),
                            seu=int(seu),
                        )


# ---------------------------------------------------------------------------
# Deck generation
# ---------------------------------------------------------------------------
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Z0-9_]+)\s*\}\}")


def _render_template(text: str, mapping: Mapping[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in mapping:
            raise KeyError(f"unknown deck placeholder {{{{{key}}}}}")
        return mapping[key]

    return _PLACEHOLDER_RE.sub(repl, text)


def _netlist_path_for_cell(netlist_dir: Path, cell: str) -> Path:
    candidates = [
        netlist_dir / f"{cell}.sp",
        netlist_dir / f"{cell.lower()}.sp",
        netlist_dir / f"{cell.upper()}.sp",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _builtin_probe_deck(point: CornerPoint, raw_path: Path, mapping: Mapping[str, str]) -> str:
    """Self-contained RC probe deck — no PDK required.

    Exercises the same parameter substitutions a real cell deck would use so
    the driver, .raw parsing, CSV, and plot paths can be smoke-tested. SEU=1
    injects a brief current pulse on the output node.
    """
    # Corner / temperature lightly modulate R so metrics vary across the grid.
    corner_scale = {"ss": 1.15, "tt": 1.0, "ff": 0.85}.get(point.corner, 1.0)
    temp_scale = 1.0 + 0.002 * (point.temperature_c - 27.0)
    r_ohm = 1000.0 * corner_scale * temp_scale
    c_f = 1.0e-12
    pulse_amp = 50e-6 if point.seu else 0.0
    return f"""* Autogenerated characterization probe for {point.tag}
* pdk={mapping['PDK']} device_class={mapping['DEVICE_CLASS']}
* cell={point.cell} supply={point.supply_v} corner={point.corner}
* temp={point.temperature_c} seu={point.seu}
.param supply={point.supply_v}
.param temp_c={point.temperature_c}
.param seu_flag={point.seu}
.temp {point.temperature_c}

Vdd vdd 0 DC {{supply}}
Vin in 0 PULSE(0 {{supply}} 1n 0.1n 0.1n 20n 40n)
R1 in out {r_ohm}
C1 out 0 {c_f}
* SEU current injection (no-op when seu_flag=0)
Iseu out 0 PULSE(0 {pulse_amp} 15n 0.05n 0.05n 0.5n 40n)

.control
set filetype=ascii
tran 0.05n 60n
write {raw_path.as_posix()}
echo MEASURE supply={{supply}} corner={point.corner} temp={{temp_c}} seu={{seu_flag}}
meas tran vout_final FIND v(out) AT=59n
meas tran vin_peak MAX v(in)
meas tran tpd TRIG v(in) VAL={{supply}}/2 RISE=1 TARG v(out) VAL={{supply}}/2 RISE=1
quit
.endc
.end
"""


def _cell_include_deck(
    point: CornerPoint,
    netlist: Path,
    raw_path: Path,
    mapping: Mapping[str, str],
) -> str:
    """Parameterized wrapper around an existing cell netlist.

    Instantiates POR or LS_UP with supply / temp / SEU parameters. Device
    models are left to the included netlist / PDK; if models are missing
    ngspice will fail and the runner records status=fail.
    """
    cell = point.cell.upper()
    seu_pulse = 100e-6 if point.seu else 0.0
    if cell == "POR":
        instance = "X1 vdd 0 por_n POR"
        sources = f"""
Vdd vdd 0 PWL(0 0 50u {{supply}} 150u {{supply}} 200u 0)
Iseu por_n 0 PULSE(0 {seu_pulse} 80u 1n 1n 10n 200u)
"""
        analysis = """
tran 0.1u 220u
write {raw}
meas tran release_v FIND v(vdd) WHEN v(por_n)=supply/2 RISE=1
meas tran vout_final FIND v(por_n) AT=140u
""".format(raw=raw_path.as_posix())
    else:
        # Default / LS_UP dual-rail level-shifter wrapper
        instance = "X1 in out vddl vddh 0 LS_UP"
        sources = f"""
Vvddl vddl 0 DC {{supply}}
Vvddh vddh 0 DC {{supply}}
Vin in 0 PULSE(0 {{supply}} 1n 0.1n 0.1n 20n 40n)
Iseu out 0 PULSE(0 {seu_pulse} 15n 0.05n 0.05n 0.5n 40n)
"""
        analysis = """
tran 0.05n 60n
write {raw}
meas tran tpd TRIG v(in) VAL={{supply}}/2 RISE=1 TARG v(out) VAL={{supply}}/2 RISE=1
meas tran vout_final FIND v(out) AT=59n
""".format(raw=raw_path.as_posix())

    return f"""* Autogenerated characterization deck for {point.tag}
* pdk={mapping['PDK']} device_class={mapping['DEVICE_CLASS']}
.param supply={point.supply_v}
.param temp_c={point.temperature_c}
.param seu_flag={point.seu}
.temp {point.temperature_c}
.include "{netlist.resolve().as_posix()}"
{sources}
{instance}
.control
set filetype=ascii
{analysis}
quit
.endc
.end
"""


def write_deck_for_point(
    point: CornerPoint,
    *,
    sim_dir: Path,
    netlist_dir: Path,
    template: str | None,
    device_class: str,
    pdk: str,
    use_builtin_probe: bool,
) -> tuple[Path, Path, Path]:
    """Write the SPICE deck for one grid point.

    Returns (deck_path, raw_path, log_path).
    """
    run_dir = sim_dir / point.cell / point.tag
    run_dir.mkdir(parents=True, exist_ok=True)
    deck_path = run_dir / f"{point.tag}.sp"
    raw_path = run_dir / f"{point.tag}.raw"
    log_path = run_dir / f"{point.tag}.log"

    netlist = _netlist_path_for_cell(netlist_dir, point.cell)
    mapping = {
        "CELL": point.cell,
        "SUPPLY": f"{point.supply_v}",
        "CORNER": point.corner,
        "TEMP": f"{point.temperature_c}",
        "SEU": f"{point.seu}",
        "NETLIST": netlist.resolve().as_posix() if netlist.exists() else "",
        "RAW_PATH": raw_path.resolve().as_posix(),
        "DEVICE_CLASS": device_class,
        "PDK": pdk,
        "TAG": point.tag,
    }

    if template is not None:
        body = _render_template(template, mapping)
    elif use_builtin_probe or not netlist.is_file():
        body = _builtin_probe_deck(point, raw_path.resolve(), mapping)
    else:
        body = _cell_include_deck(point, netlist, raw_path.resolve(), mapping)

    deck_path.write_text(body, encoding="utf-8")
    return deck_path, raw_path, log_path


# ---------------------------------------------------------------------------
# ngspice runner
# ---------------------------------------------------------------------------
def run_ngspice(
    deck_path: Path,
    log_path: Path,
    *,
    ngspice: str,
    timeout: float,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [ngspice, "-b", "-o", str(log_path), str(deck_path)]
    LOG.info("Running: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )


# ---------------------------------------------------------------------------
# .raw file parsing (ASCII + binary ngspice)
# ---------------------------------------------------------------------------
@dataclass
class RawData:
    title: str
    date: str
    plotname: str
    flags: str
    variables: list[tuple[int, str, str]]  # index, name, type
    data: dict[str, list[float]]

    @property
    def n_points(self) -> int:
        if not self.variables:
            return 0
        name = self.variables[0][1]
        return len(self.data.get(name, []))


def _normalize_var_name(name: str) -> str:
    return name.strip().lower()


def read_raw_file(path: Path) -> RawData:
    """Parse an ngspice .raw file (ASCII or binary)."""
    with path.open("rb") as fh:
        header_lines: list[str] = []
        binary = False
        while True:
            line_b = fh.readline()
            if not line_b:
                break
            try:
                line = line_b.decode("ascii", errors="replace").rstrip("\r\n")
            except Exception:
                line = line_b.decode("latin-1", errors="replace").rstrip("\r\n")
            header_lines.append(line)
            low = line.lower()
            if low.startswith("binary:"):
                binary = True
                break
            if low.startswith("values:"):
                binary = False
                break

        meta: dict[str, str] = {}
        variables: list[tuple[int, str, str]] = []
        in_vars = False
        n_vars = 0
        n_points = 0
        for line in header_lines:
            if ":" in line and not line.lower().startswith(("variables:", "values:", "binary:")):
                key, _, val = line.partition(":")
                key_l = key.strip().lower()
                val = val.strip()
                meta[key_l] = val
                if key_l == "no. variables":
                    n_vars = int(val)
                elif key_l == "no. points":
                    n_points = int(val)
                continue
            if line.lower().startswith("variables:"):
                in_vars = True
                continue
            if in_vars and not line.lower().startswith(("values:", "binary:")):
                parts = line.split()
                if len(parts) >= 3 and parts[0].lstrip("-").isdigit():
                    variables.append((int(parts[0]), parts[1], parts[2]))
                if n_vars and len(variables) >= n_vars:
                    in_vars = False

        data: dict[str, list[float]] = { _normalize_var_name(n): [] for _, n, _ in variables }

        if binary:
            # Complex plots store real/imag pairs; real plots store one float8.
            complex_plot = "complex" in meta.get("flags", "").lower()
            width = n_vars * (2 if complex_plot else 1)
            fmt = f"<{width}d"
            size = struct.calcsize(fmt)
            for _ in range(n_points):
                chunk = fh.read(size)
                if len(chunk) < size:
                    break
                values = struct.unpack(fmt, chunk)
                if complex_plot:
                    # Keep magnitude of complex values.
                    for idx, (_, name, _) in enumerate(variables):
                        re_v = values[2 * idx]
                        im_v = values[2 * idx + 1]
                        data[_normalize_var_name(name)].append(math.hypot(re_v, im_v))
                else:
                    for idx, (_, name, _) in enumerate(variables):
                        data[_normalize_var_name(name)].append(float(values[idx]))
        else:
            # ASCII: each point starts with "index\tval0" then continuation lines.
            # Consume remaining text.
            rest = fh.read().decode("ascii", errors="replace")
            tokens = rest.replace(",", " ").split()
            i = 0
            while i < len(tokens):
                # Skip point index
                i += 1
                for _, name, _ in variables:
                    if i >= len(tokens):
                        break
                    # Complex values may appear as real,imag
                    tok = tokens[i]
                    i += 1
                    if "," in tok:
                        re_s, _, im_s = tok.partition(",")
                        try:
                            val = math.hypot(float(re_s), float(im_s or 0.0))
                        except ValueError:
                            val = float("nan")
                    else:
                        try:
                            val = float(tok)
                        except ValueError:
                            val = float("nan")
                    data[_normalize_var_name(name)].append(val)

    return RawData(
        title=meta.get("title", ""),
        date=meta.get("date", ""),
        plotname=meta.get("plotname", ""),
        flags=meta.get("flags", ""),
        variables=variables,
        data=data,
    )


def _first_matching(data: Mapping[str, list[float]], candidates: Iterable[str]) -> list[float] | None:
    for name in candidates:
        key = _normalize_var_name(name)
        if key in data and data[key]:
            return data[key]
    # Fuzzy contains match
    for cand in candidates:
        cand_l = cand.lower()
        for key, series in data.items():
            if cand_l in key and series:
                return series
    return None


def extract_metrics_from_raw(raw: RawData, point: CornerPoint) -> dict[str, float]:
    """Derive key performance metrics from parsed waveform data."""
    metrics: dict[str, float] = {
        "n_points": float(raw.n_points),
        "n_variables": float(len(raw.variables)),
    }
    time = _first_matching(raw.data, ("time", "t"))
    out = _first_matching(raw.data, ("v(out)", "out", "v(por_n)", "por_n", "v(vout)"))
    inp = _first_matching(raw.data, ("v(in)", "in", "v(vin)", "v(vdd)"))

    if out:
        metrics["vout_final"] = float(out[-1])
        metrics["vout_min"] = float(min(out))
        metrics["vout_max"] = float(max(out))
        metrics["vout_mid"] = float(out[len(out) // 2])
    if inp:
        metrics["vin_final"] = float(inp[-1])
        metrics["vin_max"] = float(max(inp))
    if time and out and inp and point.supply_v > 0:
        thr = 0.5 * point.supply_v
        t_in = _crossing_time(time, inp, thr, rising=True)
        t_out = _crossing_time(time, out, thr, rising=True)
        if t_in is not None and t_out is not None:
            metrics["tpd_s"] = float(t_out - t_in)
            metrics["tpd_ns"] = float((t_out - t_in) * 1e9)

    # SEU signature: peak |dv/dt| after mid-run when SEU is enabled
    if time and out and len(time) > 2:
        dt = max(time[1] - time[0], 1e-18)
        peak_slew = max(abs(out[i] - out[i - 1]) / dt for i in range(1, len(out)))
        metrics["peak_slew_v_per_s"] = float(peak_slew)

    return metrics


def _crossing_time(
    time: Sequence[float],
    wave: Sequence[float],
    threshold: float,
    *,
    rising: bool,
) -> float | None:
    for i in range(1, min(len(time), len(wave))):
        y0, y1 = wave[i - 1], wave[i]
        if rising and y0 < threshold <= y1:
            if y1 == y0:
                return float(time[i])
            frac = (threshold - y0) / (y1 - y0)
            return float(time[i - 1] + frac * (time[i] - time[i - 1]))
        if not rising and y0 > threshold >= y1:
            if y1 == y0:
                return float(time[i])
            frac = (threshold - y0) / (y1 - y0)
            return float(time[i - 1] + frac * (time[i] - time[i - 1]))
    return None


def extract_metrics_from_log(log_path: Path) -> dict[str, float]:
    """Parse ngspice `meas` / `echo` numeric results from the log."""
    metrics: dict[str, float] = {}
    if not log_path.is_file():
        return metrics
    text = log_path.read_text(encoding="utf-8", errors="replace")
    # Examples: "tpd = 1.234e-09" or "vout_final= 1.2"
    for match in re.finditer(
        r"(?i)\b([a-z_][a-z0-9_]*)\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)",
        text,
    ):
        name, value = match.group(1).lower(), match.group(2)
        if name in {"temp", "temper", "version"}:
            continue
        try:
            metrics[f"meas_{name}"] = float(value)
        except ValueError:
            continue
    return metrics


# ---------------------------------------------------------------------------
# CSV / plot outputs
# ---------------------------------------------------------------------------
def save_csv(results: Sequence[RunResult], csv_path: Path) -> Path:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [r.to_row() for r in results]
    # Stable column order: identity fields first, then sorted metric keys.
    identity = [
        "cell",
        "supply_v",
        "corner",
        "temperature_c",
        "seu",
        "status",
        "tag",
        "raw_path",
        "log_path",
        "message",
    ]
    extra: list[str] = []
    seen = set(identity)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                extra.append(key)
    extra.sort()
    fieldnames = identity + extra
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return csv_path


def save_plots(results: Sequence[RunResult], reports_dir: Path) -> list[Path]:
    """Generate summary PNG plots from successful runs using pandas/matplotlib."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import pandas as pd
    except ImportError as exc:
        LOG.warning("pandas/matplotlib unavailable (%s); skipping plots", exc)
        return []

    rows = [r.to_row() for r in results if r.status == "pass" and r.metrics]
    if not rows:
        LOG.warning("No successful runs with metrics; skipping plots")
        return []

    df = pd.DataFrame(rows)
    reports_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    metric_candidates = [
        "tpd_ns",
        "meas_tpd",
        "vout_final",
        "meas_vout_final",
        "peak_slew_v_per_s",
        "vout_max",
    ]
    metric_col = next((c for c in metric_candidates if c in df.columns), None)
    if metric_col is None:
        # Fall back to first numeric non-identity column
        skip = {
            "supply_v",
            "temperature_c",
            "seu",
            "n_points",
            "n_variables",
        }
        for col in df.columns:
            if col in skip:
                continue
            if pd.api.types.is_numeric_dtype(df[col]):
                metric_col = col
                break
    if metric_col is None:
        LOG.warning("No numeric metric column found for plotting")
        return []

    # 1) Metric vs supply, faceted by corner (one figure per cell)
    for cell, cdf in df.groupby("cell"):
        fig, ax = plt.subplots(figsize=(8, 5))
        for corner, g in cdf.groupby("corner"):
            # Average across temps / SEU for a clean supply sweep view
            grouped = g.groupby("supply_v", as_index=False)[metric_col].mean()
            ax.plot(
                grouped["supply_v"],
                grouped[metric_col],
                marker="o",
                label=str(corner),
            )
        ax.set_xlabel("Supply (V)")
        ax.set_ylabel(metric_col)
        ax.set_title(f"{cell}: {metric_col} vs supply")
        ax.grid(True, alpha=0.3)
        ax.legend(title="corner")
        path = reports_dir / f"{cell}_metric_vs_supply.png"
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        written.append(path)

    # 2) Heatmap-style pivot: temperature × corner at nominal supply / SEU=0
    nominal_supply = 3.3 if 3.3 in set(df["supply_v"]) else float(df["supply_v"].median())
    subset = df[(df["seu"] == 0) & (abs(df["supply_v"] - nominal_supply) < 1e-9)]
    if not subset.empty:
        for cell, cdf in subset.groupby("cell"):
            pivot = cdf.pivot_table(
                index="temperature_c",
                columns="corner",
                values=metric_col,
                aggfunc="mean",
            )
            if pivot.empty:
                continue
            fig, ax = plt.subplots(figsize=(7, 4.5))
            im = ax.imshow(pivot.values, aspect="auto", cmap="viridis")
            ax.set_xticks(range(len(pivot.columns)))
            ax.set_xticklabels([str(c) for c in pivot.columns])
            ax.set_yticks(range(len(pivot.index)))
            ax.set_yticklabels([f"{t:g}" for t in pivot.index])
            ax.set_xlabel("Corner")
            ax.set_ylabel("Temperature (°C)")
            ax.set_title(f"{cell}: {metric_col} @ {nominal_supply:g} V (SEU=0)")
            fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
            path = reports_dir / f"{cell}_pvt_heatmap.png"
            fig.tight_layout()
            fig.savefig(path, dpi=120)
            plt.close(fig)
            written.append(path)

    # 3) SEU impact: metric delta (seu1 - seu0) vs supply for tt / 27 C
    tt = df[(df["corner"] == "tt") & (abs(df["temperature_c"] - 27.0) < 1e-9)]
    if not tt.empty and set(tt["seu"]) >= {0, 1}:
        for cell, cdf in tt.groupby("cell"):
            zero = cdf[cdf["seu"] == 0].set_index("supply_v")[metric_col]
            one = cdf[cdf["seu"] == 1].set_index("supply_v")[metric_col]
            aligned = one.subtract(zero, fill_value=float("nan")).dropna()
            if aligned.empty:
                continue
            fig, ax = plt.subplots(figsize=(8, 4.5))
            ax.bar([float(x) for x in aligned.index], aligned.values, width=0.25)
            ax.set_xlabel("Supply (V)")
            ax.set_ylabel(f"Δ {metric_col} (SEU1 − SEU0)")
            ax.set_title(f"{cell}: SEU impact @ tt / 27 °C")
            ax.grid(True, axis="y", alpha=0.3)
            path = reports_dir / f"{cell}_seu_impact.png"
            fig.tight_layout()
            fig.savefig(path, dpi=120)
            plt.close(fig)
            written.append(path)

    return written


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def characterize(args: argparse.Namespace) -> list[RunResult]:
    args.sim_dir.mkdir(parents=True, exist_ok=True)
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    args.build_dir.mkdir(parents=True, exist_ok=True)

    template: str | None = None
    if args.deck is not None:
        if not args.deck.is_file():
            raise FileNotFoundError(f"deck template not found: {args.deck}")
        template = args.deck.read_text(encoding="utf-8")

    grid = list(
        iter_parameter_grid(
            cells=args.cells,
            supplies=args.supplies,
            corners=args.corners,
            temperatures=args.temperatures,
            seu_states=args.seu_states,
        )
    )
    LOG.info(
        "Characterization grid: %d points (%d cells × %d supplies × %d corners × %d temps × %d SEU)",
        len(grid),
        len(args.cells),
        len(args.supplies),
        len(args.corners),
        len(args.temperatures),
        len(args.seu_states),
    )

    results: list[RunResult] = []
    for point in grid:
        netlist = _netlist_path_for_cell(args.netlist_dir, point.cell)
        use_probe = bool(args.use_builtin_probe)
        if not use_probe and template is None and not netlist.is_file():
            if args.skip_missing_netlist:
                LOG.warning("Skipping %s — missing netlist %s", point.tag, netlist)
                results.append(
                    RunResult(
                        point=point,
                        status="skip",
                        message=f"missing netlist {netlist}",
                    )
                )
                continue
            LOG.warning(
                "Netlist %s missing; falling back to built-in probe deck for %s",
                netlist,
                point.tag,
            )
            use_probe = True

        deck_path, raw_path, log_path = write_deck_for_point(
            point,
            sim_dir=args.sim_dir,
            netlist_dir=args.netlist_dir,
            template=template,
            device_class=args.device_class,
            pdk=args.pdk,
            use_builtin_probe=use_probe,
        )

        if args.dry_run:
            results.append(
                RunResult(
                    point=point,
                    status="dry-run",
                    deck_path=deck_path,
                    raw_path=raw_path,
                    log_path=log_path,
                    message="deck written; ngspice not invoked",
                )
            )
            continue

        try:
            proc = run_ngspice(
                deck_path,
                log_path,
                ngspice=args.ngspice,
                timeout=args.timeout,
                cwd=deck_path.parent,
            )
        except FileNotFoundError:
            results.append(
                RunResult(
                    point=point,
                    status="fail",
                    deck_path=deck_path,
                    raw_path=raw_path,
                    log_path=log_path,
                    message=f"ngspice executable not found: {args.ngspice}",
                )
            )
            continue
        except subprocess.TimeoutExpired:
            results.append(
                RunResult(
                    point=point,
                    status="fail",
                    deck_path=deck_path,
                    raw_path=raw_path,
                    log_path=log_path,
                    message=f"ngspice timed out after {args.timeout}s",
                )
            )
            continue

        # Append captured stderr to log for post-mortem.
        if proc.stdout or proc.stderr:
            with log_path.open("a", encoding="utf-8") as lf:
                if proc.stdout:
                    lf.write("\n--- stdout ---\n")
                    lf.write(proc.stdout)
                if proc.stderr:
                    lf.write("\n--- stderr ---\n")
                    lf.write(proc.stderr)

        metrics: dict[str, float] = {}
        status = "pass"
        message = ""
        if proc.returncode != 0:
            status = "fail"
            message = f"ngspice exit {proc.returncode}"
        elif not raw_path.is_file():
            status = "fail"
            message = "ngspice completed but .raw file missing"
        else:
            try:
                raw = read_raw_file(raw_path)
                metrics.update(extract_metrics_from_raw(raw, point))
                metrics.update(extract_metrics_from_log(log_path))
            except Exception as exc:  # noqa: BLE001 — record and continue grid
                status = "fail"
                message = f"raw parse error: {exc}"

        results.append(
            RunResult(
                point=point,
                status=status,
                deck_path=deck_path,
                raw_path=raw_path if raw_path.is_file() else None,
                log_path=log_path,
                metrics=metrics,
                message=message,
            )
        )
        LOG.info("%s -> %s (%s)", point.tag, status, message or "ok")

    return results


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    level = logging.WARNING
    if args.verbose == 1:
        level = logging.INFO
    elif args.verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    results = characterize(args)

    csv_path = args.reports_dir / "characterization_results.csv"
    save_csv(results, csv_path)
    LOG.info("Wrote CSV %s (%d rows)", csv_path, len(results))

    # Also emit a compact per-cell CSV for easier golden compares later.
    by_cell: dict[str, list[RunResult]] = {}
    for result in results:
        by_cell.setdefault(result.point.cell, []).append(result)
    for cell, cell_results in by_cell.items():
        save_csv(cell_results, args.reports_dir / f"{cell}_performance.csv")

    plot_paths = [] if args.dry_run else save_plots(results, args.reports_dir)
    for path in plot_paths:
        LOG.info("Wrote plot %s", path)

    n_pass = sum(1 for r in results if r.status == "pass")
    n_fail = sum(1 for r in results if r.status == "fail")
    n_skip = sum(1 for r in results if r.status in {"skip", "dry-run"})
    summary_path = args.reports_dir / "characterization_summary.txt"
    summary_path.write_text(
        "\n".join(
            [
                "Apogee RHBD I/O characterization summary",
                f"pdk={args.pdk} device_class={args.device_class}",
                f"cells={','.join(args.cells)}",
                f"supplies_v={','.join(str(v) for v in args.supplies)}",
                f"corners={','.join(args.corners)}",
                f"temperatures_c={','.join(str(t) for t in args.temperatures)}",
                f"seu_states={','.join(str(s) for s in args.seu_states)}",
                f"total={len(results)} pass={n_pass} fail={n_fail} skip={n_skip}",
                f"csv={csv_path}",
                f"plots={len(plot_paths)}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(summary_path.read_text(encoding="utf-8"), end="")

    if args.dry_run:
        return 0
    return 0 if n_fail == 0 and n_pass > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
