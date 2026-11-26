"""Opt-in Java reference intensity matrices; no reduction routes use these.

Copyright 2022 James Bowring, Noah McLean, Scott Burdick, and CIRDLES.org.
Apache-2.0 (see resources/LICENSE-APACHE-2.0). Changed by this project's contributors:
Python/NumPy implementation with explicit shape/domain checks, 2026-11-26.
Reference: TripoliCore/src/main/java/org/cirdles/tripoli/utilities/mathUtilities/
SplineBasisModel.java:38-160 and sessions/analysis/massSpectrometerModels/
dataModels/mcmc/SingleBlockModelDriver.java:189-233 (00dc941).
"""

import math

import numpy as np


def _times(values):
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or len(x) < 2 or not np.isfinite(x).all() or np.any(np.diff(x) <= 0):
        raise ValueError(
            "Times must be a finite, strictly increasing vector of at least two entries"
        )
    return x


def java_spline_basis(times, segments: int, degree: int, *, lower=None, upper=None):
    """Java truncated-power/difference basis, rows=time, columns=segments+degree.

    Explicit bounds expand to include the observed endpoints, as in Java's
    five-argument overload. The endpoint support mask is strict (<).
    """
    x = _times(times)
    if (
        type(segments) is not int
        or segments < 1
        or type(degree) is not int
        or not 0 <= degree <= 12
    ):
        raise ValueError("Require positive integer segments and integer degree 0..12")
    xl, xr = (
        x[0] if lower is None else float(lower),
        x[-1] if upper is None else float(upper),
    )
    if not np.isfinite([xl, xr]).all() or xl >= xr:
        raise ValueError("Spline bounds must be finite and ordered")
    xl, xr = min(xl, x[0]), max(xr, x[-1])
    dx = (xr - xl) / segments
    knots = np.linspace(xl - degree * dx, xr + degree * dx, segments + 2 * degree + 1)
    delta = x[:, None] - knots
    powers = delta**degree * (delta >= 0)
    differences = np.diff(np.eye(len(knots)), n=degree + 1, axis=0)
    basis = powers @ differences.T / (math.factorial(degree) * dx**degree)
    return basis * (x[:, None] < knots[degree + 1 :])


def linear_cycle_matrix(times, cycle_starts):
    """SingleBlockModelDriver.java:189-233, including final observed-time knot."""
    x = _times(times)
    starts = np.asarray(cycle_starts)
    if (
        starts.ndim != 1
        or not len(starts)
        or starts.dtype.kind not in "iu"
        or starts[0] != 0
        or np.any(np.diff(starts) <= 0)
        or starts[-1] >= len(x) - 1
    ):
        raise ValueError(
            "Cycle starts must be ordered integer row indices from 0; last cycle needs two times"
        )
    knots = x[np.r_[starts, len(x) - 1]]
    result = np.zeros((len(x), len(knots)))
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(x) - 1
        rows = np.arange(start, end)
        fraction = (x[rows] - knots[i]) / (knots[i + 1] - knots[i])
        result[rows, i] = 1 - fraction
        result[rows, i + 1] = fraction
    result[-1, -1] = 1.0
    return result


def spline_basis(times, segments: int, degree: int, *, lower=None, upper=None):
    """Oracle K/MATLAB positive basis convention.

    Java 00dc941 omits (-1)**(degree+1): its even-degree output has the
    opposite sign to its committed answers. Keep the literal Java function
    separately available; never conceal this discrepancy with abs/tolerance.
    """
    return (-1) ** (degree + 1) * java_spline_basis(
        times, segments, degree, lower=lower, upper=upper
    )
