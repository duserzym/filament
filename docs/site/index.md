# Overview

!!! abstract "In short"
    This walkthrough follows measured ion signals through to isotope ratios and dates. Each step explains what changes and why. Dead time matters because a busy counter misses a larger fraction of a strong beam than of a weak one.

This walkthrough follows **the example zircon fraction (z1)** from counted pulses to the ratios used for dating. Read in order for the full calculation, or jump to [dead time in depth](dead-time.md) to move the counter's dead time and see what changes.

The central idea is simple: a busy counter misses a larger fraction of a strong beam than of a weak beam. Correcting those beams by different amounts changes their ratio. The date engine then converts the changed, chemically corrected isotope ratios into dates.

The glossary below defines the measurement units and the groups of readings used in this pipeline.

1. Read scan codes, times and collector assignments.
2. Convert Faraday codes to volts and Pb counts per second; correct each Daly scan for dead time.
3. Reject anomalous integrations, average each sequence, interpolate beams to a common time and subtract the block baseline.
4. Build Faraday–Daly gain and cycle ratios.
5. Restore the saved ratio selections; calculate means, standard errors and correlations.
6. Pass the measured ratios to IDTIMS_UPbRPy for fractionation, tracer subtraction, blank/common Pb, disequilibrium and dates.

## Glossary

| Term | Plain meaning |
|---|---|
| Scan or integration | One measurement collected over a short time interval |
| Sequence | Scans collected at one magnet setting |
| Peak hop | A change in magnet setting that brings a different isotope mass onto a detector |
| Cycle | One complete set of sequences through the chosen masses |
| Block | A group of cycles with its own background measurements |
| Half mass | A setting between integer isotope masses, away from the isotope peak, used to measure background |
| Baseline | The background signal measured away from a peak |
| Gross / net | Signal before / after subtracting the baseline |
| cps | Counts per second; the rate scale for Pb signals here |
| Daly / Faraday | A detector that counts ion-generated pulses / a collector that measures ion current |
| Dead time | The brief recovery interval during which the counter cannot record another pulse |
| Beam interpolation | Estimating signals at a shared time from measurements taken at different times |
| Gain | A calibration factor relating two signal scales |
| Mask | A list marking which cycle values to include or exclude |
| SD / SE / %SE | Spread of individual values / standard error of their mean / that error as a percentage of the mean |
| Radiogenic | Produced by radioactive decay, after removing tracer, blank and initial common Pb |

## Notation

A rate is a number of ions per second. A ratio divides two rates expressed on the same scale.

\[
R_{a/b}=I_a/I_b,\qquad I=N-B.
\]

Where:

| Symbol | Meaning | Units |
|---|---|---|
| \(N_{\rm obs}\) | Observed pulse rate | cps (s⁻¹) |
| \(N\) | Dead-time-corrected gross Daly rate | cps |
| \(I\), \(D\) | Net intensity, net Daly intensity | cps for Pb; V for static U Faradays |
| \(B\) | Block baseline in the same collector | cps for Pb; V for U |
| \(F\) | Net Faraday intensity | cps for Pb |
| \(\tau\), \(\Delta\tau\) | Dead time, change in dead time | s in equations; ns in controls |
| \(G\) | Faraday–Daly gain | dimensionless |
| \(R\) | Isotope or beam ratio | dimensionless |
| \(n\), \(s\), SE | Count of included values, sample SD, error of the mean | count; ratio units for SD/SE |
| \(t\), \(t_0\) | Time since run start, interpolation target | s |
| \(\lambda\) | Decay constant | yr⁻¹ |
| \(f_{\rm Pb}\), \(f_U\) | Linear mass fractionation coefficient | amu⁻¹ |

## Worked example

The Pb run exports {{ v.overview.blocks }} blocks × {{ v.overview.per_block }} cycles = **{{ v.overview.cycles }} cycle rows**. The example's mean net Daly rate at mass 206 is {{ v.depth.rates['206'] | fmt('.0f') }} cps. Its much weaker mass-207 beam is {{ v.depth.rates['207'] | fmt('.0f') }} cps. That intensity difference is why their ratio is sensitive to dead time.

!!! info "Who does which calculation?"
    **Instrument software (IonVantage; similarly IsoLinx cycle exports):** scan conversion, dead time, integration processing, interpolation, baseline subtraction and cycle functions.

    **Legacy Tripoli:** accepts the exported cycle values; selects/rejects cycles and computes arithmetic run statistics. It applies **no additional dead-time correction**. It can perform an oxide correction when needed.

    **filament:** reads those cycle values or independently reconstructs them from acquisitions; makes reduction choices explicit; carries masks, ratios, errors and correlations to a fraction contract.

    **IDTIMS_UPbRPy:** applies fractionation and tracer/blank/common-Pb corrections and computes dates and their uncertainties in its own Python process.

**In filament:** `rawtims.readers.ionvantage_raw.decode_raw`, `rawtims.reprocess.reprocess`, `rawtims.fractions.fraction_row`. These calculations run without a graphical interface.
