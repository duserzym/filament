# Faraday–Daly gain

!!! abstract "In short"
    The Faraday and Daly detectors can report different rates for the same beam. Their gain ratio puts those signals on a common scale. Changing Daly dead time changes this gain, so it also changes the mixed-detector 208/205 ratio.

A Faraday collector measures ion current. The Daly detector counts pulses. Both Pb signals are expressed in **cps**, or counts per second, but their calibrated responses can still differ. A **gain** is the factor that relates those responses. We need it before comparing a Faraday beam with a Daly beam.

A **sequence** groups timed readings, or **scans**, at one mass setting. **Peak hopping** changes that setting; one complete set of sequences is a **cycle**. The same mass-206 beam reaches a Faraday and the Daly in different sequences. We estimate both signals at a shared time and subtract their **baselines**, or backgrounds. Their **net** rates exclude background; **gross** rates include it. The net-rate quotient puts the Daly signal on the Faraday scale.

\[
G=\frac{F_{206,S2,H1}}{D_{206,S3}},\qquad
R_{208/205}=\frac{F_{208,S4,H1}}{G D_{205,S2}}
=\frac{F_{208,S4,H1}}{F_{206,S2,H1}}\frac{D_{206}}{D_{205}}.
\]

Where:

- \(F\): net Faraday equivalent rate (cps); H1 means High1.
- \(D\): net Daly rate (cps); S2–S4 identify peak-hop sequences.
- \(G\): Faraday–Daly gain (dimensionless); \(R\): beam ratio (dimensionless).

## Worked example

For the first exported cycle, \(F_{206}\) = {{ v.gain.f206 | fmt('.1f') }} cps and \(D_{206}\) = {{ v.gain.d206 | fmt('.1f') }} cps. Their quotient is **{{ v.gain.gain | fmt(8) }}**. The High1 mass-208 intensity is {{ v.gain.f208 | fmt('.1f') }} cps.

Increasing dead time raises corrected \(D_{206}\), so \(G\) falls. The 208/205 ratio combines Faraday 208 with gain-scaled Daly 205. It therefore rises in proportion to Daly 206/205 for that cycle. A Faraday itself has no pulse-counting dead time; the effect enters through the gain calibration.

**In filament:** `rawtims.reprocess._functions`. IonVantage's exported gain/function columns already contain this calculation; unchanged workbook values pass through exactly.
