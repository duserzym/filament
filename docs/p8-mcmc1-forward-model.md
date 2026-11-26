# MCMC1 deterministic research model (P8, first increment)

This is an explicitly imported, Qt-free **research preview**, off by default.
`rawtims.mcmc1` implements deterministic Java MCMC1 forward calculations. It is
not a validated Bayesian reduction. Nothing imports it from Analysis, readers,
sessions, GUI or export code. There is no sampler, chain store, export, production
value, MCMC2, peak-shape tool or remote job. D15/D16/D17 remain open.

| Row | Status after this increment | Scope / remaining work |
|---|---|---|
| F24 | partial | Synthetic observation preparation only; no new raw acquisition route |
| F28 | partial | Deterministic MCMC1 prerequisite; no Bayesian fitting |
| F50 | done for supported research inputs | Linear/cubic basis, knot initialization and forward evaluation; no production inference claim |
| F51 | partial | Baseline sample statistics, fixed noise initialization, priors and updater covariance arithmetic; no initializer grid-search covariance or noise hierarchy |
| F52 | partial | Interior-knot PM/Faraday gain initialization; no posterior joint inference |
| F55 | partial | Observed/model/residual/variance arrays and inclusion-aware misfit; no desktop workspace |

F22 remains partial (no new view); F53/F54/F57/F58/F59 remain not done. F56 stays
partial. Deterministic `apply_delta` and the covariance recurrence are small
reference helpers for oracle M, not an adaptive sampler or convergence control.

## Explicit APIs and supported inputs

- `forward.intensity_basis(times, cycle_starts, kind="linear" | "cubic")` uses the
  P6 basis functions. Both have cycles + 1 columns. Cubic uses degree 3 and
  cycles − 2 segments and needs at least three cycles. P6's literal Java versus
  positive stored-answer even-degree sign distinction remains unchanged.
- `forward.Observations` owns copied, read-only arrays: observed counts, detector
  ordinal, species ordinal, time index, included flags and the intensity basis.
  The observation partition is baseline, on-peak Faraday, on-peak PM. Species 0
  means baseline; 1..N−1 are numerator species; N is the reference denominator.
  Baseline parameters follow ascending Faraday detector ordinal. This is an
  explicit prepared-data API, not generic method-driven raw allocation.
- `initialize.prepare_two_isotope_synthetic(acquisition, block=1, kind="linear")`
  accepts only the pinned Java Version 1.00 ten-detector layout. It uses the Java
  built-in Ax S2 / PM S1 = 206Pb, H1 S1 / PM S2 = 208Pb mapping and BL1 on Ax/H1.
  Other measured columns are intentionally outside that method. It preserves
  Java's detector/sequence ordering and decimal HALF_UP rounding to 12 significant
  figures. Synthetic counts receive no Phoenix Full volts conversion.
- `initialize.initialize(observations)` returns versioned initialization results,
  immutable parameters, model/residual/variance arrays and a gain-fallback reason.
  Its supported grid has exactly one observation per species at each basis time.
  Missing/duplicate grids and rank-deficient denominator fits are refused.
- `forward.forward`, `noise_variance` and `evaluate` accept explicit parameters.
  These functions do not require initialization or that complete grid. Likelihood
  rows need positive variance; zero variance may remain on excluded rows. Returned
  vectors are independent of inputs; masks never mutate an Analysis.
- `reference.PRIORS`, `apply_delta`, `update_mean_covariance` implement only the
  deterministic arithmetic needed by oracle M. Parameter order is log ratios,
  intensity knots, baselines, gain. Zero gain is undefined in forward evaluation
  and is refused, even though Java's prior includes zero.

Notebook example from the repository root, using a committed upstream synthetic
fixture (not lab data):

```python
from rawtims.synthetic_acquisition import read_java_synthetic
from rawtims.mcmc1.initialize import prepare_two_isotope_synthetic, initialize

source = read_java_synthetic("tests/fixtures/tripoli/p6/JavaDataset_01.txt")
data = prepare_two_isotope_synthetic(source, kind="linear")
preview = initialize(data)
model = preview.evaluation.model
residual = preview.evaluation.residual
```

## Literal source behavior and limits

Sources below are relative to Java Tripoli commit
`00dc94109f572c22bb3f357c0f7b1bb5347f62f5`, under
`TripoliCore/src/main/java/org/cirdles/tripoli/`. They are local source oracles;
**Java was not executed**.

| Source | Implemented behavior |
|---|---|
| `sessions/analysis/methods/AnalysisMethodBuiltinFactory.java:54-91` | Two-isotope synthetic collector/sequence mapping |
| `sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockDataAccumulatorMCMC.java:47-187` | Baseline/Faraday/PM allocation, synthetic counts, baseline excluded and on-peak included |
| `utilities/mathUtilities/MatLab.java:33-40` | Decimal-string HALF_UP significant-figure rounding |
| `sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelDriver.java:172-233` | Linear and cubic dimensions/knots |
| `sessions/analysis/massSpectrometerModels/dataModels/mcmc/initializers/SingleBlockModelInitForMCMC.java:70-181,222-267,366-438,684-810,814-870` | Baseline, gain, intensity/ratio initialization, variance, forward model and misfit |
| `sessions/analysis/massSpectrometerModels/dataModels/mcmc/ProposedModelParameters.java:59-66` | Reference prior bounds |
| `sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelUpdater.java:96-254` | Component-wise prior reversion and literal mean/covariance recurrence |
| `sessions/analysis/massSpectrometerModels/dataModels/mcmc/MCMCProcess.java:152-156,243-251,392-437` | Default weights/temperature, initial included-only and later all-row misfits, fixed initialized Dsig |

The Faraday model is `exp(log ratio) * intensity / gain + baseline`; the denominator
ratio is 1. PM uses `exp(log ratio) * intensity`, with no baseline or gain. Noise
**variance** Dsig is baseline SD², or Faraday signal / 0.1 + baseline SD², or
PM signal / 0.1 × 2. The hard-coded 0.1 s interval and PM factor 2 are source
behavior, not inferred acquisition/calibration facts.

Gain is the mean ratio of separately fitted PM/Faraday denominator knots, omitting
first and last knots. Fits use NumPy least squares with full-column-rank checks;
Java uses QR. Numerical equivalence has finite precision, not cross-engine byte
identity. Gain fit failures return Java's fallback 0.9 with an explicit reason;
invalid/nonpositive estimates also trigger this documented adapter guard.

Java ratio initialization sorts the corrected data but uses **unsorted** original
time indices to select denominator intensity (`260,266`). This is reproduced
literally and tested with independently specified varying intensity: initialization
can bias the known ratio. The numerator/denominator masks in this API are paired
in chronological species order. Baseline, gain and intensity fits use all their
observations, as in Java; the ratio mean uses the joint inclusion mask. The lower
ratio clamp is exp(−20); initialization does not apply an upper clamp.

`evaluate` defaults to the included-only initial misfit. Explicit all-True inclusion
reproduces the later all-row proposal calculation. A caller can pass initialized
`variance=` to freeze Dsig during parameter changes, as Java does. `log_kernel`
is −E/2 (fixed-variance acceptance); `gaussian_log_likelihood` additionally includes
log variance and the Gaussian normalization constant. These are different fields.
The covariance helper retains Java's nonstandard extra factor in the recurrence;
it is not substituted for filament's existing covariance/statistics estimators.

## Evidence and missing truth

[Tests](../tests/test_p8_mcmc1.py) cover both K datasets with both bases: 600 baseline,
1,500 Faraday and 1,500 PM observations, a 1,500 × 16 basis and 20 parameters.
Independent scalar loops check every prepared identity and forward/noise entry;
scalar baseline calculations and the literal ratio formula are checked separately.
These are **source-formula comparisons**, not stored Java forward answers. P6's
100 K stored spline-matrix comparisons run alongside these tests.

Oracle M's arrays and stored baseline/prior/covariance assertion are extracted to
`tests/fixtures/tripoli/p8/updater_M.json`, with original-source and derived-file
SHA-256/provenance in the fixture ledger. Source:
`TripoliCore/src/test/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelUpdaterTest.java:51-92,146-218`.
The baseline tolerance is the upstream 1e−7; covariance[0,0] equals the stored
`4.6228166366862166e−5` exactly. M establishes only that covariance entry. Its
comment at lines 178-179 explicitly leaves a Java/MATLAB gain discrepancy open.
No whole-matrix MATLAB or posterior inference equivalence is claimed.

Still needed: documented K generating ratios/intensity/gain/noise/seeds and
independent end-to-end Java initialized forward/likelihood snapshots; broader
initial-covariance validation; replicated posterior recovery/coverage truth; paired
real BSU integrations/methods/calibrations and accepted vendor/Tripoli results.
The MCMC2 driver references an absent SyntheticOutToTripoli resource. No truth is
invented from successful initialization. D15 governs preview versus production,
D16 the eventual model family, and D17 execution/storage. This increment makes
none of those decisions and leaves sampling, ensembles, export and scheduling
for later work. No new desktop controls or layouts were added.
