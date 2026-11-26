"""Headless research model tests; Java paths below are relative to Tripoli 00dc941.

Oracle K/M checks use committed synthetic resources and stored assertions only.
Source-formula comparisons are identified separately from Java runtime execution.
"""

import json
import math
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from rawtims.mcmc1.forward import (
    Observations,
    Parameters,
    evaluate,
    forward,
    intensity_basis,
    noise_variance,
)
from rawtims.mcmc1.initialize import initialize, prepare_two_isotope_synthetic
from rawtims.mcmc1.reference import PRIORS, apply_delta, update_mean_covariance
from rawtims.synthetic_acquisition import read_java_synthetic

FIXTURES = Path(__file__).parent / "fixtures/tripoli"


def scalar():
    # SYNTHETIC: BL Ax [-2,0,2], H1 [8,10,12]; peak Far species 1,2; PM 1,2.
    data = Observations(
        [-2, 0, 2, 8, 10, 12, 12, 40, 5, 20],
        [4, 4, 4, 6, 6, 6, 4, 6, 5, 5],
        [0] * 6 + [1, 2, 1, 2],
        [0] * 6 + [0, 1, 0, 1],
        [False] * 6 + [True] * 4,
        [[1, 0], [0, 1]],
        6,
        2,
        2,
    )
    return data, Parameters([math.log(0.5)], [10, 20], [0, 10], [2, 2], 0.5)


def test_source_forward_noise_and_likelihood_scalar():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/initializers/SingleBlockModelInitForMCMC.java:366-396,814-870;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/MCMCProcess.java:243-251,392-437.
    Hand-computed signed residual and noise VARIANCE, including PM factor 2.
    """
    data, params = scalar()
    np.testing.assert_allclose(
        forward(data, params), [0, 0, 0, 10, 10, 10, 10, 50, 5, 20]
    )
    variance = [4] * 6 + [104, 404, 100, 400]
    np.testing.assert_allclose(noise_variance(data, params), variance)
    result = evaluate(data, params)
    assert result.count == 4
    assert result.unweighted_error == 104
    chi = 4 / 104 + 100 / 404
    assert result.weighted_error == pytest.approx(chi)
    assert result.log_kernel == pytest.approx(-chi / 2)
    assert result.gaussian_log_likelihood == pytest.approx(
        -0.5 * (chi + sum(math.log(2 * math.pi * v) for v in variance[6:]))
    )
    all_rows = evaluate(data, params, included=np.ones(10, bool))
    assert all_rows.weighted_error == pytest.approx(chi + 4)
    assert all_rows.count == 10
    assert all_rows.unweighted_error == 120
    # Java holds initialized Dsig fixed during parameter proposals.
    changed = replace(params, gain=1.0)
    fixed = evaluate(data, changed, variance=result.variance)
    assert not np.array_equal(fixed.variance, noise_variance(data, changed))
    np.testing.assert_array_equal(fixed.variance, result.variance)
    assert data.parameter_count == len(params.vector) == 6
    assert not result.model.flags.writeable and not result.residual.flags.writeable


def truth_grid():
    """SYNTHETIC independently specified noiseless on-peak truth; noisy BL SD=2."""
    times = np.arange(12.0)
    basis = intensity_basis(times, [0, 4, 8])
    # Hand linear interpolation from knots [100,120,140,160].
    intensity = np.array(
        [100, 105, 110, 115, 120, 125, 130, 135, 140, 146 + 2 / 3, 153 + 1 / 3, 160]
    )
    obs, det, sp, ti = [-2, 0, 2, 8, 10, 12], [4] * 3 + [6] * 3, [0] * 6, [0] * 6
    far, pm = [], []
    for species in (1, 2):
        for i in range(12):
            use_faraday = i % 4 < 2
            signal = intensity[i] * (0.5 if species == 1 else 1)
            if use_faraday:
                far.append(
                    (
                        signal / 0.8 + (0 if species == 1 else 10),
                        4 if species == 1 else 6,
                        species,
                        i,
                    )
                )
            else:
                pm.append((signal, 5, species, i))
    for value, detector, species, time in far + pm:
        obs.append(value)
        det.append(detector)
        sp.append(species)
        ti.append(time)
    return Observations(obs, det, sp, ti, [False] * 6 + [True] * 24, basis, 6, 12, 2)


def test_synthetic_initialization_gain_knots_and_literal_java_ratio():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/initializers/SingleBlockModelInitForMCMC.java:70-181,222-267,684-810.
    Known scalar truth; also exposes Java sorted-data/unsorted-time ratio bias.
    """
    data = truth_grid()
    result = initialize(data)
    p = result.parameters
    np.testing.assert_allclose(p.baselines, [0, 10], atol=1e-12)
    np.testing.assert_allclose(p.baseline_sd, [2, 2], atol=1e-12)
    np.testing.assert_allclose(p.knots, [100, 120, 140, 160], atol=1e-11)
    assert p.gain == pytest.approx(0.8, abs=1e-14)
    # Java divides time-sorted observations by an unsorted intensity vector.
    intensity = [
        100,
        105,
        110,
        115,
        120,
        125,
        130,
        135,
        140,
        146 + 2 / 3,
        153 + 1 / 3,
        160,
    ]
    original_times = [0, 1, 4, 5, 8, 9, 2, 3, 6, 7, 10, 11]
    expected_ratio = (
        sum(0.5 * value / intensity[t] for value, t in zip(intensity, original_times))
        / 12
    )
    assert p.log_ratios[0] == pytest.approx(math.log(expected_ratio), abs=1e-14)
    assert expected_ratio != pytest.approx(0.5)
    assert result.gain_fallback_reason is None
    # Ratio means use the joint numerator/denominator mask, not all points.
    changed = data.observed.copy()
    changed[6] = 1e8
    included = data.included.copy()
    included[6] = False
    excluded = initialize(replace(data, observed=changed, included=included))
    expected_excluded = (
        sum(
            0.5 * value / intensity[t]
            for value, t in zip(intensity[1:], original_times[1:])
        )
        / 11
    )
    assert excluded.parameters.log_ratios[0] == pytest.approx(
        math.log(expected_excluded), abs=1e-14
    )
    np.testing.assert_allclose(excluded.parameters.knots, p.knots, atol=1e-11)


@pytest.mark.parametrize("index", [1, 2])
@pytest.mark.parametrize("kind", ["linear", "cubic"])
def test_oracle_k_preparation_initialization_and_scalar_forward(index, kind):
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethodBuiltinFactory.java:54-91;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockDataAccumulatorMCMC.java:47-187;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelDriver.java:172-233;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/initializers/SingleBlockModelInitForMCMC.java:70-181,366-396,814-863.
    K SyntheticDataset_01/02.txt:19-1819: input resource, NOT stored forward answers.
    Independent scalar source-formula comparison; Java is not executed.
    """
    acquisition = read_java_synthetic(FIXTURES / f"p6/JavaDataset_0{index}.txt")
    data = prepare_two_isotope_synthetic(acquisition, kind=kind)
    assert data.basis.shape == (1500, 16)
    assert len(data.observed) == 3600
    assert (data.baseline_count, data.faraday_count, data.species_count) == (
        600,
        1500,
        2,
    )
    assert data.faraday_ordinals == (4, 6)
    assert data.parameter_count == 20
    assert data.included.sum() == 3000
    block = acquisition.blocks[0]
    # Check all prepared observation identities, values and order independently.
    expected = [
        (r.intensities[d], d, 0, i)
        for d in (4, 6)
        for i, r in enumerate(block.baseline)
    ]
    for d, seq, s in ((4, "S2", 1), (6, "S1", 2), (5, "S1", 1), (5, "S2", 2)):
        expected += [
            (r.intensities[d], d, s, i)
            for i, r in enumerate(block.on_peak)
            if r.sequence == seq
        ]
    np.testing.assert_array_equal(
        np.column_stack((data.observed, data.detector, data.species, data.time_index)),
        expected,
    )
    init = initialize(data)
    again = initialize(data)
    np.testing.assert_array_equal(init.parameters.vector, again.parameters.vector)
    np.testing.assert_array_equal(init.evaluation.model, again.evaluation.model)
    assert init.gain_fallback_reason is None
    assert np.isfinite(init.evaluation.gaussian_log_likelihood)
    p = init.parameters
    # Independently pin Java's sorted-dd / original-time ratio initialization.
    original = [i for i, species in enumerate(data.species) if species == 1]
    chronological = sorted(original, key=lambda i: data.time_index[i])
    terms = []
    for sorted_row, original_row in zip(chronological, original):
        numerator = data.observed[sorted_row]
        if sorted_row < 2100:
            numerator = (numerator - p.baselines[0]) * p.gain
        denominator = math.fsum(
            float(a * b)
            for a, b in zip(data.basis[data.time_index[original_row]], p.knots)
        )
        terms.append(numerator / denominator)
    assert p.log_ratios[0] == pytest.approx(
        math.log(max(math.fsum(terms) / 1500, math.exp(-20))), abs=2e-13
    )
    for j, d in enumerate((4, 6)):
        values = [r.intensities[d] for r in block.baseline]
        mean = math.fsum(values) / 300
        sd = math.sqrt(math.fsum((v - mean) ** 2 for v in values) / 299)
        assert p.baselines[j] == pytest.approx(mean, abs=1e-9)
        assert p.baseline_sd[j] == pytest.approx(sd, abs=1e-9)
    for i in range(3600):
        d, s, t = int(data.detector[i]), int(data.species[i]), int(data.time_index[i])
        if s == 0:
            model = p.baselines[(4, 6).index(d)]
            variance = p.baseline_sd[(4, 6).index(d)] ** 2
        else:
            signal = math.fsum(float(a * b) for a, b in zip(data.basis[t], p.knots))
            if s == 1:
                signal *= math.exp(p.log_ratios[0])
            if d != 5:
                signal /= p.gain
                j = (4, 6).index(d)
                model, variance = (
                    signal + p.baselines[j],
                    signal / 0.1 + p.baseline_sd[j] ** 2,
                )
            else:
                model, variance = signal, signal / 0.1 * 2
        assert init.evaluation.model[i] == pytest.approx(model, rel=2e-13, abs=1e-8)
        assert init.evaluation.variance[i] == pytest.approx(
            variance, rel=2e-13, abs=1e-6
        )


def oracle_m(suffix=""):
    doc = json.loads((FIXTURES / "p8/updater_M.json").read_text())
    p = Parameters(
        doc["logRatios" + suffix],
        doc["IO" + suffix],
        doc["baseLineMeansArray" + suffix],
        doc["baseLineStdArray" + suffix],
        doc["gain"],
    )
    return doc, p


def test_oracle_m_baseline_and_prior_assertions():
    """TripoliCore/src/test/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelUpdaterTest.java:51-92,146-210 (stored MATLAB values).
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/ProposedModelParameters.java:59-66;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelUpdater.java:96-197.
    Upstream explicitly leaves the MATLAB gain discrepancy unresolved.
    """
    doc, p = oracle_m()
    proposed = apply_delta(p, doc["delx"])
    np.testing.assert_allclose(
        proposed.baselines, doc["matLabBaseLineArray"], rtol=0, atol=1e-7
    )
    assert PRIORS.baseline_faraday == (-math.inf, math.inf)
    assert PRIORS.baseline_daly == (0, 0)
    assert PRIORS.log_ratio == (-20, 20)
    assert PRIORS.intensity == PRIORS.gain == (0, math.inf)
    assert PRIORS.noise_faraday == (0, 1e6)
    assert PRIORS.noise_daly == (0, 0)
    assert PRIORS.poisson_daly == (0, 10)
    assert (
        proposed.gain == p.gain + doc["delx"][-1]
    )  # Java arithmetic, no guessed MATLAB fix


def test_oracle_m_covariance_assertion():
    """TripoliCore/src/test/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelUpdaterTest.java:69-92,202-218;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelUpdater.java:204-254.
    The stored MATLAB assertion covers only covariance[0,0], not the full matrix.
    """
    doc, p = oracle_m("M40")
    p = apply_delta(p, doc["delxM40"])
    cov, mean = update_mean_covariance(p, np.zeros((24, 24)), doc["xMeanM40"], 40)
    assert cov[0, 0] == doc["covariance_00"]
    assert cov.shape == (24, 24) and mean.shape == (24,)


def test_synthetic_updater_bounds_and_literal_covariance():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelUpdater.java:138-164,229-252.
    Hand arithmetic pins the literal nonstandard covariance recurrence.
    """
    _, p = scalar()
    delta = np.array([100, -1000, 1, 2, 3, -100])
    updated = apply_delta(p, delta)
    np.testing.assert_allclose(updated.vector, [math.log(0.5), 10, 21, 2, 13, 0.5])
    cov, mean = update_mean_covariance(p, np.eye(6), p.vector - 2, 2)
    np.testing.assert_allclose(mean, p.vector - 1)
    np.testing.assert_array_equal(cov, np.eye(6) * 0.5 + np.ones((6, 6)) * 0.5)
    cov, mean = update_mean_covariance(p, np.eye(6), p.vector - 2, 1)
    np.testing.assert_array_equal(cov, np.zeros((6, 6)))
    np.testing.assert_allclose(mean, p.vector, rtol=0, atol=2e-16)


@pytest.mark.parametrize(
    "variant",
    [
        "vectors",
        "integer",
        "boolean",
        "species",
        "time",
        "detector",
        "partition",
        "basis",
        "nonfinite",
    ],
)
def test_observation_refusals(variant):
    data, _ = scalar()
    changes = {
        "vectors": {"observed": [1]},
        "integer": {"detector": data.detector.astype(float)},
        "boolean": {"included": [1] * 10},
        "species": {"species": [1] * 10},
        "time": {"time_index": [0] * 9 + [2]},
        "detector": {"detector": [4] * 6 + [9, 9, 5, 5]},
        "partition": {"baseline_count": 0},
        "basis": {"basis": np.empty((0, 0))},
        "nonfinite": {"observed": [math.nan] * 10},
    }
    with pytest.raises(ValueError):
        replace(data, **changes[variant])


@pytest.mark.parametrize(
    "variant",
    [
        "gain",
        "sd",
        "dimension",
        "variance",
        "selected_zero",
        "include",
        "delta",
        "cov",
        "count",
    ],
)
def test_parameter_evaluation_and_updater_refusals(variant):
    data, p = scalar()
    with pytest.raises(ValueError):
        if variant == "gain":
            replace(p, gain=0)
        elif variant == "sd":
            replace(p, baseline_sd=[-1, 2])
        elif variant == "dimension":
            forward(data, replace(p, knots=[1]))
        elif variant == "variance":
            evaluate(data, p, variance=[1])
        elif variant == "selected_zero":
            evaluate(data, p, variance=[0] * 10)
        elif variant == "include":
            evaluate(data, p, included=[True])
        elif variant == "delta":
            apply_delta(p, [1])
        elif variant == "cov":
            update_mean_covariance(p, [[1]], p.vector, 2)
        elif variant == "count":
            update_mean_covariance(p, np.eye(6), p.vector, 0)


def test_synthetic_fallback_domains_masks_and_array_ownership():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/initializers/SingleBlockModelInitForMCMC.java:110-116,149-181,258-266.
    Refusal/ownership extensions are this adapter's explicit supported domain.
    """
    data = truth_grid()
    # No PM denominator overlap: explicit Java fallback, not a calibrated gain.
    det = data.detector.copy()
    det[18:] = 6
    fallback = initialize(replace(data, detector=det, faraday_count=24))
    assert fallback.parameters.gain == 0.9 and fallback.gain_fallback_reason
    with pytest.raises(ValueError, match="one observation"):
        initialize(replace(data, time_index=np.zeros(len(data.observed), int)))
    with pytest.raises(ValueError, match="jointly included"):
        initialize(replace(data, included=np.zeros(len(data.observed), bool)))
    _, p = scalar()
    source = p.knots.copy()
    copied = replace(p, knots=source)
    source[0] = 1e8
    assert copied.knots[0] == 10
    with pytest.raises(ValueError):
        p.knots[0] = 10
    with pytest.raises(ValueError, match="rank deficient"):
        initialize(replace(data, basis=np.ones_like(data.basis)))
    with pytest.raises(ValueError):
        intensity_basis([0, 1, 2, 3], [0], kind="cubic")
    with pytest.raises(ValueError):
        intensity_basis([0, 1, 2, 3], [0], kind="other")


def test_adapter_refusals_and_headless_import():
    data = read_java_synthetic(FIXTURES / "p6/JavaDataset_01.txt")
    with pytest.raises(ValueError):
        prepare_two_isotope_synthetic(data, block=2)
    with pytest.raises(ValueError):
        prepare_two_isotope_synthetic(replace(data, columns=("other",)))
    with pytest.raises(TypeError):
        prepare_two_isotope_synthetic(object())
    script = "from rawtims.mcmc1 import forward, initialize, reference; import sys; assert not any(x.startswith(('PySide6','rawtims_gui','requests','keyring')) for x in sys.modules)"
    subprocess.run([sys.executable, "-c", script], check=True)


def test_source_significant_figure_rounding_on_synthetic_adapter():
    """TripoliCore/src/main/java/org/cirdles/tripoli/utilities/mathUtilities/MatLab.java:33-40;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockDataAccumulatorMCMC.java:82,169.
    Local synthetic decimal ties exercise HALF_UP, including signed tiny counts.
    """
    acquisition = read_java_synthetic(FIXTURES / "p6/JavaDataset_01.txt")
    block = acquisition.blocks[0]
    rows = list(block.baseline)
    expected = [1.23456789013, -1.23456789013e-20]
    for i, value in enumerate([1.234567890125, -1.234567890125e-20]):
        counts = list(rows[i].intensities)
        counts[4] = value
        rows[i] = replace(rows[i], intensities=tuple(counts))
    modified = replace(acquisition, blocks=(replace(block, baseline=tuple(rows)),))
    data = prepare_two_isotope_synthetic(modified)
    np.testing.assert_array_equal(data.observed[:2], expected)
