"""Deterministic MCMC1 research preview; never a reduction or export route.

Copyright 2022 James Bowring, Noah McLean, Scott Burdick, and CIRDLES.org.
Apache-2.0 (../resources/LICENSE-APACHE-2.0). Adapted to Python/NumPy with
explicit validation and independent arrays, 2026-11-26. Java Tripoli 00dc941:
TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/
massSpectrometerModels/dataModels/mcmc/initializers/SingleBlockModelInitForMCMC.java.
"""

from dataclasses import dataclass

import numpy as np

from rawtims.intensity_matrices import java_spline_basis, linear_cycle_matrix


def array(value, *, ndim=1, integer=False, boolean=False):
    raw = np.asarray(value)
    if integer and raw.dtype.kind not in "iu":
        raise ValueError("Indices must be integers")
    if boolean and raw.dtype.kind != "b":
        raise ValueError("Inclusion must be boolean")
    result = np.array(
        value, dtype=bool if boolean else int if integer else float, copy=True
    )
    if result.ndim != ndim or not np.isfinite(result).all():
        raise ValueError("Require finite arrays with the declared dimensions")
    result.setflags(write=False)
    return result


def intensity_basis(times, cycle_starts, *, kind="linear"):
    """SingleBlockModelDriver.java:172-233; cubic has cycles+1 columns too."""
    linear = linear_cycle_matrix(times, cycle_starts)  # validates both inputs
    if kind == "linear":
        return linear
    if kind != "cubic":
        raise ValueError("Intensity basis must be linear or cubic")
    segments = linear.shape[1] - 3
    if segments < 1:
        raise ValueError("Cubic basis requires at least three cycles")
    return java_spline_basis(times, segments, 3)


@dataclass(frozen=True)
class Observations:
    """Prepared vectors in Java order: baseline, on-peak Faraday, on-peak PM.

    Species: baseline=0, other species=1..N-1, denominator=N. Detector ordinals
    are explicit; PM ordinals never index baseline parameters. Time indices on
    baselines are retained but never used to index the on-peak basis.
    """

    observed: np.ndarray
    detector: np.ndarray
    species: np.ndarray
    time_index: np.ndarray
    included: np.ndarray
    basis: np.ndarray
    baseline_count: int
    faraday_count: int  # number of on-peak observations, not detectors
    species_count: int

    def __post_init__(self):
        for name in (
            "observed",
            "detector",
            "species",
            "time_index",
            "included",
            "basis",
        ):
            object.__setattr__(
                self,
                name,
                array(
                    getattr(self, name),
                    ndim=2 if name == "basis" else 1,
                    integer=name in ("detector", "species", "time_index"),
                    boolean=name == "included",
                ),
            )
        n = len(self.observed)
        if any(
            len(getattr(self, name)) != n
            for name in ("detector", "species", "time_index", "included")
        ):
            raise ValueError("Observation vectors must have equal lengths")
        b, f, s = self.baseline_count, self.faraday_count, self.species_count
        if (
            any(type(v) is not int for v in (b, f, s))
            or b < 1
            or f < 0
            or b + f > n
            or s < 2
        ):
            raise ValueError("Invalid observation partition/species counts")
        if min(self.basis.shape) < 1 or np.any(self.detector < 0):
            raise ValueError("Empty basis or negative detector index")
        if (
            np.any(self.species[:b] != 0)
            or np.any(self.species[b:] < 1)
            or np.any(self.species[b:] > s)
        ):
            raise ValueError("Baseline species must be 0; on-peak species must be 1..N")
        if np.any(self.time_index < 0) or np.any(
            self.time_index[b:] >= len(self.basis)
        ):
            raise ValueError("On-peak time index outside intensity basis")
        if not set(self.detector[b : b + f]) <= set(self.detector[:b]):
            raise ValueError("On-peak Faraday detector has no baseline")

    @property
    def faraday_ordinals(self):
        return tuple(int(i) for i in np.unique(self.detector[: self.baseline_count]))

    @property
    def parameter_count(self):
        return (
            self.species_count
            - 1
            + self.basis.shape[1]
            + len(self.faraday_ordinals)
            + 1
        )


@dataclass(frozen=True)
class Parameters:
    log_ratios: np.ndarray
    knots: np.ndarray
    baselines: np.ndarray  # ascending Faraday detector ordinal
    baseline_sd: np.ndarray  # sample SD, not SE
    gain: float

    def __post_init__(self):
        for name in ("log_ratios", "knots", "baselines", "baseline_sd"):
            object.__setattr__(self, name, array(getattr(self, name)))
        if len(self.baselines) != len(self.baseline_sd) or np.any(self.baseline_sd < 0):
            raise ValueError("Baseline mean/SD dimensions differ or SD is negative")
        if not np.isfinite(self.gain) or self.gain <= 0:
            raise ValueError("Gain must be finite and positive")

    @property
    def vector(self):
        """SingleBlockModelRecord.java:75; updater order ratios, knots, BL, gain."""
        return np.r_[self.log_ratios, self.knots, self.baselines, self.gain]


def _parts(data, parameters):
    b, end = data.baseline_count, data.baseline_count + data.faraday_count
    if (
        len(parameters.log_ratios) != data.species_count - 1
        or len(parameters.knots) != data.basis.shape[1]
        or len(parameters.baselines) != len(data.faraday_ordinals)
    ):
        raise ValueError("Parameter dimensions do not match prepared observations")
    index = {ordinal: i for i, ordinal in enumerate(data.faraday_ordinals)}
    det = np.array([index[int(i)] for i in data.detector[:end]])
    intensity = data.basis @ parameters.knots
    with np.errstate(over="ignore", invalid="ignore"):
        ratios = np.exp(np.r_[parameters.log_ratios, 0.0])
        signal = ratios[data.species[b:] - 1] * intensity[data.time_index[b:]]
    signal[: data.faraday_count] /= parameters.gain
    if not np.isfinite(signal).all():
        raise ValueError("Forward signal is non-finite")
    return b, end, det, signal


def forward(data: Observations, parameters: Parameters):
    """SingleBlockModelInitForMCMC.java:814-863: PM has no baseline or gain."""
    b, end, det, signal = _parts(data, parameters)
    model = np.r_[parameters.baselines[det[:b]], signal]
    model[b:end] += parameters.baselines[det[b:end]]
    return array(model)


def noise_variance(data: Observations, parameters: Parameters):
    """Initializer.java:366-396: Dsig is VARIANCE; 0.1 s and PM factor 2."""
    b, end, det, signal = _parts(data, parameters)
    variance = np.r_[parameters.baseline_sd[det[:b]] ** 2, signal / 0.1]
    variance[b:end] += parameters.baseline_sd[det[b:end]] ** 2
    variance[end:] *= 2.0
    if np.any(variance < 0) or not np.isfinite(variance).all():
        raise ValueError("Noise variance must be finite and nonnegative")
    return array(variance)


@dataclass(frozen=True)
class Evaluation:
    model: np.ndarray
    residual: np.ndarray
    variance: np.ndarray
    count: int
    weighted_error: float
    unweighted_error: float
    log_kernel: float  # Java non-noise acceptance: -E/2 with fixed Dsig
    gaussian_log_likelihood: float  # includes normalizing terms; distinct from kernel


def evaluate(
    data: Observations, parameters: Parameters, *, variance=None, included=None
):
    """MCMCProcess.java:243-251,392-437; caller may freeze initialized Dsig.

    Default selection matches Java's initial included-only misfit. To reproduce
    its later all-row proposal loop, explicitly pass an all-True vector. Baseline
    multipliers and temperature are 1 in the pinned Java defaults (152-156).
    """
    model = forward(data, parameters)
    var = noise_variance(data, parameters) if variance is None else array(variance)
    use = data.included if included is None else array(included, boolean=True)
    if len(var) != len(model) or len(use) != len(model):
        raise ValueError("Variance/inclusion dimensions differ from observations")
    if np.any(var < 0) or np.any(var[use] <= 0):
        raise ValueError("Selected likelihood rows need strictly positive variance")
    residual = array(data.observed - model)
    squared = residual[use] ** 2
    error = float(np.sum(squared / var[use]))
    log_normalizer = float(np.sum(np.log(2.0 * np.pi * var[use])))
    return Evaluation(
        model,
        residual,
        var,
        int(use.sum()),
        error,
        float(squared.sum()),
        -0.5 * error,
        -0.5 * (error + log_normalizer),
    )
