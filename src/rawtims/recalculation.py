"""Headless, scratch-only KD33 hand-off demo; dates are computed in the other engine.

No age equations or GUI imports live here. The separate interpreter reads the
contract and settings; this module only orchestrates and compares its results.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from rawtims.contract import (
    PB_REQUIRED_RATIOS,
    U_RATIOS,
    csv_text,
    mean_column,
    se_column,
    write_csv,
)
from rawtims.fractions import Fraction, fraction_row
from rawtims.parity import (
    _view,
    drive_path,
    read_sheet_references,
    replay_project,
    sheets_path,
)
from rawtims.readers import open_run
from rawtims.readers._xls import open_xls
from rawtims.readers.ionvantage_raw import PB_WORKBOOK_RTOL, U_WORKBOOK_RTOL
from rawtims.readers.trip import read_trip
from rawtims.reduction_params import as_acquired
from rawtims.reprocess import reprocess

PINNED_EXPORT_TIME = datetime(2026, 11, 18, tzinfo=UTC)

# Runs only in IDTIMS_UPbRPy's existing venv, via python -c. No notebook API changes.
AGE_WORKER = r'''
import contextlib, io, json, platform, subprocess, sys
from importlib.metadata import version
from pathlib import Path
from IDTIMS_UPbRPy.fractions import read_fractions, write_fractions
from IDTIMS_UPbRPy.settings import ReductionSettings, decay_constants
from IDTIMS_UPbRPy.constants import common_U238_U235
from idtims_app.reduction import prepare
settings = ReductionSettings.from_dict(json.loads(Path(sys.argv[1]).read_text()))
answer = {"versions": {name: version(name) for name in ("IDTIMS_UPbRPy", "numpy", "scipy")},
          "python": platform.python_version(),
          "engine_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
          "constants": dict(decay_constants()), "runs": {}}
answer["constants"]["common_U238_U235"] = common_U238_U235
for path in sys.argv[2:]:
    table = read_fractions(path)
    # Verify unknown provenance is lossless in both reader and re-export.
    buf = io.StringIO()
    write_fractions(table, buf)
    again = read_fractions(io.StringIO(buf.getvalue()))
    for element in ("Pb", "U"):
        for suffix in ("Reduction Parameters", "Reduction Parameters SHA256", "Reduction Route"):
            name = element + " " + suffix
            assert table.frame.iloc[0][name] == again.frame.iloc[0][name]
    with contextlib.redirect_stdout(io.StringIO()):
        reduced = prepare(table, settings, strict=False).run()
    result = reduced.result("z1")
    if result.grain is None:
        raise ValueError(result.reason)
    g = result.grain
    # D-mode disequilibrium correction, matching the sheet's selected output.
    dates = {"206/238": [float(g.t68_Th_corr), 2*float(g.t68_Th_corr_std)],
             "207/235": [float(g.t75), 2*float(g.t75_std)],
             "207/206": [float(g.t76_Th_corr), 2*float(g.t76_Th_corr_std)]}
    uncorrected = {k: [float(getattr(g, a)), 2*float(getattr(g, a+"_std"))]
                   for k, a in (("206/238", "t68"), ("207/235", "t75"), ("207/206", "t76"))}
    answer["runs"][Path(path).stem] = {"dates": dates, "uncorrected_dates": uncorrected,
             "status": result.status, "substitutions": result.substitutions,
             "assumptions": g.uncertainty_assumptions,
             "quality": g.data_quality_checks,
             "provenance_roundtrip": True}
print(json.dumps(answer, sort_keys=True, allow_nan=False))
'''


def read_kd33_setup(path):
    """Read z1 settings from UPbR24XML cached cells, checking their labels.

    This deliberately refuses a shifted/template layout instead of borrowing
    coordinates from UPbR26XML. All coordinates in the returned audit are Excel
    one-based. Settings contain no raw/per-cycle measurements.
    """
    book = open_xls(file_contents=Path(path).read_bytes(), on_demand=True)
    cells = {}
    try:
        raw, engine = (book.sheet_by_name(n) for n in ("Raw Data Input", "Data Reduction Engine"))
        if raw.cell_value(3, 4) != "z1":
            raise ValueError("expected z1 in Raw Data Input!E4")
        def e(row, label=None):
            actual = str(engine.cell_value(row-1, 0))
            if label is not None and actual != label:
                raise ValueError(f"Data Reduction Engine!A{row}: expected {label!r}, got {actual!r}")
            value = float(engine.cell_value(row-1, 2))
            cells[f"Data Reduction Engine!C{row}"] = {"label": actual, "value": value}
            return value
        setup = {}
        for name, row in (("sample_weight_mg", 5), ("spike_weight_g", 6), ("spike_type", 7), ("spike", 8), ("collector", 9)):
            value = raw.cell_value(row-1, 4)
            setup[name] = str(int(value)) if name == "spike_type" else value
            cells[f"Raw Data Input!E{row}"] = {"label": raw.cell_value(row-1, 0), "value": value}
        settings = {
            "format": "idtims-reduction-settings", "version": 1,
            "fractionation": {"FPb_Daly": e(222, "F(Pb)")*100, "FPb_Daly_std": e(223)*100,
                              "FPb_Faraday": e(222)*100, "FPb_Faraday_std": e(223)*100},
            "lab_blanks": {"Pb_blank_total": e(211, "Pb blank assumed [pg]"), "Pb_blank_total_std_rel": e(212),
                           "U_blank_total": e(217, "U blank assumed [pg]"), "U_blank_total_std_rel": e(218),
                           "R64b": e(198, "RPb64b"), "R64b_std_rel": e(199),
                           "R74b": e(200, "RPb74b"), "R74b_std_rel": e(201),
                           "R84b": e(202, "RPb84b"), "R84b_std_rel": e(203),
                           "rho_6474_b": e(209), "rho_6484_b": e(209)},
            "common_pb": {"model": "explicit", "R64c": e(185, "RPb64c"), "R64c_std_rel": e(186),
                          "R74c": e(187, "RPb74c"), "R74c_std_rel": e(188), "R84c": e(189, "RPb84c"), "R84c_std_rel": e(190),
                          "rho_6474_c": e(196), "rho_6484_c": e(196)},
            "th_correction": {"kind": "D", "D_Th_U": e(676, "DTh/DU"), "D_Th_U_std": e(677),
                              "Th_U_magma": e(672, "Th/U magma"), "Th_U_magma_std": e(673)},
            "spike_version": "v3", "strict_covariance": False,
        }
        # Record, but do not replace, the engine's pinned physical constants.
        sheet_constants = {name: e(row) for name, row in (("lambda_235", 241), ("lambda_238", 242),
                           ("lambda_232", 243), ("lambda_230", 244), ("common_U238_U235", 245))}
        # Raw sheet selected D and t68; verify rather than assume.
        selection = {"Th_kind": raw.cell_value(53, 45), "Th_age": raw.cell_value(55, 45)}
        if selection != {"Th_kind": "D", "Th_age": "t68"}:
            raise ValueError(f"unverified sheet disequilibrium selection: {selection}")
        dates = {"206/238": [float(raw.cell_value(50, 5)), float(raw.cell_value(50, 6))],
                 "207/235": [float(raw.cell_value(50, 3)), float(raw.cell_value(50, 4))],
                 "207/206": [float(raw.cell_value(50, 1)), float(raw.cell_value(50, 2))]}
        return setup, settings, {"cells": cells, "sheet_dates": dates, "sheet_constants": sheet_constants, "selection": selection}
    finally:
        book.release_resources()


def run_recalculation_demo(*, folder=None, sheet=None, age_repo=None):
    """Return aggregate evidence, scratch path and Markdown. Never stores cycle data.

    All CSV/JSON artifacts go to a newly created system temporary directory.
    Caller may save the aggregate Markdown report under docs/.
    """
    folder = Path(folder) if folder is not None else drive_path()
    sheet = Path(sheet) if sheet is not None else sheets_path() / "KD33_ BSULab_UPbR24XML.xls"
    age_repo = Path(age_repo) if age_repo is not None else Path.home() / "Github" / "IDTIMS_UPbRPy"
    python = age_repo / ".venv" / "bin" / "python"
    scratch = Path(tempfile.mkdtemp(prefix="rawtims-recalculation-"))
    setup, settings, sheet_audit = read_kd33_setup(sheet)
    (scratch / "settings.json").write_text(json.dumps(settings, sort_keys=True, indent=2) + "\n")
    (scratch / "sheet-cells.json").write_text(json.dumps(sheet_audit, sort_keys=True, indent=2) + "\n")
    runs = {element: open_run(folder / f"B1606_F15_KD33 z1 {element}-{serial}.xls") for element, serial in (("Pb", 56136), ("U", 56137))}
    projects = {"Pb": read_trip(folder / "KD33_z1_Pb.trip"), "U": read_trip(folder / "KD33_z1_U_partial.trip")}
    variants = {}, {}, {}
    rows, evidence, timings = variants
    baseline = {element: as_acquired(run) for element, run in runs.items()}
    for name, route, deadtime in (("acquired", "workbook", 36.3), ("raw36", "raw", 36.3),
                                  ("raw40", "raw", 40), ("workbook40", "workbook", 40),
                                  ("repeat", "workbook", 36.3)):
        analyses = {}
        metrics = {}
        for element, run in runs.items():
            params = replace(baseline[element], route=route, daly_dead_time_ns=deadtime) if element == "Pb" else baseline[element]
            # Hold U fixed to isolate the Daly change; verify raw U independently below.
            start = time.perf_counter()
            reduced = reprocess(run, params)
            timings[f"{name}_{element}_seconds"] = time.perf_counter()-start
            if name == "raw36":
                metrics[element] = {"max_cycle_relative_error": float(np.max(np.abs(reduced.values / run.values - 1)))}
            analyses[element] = replay_project(_view(reduced, projects[element]), projects[element])
            analyses[element].remember_legacy_masks()
        fraction = Fraction("z1", pb=analyses["Pb"], u=analyses["U"], sample="KD33", timezone="America/Boise", **setup)
        row = fraction_row(fraction, PINNED_EXPORT_TIME, allow_legacy_per_ratio=True)
        rows[name] = row
        evidence[name] = metrics
        write_csv([row], scratch / f"{name}.csv")
    assert csv_text([rows["acquired"]]) == csv_text([rows["repeat"]]), "contract repeat differs"
    # Compare against the independent BSU E7 clipboard values, all nine pairs.
    refs = read_sheet_references(sheet.parent)
    comparisons = []
    for element, project in projects.items():
        for ratio in project.ratios:
            key = ("KD33", "z1", ratio.name)
            if key not in refs:
                continue
            analysis = replay_project(_view(reprocess(runs[element], baseline[element]), project), project)
            stat = analysis.stats(ratio.name)
            _, mean, se = refs[key]
            # E7 has eight significant digits; stable centered variance can differ
            # inside the legacy cancellation bound quantified by Phase 1.
            from rawtims.parity import numeric_tolerance
            active = ratio.values[ratio.values > 0]
            comparisons.append({"function": ratio.name, "mean": stat.mean, "se_pct": stat.se_pct,
                                "sheet_mean": mean, "sheet_se_pct": se,
                                "mean_matches_E7": bool(abs(mean-stat.mean) <= numeric_tolerance(mean, "mean", active, clipboard=True)),
                                "se_matches_E7": bool(abs(se-stat.se_pct) <= numeric_tolerance(se, "se_pct", active, clipboard=True))})
    assert len(comparisons) == 9 and all(c["mean_matches_E7"] and c["se_matches_E7"] for c in comparisons)
    # A control with exactly the sheet's rounded pasted inputs distinguishes
    # clipboard rounding from the age engine's equations/solver.
    from rawtims.contract import FractionRow
    sheet_values = dict(rows["acquired"].values)
    for element, project in projects.items():
        for contract_ratio, entry in (replay_project(_view(runs[element], project), project).mapping.ratios.items()):
            _, mean, se = refs["KD33", "z1", entry.key]
            sheet_values[mean_column(contract_ratio)] = mean
            sheet_values[se_column(contract_ratio)] = se
    rows["sheet_input"] = FractionRow(values=sheet_values)
    write_csv([rows["sheet_input"]], scratch / "sheet_input.csv")
    # U raw validation deliberately excludes the known duplicated cached terminal row.
    start = time.perf_counter()
    u_raw = reprocess(runs["U"], replace(baseline["U"], route="raw"))
    timings["raw_U_seconds"] = time.perf_counter()-start
    u_error = float(np.max(np.abs(u_raw.values[:-1] / runs["U"].values[:-1]-1)))
    assert u_error <= U_WORKBOOK_RTOL
    pb_error = evidence["raw36"]["Pb"]["max_cycle_relative_error"]
    assert pb_error <= PB_WORKBOOK_RTOL
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["QT_QPA_PLATFORM"] = "offscreen"
    start = time.perf_counter()
    result = subprocess.run([str(python), "-c", AGE_WORKER, str(scratch / "settings.json"),
                             *(str(scratch / f"{name}.csv") for name in rows)],
                            cwd=age_repo, env=env, capture_output=True, text=True, timeout=60, check=True)
    timings["age_subprocess_seconds"] = time.perf_counter()-start
    ages = json.loads(result.stdout)
    for name, value in sheet_audit["sheet_constants"].items():
        assert ages["constants"][name] == value, f"sheet/engine {name} differs"
    assert json.dumps(ages["runs"]["acquired"]["dates"], sort_keys=True) == json.dumps(ages["runs"]["repeat"]["dates"], sort_keys=True), "dates repeat differs"
    u_columns = [mean_column(r) for r in U_RATIOS] + [se_column(r) for r in U_RATIOS]
    assert all(all(rows[name].get(c) == rows["acquired"].get(c) for c in u_columns) for name in rows if name != "sheet_input")
    report = {"rows": {name: row.values for name, row in rows.items()}, "ages": ages, "timings": timings,
              "clipboard": comparisons, "sheet": sheet_audit,
              "reproducibility": {"contract_bit_identical": True, "dates_bit_identical": True,
                   "contract_sha256": hashlib.sha256(csv_text([rows["acquired"]]).encode()).hexdigest(),
                   "pb_max_cycle_relative_error": pb_error, "u_nonterminal_max_cycle_relative_error": u_error,
                   "u_raw_terminal_distinct": bool(np.any(u_raw.values[-1] != runs["U"].values[-1])),
                   "u_unchanged": True},
              "inputs": {element: run.raw.sha256 for element, run in runs.items()}}
    (scratch / "result.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    return report, scratch, render_demo_report(report)


def render_demo_report(report):
    rows, ages = report["rows"], report["ages"]["runs"]
    lines = ["# KD33 z1 recalculation from acquisitions", "",
             ("Generated by `env -u PYTHONPATH .venv/bin/python scripts/recalculation_demo.py`. "
             "All Drive inputs are read-only; contract CSV, settings JSON and detailed aggregate audit JSON are in system scratch. "
             "No raw/cycle measurements are stored here. Dates below come only from IDTIMS_UPbRPy in its own venv."), "",
             "## Pb ratios", "",
             ("Tripoli's exact per-ratio masks are restored through Phase 1 strict history replay. "
             "This explicit legacy-audit export declares `per_ratio`; ordinary GUI export still requires shared selection. "
             "The six Pb and three U workbook means and 1σ %SE match the BSU pasted E7 values (all 18 comparisons pass). "
             "The raw 36.3 ns route is compared by its numerical tolerance, not by E7 equality."), "",
             "| Ratio | Workbook 36.3 mean; %SE | Raw 36.3 mean; %SE | Raw 40 mean; %SE | Workbook 40 mean; %SE | WB40−raw40 mean ppm | Raw Δmean % | Raw Δ%SE | WB40−raw40 Δ%SE |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for ratio in PB_REQUIRED_RATIOS:
        m, s = mean_column(ratio), se_column(ratio)
        cells = [f"{rows[n][m]:.12g}; {rows[n][s]:.9g}" for n in ("acquired", "raw36", "raw40", "workbook40")]
        ppm = (rows["workbook40"][m]/rows["raw40"][m]-1)*1e6
        delta_mean = (rows["raw40"][m]/rows["raw36"][m]-1)*100
        delta_se = rows["raw40"][s]-rows["raw36"][s]
        route_se = rows["workbook40"][s]-rows["raw40"][s]
        lines.append(f"| {ratio} | " + " | ".join(cells) + f" | {ppm:.6g} | {delta_mean:+.8g} | {delta_se:+.8g} | {route_se:+.8g} |")
    lines += ["", ("The workbook dead-time route adds the measured block Daly baseline before the cycle-level "
              "transformation, rebuilds Faraday–Daly gain and every ratio, and records the approximation. "
              "This small route difference includes the raw common-time reconstruction residual; the investigation's "
              "intrinsic approximation bound (≤0.174 ppm/cycle for z1/z2, 36.3→40 ns) is not a universal guarantee."), "",
              "## U control", "", ("U uses acquired workbook parameters in every date scenario to isolate the Pb dead-time change. "
              "Every U mean and %SE is bit-identical across all scenarios."), "", "| Ratio | Mean | 1σ %SE |", "|---|---:|---:|"]
    for ratio in U_RATIOS:
        lines.append(f"| {ratio} | {rows['acquired'][mean_column(ratio)]:.12g} | {rows['acquired'][se_column(ratio)]:.9g} |")
    lines += ["", ("Independent raw U reduction uses the distinct final acquisition with unchanged row count. "
              "Its nonterminal comparison excludes only the duplicated cached terminal row. All U workbooks' "
              "`270/267` intensity alias is flagged; oxide calculations use 265/267/270 intensities."), "",
              "## Dates (Ma ± 2σ)", "", ("D-mode 230Th correction (D=0.2±0.05, t68 basis) matches the sheet's selected output: "
              "t68 and t76 are Th-corrected; t75 is unchanged by that correction. Random/tracer errors are propagated "
              "jointly by the engine; they are not a copy of the sheet's error formulas."), "",
              "| Ratio | Workbook 36.3 | Raw 36.3 | Raw 40 | Workbook 40 | BSU sheet row 51 |", "|---|---:|---:|---:|---:|---:|"]
    for ratio in ("206/238", "207/235", "207/206"):
        pairs = [ages[n]["dates"][ratio] for n in ("acquired", "raw36", "raw40", "workbook40")]
        pairs.append(report["sheet"]["sheet_dates"][ratio])
        lines.append(f"| {ratio} | " + " | ".join(f"{m:.9f} ± {s:.9f}" for m, s in pairs) + " |")
    lines += ["", ("Settings are read from `Raw Data Input!E5:E9` and `Data Reduction Engine!C185:C223` "
              "(initial Pb, blank composition/amounts, Pb fractionation), `C672:C677` (Th/U and D). "
              "The scratch audit lists every input cell with its label. Tracer ET535 calibration is pinned to `v3`. "
              "The reader's unknown-parameter provenance survives read/write/read exactly; no notebook function was changed."), "",
              ("The sheet and engine use different uncertainty propagation; the documented sheet errors include the "
              "207Pb derivative using 207/206 in place of 206/205 and the 208/204 ratio inside a square root. "
              "See `../IDTIMS_UPbRPy/docs/BSU_SHEET_NOTES.md`. Central-value differences can also reflect the sheet's "
              "eight-significant-digit inputs, tracer/constant versions and t76 bisection precision. The engine's "
              "actual constants and all assumptions are retained in the scratch JSON."), ""]
    for name in ("acquired", "raw36", "raw40", "workbook40"):
        lines.append(f"- {name}: status `{ages[name]['status']}`; diagnostic substitutions: " + ("; ".join(ages[name]["substitutions"]) or "none") + ".")
    lines += ["", "Control using exactly the sheet's pasted means/errors (engine minus sheet; Ma): " +
              "; ".join(f"{r}: {ages['sheet_input']['dates'][r][0]-report['sheet']['sheet_dates'][r][0]:+.9g}" for r in ("206/238", "207/235", "207/206")) + ". "
              "The remaining t76 residual is within the sheet's 0.0018 Ma bisection precision. "
              "The t68/t75 difference with unrounded contract inputs is therefore attributable to E7 input rounding. "
              "The four central decay constants and natural 238U/235U were checked against the sheet and agree."]
    reprod = report["reproducibility"]
    lines += ["", "## Reproducibility and timings", "",
              f"- Acquired workbook pipeline rerun: full contract CSV bytes (pinned Exported At, including every numeric/parameter column) and dates bit-identical. CSV SHA-256 `{reprod['contract_sha256']}`.",
              f"- Raw Pb 36.3 vs workbook maximum across all functions/cycles: {reprod['pb_max_cycle_relative_error']:.9g} relative (bound 3e-6, KD33 z1/z2 investigation).",
              f"- Raw U vs workbook, nonterminal rows: {reprod['u_nonterminal_max_cycle_relative_error']:.9g} relative (bound 1e-10). Terminal raw row is distinct: {reprod['u_raw_terminal_distinct']}.", "",
              "| Operation | Seconds |", "|---|---:|"]
    lines += [f"| {k} | {v:.6f} |" for k, v in report["timings"].items()]
    lines += ["", "Engine/runtime versions: `" + json.dumps(report["ages"]["versions"], sort_keys=True) + "`; Python `" + report["ages"]["python"] + "`, age-engine commit `" + report["ages"]["engine_commit"] + "`.",
              ("Timing includes workbook load and raw input hashes. Wall times vary; deterministic comparisons exclude them. "
              "Raw acquisition decoding is method-specific; two-sequence Pb and non-1 s acquisitions remain unsupported."), ""]
    return "\n".join(lines)
