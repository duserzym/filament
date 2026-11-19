# U oxide correction

!!! abstract "In short"
    A small oxygen-isotope contribution overlaps the U signal at mass 267. Removing it gives the U isotope ratios needed by the age calculation. This correction acts on Faraday measurements and stays fixed in the Pb dead-time experiment.

Uranium is measured as a molecular ion, UO₂⁺: one U atom bound to two oxygen atoms. The mass-267 collector receives the desired ²³⁵U¹⁶O¹⁶O. It also receives a small contribution from ²³³U¹⁶O¹⁸O. These different ions have the same nominal mass, an **isobaric overlap**.

Subtracting the overlap makes the U-235 denominator smaller. This raises both isotope ratios that use it. We use **net** intensities, after subtracting the **baseline**, or background. **Gross** intensities still include that background. The measurements come from Faraday collectors, which measure current rather than count pulses.

\[
y'=y-2r_{18}x,\quad
R_{233/235}=\frac{x}{y'}=\frac{x/y}{1-2r_{18}x/y},\quad
R_{238/235}=\frac{z}{y'},\quad R_{238/233}=\frac{z}{x}.
\]

Where:

- \(x,y,z\): net mass-265, mass-267 and mass-270 intensities (V).
- \(r_{18}=^{18}O/^{16}O\): oxygen isotope ratio (dimensionless).
- \(y'\): corrected mass-267 intensity (V); the factor of two counts the two oxygen positions.
- \(R\): uranium isotope ratio (dimensionless).

## Worked example

A **cycle** is one repeated set of measurements. The first U cycle has \(x\) = {{ v.oxide.x | fmt(6) }} V, \(y\) = {{ v.oxide.y | fmt(6) }} V and \(z\) = {{ v.oxide.z | fmt(6) }} V. With \(r_{18}\) = **{{ v.oxide.r18 | fmt(6) }}**, the denominator factor is **{{ v.oxide.factor | fmt(8) }}**.

| Quantity | Value |
|---|---:|
| Measured 265/267 | {{ v.oxide.r265 | fmt(8) }} |
| Physical 270/267 | {{ v.oxide.r270 | fmt(8) }} |
| Corrected 233/235 | {{ v.oxide.r233_235 | fmt(8) }} |
| Corrected 238/235 | {{ v.oxide.r238_235 | fmt(8) }} |
| Corrected 238/233 | {{ v.oxide.r238_233 | fmt(8) }} |
| Cached corrected 238/235 | {{ v.oxide.cached | fmt(8) }} |

An **alias** repeats data under another label. The “270/267” label repeats an intensity in this acquisition, so it must not be used as a ratio. The values above are computed from physical intensities. Already corrected acquisition columns pass through unchanged; the contract says `instrument`. Recomputing from intensities records `isobar_233_18O`.

The Java comparison option `tripoli_java_00dc941` uses \(1-2r_{18}R_{270/267}\) in the 238/235 denominator instead. It is available for comparisons but differs from the physical mass-267 isobar correction above and from the legacy C# formula. The example's stored (cached) correction agrees with the physical formula.

**In filament:** `rawtims.oxide.correct`, `find_inputs`, `oxide_correction`; changed parameters are rebuilt by `rawtims.reprocess._functions`. The original corrected columns were supplied by the acquisition software.
