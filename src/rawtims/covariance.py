"""Unused-by-default covariance validators. No expression or export propagation."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MatrixValidity:
    valid: bool
    issues: tuple[str, ...]
    minimum_eigenvalue: float | None


def validate_covariance(names, matrix, *, relative_tolerance=1e-12) -> MatrixValidity:
    """Check labeled finite symmetry and PSD, accepting singular covariance.

    Tolerance scales with matrix magnitude (no unit-dependent absolute floor).
    No matrix is repaired or symmetrized for the caller. Roundoff symmetry is
    averaged only for the eigenvalue check. Negative variances always fail.
    """
    names = tuple(names)
    issues = []
    if not names or any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names):
        issues.append('Names must be nonempty and unique')
    if not np.isfinite(relative_tolerance) or not 0 <= relative_tolerance <= 1e-6:
        raise ValueError('Tolerance must be finite and between 0 and 1e-6')
    values = np.asarray(matrix, dtype=float)
    if values.shape != (len(names), len(names)):
        return MatrixValidity(False, tuple(issues + ['Matrix shape must match names']), None)
    if not np.all(np.isfinite(values)):
        return MatrixValidity(False, tuple(issues + ['Matrix contains missing or nonfinite entries']), None)
    scale = float(np.max(np.abs(values))) if values.size else 0.
    tolerance = relative_tolerance * scale
    if np.any(np.diag(values) < 0):
        issues.append('Negative variance')
    if not np.all(np.abs(values - values.T) <= tolerance):
        return MatrixValidity(False, tuple(issues + ['Matrix is not symmetric']), None)
    minimum = float(np.linalg.eigvalsh((values / 2 + values.T / 2) / scale)[0]) * scale if scale else 0.
    if minimum < -tolerance:
        issues.append('Matrix is not positive semidefinite')
    return MatrixValidity(not issues, tuple(issues), minimum)


def measured_correlation_to_covariance(names, standard_errors, correlations):
    """Return D R D from absolute 1σ errors and a complete measured correlation matrix.

    Missing correlations must stay unknown: NaN is refused, never filled with
    zero. A pairwise-valid R may still be non-PSD (e.g. differing cycle masks).
    """
    names = tuple(names)
    errors = np.asarray(standard_errors, dtype=float)
    if errors.shape != (len(names),) or not np.all(np.isfinite(errors)) or np.any(errors < 0):
        raise ValueError('Absolute standard errors must be finite and nonnegative, one per name')
    rho = np.asarray(correlations, dtype=float)
    validity = validate_covariance(names, rho)
    if not validity.valid:
        raise ValueError('; '.join(validity.issues))
    if not np.all(np.diag(rho) == 1) or np.any(np.abs(rho) > 1):
        raise ValueError('Correlation diagonal must be one and entries in [-1, 1]')
    with np.errstate(over='ignore', invalid='ignore'):
        covariance = errors[:, None] * rho * errors[None, :]
    validity = validate_covariance(names, covariance)
    if not validity.valid:
        raise ValueError('; '.join(validity.issues))
    return covariance


def covariance_to_measured_correlation(names, matrix):
    """Normalize S as D^-1 S D^-1; zero uncertainty makes correlation undefined."""
    validity = validate_covariance(names, matrix)
    if not validity.valid:
        raise ValueError('; '.join(validity.issues))
    values = np.asarray(matrix, dtype=float)
    errors = np.sqrt(np.diag(values))
    if np.any(errors <= 0):
        raise ValueError('Correlation is undefined for zero uncertainty')
    rho = values / errors[:, None] / errors[None, :]
    if np.any(np.abs(rho) > 1 + 1e-12):
        raise ValueError('Measured correlation outside [-1, 1]')
    return np.clip(rho, -1, 1)
