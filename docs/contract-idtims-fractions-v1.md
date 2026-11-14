# Contract `idtims-fractions/1`: measured ratios from raw-data review to reduction

Status: **agreed** on 2026-11-14 between the raw-data app (filament, writer) and the ID-TIMS
reduction app (IDTIMS_UPbRPy, reader). Clarifications 1 to 6 were agreed the same day. They add one
optional column and change no existing column or meaning, so the version stays /1. The same text is kept in both repositories as
`docs/contract-idtims-fractions-v1.md`. This CSV text is the contract. Any class either side ships
to read or write it is an implementation.

## Purpose

Each row is one measured fraction, or one block of it (see "Rows and merging"). It holds the
fraction's measured isotope ratios with 1σ % errors, plus its identity and provenance. These are
the ratios before fractionation correction. The file goes from raw-data review to reduction.

This is also the format a person types or pastes from Tripoli, so manual entry and CSV import use
it too.

## File

- CSV, UTF-8 (a BOM is tolerated on read), comma separator, one header row, `.` decimal point, no
  comment lines.
- Suggested file name: `<anything>.fractions.csv`. Readers must not depend on the name.
- Numbers are written as the shortest text that reads back to the same float (Python `repr`), never
  rounded for display. Readers parse them as IEEE doubles.
- The writer ends lines with `\n`; readers accept both `\n` and `\r\n`.
- An empty cell means missing.
- Unknown extra columns are allowed. Readers ignore them and keep them on re-export.
- Column order is free. Column names are exact; case and spacing matter.

## Versioning

- Column `Contract` appears on every row with the value `idtims-fractions/1`.
- Adding an optional column does not change the version. Renaming or removing a column, or changing
  its meaning, unit or sigma level, makes `idtims-fractions/2`.
- Readers reject a major version they do not know, with a clear message.
- Files without a `Contract` column are read as legacy CSVs (see "Legacy").

## Rows and merging

- `Fraction ID` is unique within one file.
- A row may carry only the Pb block, only the U block, or both. Pb and U are separate acquisitions,
  and the writer pairs them by the user-set `Fraction ID`.
- The reader merges rows that share a `Fraction ID` across several files. If two files give
  different non-empty values for the same column, that is an error naming the fraction, the column
  and both files.
- A fraction can be reduced only once both blocks are present.

## Columns

### Identity

The writer fills what it knows; the reduction app lets the user complete the rest.

| Column | Req | Meaning |
|---|---|---|
| `Contract` | yes | `idtims-fractions/1` |
| `Fraction ID` | yes | Fraction label, e.g. `z1` |
| `Sample` | no | Sample name, e.g. `SA18-1` |
| `Beaker` | no | Dissolution beaker or capsule (BSU sheet "Barrel number"), e.g. `K1`, `B1677` |
| `Source Mount` | no | LA-ICP-MS mount name |
| `Source Grain` | no | LA-ICP-MS grain the fraction was plucked from (grainatlas / laicpmsdb label) |
| `Source Spot` | no | LA-ICP-MS spot on that grain |
| `Aliquot` | no | Free label for grouping fractions |

Database identifiers for grains and spots come later, as optional `Source Grain UID` and
`Source Spot UID` columns. They are not part of v1.

### Analysis setup

These columns are optional for the writer; the reduction app asks for whatever is missing.

| Column | Meaning |
|---|---|
| `Sample Weight (mg)` | mg |
| `Spike Weight (g)` | g |
| `Spike Type` | `535` or `2535` |
| `Spike` | Tracer name as in the reduction app's tracer table, e.g. `ET535`, `ET2535`, `BSU1B` |
| `Collector` | `F` (Faraday) or `D` (Daly/ion counter): the detector the Pb fractionation factor applies to |
| `Pb Collector Detail` | Free text for mixed methods, e.g. `204 Daly; 205-208 Faraday` |
| `Pb Method`, `U Method` | Instrument method names |

### Measured ratios

Each ratio has a mean column `<ratio> Mean` and an error column `<ratio> % Standard Error`. The
error is the 1σ standard error of the mean of the accepted cycles, in percent of the mean. This is
Tripoli's "% Standard Error" and the `load_grains` default.

| Block | Ratios |
|---|---|
| Pb | `206Pb/204Pb`, `206Pb/207Pb`, `206Pb/205Pb`, `207Pb/205Pb`, `204Pb/205Pb`, `208Pb/205Pb`; `202Pb/205Pb` when `Spike Type` is `2535` |
| U | `238U/235U`, `233U/235U`, `238U/233U` |

Every ratio in a block is required when that block is present.

`202Pb/205Pb` and the spike type:
- `202Pb/205Pb` is required when `Spike Type` = `2535`.
- If `Spike Type` is empty and `202Pb/205Pb` is present, the reader infers 2535 and asks the user to
  confirm.

What the ratios mean:
- They are baseline corrected, detector corrected (dead time, Daly gain) and cycle-filtered.
- They are **not** corrected for Pb or U mass fractionation and **not** spike-stripped. The
  reduction app does that.
- The U ratios are metal-equivalent ratios, corrected for UO2 oxide (18O/16O). Either the writer
  applies the correction, or the instrument software already did (e.g. IonVantage user functions
  named "238/235 oxide R18 0.00206").
  - The writer records the 18O/16O in `U Oxide 18O/16O` and the formula in `U Oxide Formula`.
  - If `U Oxide 18O/16O` is empty in a U block, the reduction app does not reduce U until the user
    supplies the value or confirms that no oxide correction applies.

#### `U Oxide Formula`

Required whenever `U Oxide 18O/16O` is filled. Each value is defined only by its formula, with r18 the
18O/16O, r270/267 and r265/267 the measured oxide-mass ratios, and r238/233 = r238/235 / r233/235 in
every case.

| Value | Meaning |
|---|---|
| `isobar_233_18O` | Removes the 233U16O18O isobar from mass 267, which is 2·r18 times the 233U16O2 beam at mass 265: r238/235 = r270/267 / (1 − 2·r18·r265/267); r233/235 = r265/267 / (1 − 2·r18·r265/267). This is the form used by ET_Redux, legacy Tripoli and Triton. **Default.** |
| `tripoli_java_00dc941` | The form in CIRDLES Tripoli (Java) at commit 00dc941: r238/235 = r270/267 / (1 − 2·r18·r270/267); r233/235 = r265/267 / (1 − 2·r18·r265/267). Its 238/235 correction grows with the sample-to-spike ratio. Kept only as a labelled comparison option; the reduction app shows a note on fractions imported with it. |
| `instrument` | The ratios arrived already oxide-corrected from the instrument software, and the writer did not recompute them. The formula is unknown. `U Oxide 18O/16O` holds the value parsed from the instrument function name. |

The reader shows the formula in its issues list. It refuses to merge files whose U rows for one
fraction use different formulas.
- `206Pb/204Pb` and `206Pb/207Pb` are Tripoli's orientations. Readers derive 204/206 and 207/206
  from them, with the same relative error to first order. A writer may add `204Pb/206Pb` and
  `207Pb/206Pb` as well.

### Optional measured correlations

- Column name: `rho <ratio A>|<ratio B>`, with ratio names exactly as above, e.g.
  `rho 206Pb/205Pb|207Pb/205Pb`.
- Value: the correlation coefficient of the two cycle-mean ratios, over the cycles accepted for
  both. It is only given for pairs measured in the same cycles.
- A missing value means unknown. The reduction app then keeps its documented assumption.

### Provenance

Optional, and strongly encouraged from the raw-data app.

| Column | Meaning |
|---|---|
| `Pb Raw File`, `U Raw File` | Raw file names |
| `Pb Raw SHA256`, `U Raw SHA256` | Hex SHA-256 of each raw file as read |
| `Pb Run Start`, `U Run Start` | ISO 8601 with offset, when the offset is known. Otherwise leave the column empty and put the instrument's local time text in `Notes`. |
| `Instrument` | e.g. `IsotopX IsoprobeT (BSU)` |
| `Pb Cycles Used`, `Pb Cycles Total`, `U Cycles Used`, `U Cycles Total` | Integers. Cycles Used counts the cycles accepted for every one of that element's exported ratios (the intersection). With synchronised rejection, this equals each ratio's n. |
| `Filter Rule` | Short text, e.g. `2-sigma iterative, Tripoli-equivalent`. When both runs are present: `Pb: <text> \| U: <text>` |
| `U Oxide 18O/16O` | The 18O/16O used for the oxide correction (see `U Oxide Formula`) |
| `U Oxide Formula` | `isobar_233_18O`, `tripoli_java_00dc941` or `instrument` (see above) |
| `Raw App` | Writer name and version, e.g. `filament 0.1.0` |
| `Raw App Session`, `Raw App Session SHA256` | The writer's own session file (rejected block/cycle lists, dead time, Daly gain, baseline and interference settings); readers keep it as provenance |
| `Exported At` | ISO 8601 with offset |
| `Notes` | Free text |

## Legacy (reader side only)

A CSV without a `Contract` column is read in today's IDTIMS_UPbRPy/Tripoli layout
(`examples/MA1_zircon_CA-ID-TIMS.csv`):
- `Grain ID` is taken as the fraction label (`Fraction ID`).
- All other column names are the same as in this contract.

Notebook users see no change. `load_grains` keeps its defaults (`id='Grain ID'`), and the
reduction app passes `id='Fraction ID'`.
