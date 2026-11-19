# Inside a raw file

!!! abstract "In short"
    Raw acquisitions record individual measurements and the settings needed to interpret them. The exported workbook already contains processed cycle values. Reading the raw measurements lets us check where the dead-time correction enters.

A raw acquisition folder holds individual readings called **scans**, or **integrations**. The companion IonVantage workbook holds processed **cycle** values: one set of results from a complete pass through the chosen masses. The software has already corrected and combined many scans to make each cycle value.

| Component | What it holds |
|---|---|
| DAT | Interleaved scan values and times, including Faraday ADC codes and Daly pulse rates |
| IDX | Offsets and scan-layout information that index DAT |
| STS | Scan status, including the magnet's set mass and acquisition/event type |
| `_AcqParams.000` | Collector-to-channel mapping, gains, resistor values and dead time |
| IEF method definition | Magnet positions and integration counts/durations |
| IPF parameter file | Software correction flags and integration rejection settings |
| IonVantage XLS workbook | Cycle intensity/function columns, tuning and acquisition settings |

No source identity or calendar time is needed to follow these calculations. All times here are seconds since the start of the run.

## Scans, sequences, cycles, blocks

A **peak hop** changes the magnet setting to measure a different mass. A **sequence** collects scans at one setting. A **cycle** visits all the settings once. A **block** groups cycles with their own background measurements. A **half-mass** setting lies between isotope peaks and measures that background.

Each scan integrates for {{ v.acquisition.seconds_per_scan }} s. A cycle has {{ v.acquisition.sequences }} sequences. A block has two half-mass baseline acquisitions, each containing {{ v.acquisition.baseline_scans }} scans, followed by {{ v.acquisition.acquired_cycles_per_block }} acquired cycles. The first {{ v.acquisition.precycles }} provide beam history, leaving {{ v.overview.per_block }} exported cycles. There are {{ v.overview.blocks }} blocks.

| Sequence | Daly (“Multiplier”) | Daly scans | Faraday used in Pb functions |
|---|---|---:|---|
| S1 | 204 | {{ v.acquisition.scans[0] }} | 206 on High2 |
| S2 | 205 | {{ v.acquisition.scans[1] }} | 206 on High1 |
| S3 | 206 | {{ v.acquisition.scans[2] }} | 208 on High2 |
| S4 | 207 | {{ v.acquisition.scans[3] }} | 208 on High1 |

A Daly detector turns ion impacts into pulses and counts them. We express its rate in **cps**, or counts per second. A Faraday collector measures ion current through a resistor. Its analog-to-digital converter (ADC) records a numerical code proportional to voltage. Converting Pb Faraday measurements to equivalent cps lets us compare them with Daly measurements.

\[
V=(C-C_0)k_V g_F,\quad A=V/R_F,\quad F=V/(R_F e).
\]

Where:

- \(C,C_0\): scan code and zero-offset code (codes).
- \(k_V\): conversion factor (V/code); \(g_F\): collector calibration gain (dimensionless).
- \(V\): calibrated voltage (V); \(A\): current (A).
- \(R_F\): resistor (Ω); \(e\): charge per singly charged ion (C); \(F\): equivalent ion rate (cps).

## Worked example

One real High1 scan has code **{{ v.acquisition.faraday.code | fmt('.0f') }}**. Subtract {{ v.acquisition.faraday.zero | fmt('.0f') }}, multiply by {{ v.acquisition.faraday.v_per_code | sci(6) }} V/code and gain {{ v.acquisition.faraday.gain | fmt(8) }}. This gives **{{ v.acquisition.faraday.volts | fmt(6) }} V**. Dividing by {{ v.acquisition.faraday.resistor | sci }} Ω × {{ v.acquisition.faraday.charge | sci(4) }} C gives **{{ v.acquisition.faraday.cps | fmt('.1f') }} cps**.

These are the recovered vendor conversion constants, including its historical electron charge value. The U method keeps the magnet at one setting; its Faraday readings remain in volts. Only Pb Faraday readings are converted to cps here. This scan illustrates conversion; the gain page uses the common-time **S2** High1 value, after estimating it at the shared time and subtracting background. The total signal is called **gross**; the background-subtracted signal is **net**.

**In filament:** `rawtims.readers.ionvantage_raw.decode_raw`; calibration values come from `rawtims.reduction_params.as_acquired`.
