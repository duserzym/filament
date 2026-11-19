# Baselines

!!! abstract "In short"
    The baseline measures the signal present away from an isotope peak. Subtracting it leaves the isotope beam we want to compare. A dead-time correction must first act on the total signal because background pulses also occupy the counter.

A collector can report a signal even when no isotope peak is present. We call this background the **baseline**. A **block** is a group of measurement cycles that share a baseline. A **cycle** visits all the mass settings once.

At the start of each block, the software measures on either side of the peak region. These **half-mass** settings lie between integer isotope masses, away from the isotope peaks. Each reading is a **scan**, or timed integration. The software excludes unusual scans and averages the two background measurements. This samples background near the peaks without counting the peak itself.

Pb rates use **cps**, or counts per second. The **gross** signal includes background. Subtracting the baseline leaves the **net** isotope signal.

\[
B=\frac{\bar N_{\rm low}+\bar N_{\rm high}}{2},\qquad I=N(t_0)-B.
\]

Where:

- \(\bar N_{\rm low},\bar N_{\rm high}\): rejection-filtered half-mass rates (cps).
- \(B\): block baseline (cps), one value per collector; \(N(t_0)\): interpolated gross rate (cps).
- \(I\): net beam intensity (cps). U Faradays use the same subtraction in V.

## Worked example

At half masses {{ v.baseline.low_mass | fmt(5) }} and {{ v.baseline.high_mass | fmt(5) }}, each with {{ v.acquisition.baseline_scans }} scans, the Daly filtered means are {{ v.cycle.baseline_low | fmt('.2f') }} and {{ v.cycle.baseline_high | fmt('.2f') }} cps. Their average is **{{ v.cycle.baseline | fmt('.2f') }} cps**. Subtracting it from {{ v.cycle.gross | fmt('.2f') }} gives **{{ v.cycle.net | fmt('.2f') }} cps**.

The net result is equal to the engine value at full precision (checked by the docs test). The displayed intermediate values are rounded.

## Why add the baseline back?

The counter misses pulses from the total incident signal. Background pulses also occupy the electronics. A dead-time change must therefore act on the gross rate, not on the background-subtracted beam:

\[
I_1=\frac{I_0+B}{1-(I_0+B)\Delta\tau}-B.
\]

Where:

- \(I_0,I_1\): old and new net Daly intensities (cps).
- \(B\): acquired block Daly baseline (cps); \(\Delta\tau\): new minus old dead time (s).

This applies a single-rate correction to a processed cycle value. It is the workbook route's cycle-level approximation. It holds the acquired baseline fixed. The raw route re-corrects the individual baseline scans too, then repeats rejection and interpolation. The two procedures are close for this fraction, but are not identical.

**In filament:** `rawtims.readers.ionvantage_raw.decode_raw` measures/subtracts baselines; `rawtims.reprocess.reprocess` adds them back for workbook dead-time changes.
