# Scans to cycles

!!! abstract "In short"
    Several scans make one measurement at a mass setting. We remove unusual scans, then estimate the beams at a shared time. This avoids comparing masses at different beam strengths and carries the scan-level dead-time correction into each cycle.

A **scan**, or **integration**, is one timed reading. A **sequence** groups scans at the same magnet setting. A **cycle** visits each setting once. Moving between settings is called **peak hopping**.

Beams can grow or decay during a run. Peak hopping sees the masses at different times, so their measured intensities also reflect that change in beam strength. **Beam interpolation** estimates all beams at one shared time. First, the software removes unusual scans and averages those that remain. It then fits the change in each beam through time.

Pb rates use **cps**, or counts per second. A **gross** rate includes background; a **net** rate has the background subtracted.

## Integration rejection

\[
\bar x=\frac{\sum_{i\in K}x_i}{n},\quad
s=\sqrt{\frac{\sum_{i\in K}(x_i-\bar x)^2}{n-1}},\quad
K'=\{i\in K: |x_i-\bar x|\leq k s\}.
\]

Where:

- \(x_i\): corrected integration rate (cps for Pb); \(K\): current included integrations.
- \(n=|K|\): count; \(\bar x\): mean (cps); \(s\): sample standard deviation, the spread of the scans (cps).
- \(k\): rejection threshold expressed as a multiple of the sample SD, {{ v.scan.sigma | fmt(3) }} in this acquisition.

An **outlier** is a scan farther from the current mean than the threshold allows. The software removes all outliers found in one pass together. It repeats the calculation only while the **previous** percentage lost is below {{ v.scan.max_percent | fmt(3) }}%. One pass can therefore remove more than that percentage. This scan filter differs from Tripoli's cycle rejection.

## Beam interpolation

Fit an **ordinary least-squares (OLS)** line: the straight line that minimizes the summed squared differences between measured and fitted intensities. Use a separate line for each sequence/collector across {{ v.acquisition.histories }} cycles of readings. Evaluate every line at the midpoint between the earliest first-sequence time and latest last-sequence time:

\[
t_0=\frac{t_{k-2,S1}+t_{k,S4}}{2},\quad
m=\frac{\sum_j(t_j-\bar t)(y_j-\bar y)}{\sum_j(t_j-\bar t)^2},\quad
N(t_0)=\bar y+m(t_0-\bar t).
\]

Where:

- \(t_j,\bar t,t_0\): sequence times, their mean and shared target (s since run start).
- \(y_j,\bar y\): sequence intensity and its mean (cps); \(m\): fitted slope (cps/s).
- \(k\): latest acquired cycle; \(j\): the history index. Each collector gets its own slope.

## Worked example

For the mass-206 Daly sequence:

| History time (s) | Rejection-filtered intensity (cps) |
|---:|---:|
{% for row in v.cycle.history %}| {{ row.seconds | fmt('.2f') }} | {{ row.mean | fmt('.2f') }} |
{% endfor %}

The current sequence's arithmetic mean is {{ v.scan.arithmetic | fmt('.2f') }} cps. Its **sample standard deviation (SD)**, the spread of the individual readings, is {{ v.scan.sd | fmt('.2f') }} cps. Its filtered mean is {{ v.scan.mean | fmt('.2f') }} cps. Across the history readings, the mean time is {{ v.cycle.time_mean | fmt('.2f') }} s and the mean intensity is {{ v.cycle.value_mean | fmt('.2f') }} cps. The fitted slope is {{ v.cycle.slope | fmt('.2f') }} cps/s. At **{{ v.cycle.t0 | fmt('.2f') }} s**, the OLS line gives **{{ v.cycle.gross | fmt('.2f') }} cps**.

A **block** groups cycles with a shared background measurement, called its **baseline**. Subtract the block baseline {{ v.cycle.baseline | fmt('.2f') }} cps to get **{{ v.cycle.net | fmt('.2f') }} cps**. The decoder's value is **{{ v.cycle.decoded | fmt('.2f') }} cps**, equal to the engine value at full precision (checked by the docs test). The workbook is {{ v.cycle.workbook | fmt('.2f') }} cps; the relative difference is {{ v.cycle.nonpar_relative_error | sci }}. Displayed values are rounded. The docs test checks the unrounded calculation in the same order as the decoder.

**In filament:** `rawtims.readers.ionvantage_raw.rejection_mean` and `decode_raw` (the OLS calculation is inside the decoder).
