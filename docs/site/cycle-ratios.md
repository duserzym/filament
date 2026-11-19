# Cycle ratios

!!! abstract "In short"
    Each cycle ratio compares two beams after background subtraction and alignment in time. The detector combination determines how dead time affects it. Daly ratios change directly, while the mixed Faraday–Daly ratio changes through the gain.

A **cycle** is one complete pass through the chosen mass settings. A **sequence** groups timed readings, or **scans**, at one setting. **Peak hopping** moves between settings, so the masses are measured at different times.

We first estimate every beam at a shared time. We then subtract the **baseline**, or background. This changes a **gross** signal into a **net** signal. Ratios of these net rates compare isotope abundances without mixing in the beam's growth or decay. Pb rates use **cps**, or counts per second.

## Pb functions

\[
\begin{aligned}
R_{206/204}&=D_{206}/D_{204},& R_{206/207}&=D_{206}/D_{207},\\
R_{206/205}&=D_{206}/D_{205},& R_{207/205}&=D_{207}/D_{205},\\
R_{204/205}&=D_{204}/D_{205},& R_{208/205}&=F_{208,S4,H1}/(G D_{205}),\\
H1&=F_{206,S2,H1}/F_{208,S4,H1},&H2&=F_{206,S1,H2}/F_{208,S3,H2},\\
R_{206/208,F}&=\sqrt{H1\,H2},&G&=F_{206,S2,H1}/D_{206}.
\end{aligned}
\]

Where:

- \(D_m,F_m\): baseline-subtracted Daly and Faraday rates (cps) for mass \(m\).
- \(G\): Faraday–Daly gain, the factor relating the two detector scales; \(R,H1,H2\): dimensionless ratios.
- S1–S4 and H1/H2 specify sequence and High1/High2 collector. The separate “208 F (H1)” function is simply \(F_{208,S4,H1}\) in cps.

## Worked example

The first exported cycle gives these values. Raw reconstruction and the exported workbook use the same formulas. The raw route estimates the shared time slightly differently from the workbook. This leaves small numerical differences.

| Function | Workbook | Raw reconstruction | Relative difference |
|---|---:|---:|---:|
{% for row in v.ratios.cycles %}| {{ row.ratio }} | {{ row.workbook | fmt(8) }} | {{ row.reconstructed | fmt(8) }} | {{ row.relative_error | sci }} |
{% endfor %}

The maximum relative error across **all** Pb functions and cycles is {{ v.depth.max_relative_error | sci }}, inside the documented bound {{ v.depth.pb_bound | sci }}. This bound is evidence for this method and example, not a universal guarantee.

## U functions

The **static U** method keeps the magnet at one setting instead of peak hopping. Write \(x=I_{265},y=I_{267},z=I_{270}\), all in V. The physical beam ratios are \(R_{265/267}=x/y\), \(R_{270/265}=z/x\) and \(R_{270/267}=z/y\).

An **alias** is a second label for the same data. **Alias anomaly:** the exported column labelled `270/267` actually repeats the mass-270 intensity in this acquisition. filament flags it. The oxide correction removes overlapping oxygen-isotope contributions from the U beams. Its physical calculation uses intensities or the product `270/265 × 265/267`, never that intensity alias. The stored (cached) oxide-corrected columns pass through unchanged when no reduction settings change.

**In filament:** `rawtims.reprocess._functions`, `rawtims.oxide.find_inputs` and `rawtims.readers.open_run`.
