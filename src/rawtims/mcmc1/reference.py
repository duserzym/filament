"""Deterministic updater arithmetic only; no random proposals or sampling.

Copyright 2022 James Bowring, Noah McLean, Scott Burdick, and CIRDLES.org.
Apache-2.0 (../resources/LICENSE-APACHE-2.0). Python adaptation, 2026-11-26.
Source: Java Tripoli 00dc941, TripoliCore/src/main/java/org/cirdles/tripoli/
sessions/analysis/massSpectrometerModels/dataModels/mcmc/.
"""

from dataclasses import dataclass

import numpy as np

from rawtims.mcmc1.forward import Parameters, array


@dataclass(frozen=True)
class Priors:
    """ProposedModelParameters.java:59-66; reference bounds, not lab settings."""

    baseline_faraday: tuple = (-np.inf, np.inf)
    baseline_daly: tuple = (0.0, 0.0)
    log_ratio: tuple = (-20.0, 20.0)
    intensity: tuple = (0.0, np.inf)
    gain: tuple = (0.0, np.inf)
    noise_faraday: tuple = (0.0, 1e6)
    noise_daly: tuple = (0.0, 0.0)
    poisson_daly: tuple = (0.0, 10.0)


PRIORS = Priors()


def apply_delta(parameters: Parameters, delta):
    """SingleBlockModelUpdater.java:96-197, allFlag: reject bounds per component.

    A zero gain proposal is in Java's prior but undefined for forward evaluation;
    this API refuses it through Parameters' domain check.
    """
    original = parameters.vector
    delta = array(delta)
    if delta.shape != original.shape:
        raise ValueError("Delta dimensions differ from parameter vector")
    r, k, b = map(len, (parameters.log_ratios, parameters.knots, parameters.baselines))
    bounds = np.array(
        [PRIORS.log_ratio] * r
        + [PRIORS.intensity] * k
        + [PRIORS.baseline_faraday] * b
        + [PRIORS.gain]
    )
    updated = original + delta
    outside = (updated < bounds[:, 0]) | (updated > bounds[:, 1])
    updated[outside] = original[outside]
    return Parameters(
        updated[:r],
        updated[r : r + k],
        updated[r + k : r + k + b],
        parameters.baseline_sd,
        float(updated[-1]),
    )


def update_mean_covariance(parameters: Parameters, covariance, mean, count: int):
    """SingleBlockModelUpdater.java:204-254, literal Java recurrence.

    Retains Java's extra (m-1)/m factor relative to a conventional online
    population covariance update. This is reference arithmetic, not a new
    statistical estimator used by the existing reduction core.
    """
    mean, covariance = array(mean), array(covariance, ndim=2)
    vector = parameters.vector
    if type(count) is not int or count < 1:
        raise ValueError("Count must be a positive integer")
    if mean.shape != vector.shape or covariance.shape != (len(vector), len(vector)):
        raise ValueError("Mean/covariance dimensions differ from parameters")
    difference = vector - mean
    updated_mean = mean + difference / count
    updated_covariance = covariance * ((count - 1.0) / count) + np.outer(
        (vector - updated_mean) * ((count - 1.0) / count**2), difference
    )
    return array(updated_covariance, ndim=2), array(updated_mean)
