# Daly dead time

!!! abstract "In short"
    The Daly counter briefly recovers after each recorded pulse. The dead-time correction estimates how many pulses it missed. We apply it to each scan before averaging because strong signals lose a larger fraction of their counts.

A **scan**, or **integration**, is one timed measurement of the beam. Its rate is in **cps**, or counts per second. After recording a pulse, the Daly counter is briefly unable to record the next one. A stronger beam loses more counts. IonVantage corrects each scan before averaging. filament's raw route follows the same order. These are **gross** rates, which still include background. Subtracting that background later gives **net** rates.

\[
N=\frac{N_{\rm obs}}{1-N_{\rm obs}\tau},\qquad N_g=g_D N.
\]

Where:

- \(N_{\rm obs}\): observed scan rate (cps).
- \(\tau\): dead time (s); the example was acquired at {{ v.scan.tau | fmt(4) }} ns.
- \(N\): non-paralysable corrected rate (cps).
- \(g_D\): multiplier gain (dimensionless); \(N_g\): calibrated gross rate (cps).

## Worked example

A **sequence** groups scans at one mass setting. A **cycle** visits each setting once; changing settings is called **peak hopping**. A **block** groups cycles with their own background measurements. These are the actual mass-206 scans in the third acquired cycle of the first block. The software uses readings from this cycle and the preceding cycles to estimate all beams at a shared time. This produces the first exported cycle value. Each integration lasts {{ v.acquisition.seconds_per_scan }} s and the multiplier gain is {{ v.scan.multiplier_gain | fmt(6) }}.

| Observed (cps) | Corrected (cps) |
|---:|---:|
{% for row in v.scan.rows %}| {{ row.observed | fmt('.1f') }} | {{ row.corrected | fmt('.1f') }} |
{% endfor %}

After excluding unusual scans, the sequence mean is **{{ v.scan.mean | fmt('.1f') }} cps**. The correction grows faster as the rate increases. Correcting an average rate therefore differs from averaging the corrected scans. [Continue through the cycle calculation](scans-to-cycles.md), or [derive the correction and explore dates](dead-time.md).

**In filament:** `rawtims.readers.ionvantage_raw.dead_time`, called by `decode_raw`. Legacy Tripoli receives already corrected cycle values and does not repeat this step.
