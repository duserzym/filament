# filament: specification (Phase 0)

Status: draft for review by the coordinating session, 2026-11-14. No app code exists yet.
`filament` is a working name Yiming has not confirmed (see "Naming" below).

filament is the raw-data step of the ID-TIMS part of the UPb Lab suite. It does what Yiming does today in
CIRDLES Tripoli:

1. open the IsotopX IsoprobeT run files for each fraction (one Pb run, one U run);
2. review the cycles by block, reject outliers by hand and by rule;
3. apply the corrections Tripoli applies (the UO2 oxide correction);
4. hand the cycle-filtered means with 1σ % standard errors to the ID-TIMS reduction app (IDTIMS_UPbRPy)
   through the agreed contract `idtims-fractions/1` ([contract-idtims-fractions-v1.md](contract-idtims-fractions-v1.md)).

It does not compute ages, spike-strip, or correct for mass fractionation. Those happen in the reduction app,
as they do in the BSU spreadsheet and in ET_Redux today.

## 0. Review decisions (coordinating session, 2026-11-14)

The spec was confirmed for Phase 1 with these conditions, which override anything below:

1. Dead time, gain, baseline, BaPO2/Tl and double-spike fractionation stay out of Phase 1. Studio's theme
   is vendored by copy, with its source commit recorded, so the apps can later share one design package.
   The package names are neutral, with one branding file.
2. The oxide correction uses the ET_Redux form. The current-Tripoli difference is recorded as a factual
   observation (section 1.2). We open no issues and contact no one.
3. Until Yiming says how they reject cycles, **no automatic rejection is applied by default**.
   - Chauvenet and k-σ are explicit actions. Each shows a preview of what it would reject before it is
     applied.
   - Every applied rule is in the history and in the exported provenance.
   - The "Auto" button of the GUI therefore does not reject anything in Phase 1.
4. Synthetic fixtures carry `synthetic` in the file name and in `tests/fixtures/MANIFEST.toml`. No test that
   claims agreement with BSU numbers may rest on them. Section 11 lists what is still unvalidated against
   real BSU data.
5. Citations from memory are marked as such until checked (section 1.3).
6. Phase 1 pauses after step 4 (engine, contract writer, MA1 round-trip) for a report of numbers and test
   results, then continues with the GUI. The 1280 × 800 screenshots go to Yiming at step 8.

---

## 1. What I found

### 1.1 What the IsoprobeT writes at Boise State (evidence, not guesswork)

**There is no raw IsoprobeT file from Yiming's own runs on this machine.** I searched Yiming's Drive
(`My Drive*/Research/`: `Lab`, `Lab/TIMS`, `Lab_visits/2024_Boise`, `2025_Boise` and `2026_Boise`, and
`Projects`), the `yiming-z@umn.edu` Drive (`Grenville_TIMS`), `~/Github/IDTIMS_UPbRPy` (`examples/`,
`MCR_data/`), `~/Github/ET_Redux/ET_Redux Data` (only `.ser` lab defaults, empty `samples/`), `~/Data`,
`~/Documents` and `~/Downloads`. A Spotlight name search found nothing either. Everything I found there is
fraction-level output: Tripoli means already pasted into BSU spreadsheets.

Three public sources show the format instead:

- **A real Boise State IonVantage workbook** ships in the Tripoli repository (Apache-2.0):
  `TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/ogTripoli/isotopxPhoenixTIMS/boiseState/B998_F11_13223M02_iz1_Pb1-14973.xls`.
  It is a 2018 Pb run, method `Pb 205 Daly 150 ratios`, sample `13223M02 iz1`, job `B0998`, project folder
  `C:\IonVantage Projects\Uranium-Lead.PRO\`. The run was aborted after 96 of 150 ratios, which a reader must
  handle. Layout (I read it with xlrd, which needs its defined-names pass disabled because the workbook's
  name records crash xlrd 2.x):
  - Sheets: `STD, CA, IsoWorks, USER, CYCLE, BLOCK, C-CHARTS, B-CHARTS, MONITORING, TUNING, PARAMS, CTRL, SUMMARY`.
  - `CYCLE`: row 1 holds the function names from column 2 on. Rows 3-11 hold IonVantage's own run statistics
    (`Mean (After)`, `Std Dev% (After)`, `Std Err% (After)`, `Included`, `Total`, `Mean`, `Std Dev`,
    `Std.Dev%`, `Std Err%`). Per-cycle rows start at row 16 with `Cycle`, `Time (s)`, then one column per
    function. Cycles are numbered continuously, and block = (cycle − 1) // cycles per block + 1.
  - The functions are already processed by IonVantage/IsoWorks (`Apply Baselines: 1`, `Correct for STDBL: 1`
    and `Correct for BLKBL: 1` in `CTRL`): 5-sequence peak-hopping intensities (`Pb204+Hg204 S1 int`,
    `Tl205 S2 int`, …), raw ratios, and **BSU user functions named exactly as in Yiming's spreadsheets**:
    `206/204 D`, `206/207 D`, `206/205 D`, `207/205 D`, `204/205 D`, `208/205 D`, `206/208 D`, `207/204 D`,
    `208/204 D`, single-isotope Daly intensities `204 D` … `208 D`, the Faraday equivalents
    (`206/207 F`, `206/205 F`, `206/204 F-D`, …) and `Daly/Faraday Gain`. Some names occur twice
    (two `Daly/Faraday Gain` columns, for example), so columns must be keyed by index and not by name.
  - `CTRL`: sample ID, serial number, method name, cycles per block (15), number of blocks (10),
    total ratios, analysis start time (`Tuesday 3 July 2018 7:46:32`), `Run Terminated`,
    `IsoWorks Error Message` (`Data processing ABORTED!`), IonVantage's own rejection settings
    (`Rejection %: 5`, `Sigma Level: 2`), `Beam Interpolation (BI): 1`, `HT Scaling`, and job code.
  - `USER` lists each user function (`UF_n`), its comment (= the column name) and whether it is summarised.
    The formulas are Excel formulas, of which the file stores only cached values.
  - `MONITORING`: filament current, pyrometer and gauges every 5 cycles. `STD` and `CA` hold the collector
    array (Low8 … High8, `Multiplier` = Daly, `Ax Fara`) per sequence.
- **Yiming's own spreadsheets** confirm the hand-off. In the `Raw Data Input` sheet of
  `IDTIMS_UPbRPy/BSULab_UPbR26XML.xls` and of the eight `Grenville_TIMS/*_UPbR23XML.xls` (plus three
  `Egypt/*_UPbR24XML.xls`), the pasted blocks are headed `206/204 D  (Mean, %StdErr)` …
  `202/205 D  (Mean, %StdErr)` and `238/235 oxide R18 0.00206  (Mean, %StdErr)`,
  `233/235 oxide R18 0.00206  (Mean, %StdErr)`, `238/233 oxide  (Mean, %StdErr)`.
  `name (Mean, %StdErr)\nvalue\noneSigma` is current Tripoli's clipboard export
  (`Analysis.prepareFractionForClipboardExport`). The names are the IonVantage function names.
  So at BSU, current Tripoli only filters cycles and averages them, Pb is not fractionation-corrected, and
  U comes out oxide-corrected with 18O/16O = 0.00206.
- **The other IsotopX format, IsoLinx `.TIMSDP`** (newer Phoenix software), is plain CSV text with
  `#HEADER, #SAMPLELIST, #COLLECTORS, #USERTABLES, #BASELINES, #CYCLES, #BLOCKS, #SUMMARY, #FUNCTIONS, #END`.
  Its `#CYCLES` section also holds instrument-processed per-cycle functions. The Tripoli repo ships 23 real
  files (Purdue and KU, Pb and UO2) with Tripoli's expected outputs (`Oracle-*` short, full and cycle
  reports). Two IonVantage `.xls` examples from KU (GHR1 Pb and U, in `tripoli-manual/testData`) show the
  U layout without BSU's user functions: `i265 i267 i270 i272 270/267 265/267 272/270`, 110 cycles per
  block × 100 blocks.
- **Raw integrations** live only in IsoLinx `.TIMSAD` files (SQLite: tables `Baseline` and `ONPeak`,
  Faraday `FCh0-10` and ion-counter `IC1Ch0-7` channels). No Tripoli version parses them, and their
  semantics are undocumented. IonVantage's raw `.RAW` folders were not available to inspect.

**Consequence for the design:** at BSU the instrument software has already applied the baseline, dead time,
Faraday gains and (through user functions) the Daly/Faraday gain before Tripoli sees the data. Tripoli does
statistics, rejection and, when the file has raw `270/267` and `265/267` columns, the oxide correction.
filament must do the same. Raw-integration processing (baseline fit, dead time, Daly gain) stays *later*,
and only if Yiming can get raw integrations out of the IsoprobeT.

**Not verified:**
- a BSU **U** run file. I don't know whether BSU's `238/235 oxide R18 0.00206` is an IonVantage user function,
  which would mean the oxide correction is already applied in the file, or a Tripoli custom expression;
- any ET2535 Pb file with `202/205` (none exists in any repo);
- whether BSU's IsoprobeT still writes IonVantage `.xls` today or has moved to IsoLinx `.TIMSDP`;
- how IonVantage marks its own rejected cycles in the workbook. The values do not show it: the cycle rows hold
  every cycle, and only the `(After)` statistics reflect IonVantage's 2σ/5% rejection.

### 1.2 What Tripoli does (current Java app and the legacy C# app)

Sources: CIRDLES/Tripoli at commit `00dc941` (2026-10-09), CIRDLES/OGTripoli (legacy C# 4.10.0.3),
CIRDLES/tripoli-manual and the local `~/Github/ET_Redux` at `01fc486`. The detailed notes with file and line
citations are in [tripoli-research-notes.md](tripoli-research-notes.md). The essentials:

- **Statistics** (current, `sessions/analysis/AnalysisStatsRecord.java`, `GeometricMeanStatsRecord.java`):
  - Cycle mode is the default. It pools the included cycles of the included blocks.
  - Isotopic ratios are averaged as ln(ratio), so the reported mean is the geometric mean exp(mean ln r).
    The reported 1σ % is the smaller of (exp(m+se)−gm)/gm and (gm−exp(m−se))/gm, i.e.
    (1 − e^(−se))·100 with se = SD(ln r)/√n (`outputs/etRedux/MeasuredUserFunction.refreshStats`).
  - Non-ratio functions use arithmetic statistics.
  - Block mode, an inverse-variance weighted mean of block means with MSWD, exists but is "abandoned for now"
    in the code.
  - Legacy Tripoli used arithmetic statistics on the ratios.
- **Rejection:**
  - by hand ("sculpting"): click or box-select cycles, toggle whole blocks, SYNCH one selection across all
    plots;
  - by rule: Chauvenet's criterion, one pass, n·erfc(|z|/√2) < 0.5 with at least 20 included points
    (`utilities/mathUtilities/MathUtilities.applyChauvenetsCriterion`), with editable probability and
    minimum count;
  - include flags are kept per function, per cycle and per block;
  - there is no undo for rejection, only Reset Data / Reset All Data;
  - legacy Tripoli also had per-ratio 2σ rejection and an undo history.
- **UO2 oxide correction** (current `AnalysisMethod.java:141-171`, `MassSpecOutputBlockRecordLite.java:29-43`):
  runs automatically when the columns include `270/267` and `265/267`, with a default 18O/16O of 0.00205.
  **Current Tripoli's 238/235 formula differs from the legacy one** (I checked the code myself):
  - current: 238/235oc = R270/267 / (1 − 2·r18·**R270/267**);
  - legacy Tripoli (`TripoliWorkProduct.cs:2655-2672`), Thermo Triton's own equation and ET_Redux
    (`R238_235oc.java`): 238/235oc = R270/267 / (1 − 2·r18·**R265/267**).
  - The interference on mass 267 is 233U16O18O, which scales with mass 265, so the legacy form is right.
  - On Tripoli's own KU oracle cycle (265/267 = 0.97291, 270/267 = 2.42704) the two differ by 0.6 %.
  - filament uses the legacy/ET_Redux form, with a regression test that pins both values. Whether BSU's
    numbers are affected depends on the open question above: an IonVantage user function would not be.
  - Observation for Yiming, to decide whether to report it upstream (we do not contact CIRDLES ourselves):
    in CIRDLES/Tripoli at commit `00dc941`, file
    `TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/MassSpecOutputBlockRecordLite.java`,
    lines 35-38 compute `233/235oc = R265_267 / (1 - 2·r18·R265_267)` and
    `238/235oc = R270_267 / (1 - 2·r18·R270_267)`. Tripoli's expected-output file
    `TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/cycleReports/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239-report.tsv`,
    cycle 1 (265/267 = 0.97291, 270/267 = 2.42704, r18 = 0.00205), gives 238/235oc = 2.45143. The
    R265_267 form used by ET_Redux, legacy Tripoli and the Thermo Triton equation gives 2.43676 for the same
    cycle, 0.6 % lower.
- **Fractionation, BaPO2 and Tl corrections:** current Tripoli applies none (`fracCorr` is always false and
  `meanAlphaPb` and `meanAlphaU` are always 0). Legacy C# Tripoli had them, all with a linear law:
  - Pb from 202/205: α = (1 − 202/205t ÷ 202/205m)/3, applied per amu;
  - a closed-form combined BaPO2 + Tl correction from 201/202/203 over 205;
  - the U 233/235 double spike: 233/235 ×(1−2α), 238/235 ×(1+3α).
  BSU's reduction applies the Pb and U fractionation, so filament does not.
- **Export to ET_Redux:**
  - one `<UPbReduxFraction>` XML per fraction per element, holding names like `206_204` with a value and a
    `oneSigma` in percent (1σ standard error);
  - a clipboard block `name (Mean, %StdErr)` (what BSU pastes into the spreadsheet);
  - CSV reports, and a "Cycles Export" TSV in which rejected values are wrapped in `&`.
- **Session:** Java-serialized `.tripoli` files, which are not portable. Several analyses with the same
  sample and fraction can be concatenated. Parameters cascade from user to session to analysis.

### 1.3 Licenses

- Current Tripoli: Apache-2.0, "Copyright 2022 James Bowring, Noah McLean, Scott Burdick, and CIRDLES.org"
  (`LICENSE`, `CITATION.cff`).
- Legacy C# Tripoli: Apache-2.0 per its file headers, "Copyright 2004-2021 James F. Bowring and
  www.Earth-Time.org" (the repo has no LICENSE file).
- ET_Redux: Apache-2.0, "Copyright 2006-2018 James F. Bowring, CIRDLES.org, and Earth-Time.org".
- None of them has a NOTICE file.

What this allows (a plain reading of Apache-2.0, not legal advice):

- filament is a **clean Python re-implementation of the methods**: no line-by-line translation. Methods,
  formulas, file-format knowledge, default constants (18O/16O, the Chauvenet 0.5/20) and ratio names are
  not copyrightable and need no licence. We cite them: README credit plus the papers below.
- Test fixtures copied from the Tripoli repo (`.xls`, `.TIMSDP`, `Oracle-*` reports) are Apache-2.0
  material. We may vendor them under `tests/fixtures/tripoli/` with a copy of the Apache-2.0 licence and a
  NOTICE that names the source repo, commit and copyright holders.
- If we ever translate a function directly, that file carries the original copyright line, the Apache
  licence text and a "changed by" note (Apache §4).
- `MatLabCholesky.java` embeds MathWorks code; never copy it.
- "Tripoli" is CIRDLES's name; filament never calls itself Tripoli.
- filament's own licence is Yiming's choice. Apache-2.0 would match the sources and is compatible with
  them.

Papers to cite:
- Bowring, McLean & Bowring 2011, G-cubed 12, Q0AA19, doi:10.1029/2010GC003479 (Tripoli and U-Pb_Redux;
  verified).
- [FROM MEMORY, unchecked] McLean, Bowring & Bowring 2011, G-cubed 12, Q0AA18 (ID-TIMS data reduction and
  the UO2 math cited by Tripoli's `autoUO2Correction.md`).
- [FROM MEMORY, unchecked] Condon et al. 2015 and McLean et al. 2015, GCA 164 (ET535/ET2535 calibration).

Citations marked FROM MEMORY stay marked until checked against the papers themselves; none goes into the
README or the app's About text before that.

---

## 2. Feature inventory

Must = Phase 1. Later = designed for, built after Phase 1. Not = deliberately out of scope.

| # | Feature | Tripoli behaviour it mirrors | Mark |
|---|---|---|---|
| F1 | Open IonVantage `.xls` workbooks (Pb and U): sample ID, method, blocks, cycles per block, start time, function names, per-cycle values; tolerate aborted runs, duplicate function names, the xlrd name-record crash | `PhoenixMassSpec.extractMetaDataAndBlockDataFromIonvantageXLS` | Must |
| F2 | Open IsoLinx `.TIMSDP` (sections above; both date formats; tolerate duplicated `#CYCLES`) | `PhoenixMassSpec.extractDataFromFileVersion_2_TIMSDP` | Must (cheap, real fixtures exist, protects against a BSU software upgrade) |
| F3 | Route files by content, not extension or user choice (UX rule 4); folders and many files at once | format sniffing in `MassSpectrometerContextEnum` | Must |
| F4 | Classify columns: isotopic ratio vs intensity vs other function; ratio numerator/denominator from the name (`206/204 D`, `270/267`, `Pb206+At206/Tl205 raw`); hide Cycle/Time | `AnalysisMethod` regex | Must |
| F5 | Analysis = one run file. Fraction = the Pb and U analyses that belong together, paired by fraction ID (from the sample ID, e.g. `13223M02 iz1`, editable) | Analysis Manager metadata | Must |
| F6 | Cycle plot wall: each selected function vs cycle, blocks shaded alternately, mean line and 1σ/2σ/2SE bands, rejected points in red, ratio or log-ratio toggle, invert | "Ratios and User Functions by Cycles and Blocks" | Must |
| F7 | Cycle table: block, cycle, time, values, include flags; edits sync with plots | Cycles Export view | Must |
| F8 | Reject by hand: click a point, box-select, toggle a whole block, with SYNCH (apply the same cycles to all functions) on by default | sculpting mode, SYNCH | Must |
| F9 | Reject by rule: Chauvenet (P, min n); iterative k-σ (legacy TwoSigma) as an option; scope run or block; per function or synced | Chauvenet button; legacy TwoSigma | Must |
| F10 | Undo/redo of every rejection and setting change; Reset analysis | legacy undo history; current Reset Data | Must (better than current Tripoli) |
| F11 | Statistics per function: geometric mean of ratios (Tripoli default) and arithmetic option; SD, SE, % SE (Tripoli's smaller-side convention), n used/total; per block too | `AnalysisStatsRecord`, `MeasuredUserFunction` | Must |
| F12 | UO2 oxide correction from `270/267` and `265/267` with editable 18O/16O (default 0.00205, BSU 0.00206), ET_Redux formula; pass-through when the file already has oxide-corrected functions, recording r18 from the name | auto UO2 correction | Must |
| F13 | Show the in-run 18O/16O monitor (`272/270`/2) when present | not in Tripoli; Triton `R18 = R4/2` | Later |
| F14 | Map functions to contract ratios (`206/204 D` → `206Pb/204Pb`, `238/235 oxide…` → `238U/235U`), remembered per method name | ET_Redux name mapping; per-method defaults | Must |
| F15 | Export `idtims-fractions/1` CSV with correlations from shared accepted cycles and provenance | ET_Redux XML export (role) | Must |
| F16 | Copy the Tripoli clipboard block (`name (Mean, %StdErr)`) so Yiming can keep pasting into the BSU spreadsheet during the transition | Clipboard Export | Must |
| F17 | Cycle export CSV with include flags (for audit) | Cycles Export | Must |
| F18 | Session file: all analyses, pairings, flags, settings, history; JSON; re-reads raw files by hash on open | `.tripoli` session (but portable) | Must |
| F19 | Concatenate two runs of the same fraction | Session Manager concatenate | Later |
| F20 | Block mode (weighted block means, MSWD) | block mode (abandoned upstream) | Later |
| F21 | x-y plot of any two functions | "Plot Any Two User Functions" | Later |
| F22 | Intensity vs time and Daly/Faraday gain trend plots | OnPeak intensities tab | Later |
| F23 | Custom expressions over columns | expression editor | Later (only if a needed function is missing from the files) |
| F24 | Raw-integration processing: baseline, dead time, Daly/Faraday gain, beam interpolation from raw integrations (`.TIMSAD` or IonVantage raw) | MCMC engine (Phoenix Full only) | Later, needs data that does not exist yet |
| F25 | Pb fractionation by 202/205 double spike, U by 233/235, linear law | legacy C# only | Not (the reduction app owns it; the contract says ratios are not fractionation-corrected). A diagnostic α plot may come later |
| F26 | BaPO2 and Tl interference correction | legacy C# only | Later, if Yiming needs it; it changes measured ratios, so it would need a contract column saying it was applied |
| F27 | Live data (watch the instrument folder during a run) | Start LiveData | Not for now |
| F28 | MCMC/Bayesian raw-data models, peak shapes | MCMC1/2, demos | Not |
| F29 | Triton, Neptune, Nu, Sector 54 formats | other parsers | Not (BSU uses IsotopX) |
| F30 | Gains and standards history across runs | legacy `.triphis` | Later (database mode) |
| F31 | Database mode, opened from UPb Lab with context | ET_Redux live workflow folders (role) | Later, designed now (section 6) |

---

## 3. Data model (engine, Qt-free)

All engine classes live in the importable package `rawtims` (section 7) and use plain dataclasses and
NumPy arrays. None of them imports Qt, so a notebook can do this:

```python
from rawtims import open_run, Fraction, export_fractions
pb = open_run("B998_F11_13223M02_iz1_Pb1-14973.xls")
pb.reject_chauvenet(); pb.stats("206/204 D").mean
```

- **RawFile**: path as opened, name, size, sha256, detected format and version. It is immutable and is the
  identity of the data.
- **Run (analysis)**:
  - `run_id` (UUIDv7, as in the suite), `raw: RawFile`, `element` (`Pb`/`U`, from the method or columns,
    user-editable);
  - metadata: sample ID, serial, method name, instrument, analysis start (timezone-aware when known),
    blocks, cycles per block, terminated/aborted flag, instrument rejection settings (kept, not used);
  - `functions: list[Function]` keyed by column index, each with name, kind (ratio/intensity/other),
    numerator, denominator, collector hint (`D`/`F` suffix), unit if known;
  - `cycles`: an array (n_cycles × n_functions) plus cycle number, block number and time.
  - Values ≤ 0 or non-numeric in a ratio column are flagged `invalid` and never enter statistics. This is
    legacy Tripoli's behaviour, made visible.
- **RejectionMask**: a boolean `included[n_cycles, n_functions]`, block include flags, and the
  `synced` setting. The effective inclusion is cycle flag ∧ block flag ∧ not invalid.
- **Edit history**: an ordered list of operations (`toggle_cycles`, `toggle_block`, `apply_rule(rule,
  params, result_cycles)`, `set_setting`, `reset`), each storing exactly what it changed. Undo and redo walk
  it. The current mask is always reproducible from raw file + history, which is what the session saves.
- **DerivedFunction**: functions computed by filament, e.g. `238/235oc`, `233/235oc`, `238/233oc` from the
  oxide correction. Each records its formula id, inputs and parameters (r18), so the export can say what
  was applied.
- **Stats** (per function, per block and pooled): mean (geometric or arithmetic, recorded), SD, SE,
  % SE (Tripoli convention), n used, n total, and correlations between the functions mapped to the contract,
  over the cycles included for both.
- **Fraction**: `fraction_id`, the optional Pb run, the optional U run, identity fields from the contract
  (sample, beaker, source grain/spot, mount, aliquot), setup fields if known (weights, spike type and name,
  collector), and a function-to-contract-ratio map.
- **Session**: fractions, runs, settings (statistic mode, Chauvenet P and n, k-σ, r18, SYNCH), per-method
  remembered mappings and plotted columns, history per run, app version. It is saved as JSON
  (`format: "rawtims session"`, `format_version: 1`, extension `.rawtims`), written atomically like
  Studio's `.upbr`. It holds no raw data and no results: on open it re-reads the raw files, checks the
  sha256, replays the history and recomputes. A missing or changed raw file is reported and the session
  opens read-only for that run.

Provenance carried to the export: raw names and sha256, run starts, cycles used and total, the rule text
(e.g. `Chauvenet P=0.5 n>=20, 3 manual cycles`), r18 and whether filament or the instrument applied it,
the method names, `Raw App` = `filament <version>`, `Exported At`, and `Raw App Session` (+ SHA256) pointing
to the saved session that holds the full rejected-cycle lists and settings.

## 4. Output contract

The contract is `idtims-fractions/1`, agreed with the reduction-app session on 2026-11-14. The text is in
[contract-idtims-fractions-v1.md](contract-idtims-fractions-v1.md), byte-identical to
`IDTIMS_UPbRPy/docs/contract-idtims-fractions-v1.md` (branch `app`, `dadb3a1`). In short:

- one CSV row per fraction (UTF-8, full precision) with `Contract = idtims-fractions/1` and `Fraction ID`;
- `<ratio> Mean` and `<ratio> % Standard Error` (1σ % SE of the mean of the accepted cycles):
  Pb 206/204, 206/207, 206/205, 207/205, 204/205, 208/205, and 202/205 for 2535; U 238/235, 233/235, 238/233;
- ratios are baseline-, detector- and oxide-corrected and cycle-filtered, but not fractionation-corrected;
  238/233 needs no oxide correction;
- optional identity, setup, `rho A|B` correlations and provenance columns;
- a row may carry only Pb or only U, and the reader merges rows by Fraction ID across files;
- the version rules: a new optional column keeps the version; a rename or change of meaning makes it /2.

filament side:
- `rawtims.contract` holds a dataclass `FractionRow` with `to_csv`/`from_csv` and a column list that is the
  single source of the header names.
- A test writes the agreed example and reads `IDTIMS_UPbRPy/examples/MA1_zircon_CA-ID-TIMS.csv` (legacy
  layout) without loss.
- A test asserts that the exported mean and % SE of a fixture match Tripoli's `Oracle-*` short report for
  the same file.
- Any change goes through a message to the reduction session first.

## 5. GUI (PySide6)

Built from UPbRPy Studio's design system and patterns. Studio's `GUI` package is not a stable library: its
top-level name is `GUI`, and `GUI/theme.py`, `GUI/icon.py` and `GUI/assets/` hold Yiming's uncommitted work
per `UPbRPy/AGENTS.md`. So filament **vendors a pinned copy** of the committed `theme.py` and of the
`widgets.py` pieces it uses (`SegmentedBar`, `ChipButton`, `StyledComboBox`, `ElidedLabel`,
`RoundedPlotWidget`, `DataFrameTableModel`, `FrozenColumnsView`, `MetricCard`, busy indicator,
`CheckUpdatesButton`/`VersionChip` later) into `rawtims_gui/studio/`, with the source commit recorded in a
header. Extracting a shared `labui` package for all Python apps is a follow-up for the coordinating session to
decide. It touches Studio, which this task must not change.

Layout, at 1280 × 800 and above:

```
+--------+---------------------------------------------+------------------+
| rail   | mode bar: Ratios | Intensities | Table       | inspector tabs   |
| Import |---------------------------------------------| Stats | Rules |  |
| Review |  plot wall: one plot per selected function, | Corrections |    |
| Correct|  cycles on x, blocks shaded, mean+bands,     | Export           |
| Export |  rejected red; SYNCH on                      |                  |
|--------|                                             |                  |
|fraction|                                             |                  |
| list   |                                             |                  |
| z1 Pb U|                                             |                  |
+--------+---------------------------------------------+------------------+
 status bar: run, n used/total, history position, Undo/Redo, version, check updates
```

- **Left rail:** Studio's `WorkflowRail` with four steps (`WorkflowStep` data). Below it, the fraction list:
  each fraction shows chips for Pb and U and a done/attention state.
- **Centre:** a pyqtgraph plot wall like Studio's plot stack. Plots tile or stack with a scroll area once
  there are more than fit (rule 7), with a "plot only contract ratios" default.
- **Inspector:**
  - Stats: a per-function table, including block statistics.
  - Rules: Chauvenet / k-σ with parameters and Apply; results are listed and undoable.
  - Corrections: oxide on or off, r18, where the correction comes from (file or filament), the
    function-to-contract mapping.
  - Export: a preview of the contract rows, with missing fields shown; Save CSV, Copy Tripoli clipboard,
    Save cycles CSV.
- Light by default with Light/Dark/System, an instant state switch, one click for a good result
  ("Auto": Chauvenet on synced contract ratios), every control kept, Reset.
- Opens at 1280 × 800 centred, minimum 1024 × 640, geometry stored per viewer in QSettings, Reset layout.
  Panels collapse or tab before they overflow. Checked at 1440 × 900 and 1280 × 800, with screenshots.
- Keyboard: Delete/Backspace rejects the selection, ⌘Z/⇧⌘Z undo/redo, B toggles the block.
- Long work (opening many workbooks) runs on `QThreadPool` workers like Studio's. Files are small (a 150-cycle
  run reads in well under a second), so Studio's results cache and spawn-child restore are not needed in
  Phase 1. The session replays the history in-process. The design keeps the engine pure, so the same
  cache could be added later.

## 6. Designed for, not built: database mode and UPb Lab

These follow Studio's mechanisms so UPb Lab can treat filament like Studio:

- **URL scheme** from `branding.URL_SCHEME`: `<scheme>://open?path=…`, and later
  `<scheme>://session/<id>?server=…&via=upblab`.
- **Launch:** `--open <file|folder|session|url>`, single instance through `QLocalServer`, macOS
  `QFileOpenEvent`, Windows `--register-url-scheme`.
- **Database mode:** a later `rawtims.integration.laicpmsdb` module (Qt-free, `requests`/`keyring`
  imported lazily from a `[database]` extra) that uploads the run files, session and contract CSV as a
  bundle and links fractions to grains and spots (`Source Grain`/`Source Spot` now, UIDs in a later contract
  column).
- **Inbox:** UPb Lab notice files on submit, as in Studio's `lab_inbox.py`. No laicpmsdb change is needed now.

## 7. Repository, naming, tests, packaging

**Naming in one place.**
- The import packages have neutral, descriptive names that survive a rename: `rawtims` (engine) and
  `rawtims_gui` (GUI).
- Everything user-visible comes from `rawtims/branding.py`: `APP_NAME = "filament"`, the display name,
  executable name, bundle id, URL scheme, QSettings organisation/application, cache folder and the
  `Raw App` export string.
- The session format is named `rawtims session`, so renaming the app does not orphan saved sessions.
- Renaming the app = editing that file, the README title and the PyInstaller spec name. A test greps the
  tree so the literal `filament` appears nowhere else in code.

**Layout.** `pyproject.toml` (setuptools, Python ≥ 3.12; extras `gui`, `dev`, `build`; script
`filament-gui = rawtims_gui.main:main`, its name also taken from branding at build time), `src/rawtims/`,
`src/rawtims_gui/`, `tests/`, `tests/fixtures/tripoli/` (vendored, with LICENSE-APACHE and NOTICE),
`tests/fixtures/synthetic/` (generated files, each marked SYNTHETIC in its name and header), `packaging/`,
`scripts/`, `docs/`.

**Engine rules.** No Qt, HTTP or database imports in `rawtims`. A test asserts that importing `rawtims` and
running a full open → reject → export leaves no `PySide6`, `requests` or `keyring` in `sys.modules`. No lazy
package `__getattr__`. If one is ever added it must raise `AttributeError`, never `ModuleNotFoundError`
(Studio bug 1). A packaged-imports test forbids `from rawtims import <non-submodule>` inside
`rawtims_gui`.

**Tests from the first commit** (like `UPbRPy/docs/testing.md`):
- `make test-quick`: the affected tests through a `scripts/run_tests.py` copied from Studio's (a test map,
  parallel processes, no xdist), skipping `slow`.
- `make test`: the full suite before any build or install.
- Markers `slow` and `isolated`. Qt offscreen with temporary QSettings.
- Numeric tests:
  - reader tests on the vendored real files (BSU B998 Pb `.xls`, KU GHR1 Pb/U `.xls`, Purdue and KU
    `.TIMSDP`);
  - statistics and Chauvenet against Tripoli's `Oracle-*` short and cycle reports for the same files;
  - the oxide correction against hand-computed values for both formulas (pinning the documented 0.6 %
    difference);
  - contract round-trip;
  - synthetic files for the cases no real file covers (ET2535 Pb with 202/205, a BSU U run with
    `238/235 oxide R18` functions), clearly marked synthetic and replaced when Yiming's files arrive.

**Packaging** like Studio:
- `packaging/<APP_NAME>.spec` read from `pyproject` and branding, and `scripts/build_desktop.py` with the
  smoke test on by default. The smoke test runs the frozen app offscreen:
  - `--export png` of an empty window and of a fixture session, each over 10 KB;
  - `--verify <fixture.xls> --verification-output out.csv`, compared with the unfrozen engine's output.
- The results-cache fingerprint bug (Studio bug 2) does not apply while there is no cache. If a code
  fingerprint is ever added, hash the raw PYZ bytes the way Studio's fixed `engine_fingerprint` does.
- The packaged app is built and smoke-tested **at the end of the first GUI step**, not at the end of Phase 1.
- `make clean-build` afterwards, reporting the disk freed.
- CI workflows only on `v*` tags and manual dispatch. No tags, releases or remote until Yiming confirms the
  name.

## 8. Phase 1 plan (after confirmation)

Small steps. Each is audited (diff read and tests run by the supervising session) and committed:

1. Skeleton:
   - `pyproject`, branding, test runner, vendored fixtures with NOTICE;
   - an engine import-purity test;
   - an empty PySide6 window from the vendored theme;
   - a PyInstaller build and smoke test of that empty window (proves packaging early).
2. Readers:
   - IonVantage `.xls` and IsoLinx `.TIMSDP` into `Run`, routed by content;
   - tests on every vendored file;
   - synthetic BSU U and ET2535 Pb files.
3. Engine:
   - statistics, the rejection mask and history, Chauvenet, k-σ, oxide correction, correlations;
   - numeric tests against the Tripoli oracles.
4. Contract writer and reader, Tripoli clipboard and cycle CSV; MA1 round-trip.
5. GUI step A: import, fraction list, plot wall, cycle table, hand rejection with SYNCH, undo.
6. GUI step B: rules, stats, corrections, mapping, export.
7. Session save and restore.
8. Fit checks at 1280 × 800 and 1440 × 900, screenshots for Yiming, a full test suite, a packaged build and
   smoke test, then cleaning the build leftovers.
9. When Yiming's files arrive: validation of the same fractions against their Tripoli numbers in the
   Grenville spreadsheets.

Hands-on work: Opus 5.5 subagents until Codex quota returns on 2026-11-18 12:48, then Codex CLI
(`gpt-6.1-sol`, high), audited the same way.

## 9. Questions for Yiming

1. **Files from the same runs.** For two or three fractions already in a Grenville spreadsheet (for example
   `HH1_titanite` t1, which has Pb on Daly with a BSU1B 535 spike), the export from the IsoprobeT PC:
   - the IonVantage workbook `.xls` of the Pb run and of the U run (the files Tripoli opens), and the run's
     `.RAW` folder if easy;
   - from Tripoli, the saved session (`.tripoli`), the clipboard text you pasted, and "Cycles Export" for each
     run, so the rejections can be matched too.
   One ET2535 fraction with 202/205 would cover the double-spike columns.
2. **The U oxide correction at BSU.** Is `238/235 oxide R18 0.00206` an IonVantage user function (already
   corrected in the `.xls`) or something you set up in Tripoli? Either way, is 0.00206 the value you want as
   filament's default?
3. **Rejection practice.** Do you use Chauvenet, your own k-σ rule, or hand rejection only? Do you reject
   cycles in all ratios at once (SYNCH) or per ratio? The default "Auto" button follows your answer.
4. **Software at BSU now.** Does the IsoprobeT still run IonVantage (`.xls` workbooks), or has BSU moved to
   IsoLinx (`.TIMSDP`)?
5. Licence for the new repositories (Apache-2.0 suggested), and the app name and icon when you are ready.

## 10. Architecture check

- **Qt-free engine, PySide6 GUI, Studio patterns:** confirmed.
- **Standalone files first:** confirmed. The contract is a plain CSV.
- **Test tiers and early packaged smoke test:** confirmed.
- **One correction to the brief:** the brief lists dead time, Daly/Faraday gain, baseline, BaPO2/Tl and
  double-spike fractionation among the Tripoli features. For IsoprobeT data at BSU, the instrument software
  applies dead time, gain and baseline, current Tripoli applies no fractionation or interference correction,
  and the reduction app owns fractionation. Building them in filament would duplicate or contradict
  upstream steps. They are *later* (raw integrations) or *not needed* (fractionation), as marked in
  section 2.
- **One adjustment to "reuse Studio's design system":** vendor a pinned copy instead of importing `GUI.*`
  (see section 5).

## 11. Not yet validated against real BSU data

Real-file tests cover what the vendored Tripoli fixtures contain (the BSU 2018 Pb workbook, KU IonVantage
Pb and U, Purdue and KU `.TIMSDP`) and agreement with Tripoli's own expected outputs for those files.
Still unvalidated:

- U runs from BSU: whether the `.xls` already holds oxide-corrected `238/235 oxide R18 0.00206` functions,
  and filament's U numbers against Yiming's Tripoli U values.
- ET2535 Pb runs with `202/205` (no real file exists anywhere we looked).
- filament's means and % SE against the numbers Yiming pasted into the Grenville spreadsheets: this needs
  the raw files of those fractions.
- Yiming's rejection practice (decision 3 in section 0).
- Whether BSU now writes IsoLinx `.TIMSDP` instead of IonVantage `.xls`.
