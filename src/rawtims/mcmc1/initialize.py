"""Opt-in MCMC1 initialization and the pinned two-isotope synthetic adapter.

Copyright 2022 James Bowring, Noah McLean, Scott Burdick, and CIRDLES.org.
Apache-2.0 (../resources/LICENSE-APACHE-2.0). Python/NumPy adaptation, 2026-11-26.
Java 00dc941, TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/:
massSpectrometerModels/dataModels/mcmc/initializers/SingleBlockModelInitForMCMC.java
and methods/AnalysisMethodBuiltinFactory.java:54-91.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

import numpy as np

from rawtims.mcmc1.forward import (
    Evaluation,
    Observations,
    Parameters,
    evaluate,
    intensity_basis,
)
from rawtims.synthetic_acquisition import SyntheticAcquisition


@dataclass(frozen=True)
class Initialization:
    parameters: Parameters
    evaluation: Evaluation
    gain_fallback_reason: str | None
    schema: str = "rawtims-mcmc1-research/1"


def _solve(matrix, values):
    solution, _, rank, _ = np.linalg.lstsq(matrix, values, rcond=None)
    if rank != matrix.shape[1]:
        raise ValueError("Intensity design is rank deficient")
    return solution


def initialize(data: Observations):
    """Initializer.java:70-181,222-267,366-438,684-810.

    Supported initialization domain: one observation per species at each basis
    time. Refuse incomplete/duplicate grids rather than invent Java indexing.
    Included flags gate ratio means with the denominator mask. As in Java,
    baseline, gain and denominator intensity fits use all their observations.
    Gain's Java exception fallback (0.9) is returned with a reason, never hidden.
    """
    b, end = data.baseline_count, data.baseline_count + data.faraday_count
    ordinals = data.faraday_ordinals
    means, sd = [], []
    for ordinal in ordinals:
        values = data.observed[:b][data.detector[:b] == ordinal]
        means.append(values.mean())
        sd.append(values.std(ddof=1) if len(values) > 1 else 0.0)
    means, sd = np.array(means), np.array(sd)
    mapping = {ordinal: i for i, ordinal in enumerate(ordinals)}
    corrected = data.observed.copy()
    corrected[:end] -= means[[mapping[int(d)] for d in data.detector[:end]]]
    rows = []
    for species in range(1, data.species_count + 1):
        selected = np.flatnonzero(data.species == species)
        selected = selected[np.argsort(data.time_index[selected], kind="stable")]
        if not np.array_equal(data.time_index[selected], np.arange(len(data.basis))):
            raise ValueError(
                "Initialization needs one observation per species at each basis time"
            )
        rows.append(selected)
    denominator = rows[-1]
    pm = denominator >= end
    reason = None
    gain = 0.9
    try:
        far_knots = _solve(data.basis[~pm], corrected[denominator[~pm]])
        pm_knots = _solve(data.basis[pm], corrected[denominator[pm]])
        if len(far_knots) < 3 or np.any(far_knots[1:-1] == 0):
            raise ValueError("No usable interior Faraday knots")
        gain = float(np.mean(pm_knots[1:-1] / far_knots[1:-1]))
        if not np.isfinite(gain) or gain <= 0:
            raise ValueError("Estimated gain is nonpositive or non-finite")
    except ValueError as exc:
        gain, reason = 0.9, str(exc)
    corrected[b:end] *= gain
    knots = _solve(data.basis, corrected[denominator])
    intensity = data.basis @ knots
    if np.any(intensity <= 0):
        raise ValueError("Initialization needs positive denominator intensity")
    logs = []
    for selected in rows[:-1]:
        use = data.included[selected] & data.included[denominator]
        if not use.any():
            raise ValueError(
                "No jointly included observations for ratio initialization"
            )
        # Java 260/266 uses comparatorTimeIso.array (UNSORTED time indices)
        # after sorting dd. Preserve this mismatch; do not silently repair it.
        original = np.flatnonzero(data.species == data.species[selected[0]])
        ratio = np.mean(
            corrected[selected][use] / intensity[data.time_index[original]][use]
        )
        logs.append(np.log(max(ratio, np.exp(-20.0))))
    parameters = Parameters(logs, knots, means, sd, gain)
    return Initialization(parameters, evaluate(data, parameters), reason)


def _rounded_counts(value):
    # MatLab.java:33-40: decimal-string significant figures, ties away from zero.
    decimal = Decimal(str(value))
    return float(
        decimal.quantize(
            Decimal(1).scaleb(decimal.adjusted() - 11), rounding=ROUND_HALF_UP
        )
    )


def prepare_two_isotope_synthetic(
    acquisition: SyntheticAcquisition, *, block=1, kind="linear"
):
    """BuiltinFactory.java:54-91; SingleBlockDataAccumulatorMCMC.java:47-187.

    ONLY Java synthetic Version 1.00 ten-column two-isotope layout. Ax S2=206,
    PM S1=206, PM S2=208, H1 S1=208; BL1 on Ax/H1. No lab mapping inferred.
    Accumulator keeps synthetic counts unchanged (no Full volts conversion).
    Java rounds to 12 significant figures; supplied K values already fit that.
    """
    if not isinstance(acquisition, SyntheticAcquisition):
        raise TypeError("Expected a parsed Java synthetic acquisition")
    expected = (
        "ID",
        "Block",
        "Cycle",
        "Integ",
        "Time",
        "Mass",
        "Low5",
        "Low4",
        "Low3",
        "Low2",
        "Ax Fara",
        "Axial",
        "High1",
        "High2",
        "High3",
        "High4",
    )
    if acquisition.columns != expected or type(block) is not int:
        raise ValueError("Only the pinned two-isotope synthetic layout is supported")
    matches = [b for b in acquisition.blocks if b.number == block]
    if len(matches) != 1:
        raise ValueError("Synthetic block not found")
    source = matches[0]
    if (
        not source.baseline
        or any(r.sequence != "BL1" for r in source.baseline)
        or {r.sequence for r in source.on_peak} != {"S1", "S2"}
    ):
        raise ValueError("Expected BL1 and S1/S2 synthetic sequences")
    basis = intensity_basis(
        [r.time for r in source.on_peak], source.cycle_starts, kind=kind
    )
    records = []
    # Each tuple: source row, detector ordinal, species ordinal, time row, included.
    for detector in (4, 6):
        records.extend(
            (r, detector, 0, i, False) for i, r in enumerate(source.baseline)
        )
    baseline_count = len(records)
    for detector, sequence, species in ((4, "S2", 1), (6, "S1", 2)):
        records.extend(
            (r, detector, species, i, True)
            for i, r in enumerate(source.on_peak)
            if r.sequence == sequence
        )
    faraday_count = len(records) - baseline_count
    for sequence, species in (("S1", 1), ("S2", 2)):
        records.extend(
            (r, 5, species, i, True)
            for i, r in enumerate(source.on_peak)
            if r.sequence == sequence
        )
    return Observations(
        [_rounded_counts(r.intensities[d]) for r, d, _, _, _ in records],
        [d for _, d, _, _, _ in records],
        [s for _, _, s, _, _ in records],
        [t for _, _, _, t, _ in records],
        [inc for _, _, _, _, inc in records],
        basis,
        baseline_count,
        faraday_count,
        2,
    )
