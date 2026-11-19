# Spike and blank

!!! abstract "In short"
    The known tracer amount converts measured ratios into isotope amounts. The age engine subtracts tracer, laboratory blank and initial common Pb to find the radiogenic component. These subtractions help explain why a dead-time-induced ratio change does not transfer unchanged to a date.

A **tracer**, or **spike**, is a calibrated isotope mixture added to the sample. Its known amount lets measured isotope ratios determine isotope amounts. This is **isotope dilution**. The tracer also contains small amounts of other isotopes, which the engine subtracts.

The **laboratory blank** is Pb or U introduced during preparation and analysis. **Initial common Pb** is sample Pb that was not produced by radioactive decay. Subtracting these components leaves the **radiogenic** Pb used for dating. Without those subtractions, the isotope ratios would not describe just the decay products.

This page outlines how the engine calculates the isotope amounts. It also carries the input errors through the calculation. **Correlations** describe which measured ratios vary together and affect that uncertainty. The amount equations alone do not reproduce the date errors.

## Isotope dilution

\[
\begin{aligned}
n_{205,t}&=c_{205,t}w_t,\\
n_{206,s}&=R_{65,m}(1+f_{\rm Pb})n_{205,t}-R_{65,t}n_{205,t}-n_{206,b},\\
n_{204,b+c}&=R_{65,m}R_{46,m}(1-f_{\rm Pb})n_{205,t}-R_{45,t}n_{205,t},\\
n_{206,r}&=n_{206,s}-R_{64,c}n_{204,c},\\
n_{207,r}&=[R_{65,m}R_{76,m}(1+2f_{\rm Pb})-R_{65,t}R_{76,t}]n_{205,t}
-n_{207,b}-R_{74,c}n_{204,c},\\
n_{208,r}&=[R_{85,m}(1+3f_{\rm Pb})-R_{85,t}]n_{205,t}-n_{208,b}-n_{208,c}.
\end{aligned}
\]

Where:

- \(n_{i,t},n_{i,b},n_{i,c},n_{i,s},n_{i,r}\): isotope amounts in tracer, blank, initial common Pb, blank/tracer-subtracted sample, and radiogenic sample (mol).
- \(c_{205,t}\): tracer concentration (mol/g); \(w_t\): tracer weight (g).
- \(R_{65},R_{46},R_{45},R_{76},R_{85}\): Pb 206/205, 204/206, 204/205, 207/206 and 208/205; \(R_{64,c},R_{74,c}\): initial common Pb 206/204 and 207/204. All are dimensionless.
- \(f_{\rm Pb}\): Pb fractionation (amu⁻¹). Subscript \(m\) means the measured mixture.

The engine compares non-tracer 204Pb with the amount allowed by the assumed lab blank. If there is less than that amount, it assigns all non-tracer 204Pb to blank. It then sets initial common Pb to zero. If there is more, it assigns the assumed amount to blank. The excess 204Pb becomes initial common Pb. The isotope compositions of those two components can differ.

U also contains tracer and blank. Natural sample 235U must be allowed for rather than treating all 235U as tracer:

\[
n_{238,s}=\frac{n_{235,t}R_{85,m}(1+3f_U)-R_{85,t}n_{235,t}-n_{238,b}}
{1-R_{85,m}(1+3f_U)/Q},\qquad n_{235,s}=n_{238,s}/Q.
\]

Where:

- \(R_{85}\): now **U** 238/235 (dimensionless); \(Q\): natural 238U/235U (dimensionless).
- \(n_{238,s},n_{235,s},n_{235,t},n_{238,b}\): sample U, tracer and blank amounts (mol), using the component subscripts defined above.
- \(f_U\): linear U fractionation coefficient (amu⁻¹).

## Worked example

The tracer weight is {{ v.spike.weight | fmt(4) }} g; the assumed Pb/U blank masses are {{ v.spike.pb_blank_pg | fmt(4) }} and {{ v.spike.u_blank_pg | fmt(4) }} pg. These are model inputs, not additional measurements of this fraction.

| Age-engine quantity | Amount (mol) |
|---|---:|
| Tracer 205Pb | {{ v.fractionation.Pb205t | sci(4) }} |
| Tracer 235U | {{ v.fractionation.U235t | sci(4) }} |
| Assigned blank 204Pb | {{ v.fractionation.Pb204b | sci(4) }} |
| Initial common 204Pb | {{ v.fractionation.Pb204c | sci(4) }} |
| Radiogenic 206Pb | {{ v.fractionation.Pb206r | sci(4) }} |
| Radiogenic 207Pb | {{ v.fractionation.Pb207r | sci(4) }} |
| Sample 238U | {{ v.fractionation.U238s | sci(4) }} |

The tiny initial-common amount is numerical roundoff at the blank-only boundary. The engine assigns no initial-common 206Pb in this example.

**In filament:** `rawtims.fractions.fraction_row` supplies the measured ratio block and tracer setup. **In IDTIMS_UPbRPy:** `UPbR.assign_spike_to_sample`, `assign_lab_blanks`, `utils.calc_Pb_partitioning`, `calc_Pb206s`, `calc_Pb206r`, `calc_Pb207r`, `calc_Pb208r`, `calc_U238s`. Source variable descriptions in some utility docstrings are inconsistent; the equations here follow the executed expressions and isotope assignments.
