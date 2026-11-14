# UO2 oxide correction: the formula filament uses and why the current Tripoli form differs

Status: factual note for Yiming, 2026-11-14. Nothing has been reported upstream; that is Yiming's decision.

## Mechanism

U is run as UO2+. With a 233U-235U tracer, the beams measured are:

- mass 265: 233U16O16O;
- mass 267: 235U16O16O **plus** the isobar 233U16O18O;
- mass 270: 238U16O16O.

There are two oxygen positions, so 233U16O18O ≈ 2·R18·(233U16O16O), where R18 = 18O/16O. The 235U
signal is therefore

    235UO2 = I267 − 2·R18·I265
    r233/235 = R265/267 / (1 − 2·R18·R265/267)
    r238/235 = R270/267 / (1 − 2·R18·R265/267)
    r238/233 = r238/235 / r233/235

Both denominators contain **R265/267**, because the interference on 267 scales with the 265 beam. This is
the form in:

- ET_Redux (`src/main/java/org/earthtime/UPb_Redux/valueModels/definedValueModels/R238_235oc.java`,
  lines 71-75: `r270_267m / (1 − 2·r18O_16O·r265_267m)`);
- legacy C# Tripoli (`TripoliWorkProduct.cs`, lines 2655-2672);
- Thermo Triton's own equation as written in its exports:
  `238/235 oc = (R3/R2)/((1/R2)-(2*R18))`, with R2 = 233/235 and R3 = 238/235.

It is filament's default (`formula="et_redux"`).

## What current Java Tripoli does

In CIRDLES/Tripoli at commit `00dc941`, file
`TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/MassSpecOutputBlockRecordLite.java`:

- line 36: `233/235oc = R265_267 / (1 − 2·r18·R265_267)`, which is the same as above;
- line 38: `238/235oc = R270_267 / (1 − 2·r18·R270_267)`. The correction term uses **R270/267** instead of
  R265/267.

The correction applies automatically only when a file has columns named `270/267` and `265/267`
(`AnalysisMethod.java:141-171`).

## How the gap depends on the sample

The ratio of the two results is exact:

    238/235 (Tripoli 00dc941) / 238/235 (ET_Redux) = (1 − 2·R18·R265/267) / (1 − 2·R18·R270/267)
                                                   ≈ 1 + 2·R18·(R270/267 − R265/267)   (when both terms are small)

So the gap is not a constant. It is set by how far the measured 238/235 is from 233/235, i.e. by the
sample-to-spike ratio:

- Tripoli's result is **higher** when 270/267 > 265/267, i.e. measured 238/235 > 233/235.
- It is **lower** when measured 238/235 < 233/235.
- The two forms agree only when the two ratios are equal.

Values on the vendored real U files, with R18 = 0.00205 and geometric means over all cycles:

| run | median 265/267 | median 270/267 | 238/235, ET_Redux form | 238/235, Tripoli 00dc941 form | gap |
|---|---|---|---|---|---|
| KU GHR1 IonVantage U run2 | 0.983 | 1.241 | 1.25055 | 1.25193 | +0.11 % |
| KU GHR1 U-239 (TIMSDP; Tripoli's oracle) | 0.975 | 2.429 | 2.43850 | 2.45318 | +0.60 % |
| Purdue WH205 z41 U-655 | 10.55 | 131.9 | **137.816** | 288.2 | +109 % |
| Purdue WH233B z1 U-671 | 32.68 | 119.3 | **137.008** | 232.6 | +70 % |

The Purdue runs are not spiked with 235U, so their 238/235 should come out at natural uranium (≈137.8).
The R265/267 form gives exactly that (137.816), and the current Tripoli form does not. In practice Tripoli
never applies its correction to these two files, because their columns are named `267/265` and
`270/265`. They still show which form is physically right.

For the magnitudes in Yiming's BSU spreadsheets (238/235 ≈ 0.34-0.47, 233/235 ≈ 1.005, R18 = 0.00206),
the current Tripoli form would come out **0.22-0.28 % lower** than the ET_Redux form. That would affect
Yiming's numbers only if Tripoli applied the correction to them, which is not established (next section).

## Which formula produced Yiming's existing BSU numbers: not testable yet

The only Boise State file in Tripoli's repository is a **Pb** run
(`isotopxPhoenixTIMS/boiseState/B998_F11_13223M02_iz1_Pb1-14973.xls`). It has no U columns. No BSU U
workbook exists in any repository or folder we can read. The only file with a `238/235 oxide R18 0.00206`
column is filament's own synthetic fixture, which proves nothing about BSU.

The BSU sheet headers (`238/235 oxide R18 0.00206`, `233/235 oxide R18 0.00206`, `238/233 oxide`) follow
the naming of BSU's IonVantage user functions (the Pb workbook has the matching `206/204 D` set). So the
correction was most likely computed by IonVantage, with a formula nobody has seen yet, and passed through
Tripoli unchanged.

Once Yiming provides one BSU U workbook, the test is simple: compute both forms from its `270/267` and
`265/267` columns with R18 = 0.00206 and compare them cycle by cycle with its oxide-corrected columns.
Until then filament passes such columns through unchanged. It records R18 from the function name and the
formula as `instrument` ("from instrument software, not verified").
