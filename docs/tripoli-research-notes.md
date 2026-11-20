# Tripoli research notes for a Python re-implementation (IsotopX Phoenix / IsoprobeT ID-TIMS)

Date: 2026-11-14. Research only, nothing built or run except reading files and opening one SQLite file read-only.

## Sources examined

| Source | Where | Version / commit |
|---|---|---|
| Current Tripoli (Java 17 / JavaFX) | https://github.com/CIRDLES/Tripoli, cloned `--depth 1` to `~/scratchpad/tripoli` | commit `00dc941` (2026-10-09) |
| Legacy C# Tripoli ("OGTripoli") | https://github.com/CIRDLES/OGTripoli (fork of `bowring/Tripoli`), cloned to `.../scratchpad/ogtripoli` | `.currentVersion` = 4.10.0.3 (2021) |
| Tripoli user manual | https://github.com/CIRDLES/tripoli-manual, cloned to `.../scratchpad/tripoli-manual` | 2024-06 |
| ET_Redux | local `~/Github/ET_Redux` | commit `01fc486` (2022-07-31) |
| Other CIRDLES repos checked | `Tripoli-Issues` (issues only, "Code available on request"), `Matlab4Tripoli` (README + LICENSE only, no code) | via `gh api` |

In the rest of this file, `TC/` means `tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/`, `TA/` means `tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/`, `TR/` means `tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/`, `OG/` means `ogtripoli/source/`, and `ER/` means `~/Github/ET_Redux/src/main/java/org/earthtime/`.

---

## 1. Licenses

| Project | License | Copyright holder (from file headers) | Evidence |
|---|---|---|---|
| Current Tripoli | Apache License 2.0 | Upstream copyright holders; preserved in the vendored fixture NOTICE | `tripoli/LICENSE`; `tripoli/CITATION.cff` (`license: Apache-2.0`); header in every `.java` file |
| Legacy C# Tripoli (OGTripoli) | Apache 2.0, per file headers. **The repo has no LICENSE file** and GitHub reports license "none" for both `CIRDLES/OGTripoli` and `bowring/Tripoli` | Upstream copyright holders (see file headers) | header of `OG/vendors_data/IsotopXPhoeniX_ImportedTIMSDPDataFile.cs`, `OG/TripoliLicense.cs`, etc. |
| ET_Redux | Apache License 2.0 | Upstream copyright holders (see file headers) | `ET_Redux/LICENSE`; README badge; header in `ER/UPb_Redux/fractions/UPbReduxFractions/UPbFraction.java` |
| Tripoli manual | CC-BY-4.0 in the page front-matter (`license: CC-BY-4.0`); the repo itself has no LICENSE file | Upstream manual author (see front matter) | `tripoli-manual/using_Tripoli/06-LoadingData.md` |

None of these repos has a NOTICE file.

Third-party content inside Tripoli to watch out for: `TC/utilities/mathUtilities/MatLabCholesky.java` embeds MATLAB source comments marked "Copyright 1993-2017 The MathWorks, Inc." Do not copy that file or its comments.

**What Apache 2.0 allows (general reading of the license text, not legal advice):**
- A clean re-implementation in Python that reuses ideas, algorithms, file-format knowledge and published formulas needs no license at all. Copyright covers expression, not methods or facts. A credit line ("informed by CIRDLES Tripoli and ET_Redux") is courtesy, and also good scholarly practice: cite G-cubed 12 (2011), Q0AA19, doi:10.1029/2010GC003479.
- Physical constants, default parameters (for example 18O/16O = 0.00205, Chauvenet probability 0.5, minimum 20 data points) and lists of ratio names are facts or uncopyrightable short phrases, so copying them is fine. Whole data tables (for example `NuclidesChartData.csv` or the periodic-table CSV) are also Apache-licensed, so you can include them with attribution.
- Example data files in the repo (`.TIMSDP`, `.exp`, `.xls` and the `Oracle-*` expected reports) are Apache-2.0 as part of the repo. You can vendor them as test fixtures if you keep a LICENSE copy and an attribution note.
- **If you ever translate code directly** (Java to Python line by line, which counts as a derivative work), Apache 2.0 section 4 requires you to: (a) include a copy of the Apache 2.0 license; (b) state prominently in each modified file that you changed it; (c) keep all copyright, patent, trademark and attribution notices from the source; (d) carry forward any NOTICE file (there is none). You may license your own additions differently, including MIT, but the translated parts stay under Apache terms with those notices. Apache 2.0 is compatible with GPLv3 but not GPLv2. Section 6 grants no trademark rights, so do not call the product "Tripoli".
- Legacy C# code: the per-file headers grant Apache 2.0, so the same rules apply. Because the repo lacks a LICENSE file, treat the headers as the grant and keep them if you translate.

---

## 2. File formats Tripoli reads

### 2.1 Dispatch table (current Tripoli)

`TC/constants/MassSpectrometerContextEnum.java` holds a keyword list per format. The first lines of a file are matched against it. `caseNumber` 1 means per-cycle "lite" data (instrument-computed functions). `caseNumber` 4 means raw integrations for the MCMC engine.

| Enum | Matches | Parser method | Case |
|---|---|---|---|
| `PHOENIX_TIMSDP_CASE1` | `#HEADER, Analysis, Version, Filename, MethodName, MethodPath, FolderPath, IsoWorksMethod, TFEMode, TFEMonitorPeak` | `PhoenixMassSpec.extractDataFromFileVersion_2_TIMSDP` | 1 |
| `PHOENIX_IONVANTAGE_XLS` | "CYCLE Data" | `PhoenixMassSpec.extractMetaDataAndBlockDataFromIonvantageXLS` | 1 |
| `PHOENIX_FULL` | `#HEADER ... IsoWorksMethod, FolderPath` (raw integrations, `#BASELINES` + `#ONPEAK`) | `extractMetaAndBlockDataFromFileVersion_1_2` | 4 |
| `PHOENIX_FULL_SYNTHETIC` | `Version, Filename, Sample...` (synthetic `#START` files) | `extractMetaAndBlockDataFromFileVersion_1_0` | 4 |
| `TRITON_EXP` | "Triton Analysis Data Report" | `TritonMassSpec.extractMetaAndBlockDataFromFileTriton` | 1 |
| `NEPTUNE_EXP` | "Neptune Analysis Data Report" | `NeptuneMassSpec...` | 1 |
| `NUTIMS_TXT_CASE1` | Nu "Individual Answers" `.txt` | `NuMassSpec...` | 1 |
| `OGTRIPOLI` | "Tripoli tab-delimited output of processed data for:" | `OgTripoliImporter` (imports legacy Tripoli exports) | 1 |

The open dialog filter is `*.txt, *.exp, *.TIMSDP, *.xls` (`TA/utilities/fileUtilities/FileHandlerUtil.java:93`). The manual lists Isotopx Phoenix (IonVantage `.xls`, IsoLinx `.timsdp`), Nu TIMS and Thermo Triton as current, and Neptune and Nu Plasma 3 as planned (`tripoli-manual/using_Tripoli/06-LoadingData.md`).

The legacy C# Tripoli read: Sector 54 `.dat`, MassLynx `.xls` (the old Isoprobe/GV software), Thermo Triton `.exp`, Thermo MAT 261/262 `.txt`, Element2, Nu Plasma, IDTIMS template `.csv`, IonVantage LiveData cycle folders (2011), and IsotopX PhoeniX `.TIMSDP` (added in v4.10, April 2021). See `OG/vendors_data/*.cs`, `ogtripoli/docs/TripoliHelp.txt` and `ogtripoli/docs/ReleaseNotes.txt` lines 15-55. **So both the legacy and the current Tripoli handle IsotopX files.** The legacy app handled IonVantage LiveData folders (2011+) and `.TIMSDP` (2021). The current app handles IonVantage `.xls`, IsoLinx `.TIMSDP` and live data.

### 2.2 IsoLinx `.TIMSDP` (the main target)

This is plain CSV text with `#SECTION` markers. Sections seen in the repo: `#HEADER`, `#SAMPLELIST`, `#COLLECTORS`, `#USERTABLES`, `#ELECTRONIC_OFFSETS` (Purdue only), `#BASELINES`, `#CYCLES`, `#BLOCKS`, `#SUMMARY`, `#FUNCTIONS`, `#END,AnalysisCompleted`.

**Example files in the Tripoli repo (all IsotopX):**
- `TR/dataFiles/IsotopxPhoenixTIMS/Purdue/`: 15 files. Pb: `WH205 z4 Pb-654`, `z5 Pb-658`, `z6 Pb-661`, `z8 Pb-665`, `WH233A  Pb-651`, `WH233A z3 Pb-642`, `z4 Pb-647`, `WH233B z3 Pb-678`. U: `WH205 z41 U-655`, `z51 U-659`, `z6 U-662`, `WH233A z41 U-648`, `z71 U-652`, `WH233B z1 U-671`. Plus `WH205 z9-638`. IsoLinx 2.0.11, November 2022.
- `TR/dataFiles/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion1/`: `NBS981 210325b-392`, `NBS982 201215-51` (IsoLinx 1.2.31).
- `TR/dataFiles/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion2/`: `GHR1 230921 F08b-216` (Pb), `GHR1 230921F03 U-239` (UO2), `NBS981 230024a/b/d`, `NBS982 230024c` (IsoLinx 2.1.16, 2023).
- Expected outputs for each, usable as regression oracles: `TR/cycleReports/IsotopxPhoenixTIMS/**/Oracle-*-report.tsv`, `TR/fullReports/.../Oracle-*-report.csv`, `TR/shortReports/.../Oracle-*.txt`.
- Copies in main resources: `tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/ogTripoli/isotopxPhoenixTIMS/` (`purdue/WH205_z4_Pb-654.TIMSDP`, `kU_IGL/isolinxVersion1|2/*.TIMSDP`, `kU_IGL/ionVantage/NBS981-500_20191208-5563.xls`, `boiseState/B998_F11_13223M02_iz1_Pb1-14973.xls`).
- `tripoli/productDocs/dataFormatDocs/isotopx_examples/NBS 981 try1-12.TIMSDP` and **`NBS 981 try1-12.TIMSAD`**. The `.TIMSAD` file is a **SQLite 3 database** (see 2.4).
- Manual test data: `tripoli-manual/testData/GHR1 20200827-11 Pb-6590.xls` and `GHR1 20200827-11 U run2-6591.xls` (IonVantage).
- **None of the example files contains 202Pb** (no ET535/ET2535 202-205 Pb run). Purdue Pb runs are 205-only spiked (`PbDaly_205_...`). KU GHR1 Pb measures 204-205-206-207-208. All U runs are UO2 with 233-235 spike masses 265/267 (ET2535-style), plus 268 and 272.

**Purdue Pb file, `WH205 z4 Pb-654.TIMSDP`, lines 1-27 (header), verbatim:**
```
#HEADER
Analysis
Version,2.0.11,1.20
Filename,WH205 z4 Pb-654.TIMSDP
MethodName,PbDaly_205_45678_Quick.TIMSAM
MethodPath,C:\IsoLinx\Projects\RIGL.Pro\Methods
FolderPath,C:\IsoLinx\Projects\RIGL.Pro\Analysis\T0098_P003\WH205 z4 Pb.RAW
IsoWorksMethod,PbDaly_205_45678_Quick
TFEMode,False
TFEMonitorPeak,
PerformInterBlocks,True
BeamInterpCycles,True
DeflectBeamDuringJumps,False
ExtraMagnetFlybackTime,0
ActiveSEMDetectors,PM
BlocksToMeasure,15
CyclesToMeasure,10
RejectionSigma,99.0
RejectionPercentage,0.0
Corrected,RAW
BChannels,Yes
DTCorrected,Yes
BaselineFile,
BaselineFrequency,EveryBlock
ProcessingUnits,CPS
AnalysisStart,2022-11-28 6:30:05 AM
AnalysisEnd,2022-11-28 7:40:08 AM
```
Then `#SAMPLELIST` with `Filename, WH205 z4 Pb-654`, `AnalysisMethod`, `SampleSerialNo, 654`, `SampleID, WH205 z4`, `SampleNo`, `SamplePrepMethod, PbDaly_205_SpkdSample`, `TuneFilename`, `ResultsGroup`, `Operator`, `UserP1..6`, `Notes` and `SampleTAG..5`. The KU v2 files give dates as `26/09/2023 12:53:31` (dd/MM/yyyy). Purdue gives `2022-11-28 6:30:05 AM`. Handle both.

`#COLLECTORS` (Purdue):
```
Name,Type,Resistor,Gain,Efficiency,DT
PM,PM,1e+11,1.000000000,1.000000000,29.9000
L5,F,1e+11,1.000000000,1.000000000,0.0000
L4,F,1e+11,1.000363000,1.000000000,0.0000
...  L3 L2 Ax H1 H2 H3 H4 (F = Faraday, PM = Daly photomultiplier; DT in ns)
```
`#USERTABLES` holds `UserT,...`, `UserC,...`, `UserP,...` and `ExternalBetaFactor,0.3716...,123456,...`.

`#BASELINES` has one row per baseline measurement per block. Purdue has `B` channels (`BChannels,Yes`), so it has extra `L5.B ... H4.B` columns. KU v2 has none.
```
ID,Block,Cycle,Integ,PeakID,AxMass,Time,PM,L5,L4,L3,L2,Ax,H1,H2,H3,H4,L5.B,...,H4.B
BL1, 1, 0, 0, BL1, 203.4769, 254.278, 2.000000020e-001, -3.697e-006, ...
```
The U method has three baseline positions per block: `BL1`, `BL2`, `BL3`, at AxMass 273.67.

`#CYCLES`: **the IsoLinx-processed per-cycle values (already baseline-, dead-time- and gain-corrected by IsoLinx), not raw integrations.** Columns are `Cycle,Time,<function comments...>`. Cycle numbers run continuously (1..N over all blocks). Time is in seconds from analysis start, and the jump between blocks shows the baseline/inter-block time.
```
Cycle,Time,i205Pb,R45,R65,R75,R85,R64,R74,R84,R67,R68,R87
1,306.945,5.218627219e+004,5.465990661e-004,1.662568652e-002,...
```
KU GHR1 Pb (v2.1.16) adds intensities per species and Pb-alpha user functions:
```
Cycle,Time,204Pb,205Pb,206Pb,207Pb,208Pb,204/205,206/205,207/205,208/205,206/207,206/208,207/208,206/204,207/204,208/204,alpha 204/206,alpha 207/206,alpha 208/206
1,216.376,7.010102250e+001,7.024492688e+004,7.236925285e+004,4.411586477e+003,1.107083199e+004,9.979513911e-004,...
```
`#BLOCKS` holds IsoLinx block statistics, one row per (block, function): `Block,Function,MeanR,SdR%,SeR%,Incl,Total,Mean,Sd,Sd%`.
`#SUMMARY` holds whole-run statistics: `Function,Mean (Aft),Std Dev% (Aft),Std Err% (Aft),Included,Total,Mean,Std Dev,Std Dev%`.

`#FUNCTIONS` defines every column, which makes it the best place to learn channel and sequence assignments:
```
Function,Comment,Formula
PCI_1, i205Pb, Intensity(2,_RPM)            <- peak-hop sequence 2 on the Daly ("RPM")
Srr_1, R45, Intensity(1,_RPM)/Intensity(2,_RPM)
...
UF_1, alpha 204/206, 0.5*(1-(0.059042/Srr_1))*100   (KU; user function referencing other functions)
```
U file, `WH205 z41 U-655` (Purdue, all-Faraday static UO2), header lines 4-5:
```
MethodName,UO2_Faraday_265_267_268_270_272_AllFaraday.TIMSAM
...
BlocksToMeasure,50
CyclesToMeasure,15
ProcessingUnits,Volts
```
```
#CYCLES
Cycle,Time,265UO2_V,268/265,270/265,272/270,267/265,270/267
1,57.001,2.437749829e-004,9.878336526e-001,1.269608696e+001,2.222970986e-003,7.744537940e-002,1.639360161e+002
#FUNCTIONS
PCI_1, 265UO2_V, Intensity(1,_Low5)
Srr_1, 268/265, Intensity(1,_Low3)/Intensity(1,_Low5)
Srr_2, 270/265, Intensity(1,_Low2)/Intensity(1,_Low5)
Srr_3, 272/270, Intensity(1,_Axial)/Intensity(1,_Low2)
Srr_4, 267/265, Intensity(1,_Low4)/Intensity(1,_Low5)
Srr_5, 270/267, Intensity(1,_Low2)/Intensity(1,_Low4)
```
(This Purdue file has a duplicated `#CYCLES` line. The parser has to tolerate that.)

KU U file, `GHR1 230921F03 U-239` (static Faraday 265-7-8-0, 272 on Daly):
```
MethodName,UO2 Static 265-7-8-0 Faraday 272 Daly 18s BL 22s OP FewPlot.TIMSAM
CyclesToMeasure,110   BlocksToMeasure,100   PerformInterBlocks,False
Cycle,Time,265UO2,267UO2,268UO2,270UO2,272UO2,265/267,270/267,272/270
1,46.664,7.255090711e+006,7.457116055e+006,-9.551564872e+003,1.809868450e+007,8.877115723e+004,9.729083814e-001,2.427035380e+000,4.904840307e-003
PCI_1, 265UO2, Intensity(1,_Low4) ... PCI_5, 272UO2, Intensity(1,_RPM)
```
272/270 is the in-run 18O/16O monitor (238U16O18O / 238U16O2 = 2 x 18O/16O).

**Parser logic (current Tripoli)**, `TC/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PhoenixMassSpec.java`:
- Lines 334-417 (`extractDataFromFileVersion_2_TIMSDP`): checks that line 3 starts with `Version,1.` or `Version,2.`, then runs a phase state machine on section markers. It keeps header lines (for `CyclesToMeasure`, `SampleID`, `MethodName`, `AnalysisStart` and so on), the `#COLLECTORS` rows and the `#CYCLES` rows. It skips `#BASELINES`, `#BLOCKS`, `#SUMMARY` and `#FUNCTIONS`. Block number = `(cycle - 1) / cyclesPerBlock + 1`. `#BLOCKS` ends the cycle data.
- Each row becomes `double[]` with Cycle and Time included (lines 451-482). The result is `MassSpecOutputBlockRecordLite(blockID, cycleData[][])`.
- Header key parsing is in `MassSpecExtractedData.populateHeader` (`.../dataSourceProcessors/MassSpecExtractedData.java` ~lines 82-145): keys `METHODNAME`, `VERSION`, `FILENAME`, `CORRECTED`, `BCHANNELS`, `ANALYSISSTART`, `CYCLESTOMEASURE`, `SAMPLEID`. Date formats tried include `dd/MM/yyyy HH:mm:ss` ("Phoenix") and `yyyy-MM-dd h:mm:ss a`.
- Column classification (`TC/sessions/analysis/methods/AnalysisMethod.java:89-138`): a column is an isotopic ratio when its header matches regex `[^alph].*\d?:?\(?\d{2,3}.{0,2}\/[^alph].*\d?:?\d{2,3}.{0,2}.*`. The first two numbers become the numerator and denominator, and `num_den` is mapped to an ET_Redux name if legal. Other columns (intensities, alpha functions) are user functions. Columns named Cycle or Time are hidden.
- Legacy C# parser `OG/vendors_data/IsotopXPhoeniX_ImportedTIMSDPDataFile.cs:85-240` reads only `SampleID`, `CyclesToMeasure`, `AnalysisStart` and the `#CYCLES` table. Ratio type is "Pb" if the first function name contains "20", otherwise "U". Values <= 0 are set to 0 and treated as bad data.

### 2.3 IonVantage `.xls` (older Phoenix/IsoprobeT software)

`PhoenixMassSpec.extractMetaDataAndBlockDataFromIonvantageXLS` (lines 45-150) uses the jxl library:
- Sheet `CYCLE`: row 1 holds function names from column 2 on. Data starts at row 16 (`countOfHeaderLines = 16`). Columns 0 and 1 are Cycle and Time.
- Sheet `CTRL`: cell (3,7) sample name, (3,11) method name, (3,12) cycles per block, (1,45) boolean beam interpolation (if true, cycles per block +1), (3,17) total used cycles, (3,21) analysis date.
- Aborted runs: block count is computed from the actual row count (April 2024 fix).

The legacy app also read IonVantage **LiveData folders** of per-cycle text files named `*-B<block>-C<cycle>.txt`, with a header holding `Method,"...\<name>.RAW\<sample> <fraction>-<serial>"`, the date, the number of functions and their names, then `#START` (`OG/vendors_data/IonVantageLiveDataCyclesFolder.cs`). Cycles per block = number of `*-B1-*.txt` files.

### 2.4 `.TIMSAD`: SQLite with raw integrations (not parsed by any Tripoli)

`productDocs/dataFormatDocs/isotopx_examples/NBS 981 try1-12.TIMSAD` is SQLite 3, opened read-only. Tables: `HeaderInfo` (AnalysisStart/End, Block, Cycle, InitNoBlocks, InitNoCycles, ActNoBlocks, FdyBData, BICycles, OrgMth, CollConfig ...), `SampleEntryInfo`, `SampleListInfo`, `Events`, `PKCEvents` (peak-centre events with `ScanImage` blob), `AnalogueRB` (6718 rows of instrument read-backs), `Baseline` (120 rows) and `ONPeak` (8657 rows). `Baseline` and `ONPeak` share one schema: `AcqType, Index, AxMass, IDTAG, IDTAG2, IntegCount, Block, CyOrSP, EoS, Last, ReqAxMass, ReqAxMassExp, StartDT, EndDT, FAcqDur, FTimeout, FCh0..FCh10` (Faraday channels), `FCh0B..FCh10B` (B channels), `IC1AcqDur, IC1Timeout, IC1Ch0..IC1Ch7` (ion counter / Daly channels). **This is the only place in the repos with raw per-integration IsotopX data.** No Tripoli code references TIMSAD (grep confirms). If you want the Bayesian/raw path for IsoprobeT, this is the file to target. Its exact semantics (units, channel-to-collector map, `IDTAG` meaning) **are not documented anywhere I found.**

The "Phoenix Full" text format (`#BASELINES` + `#ONPEAK`, columns `ID,Block,Cycle,Integ,PeakID,AxMass,Time,PM,RS,L5..H4`, see `PhoenixMassSpec.java:286-300, 427-429`) is the raw-integration CSV used for the MCMC path. Only synthetic examples ship (`.../dataSources/synthetic/twoIsotopeSyntheticData/SyntheticDataset_*.txt`, `#START` format: `ID,Block,Cycle,Integ,Time,Mass,Low5,...,High4`, with BL rows first, `Cycle=0` for baselines). I could not verify which IsoLinx export produces real `#ONPEAK` files.

### 2.5 Thermo Triton `.exp` (brief)

A tab-separated text block of about 15 metadata lines (`Filename:`, `Date:`, `Sample ID:`, `Method Name:`, `Analysis date/time`, `Data Version`). Then a `Cycle	Time	<ratio columns ...>` table where Time is Unix seconds and columns carry Triton's own equations (for example `238/235 oc = (R3/R2)/((1/R2)-(2*R18))`). Values prefixed `X` were outliers rejected by Triton, and `D` marks missing. It ends with `***	Cup`, `***	Info`, `***	Mean`, `StdErr (%)`, `StdDev`, `Valid Values` rows. See `TR/dataFiles/TritonTIMS/ETH/21341_ R9_z2_U_STAT.exp` lines 1-17 and 418-425. Legacy behaviour: X values are shown as outliers but the user can re-include them (`ogtripoli/docs/TripoliHelp.txt`).

---

## 3. Methods

### 3.1 What current Tripoli actually computes for TIMSDP (case 1)

**Tripoli does not compute per-cycle ratios, baseline subtraction, dead time or gains for TIMSDP or IonVantage files.** It takes IsoLinx's per-cycle function values as given. The header says `Corrected,RAW`, `DTCorrected,Yes` and `BChannels`. Collector gains and DT are in `#COLLECTORS`, and IsoLinx applied them. Tripoli's work is statistics, rejection, the UO2 oxide correction and custom expressions.

**Statistics** (`TC/sessions/analysis/AnalysisStatsRecord.java:55-140`, `BlockStatsRecord`, `GeometricMeanStatsRecord.java`):
- "Cycle mode" (the default; block mode was "abandoned for now" in October 2024 per a code comment) pools all included cycles of included blocks.
- For **isotopic ratios, statistics are computed on ln(ratio)** (or -ln for inverted display). Reported mean = exp(mean ln r), a geometric mean. Bands are exp(mean +/- 1 or 2 SD or SE). SE = sqrt(var/n).
- For non-ratio functions (intensities, alphas): arithmetic mean, SD and SE.
- Block mode: inverse-variance weighted mean of block means, its 1 sigma = sqrt(1/sum w), and MSWD (`chiSquared / (nBlocks-1)`).
- Export uncertainty (`TC/sessions/analysis/outputs/etRedux/MeasuredUserFunction.java:63-115`): ratio in cycle mode gives value = geometric mean and oneSigma = **percent 1 SE**, taking the smaller of the + and - asymmetric percentages. Non-ratios give arithmetic mean and percent SE.

**Outlier rejection:**
- Manual: click or box-select points per block in "sculpting mode", toggle whole blocks, and SYNCH a selection across all plots (`tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/docs/ogTripoliHelp.md`).
- **Chauvenet's criterion**, one pass (button "Chauvenet") (`TC/utilities/mathUtilities/MathUtilities.java:63-110`). On included data (n >= `requiredMinDatumCount`, default 20): z = |x - mean|/SD, C = n * erfc(z/sqrt 2), reject where C < P (default P = 0.5). Defaults are in `TC/constants/TripoliConstants.java:82-84` and adjustable in Settings ("Chauvenet's Criteria: Rejection Probability, Minimum Datum Count"). The code comment says outliers plot in red, statistics are recalculated, and the button is disabled after one use.
- Legacy: per ratio `HandleOutliers { Manual, TwoSigma, Chauvenet }` (`OG/RawRatio.cs:136-146`), with a per-ratio undo history and discard handling `Include/Ignore/Hide`. Default Chauvenet criterion 0.5 (`ogtripoli/Properties/Settings.settings`). Legacy statistics were arithmetic on ratios (`_Mean`, `_StdDev`, `_StdErr`, `_PctStdErr` in `RawRatio.cs:100-110`). The geometric/log-ratio approach is new in current Tripoli.

**UO2 oxide correction** (automatic when the column names contain both 270/267 and 265/267): `AnalysisMethod.java:141-171` and `MassSpecOutputBlockRecordLite.java:29-43`. Default 18O/16O = 0.00205 (`TripoliConstants.java:88`), editable in Settings. It adds three columns per cycle:
```
233/235oc = R265_267 / (1 - 2*r18*R265_267)
238/235oc = R270_267 / (1 - 2*r18*R270_267)     <-- see discrepancy below
238/233oc = 238/235oc / 233/235oc
```
`autoUO2Correction.md` says only the 233U16O18O-on-235U16O16O interference is corrected (none for 236UO2 on 238UO2), and cites "McLean et al., 2011". The math image it refers to (`UO2OxideCorrectionMath.png`) is **not in the repo**.

**DISCREPANCY (important for your spec):** legacy Tripoli (`OG/TripoliWorkProduct.cs:2655-2672`), Thermo Triton's own equation, and ET_Redux's `R238_235oc` (`ER/UPb_Redux/valueModels/definedValueModels/R238_235oc.java`) all use
`238/235oc = R270_267 / (1 - 2*r18*R265_267)`, with **R265_267** in the denominator. That form is the physically correct one, because the interference on mass 267 scales with 233UO2 at mass 265. Current Tripoli uses **R270_267** in the denominator. Its own oracle file confirms this: `TR/cycleReports/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239-report.tsv`, cycle 1: 265/267 = 0.97291 and 270/267 = 2.42704 give 238/235oc = **2.45143**. The legacy formula gives 2.43675, about 0.6% lower. ET_Redux back-calculates r270_267m from the imported 238/235 and 233/235 using its own (legacy) formula and then re-corrects with r18O_16O_revised, so the round trip does not recover the measured 270/267 if Tripoli used the other formula. **Recommendation: implement the legacy/ET_Redux formula, put a regression test on it, and consider reporting this upstream to CIRDLES.** Not verified: whether CIRDLES intends this, or whether an open issue exists.

**Custom expressions:** the user can type expressions over columns (shunting-yard parser, `TC/expressions/...`, ops `+ - * / ^ exp log sqrt`). Expressions are saved per method name as defaults (`AnalysisMethod.populateCustomExpressionFunctions`). A user could do a fractionation correction this way.

**Fractionation correction in current Tripoli: none.** `MeasuredUserFunction.fracCorr` is always false and `ETReduxFraction.meanAlphaU` and `meanAlphaPb` stay 0.0 (`TC/sessions/analysis/outputs/etRedux/ETReduxFraction.java:57-70`). There is no tracer model code: `parameterModels/tracerModels/` holds only a README. No BaPO2 or Tl interference correction either. ET_Redux therefore does the Pb fractionation correction (from r202_205m and tracer r202_205t) and the U double-spike correction during reduction.

### 3.2 Legacy C# Tripoli corrections (this is where double-spike, BaPO2 and Tl lived)

`OG/TripoliWorkProduct.cs`:
- **Pb fractionation (linear law per amu, from 202/205):** `alphaPb = (1/3) * (1 - r202_205t / r202_205m)` per cycle (`CalculateAlphaPbForFractionationCorrectionOnly`, ~line 2025). Corrections per cycle: 206/204 x(1+2a), 207/204 x(1+3a), 208/204 x(1+4a), 206/207 x(1-a), 206/208 x(1-2a), 204/205 x(1-a), 206/205 x(1+a), 207/205 x(1+2a), 208/205 x(1+3a) (lines ~1685-1715). If 202/205 is missing, a user-entered alphaPb is used. ET_Redux's `AlphaPb` uses the same formula (`ER/UPb_Redux/valueModels/definedValueModels/AlphaPb.java`, `CalculateValueI`).
- **Pb with BaPO2 and Tl isobaric interference (Noah McLean's math, v4.6.2.60, 2010):** a closed-form alphaPb from measured 201/205, 202/205 and 203/205, tracer 202/205t, and model BaPO2 ratios 201/202/203/204 to 205 plus Tl 203/205 (`CalculateAlphaPbForInterferenceAndFractionationCorrectionBoth`, line 2038). Then r205BaPO2/205Pb and r205Tl/205Pb are computed, and x/205 ratios are multiplied by `(1 + n*alpha)*(1 + r205Tl_205Pb + r205BaPO2_205Pb)` minus the 204 interference terms. Isotopic compositions come from `OG/earth_time_org/BariumPhosphateIC.cs` and `ThalliumIC.cs` (percent Ba 130-138 and O 16-18, percent Tl 203/205). The math write-up is `ogtripoli/docs/BaPO2_Tl_Interference.pdf`.
- **U double-spike (233-235) fractionation:** alphaU per cycle from a closed form using measured oxide-corrected 233/235 and 238/235, tracer r233_235t, r238_235t and concU235t, tracer mass, lab U blank mass with its r238_235b, and sample r238_235s (assumed 137.88 by default) (lines 1263-1300, "Case 1 - april 2008"). The correction is then linear per amu: 233/235 x(1-2a), 238/235 x(1+3a), 238/233 x(1+5a). The 233-236 tracer was "not yet supported" for U fractionation. Tracer types recognised: "mixed 202-205-233-235", "mixed 205-233-235", "mixed 202-205-233-236", "mixed 205-233-236". **No exponential or power law anywhere in Tripoli: linear only.**
- Oxide correction: 233-235 tracer (lines 2495-2735) and a 233-236 tracer variant (line 2736). Default r18O_16O was 0.002 in the legacy app versus 0.00205 now.

### 3.3 Raw-data / Bayesian engine (current Tripoli, case 4, the "MCMC1/MCMC2" buttons)

`TC/sessions/analysis/massSpectrometerModels/dataModels/mcmc/` and `.../mcmc2/`. For raw-integration Phoenix Full files it fits per block: baseline means and SD per Faraday, **Daly/Faraday gain** (`detectorFaradayGain`), log-ratios, intensity as a B-spline over time (`I0`, `SplineBasisModel`), and signal noise. It uses adaptive Metropolis or reversible-jump MCMC (the cited reference is Roberts 2008, "Adaptive Metropolis", `docs/references.md`). Dead time per detector is stored (`Detector.detectorDeadTime`). Outputs are ensembles per block, convergence plots and peak-shape (`PeakShapeProcess`) demos. The CITATION and NSF abstract describe log-ratio analysis, EM handling of rejected data and RJ-MCMC (`docs/nsf_award_abstract.md`). Tripoli builds no MCMC models from TIMSDP data.

### 3.4 Papers

Verified:
- Bowring, J.F., McLean, N.M., Bowring, S.A. (2011) "Engineering cyber infrastructure for U-Pb geochronology: Tripoli and U-Pb_Redux", G-cubed 12, Q0AA19, doi:10.1029/2010GC003479 (open access via MIT DSpace https://dspace.mit.edu/handle/1721.1/73487). Confirmed by web search.
- In-repo: "McLean et al., 2011" for the UO2 math (`autoUO2Correction.md`); Roberts 2008 Adaptive Metropolis (`docs/assets/articles`). Conference items only: AGU 2023 poster (Burdick), GRC 2023, GSA 2024 abstract, AGU 2025 abstracts (McLean, "Tripoli: New Software Tools for Interactive TIMS and MC-ICPMS Data Reduction and Uncertainty Estimation"; Burdick, "An Adaptive Monte Carlo method for analyzing raw multicollector mass spectrometer data"), GSA 2026 poster (`docs/publications.md`, `docs/_posts/2025-08-26-AGUAbstractsAnnouncement.md`, `2026-10-09-GSAPosterAnnouncement.md`).
- **There is no peer-reviewed "new Tripoli" paper in the repo.**

Likely relevant but not checked against the repo text (from my own knowledge, so verify before citing): McLean, Bowring & Bowring 2011 G-cubed 12, Q0AA18, "An algorithm for U-Pb isotope dilution data reduction and uncertainty propagation" (the "McLean et al. 2011" behind the oxide math and ET_Redux reduction); Condon et al. 2015 and McLean et al. 2015, GCA 164, the ET535/ET2535 tracer calibration papers.

---

## 4. What Tripoli exports to ET_Redux

**File:** one XML per fraction per element, root `<UPbReduxFraction>`, serialized with XStream (`TC/utilities/xml/ETReduxFractionXMLConverter.java:50-97`, `MeasuredRatioModelXMLConverter.java:55-85`). Schema: `https://raw.githubusercontent.com/EARTHTIME/Schema/UPbReduxInputXMLSchema.xsd` (local copy at `tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/schema/UPbReduxInputXMLSchema.xsd`). File name `<sampleName>_<fractionID>_<Pb|U>.xml` (`TA/AnalysisManagerController.java:408-409`).

Element order: `sampleName, fractionID, ratioType (Pb|U), pedigree ("None"), measuredRatios[ MeasuredUserFunctionModel{ name, value, uncertaintyType ("PCT"), oneSigma, fracCorr, oxideCorr } ], meanAlphaU, meanAlphaPb, r18O16O, labUBlankMass, r238235b, r238235s, tracerMass`. The schema also lists an optional `grainID`.

**Ratio names (no `r` prefix or `m` suffix)** from `TC/DataDictionary.java:22-38`:
- Pb: `206_204, 207_204, 208_204, 206_207, 206_208, 204_205, 206_205, 207_205, 208_205, 202_205`
- U: `238_236, 233_236, 238_235, 233_235, 238_233`

All ten Pb (or all five U) ratios are always written; ratios not measured get value 0. `oneSigma` is **percent 1 sigma standard error** (`MeasuredUserFunction.refreshStats`), from the geometric mean of log ratios in cycle mode. U values are the oxide-corrected `233/235oc`, `238/235oc` and `238/233oc` with `oxideCorr=true`, and r18O16O carries the 18O/16O used. Inverted ratios can be mapped: if a column is 205/206, its inverse name 206_205 is offered (`setInvertedETReduxName`).

**Delivery:**
1. "Export ETRedux" or menu "ET_Redux Export": save dialog (`TA/utilities/fileUtilities/FileHandlerUtil.java:238-250`).
2. Live workflow (`TA/AnalysisManagerController.java:345-447`): saves the session, looks up `<SampleMetaDataFolder>/<sample>.xml` (written by ET_Redux), matches the fraction file name against each `FractionMetaData` entry's `fractionXMLUPbReduxFileName_U` / `_Pb`, and writes into `<sampleAnalysisFolderPath>/<aliquotName>/<file>`. ET_Redux polls those aliquot folders.
3. Clipboard export: "name (Mean, %StdErr)\nvalue\noneSigma" blocks (`Analysis.prepareFractionForClipboardExport`).
4. Reports: built-in or custom CSV, plus "Cycles Export" (TSV "New Tripoli tab-delimited output", discarded values wrapped in `&`) as in the `TR/*Reports/` oracles.

**How ET_Redux consumes it:**
- `ER/UPb_Redux/samples/Sample.java:481-530` (`processXMLFractionFile`) calls `UPbFraction.readXMLFraction` (`ER/UPb_Redux/fractions/UPbReduxFractions/UPbFraction.java` ~1420-1460, XStream alias `UPbReduxFraction` at line 1513), then either adds a new fraction or calls `updateUPbFraction` (lines 706-770). That copies positive ratios, merges U and Pb into "UPb", sets meanAlphaU and meanAlphaPb, populates r18O_16O and r18O_16O_revised, U blank mass, r238_235s/b and tracer mass, and triggers `UPbFractionReducer.fullFractionReduce`.
- Live folder polling: `Sample.automaticUpdateOfUPbSampleFolder` (lines 590-650) accepts `.xml` files whose first 10 lines contain `<UPbReduxFraction` and that are newer than the folder timestamp minus 20 s.
- Name mapping `206_204` to `r206_204m`: `ER/UPb_Redux/fractions/Fraction.java:728-760`. Canonical names are in `MeasuredRatios` enum (`r206_204m ... r233_236m`).
- Reduction uses: `AlphaPb` (from r202_205m and tracer r202_205t when meanAlphaPb = 0 and 202/205 > 0); `R270_267m`/`R265_267m` back-calculation from imported oc ratios (`UPbFraction.java:436-470`); then `R238_235oc` and `R233_235oc` recomputed with `r18O_16O_revised` (`UPbFractionReducer.java:1870-1895`).
- SampleMetaData: `ER/UPb_Redux/samples/SampleMetaData.java`; folder name constant "SampleMetaData" (`ER/UPb_Redux/ReduxConstants.java:234`); IDTIMS live workflow UI in `ER/UPb_Redux/dialogs/sampleManagers/analysisManagers/SampleAnalysisWorkflowManagerIDTIMS.java:2277-2400`.
- Note: ET_Redux classes such as `TripoliFraction`, `TripoliFractionCommonLeadManager` and `SampleManagerDialogForTripolizedLAICPMS` concern **LA-ICPMS** "tripolized" data inside ET_Redux, not TIMS Tripoli.
- Local `~/Github/ET_Redux/ET_Redux Data/` holds only `ReduxLabData.ser` (88 KB), `ReduxPersistentState.ser` (3 KB) and an empty `samples/`. These are Java-serialized lab defaults (tracers, 18O/16O, blanks). I did not deserialize them.

---

## 5. Session, history, undo

- **Session** (`TC/sessions/Session.java:38-60`): name, analyst, notes, file path, map of analyses (`TripoliSessionAnalysisMap`), session default parameters and colors, live-data state. Saved as a **Java-serialized `.tripoli` file** (`FileHandlerUtil.java:45-48`; `serializeObjectToFile`). It is not portable or human-readable. Menu: New/Open/Open Recent/Open Demonstration/Save/Save As/Close Session.
- **Analysis** (`TC/sessions/analysis/Analysis.java`): name, analyst, lab, sample, sample description, fraction, data file path, method, user functions (columns) with per-cycle include flags, per-block include flags, reduction mode, parameters (Chauvenet, 18O/16O). Per-cycle state lives in `SingleBlockRawDataLiteSetRecord`. Several analyses with the same sample and fraction can be **concatenated** (Session Manager; legacy did this by time stamp).
- **Parameters cascade:** user defaults, then session defaults, then analysis (Settings window: "Save as default settings for this user", "Save as defaults for this session", "Restore Defaults", "Undo").
- **Undo:** current Tripoli has **no undo stack for data rejection.** It offers "Reset Data" / "Reset All Data" (`TA/dataViews/plots/PlotWallPane.java:471`), a Settings "Undo" (revert unsaved settings), and an undo/redo stack only for the custom-expression editor (`AnalysisManagerController.java:2567, 2764-2850`). Legacy C# had a per-ratio `_UndoHistory` (`OG/RawRatio.cs:160`) and saved `.trip` work files and `.triphis` history files (gains and standards history across files).
- **Live data:** "Start LiveData" watches the IsoLinx LiveData folder via `LiveDataStatus.txt`, ingests per-cycle files in block/cycle order, and appends to the analysis (`PhoenixLiveData.java:82-271`).

---

## 6. User-visible feature inventory (current Tripoli unless marked legacy)

Main menus (`TripoliGUI.fxml`):
- **Session:** New, Open, Open Recent, Open Demonstration Session, Save, Save As, Close, Manage Session.
- **Analysis:** New Analysis, Manage Analysis, Import Analysis from ogTripoli, Start LiveData, Export Analysis, ET_Redux Export, Clipboard Export, Cycles Export.
- **Reports:** Builtin Reports, Custom Reports (Report Builder: categories and columns drag-to-reorder, Generate File, Copy to Clipboard), Generate Report using Template 1.
- **Settings:** Settings Menu.
- **Resources:** Periodic Table.
- **Demos:** RJ MCMC 2-isotope, PeakShapes; Generate MCMC details/vectors per block.
- **Help:** User Manual, videos, GitHub, About.

Analysis Manager: metadata fields (analysis name, analyst, lab, sample, description, fraction); Load Data File, Load Method File, Reload Data; method table with detector details, Baseline Table and Sequence Table (for method files); column selection ("Select Columns to Plot", "Treat as Ratio", "Save Plotted Columns as Default"); a ratio builder (click species for numerator and denominator, invert); Custom Expressions editor (create, edit, undo, redo, "INVALID EXPRESSION!"); "Plot Any Two User Functions" (x-y with saved selections); "Preview and Sculpt Data" button; MCMC1/MCMC2 run controls ("Run All / Run None", block process status); "Export ETRedux".

Preview/Sculpt window (OGTripoliView): tabs "Ratios and User Functions by Cycles and Blocks", "OnPeak Intensities by Time", "OnPeak Residuals by Time". Toolbar: Chauvenet, Toggle ALL Sculpting, Toggle Plots' Stats, Toggle Ratios / LogRatios, Invert all, Ignore Rejects, Tile, Stack, Restore Plots, Replot, Reset Data, Reset All Data, SYNCH, Customize Colors, Plot all Isotopic Ratios / User Functions / Custom Expressions, Legend. Plot shading for 1 sigma, 2 sigma and 2 SE bands plus mean line, rejected data in red. Mouse actions per `ogTripoliHelp.md`: scroll or ctrl-scroll to zoom, right-drag to pan, ctrl-left-click to toggle a block, ctrl-right-click to zoom one block, double-click for sculpt mode, drag a box to toggle points. Units radio: Counts/Volts/Amps; detector toggles F/PM/BL/Gain/Model/Unct.

Settings: Chauvenet probability and minimum count; automatic 18O/16O for UO2; plot colors per species (Faraday, PM, model); dot size scaling; live-workflow paths (LiveDataStatus.txt, ET_Redux SampleMetaData folder); mass spectrometer context.

Legacy-only features worth a decision: double-spike Pb and U fractionation correction with tracer XML import and selection (EARTHTIME tracers); BaPO2 and Tl interference correction; gains-history and standards-history folders with graphs; annotations; histogram overlay (5/10/15/20 bins); per-point 2-sigma auto rejection; file concatenation; PbMacDat cell export.

---

## What I could not verify

- Semantics of `.TIMSAD` tables (channel-to-collector mapping, units, `IDTAG`, `AcqType`); there are no docs in the repos.
- Whether any real IsoLinx export produces the "Phoenix Full" `#ONPEAK` text format, or only synthetic data does.
- Any IsotopX example with 202Pb (ET535/ET2535 Pb with 202-205): none in the repo, so there is no test for a 202/205-based alphaPb path.
- Whether the current-Tripoli 238/235oc formula difference is intended; I found no upstream issue. CIRDLES issues were not searched.
- Content of the IonVantage `.xls` example files; I read only the parser code, not the binary sheets.
- The contents of ET_Redux's `.ser` files and the full `UPbReduxInputXMLSchema.xsd` beyond the element names.
- Exact citations of McLean et al. 2011 Q0AA18, Condon 2015 and McLean 2015, which are from my own knowledge and not checked here. The Bowring et al. 2011 citation was web-verified.
- Legal advice: section 1 is a plain reading of Apache 2.0, not a legal opinion.
