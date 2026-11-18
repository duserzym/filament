"""Re-derive intensity/functions, retaining workbook row and function identities.

The raw route corrects individual acquisitions. The workbook route is an
explicit cycle-level approximation for dead-time changes; unchanged numerical
inputs take an exact pass-through. No age calculation belongs in this engine.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np

from rawtims.model import Run
from rawtims.readers.common import invalid_mask
from rawtims.readers.ionvantage_raw import decode_raw, raw_folder, workbook_path
from rawtims.reduction_params import ReductionParameters, as_acquired

PB_INTENSITIES = {
    "Pb204+Hg204 S1 int": (0, "Multiplier"), "204 D": (0, "Multiplier"),
    "Tl205 S2 int": (1, "Multiplier"), "205 D": (1, "Multiplier"),
    "Pb206+At206 S3 int": (2, "Multiplier"), "206 D": (2, "Multiplier"),
    "Pb207 S4 int": (3, "Multiplier"), "207 D": (3, "Multiplier"),
    "Pb206+At206 S2 int": (1, "High1"), "Pb206+At206 S1 int": (0, "High2"),
    "Pb208 S4 int": (3, "High1"), "Pb208 S3 int": (2, "High2"),
}
U_INTENSITIES = {f"UOO{m} S1 int": (0, c) for m, c in ((265, "Low3"), (267, "Low2"), (270, "Axial"))}
U_INTENSITIES.update({str(m): (0, c) for m, c in ((265, "Low3"), (267, "Low2"), (270, "Axial"))})


def change_dead_time(corrected, delta_ns):
    """Algebraic cycle approximation N1=N0/(1-N0*(tau1-tau0))."""
    a = np.asarray(corrected, dtype=float)
    factor = 1 - a * delta_ns * 1e-9
    if np.any(factor <= 0):
        raise ValueError("Daly dead-time change saturates a cycle (1 - cps*delta_tau <= 0)")
    return a / factor


def _functions(run, values, params):
    """Verified method algebra; no evaluation of workbook/vendor formula text."""
    supported = (set(PB_INTENSITIES) | {"Faraday-Daly Gain", "206/204 D", "206/207 D", "206/205 D", "207/205 D", "204/205 D", "208/205 D", "206/208 F H1", "206/208 F H2", "206/208 F average", "208 F (H1)"}
                 if run.element == "Pb" else set(U_INTENSITIES) | {"265/267", "270/265", "270/267"} | {f.key for f in run.functions if f.metadata.get("oxide_corrected")})
    if set(run.keys) - supported:
        from rawtims.readers import UnsupportedFile
        raise UnsupportedFile(f"{run.metadata.method!r}: unverified function formulas {sorted(set(run.keys) - supported)}")
    out = {key: values[:, i] for i, key in enumerate(run.keys)}
    def put(k, v):
        if k in out:
            out[k][:] = v
    if run.element == "Pb":
        required = set(PB_INTENSITIES)
        if not required <= set(out):
            raise ValueError(f"Pb recalculation needs verified four-sequence functions; missing {sorted(required-set(out))}")
        d = {m: out[f"{m} D"] for m in (204, 205, 206, 207)}
        gain = out["Pb206+At206 S2 int"] / d[206]
        put("Faraday-Daly Gain", gain)
        for m, n in ((206, 204), (206, 207), (206, 205), (207, 205), (204, 205)):
            put(f"{m}/{n} D", d[m] / d[n])
        put("208/205 D", out["Pb208 S4 int"] / (gain*d[205]))
        h1 = out["Pb206+At206 S2 int"] / out["Pb208 S4 int"]
        h2 = out["Pb206+At206 S1 int"] / out["Pb208 S3 int"]
        put("206/208 F H1", h1)
        put("206/208 F H2", h2)
        put("206/208 F average", np.sqrt(h1*h2))
        put("208 F (H1)", out["Pb208 S4 int"])
    elif run.element == "U":
        if not {"265", "267", "270"} <= set(out):
            raise ValueError("U recalculation requires the 265, 267 and 270 intensity columns")
        x, y, z = (out[str(m)] for m in (265, 267, 270))
        put("265/267", x / y)
        put("270/265", z / x)
        put("270/267", z if run.metadata.extra.get("270/267_intensity_alias") else z / y)
        if params.oxide_r18 is None:
            raise ValueError("U recalculation requires oxide_r18")
        denom = y - 2 * params.oxide_r18 * x
        for f in run.functions:
            if f.metadata.get("oxide_corrected"):
                pair = (f.numerator_mass, f.denominator_mass)
                put(f.key, {(238, 235): z / denom, (233, 235): x / denom, (238, 233): z / x}[pair])


def reprocess(source, params: ReductionParameters) -> Run:
    """Reprocess a workbook/Run/.raw folder, never modifying the source Run.

    A Run argument supplies identity only: recomputation starts from the original
    workbook rather than compounding earlier parameter changes.
    Unsupported raw methods raise UnsupportedFile. Call reprocess_with_fallback
    for an explicit, warning-bearing fallback to the workbook approximation.
    """
    from rawtims.readers import open_run
    if not isinstance(params, ReductionParameters):
        raise TypeError("params must be ReductionParameters")
    path = Path(source.raw.path) if isinstance(source, Run) else Path(source)
    run = open_run(workbook_path(path) if path.is_dir() else path)
    if isinstance(source, Run):
        if run.raw.sha256 != source.raw.sha256:
            raise ValueError("source workbook changed (SHA-256); reopen it as a new run")
        run.run_id = source.run_id
    acquired = as_acquired(run)
    values = run.values.copy()
    provenance = {"reduction_parameters_sha256": params.sha256, "reduction_route": params.route}
    warnings = list(run.warnings)
    folder = raw_folder(path)
    if params.route == "raw":
        if folder is None:
            from rawtims.readers import UnsupportedFile
            raise UnsupportedFile(f"{run.metadata.method!r}: no accompanying .raw acquisition folder")
        decoded = decode_raw(folder, params)
        if len(decoded.time) != run.n_cycles or not np.array_equal(decoded.block, run.block):
            from rawtims.readers import UnsupportedFile
            raise UnsupportedFile(f"{decoded.method!r}: raw/workbook cycle correspondence differs; saved masks cannot safely apply")
        intensities = PB_INTENSITIES if run.element == "Pb" else U_INTENSITIES
        for key, (seq, collector) in intensities.items():
            if key in run.keys:
                values[:, run.function(key).index] = decoded.intensities[:, seq, decoded.collectors.index(collector)]
        warnings.extend(decoded.warnings)
        run.time = decoded.time
        provenance["raw_inputs"] = decoded.hashes
        provenance["raw_folder"] = str(folder.resolve())
        if run.element == "U" and run.warnings:
            warnings.append("raw U terminal acquisition differs from cached workbook row; no row was added or removed")
        _functions(run, values, params)
    elif replace(params, route="workbook") == acquired:
        # Do not even divide/multiply by one: repr and every numeric bit survive.
        provenance["identity"] = "as-acquired workbook values; no recomputation"
    else:
        # Only operations recoverable from cached cycle intensities are allowed.
        for name in ("beam_interpolation", "integration_rejection", "apply_baselines", "apply_faraday_gains", "correct_dead_time",
                     "adc_zero", "adc_volts_per_code", "electron_charge_c", "faraday_resistors_ohm", "multiplier_gain"):
            if getattr(params, name) != getattr(acquired, name):
                raise ValueError(f"changing {name} requires route raw")
        if params.baseline.mode == "measured":
            raise ValueError("measured baselines require route raw")
        if set(params.faraday_gains) != set(acquired.faraday_gains):
            raise ValueError("faraday_gains must retain the acquired collector keys")
        intensities = PB_INTENSITIES if run.element == "Pb" else U_INTENSITIES
        baseline = None
        if params.daly_dead_time_ns != acquired.daly_dead_time_ns and run.element == "Pb":
            if params.daly_dead_time_ns is None or acquired.daly_dead_time_ns is None:
                raise ValueError("workbook dead-time change requires acquired and requested dead times")
            warnings.append("cycle-level dead-time approximation; individual acquisitions are unavailable in this route")
            provenance["approximation"] = "cycle-level dead-time approximation"
            if folder is not None:
                from rawtims.readers import UnsupportedFile
                try:
                    decoded = decode_raw(folder, replace(acquired, route="raw"))
                except (UnsupportedFile, OSError) as error:
                    warnings.append(f"measured baseline unavailable: {error}")
                else:
                    if len(decoded.baselines) != run.n_cycles:
                        raise ValueError("baseline/workbook cycle correspondence differs")
                    baseline = decoded.baselines[:, decoded.collectors.index("Multiplier")]
                    provenance.update(raw_inputs=decoded.hashes, raw_folder=str(folder.resolve()))
            if baseline is None:
                warnings.append("full baseline history unavailable; dead-time approximation uses zero baseline")
        for key, (_seq, collector) in intensities.items():
            if key not in run.keys:
                continue
            col = run.function(key).index
            if collector == "Multiplier":
                if params.daly_dead_time_ns != acquired.daly_dead_time_ns:
                    b = 0 if baseline is None else baseline
                    values[:, col] = change_dead_time(values[:, col] + b, params.daly_dead_time_ns - acquired.daly_dead_time_ns) - b
            elif params.apply_faraday_gains and params.faraday_gains != acquired.faraday_gains:
                if collector not in params.faraday_gains:
                    raise ValueError(f"gain rescaling requires an acquired and requested gain for {collector}")
                values[:, col] *= params.faraday_gains[collector] / acquired.faraday_gains[collector]
            values[:, col] -= params.baseline.offsets.get(collector, 0)
        _functions(run, values, params)
    if run.element == "U" and "identity" not in provenance:
        provenance["oxide_recomputed"] = True
    # Names/keys stay stable for masks; metadata records the *actual* oxide r18.
    functions = tuple(replace(f, metadata={**f.metadata, "oxide_r18": params.oxide_r18})
                      if f.metadata.get("oxide_corrected") and params.oxide_r18 is not None else f for f in run.functions)
    return replace(run, functions=functions, values=values, invalid=invalid_mask(values, functions),
                   reduction_parameters=params, warnings=tuple(warnings), provenance=provenance)


def reprocess_with_fallback(source, params):
    """Explicit unknown-method fallback, preserving the actual route and warning."""
    from rawtims.readers import UnsupportedFile
    try:
        return reprocess(source, params)
    except UnsupportedFile as error:
        if params.route != "raw":
            raise
        run = reprocess(source, replace(params, route="workbook"))
        run.warnings += (f"raw route unavailable: {error}; used workbook route",)
        return run
