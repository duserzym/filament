# Mass fractionation

!!! abstract "In short"
    The mass spectrometer can transmit isotopes with slightly different efficiencies. The age engine corrects this mass-dependent effect using laboratory settings and the added tracer. This correction follows the dead-time correction and helps determine how a measured ratio change affects a date.

The mass spectrometer can transmit one isotope more efficiently than another. This **mass fractionation** changes the measured ratio. It depends on isotope mass differences, while dead-time count loss depends on beam intensity. Both can change the same ratio, so they require separate corrections.

A **tracer**, or **spike**, is a calibrated isotope mixture added to the sample. IDTIMS_UPbRPy uses laboratory settings and tracer measurements to correct fractionation. It applies a **linear per-amu law**: the correction factor changes in proportion to the isotope mass separation, measured in atomic mass units (amu).

## Pb

For the example's 535 tracer, a calibrated mixture containing 205Pb, 233U and 235U, the Pb coefficient comes from an external laboratory setting. Ratios relative to the tracer isotope are corrected with the signed mass separation:

\[
R_{m/205}^{\rm corr}=R_{m/205}^{\rm meas}[1+(m-205)f_{\rm Pb}].
\]

Where:

- \(R\): isotope ratio (dimensionless); \(m-205\): signed mass difference (amu).
- \(f_{\rm Pb}\): fractionation coefficient (amu⁻¹), stored in percent per amu in settings and divided by one hundred for calculation.

The implementation builds sample amounts using measured 206/205 and the reciprocal of measured 206/207. Multiplying two run-mean ratios does not generally give the mean of their cycle-by-cycle products. A **cycle** is one complete set of mass measurements. This matters when comparing the measured 207/205 column to the date engine's inputs.

## U double spike

A **double spike** supplies two enriched isotopes with a known ratio. The 233–235 tracer lets the engine solve for U fractionation while allowing for natural sample U in the mixture:

\[
f_U=\frac{R_{35,t}(Q-R_{85,m})+R_{35,m}(R_{85,t}-Q)}
{2R_{35,m}(R_{85,t}-Q)+3R_{35,t}R_{85,m}}.
\]

Where:

- \(R_{35}\): 233U/235U, \(R_{85}\): 238U/235U (dimensionless); the compact subscripts are isotope shorthand, not mass differences.
- \(m,t\): measured mixture and tracer.
- \(Q\): natural 238U/235U (dimensionless); \(f_U\): fractionation coefficient (amu⁻¹).

The factors correspond to the signed isotope mass separations. The docstring in `calc_FU` contains outdated ratio descriptions; the expression and the grain's `U_R35m`/`U_R85m` assignments establish the convention above.

## Worked example

These values come from the calculated fraction **inside IDTIMS_UPbRPy's own process**:

| Quantity | Value |
|---|---:|
| \(f_{\rm Pb}\) (amu⁻¹) | {{ v.fractionation.FPb | fmt(8) }} |
| \(f_U\) (amu⁻¹) | {{ v.fractionation.FU | fmt(8) }} |
| Measured Pb 206/205 | {{ v.fractionation.Pb_R65m | fmt(8) }} |
| Measured Pb 207/206 | {{ v.fractionation.Pb_R76m | fmt(8) }} |
| Measured U 233/235 | {{ v.fractionation.U_R35m | fmt(8) }} |
| Tracer U 233/235 | {{ v.fractionation.U_R35t | fmt(8) }} |
| Measured U 238/235 | {{ v.fractionation.U_R85m | fmt(8) }} |
| Tracer U 238/235 | {{ v.fractionation.U_R85t | fmt(8) }} |
| Natural U 238/235 | {{ v.depth.constants.common_U238_U235 | fmt(8) }} |

For a 202–205 double spike (2535 variant), the engine instead obtains \(f_{\rm Pb}=(1-R_{202/205,t}/R_{202/205,m})/3\). This is an outline: this fraction has no measured 202/205 double-spike example.

**In filament:** `rawtims.fractions.fraction_row` exports measured ratios without these age-engine corrections. **In IDTIMS_UPbRPy:** `UPbR.assign_fractionation_factors`, `UPb_grain.calc_FPb_2535`, `utils.calc_FPb_2535`, `utils.calc_FU`, and `UPb_grain.calc_sample`. The tracer calibration is assigned by `UPbR.assign_spike_to_sample` using `spikes.SPIKES`.
