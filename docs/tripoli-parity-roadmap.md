# Tripoli parity roadmap

Snapshot: **2026-11-25**. Owner: Yiming Zhang (they/them). Objective: inherit the functionality families of both supplied Tripoli implementations and add capabilities useful to the lab. [The inventory](tripoli-inventory.md) is the row-level source/status evidence; [the gap summary](tripoli-gap.md) remains the short entry point. This is a docs-only plan. No engine or GUI change, full test run, or new numerical validation was performed for this task.

There are **95 inventory rows: 19 done, 24 partial, 52 not done**. All 76 incomplete rows are in scope below, including F13, F15, F18–F31, histogram F32, annotations F33 and the newly numbered long tail. Umbrella and child rows overlap; phase coverage is not a sum of independent algorithms. “Done” retains the supported-input limits in the inventory and does not close a partially implemented child row.

## Priority decision: F25 ownership and the fraction contract

Filament currently exports **measured, non-fractionation-corrected, non-spike-stripped ratios**. IDTIMS_UPbRPy / the UPb Studio hub owns fractionation and tracer calibration. This is specified in [the contract Purpose and measured-ratio rules](contract-idtims-fractions-v1.md#purpose), especially its [measured-ratio section](contract-idtims-fractions-v1.md#measured-ratios); [raw reduction](raw-reduction.md#desktop-reduction-controls) retains that boundary. Inventory F25/F61–F65 record the legacy correction capability and its missing filament counterpart.

**Decision D1 for Yiming: move correction into filament, keep it in the age app, or add an opt-in filament preview? Recommendation: opt-in preview with the age app remaining authoritative.** This gives raw-data reviewers a diagnostic alpha/calibration view without applying fractionation twice.

| Option | User-visible behavior and ownership | Consequence for docs/contract-idtims-fractions-v1.md |
|---|---|---|
| Move into filament | Filament owns validated Pb 202/205 and U double-spike correction, calibration records, model versions, uncertainty propagation, correction reports and batch revisions. Age app must accept already-corrected inputs without applying its correction again. | Moving internal ownership alone can preserve /1 **only if its existing columns still carry uncorrected measured ratios**. Exporting corrected values in those same columns changes their meaning and requires a separately agreed /2, reader capability checks, explicit correction/tracer/calibration provenance and coordinated age-app migration. An optional flag does not legalize a semantic change under /1. |
| Keep in age app | Filament continues measured ratios and calibration metadata; provide a linked age-app workflow for tracer editing, alpha, calibration and batch correction. F25 numerical capability remains outside the filament engine until delegated integration provides an equivalent user workflow; do not relabel it “done” merely by deferring it. | Keep /1 unchanged; clarify ownership and diagnostic links in both repositories when approved. Any optional metadata may be additive only if units/meanings of current columns remain unchanged. This meets suite-level parity, but not a strict requirement for every calculation to execute inside filament. |
| Opt-in preview (recommended) | An isolated new function/model produces diagnostic alpha, corrected preview ratios and a comparison to the age engine. It never replaces Analysis measured columns, masks or export mapping. Mark the display “preview; measured ratios exported.” Age app remains authoritative for final correction/calibration. | Preserve /1 byte/semantic contract. No corrected preview value enters existing measured-ratio fields. If preview provenance is ever exported, agree optional names that explicitly describe a diagnostic; a separate preview artifact is simpler. Keep the shared contract documents synchronized; this task does not edit either. |

For F26 interference, a later implementation must also agree whether it is an upstream measured-ratio correction and how applied/absent status is represented. Existing /1 says ratios are baseline/detector/oxide corrected; it does not authorize silently adding BaPO2/Tl correction. Resolve D11 before defining that export route.

## Common invariance gate G0

Every phase below uses **G0**, including GUI-only phases. Before implementation, capture a baseline on an isolated checkout with pinned engine, Python/NumPy/dependencies, fixture bytes, explicit settings/masks and a fixed export time. Record commit, source/fixture SHA-256, commands, exit codes and before/after output hashes. Another GUI session is active during this audit; these documentation counts are not evidence that its numerical outputs were checked.

The **processing check** must cover processed XLS/TIMSDP parsing, arithmetic/geometric statistics, both oxide laws, shared/per-ratio masks, legacy replay and supported raw routes, plus the resulting CSV/clipboard/cycle exports. There is no single repository command named “processing check” found in this audit. Use the existing deterministic teaching generator as one concrete check:

```sh
env -u PYTHONPATH .venv/bin/python scripts/docs_site_data.py --output "$PARITY_CHECK_BEFORE"
env -u PYTHONPATH .venv/bin/python scripts/docs_site_data.py --output "$PARITY_CHECK_AFTER"
shasum -a 256 "$PARITY_CHECK_BEFORE/data/values.json" "$PARITY_CHECK_AFTER/data/values.json"
shasum -a 256 "$PARITY_CHECK_BEFORE/javascripts/z1-data.js" "$PARITY_CHECK_AFTER/javascripts/z1-data.js"
cmp "$PARITY_CHECK_BEFORE/data/values.json" "$PARITY_CHECK_AFTER/data/values.json"
cmp "$PARITY_CHECK_BEFORE/javascripts/z1-data.js" "$PARITY_CHECK_AFTER/javascripts/z1-data.js"
make test
```

These are **future implementation commands, not commands run for this docs-only task**. Set both PARITY_CHECK variables to distinct disposable directories outside the repository/Tripoli clones. The generator uses the read-only BSU examples and the separately installed age-engine environment; if either is missing, stop that acceptance gate and name the missing input. It must not silently count as a pass. Its payloads are deterministic (see [SITE.md](SITE.md#numbers-on-the-pages)); the generated grid already exercises ratios, correlations, raw parameters and downstream dates.

The generator is **necessary but insufficient**: it does not cover all parser variants, JSON sessions or clipboard dialects. Also capture canonical per-fixture numerical arrays/statistics/masks and exact export bytes using existing APIs in [analysis.py](../src/rawtims/analysis.py), [exports.py](../src/rawtims/exports.py), [session.py](../src/rawtims/session.py) and [reprocess.py](../src/rawtims/reprocess.py). Add a deterministic processing-check runner as a separately reviewed implementation task before the first engine phase, with fixed export time and identities, canonical JSON/float encoding and one SHA-256 manifest for all these outputs. The existing [parity audit](../scripts/tripoli_parity.py) can supply independent legacy comparisons; its Markdown report includes elapsed time, so hashing the entire report is not a numerical invariance test.

Run the full `make test` on the baseline as well as after implementation; record both results.

**Acceptance:** old-default outputs and processing-check hashes must be identical before/after, and the **full `make test`** must pass, with skips/fixture availability reported. New numerical behavior must live in new functions or explicit, versioned opt-in settings; old session defaults, row/function identities and ordinary /1 exports retain their meaning. GUI presentation tests may change images while the numerical/export manifest stays identical. Compare new paths separately to named oracles with justified tolerances; never widen old tolerances to force a pass. A defect correction that intentionally changes old outputs needs its own decision and versioned migration, not an exception hidden in a parity phase.

No full tests or processing generation are run in this documentation task. See the final check section for the actual narrow docs checks.

## Fixture and oracle ledger

All paths below are relative to the containing Tripoli source directory, prefixed OGTripoli/ or Tripoli/. These files were located and opened in the supplied clones. File aliases keep the phases readable; aliases are data sources, not claims of a passing comparison.

| Alias | Verified files | Expected values and limitations |
|---|---|---|
| A | `Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/dataFiles/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion2/GHR1 230921 F08b-216.TIMSDP`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/dataFiles/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion2/GHR1 230921F03 U-239.TIMSDP`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/fullReports/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239-report.csv`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/shortReports/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921 F08b-216.txt`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/shortReports/IsotopxPhoenixTIMS/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239.txt` | Processed Pb/U cycles and stored Java summary/report expectations. U includes Java oxide-law results, not an instruction to change filament defaults. |
| B | `Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/dataFiles/IsotopxPhoenixTIMS/Purdue/WH205 z4 Pb-654.TIMSDP`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/dataFiles/IsotopxPhoenixTIMS/Purdue/WH205 z41 U-655.TIMSDP`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/fullReports/IsotopxPhoenixTIMS/Purdue/Oracle-WH205 z41 U-655-report.csv` | Independent processed methods/block lengths and natural-U/oxide diagnostic inputs; no dedicated stored /2 oxygen-monitor answer. |
| C | `Tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/ogTripoli/isotopxPhoenixTIMS/boiseState/B998_F11_13223M02_iz1_Pb1-14973.xls`<br>`Tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/ogTripoli/isotopxPhoenixTIMS/kU_IGL/ionVantage/NBS981-500_20191208-5563.xls`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/shortReports/IsotopxPhoenixTIMS/KU_IGL/IonVantage/Oracle-NBS981-500 20191208-5563.txt` | XLS structural/cached-cycle checks and stored Java summary. B998 has no independent C# serialized accepted-statistic oracle in this clone. |
| D | `Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/expressions/NBS981_210325b-392_ExpressionEval.txt`<br>`Tripoli/TripoliCore/src/test/java/org/cirdles/tripoli/expressions/ExpressionTreeTest.java` | Expected expression arrays and the Java test that compares them; preserve operator precedence and referenced function names. |
| E | `Tripoli/TripoliCore/src/test/java/org/cirdles/tripoli/sessions/analysis/outputs/CyclesExportTest.java`<br>`Tripoli/TripoliCore/src/test/java/org/cirdles/tripoli/reports/AllReportsTest.java`<br>`Tripoli/TripoliCore/src/test/java/org/cirdles/tripoli/sessions/analysis/outputs/etRedux/MeasuredUserFunctionTest.java` | Code-based formatting/derived-value expectations and report regression harness; expected XML/TSV bytes still need snapshot generation/pinning. |
| F | `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/AnalysisStatsRecord.java`<br>`Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java`<br>`Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/Session.java` | Reference implementation only: block formulas, concatenation, defaults. Constructed edge cases need independent scalar expectations. |
| G | `Tripoli/TripoliCore/src/test/java/org/cirdles/tripoli/utilities/stateUtilities/TripoliSerializerTest.java` | Constructed serialize/deserialize tests, not a shipped real .tripoli session specimen. |
| H | `OGTripoli/docs/ID_TIMS_DataImportTemplate.csv` | Exact import layout template; empty template is not a numerical dataset. Fill known scalar cycles as a generated test fixture. |
| I | `OGTripoli/source/TripoliWorkProduct.cs`<br>`OGTripoli/source/GainsFile.cs`<br>`OGTripoli/source/TripoliHistoryFolderStandards.cs`<br>`OGTripoli/source/earth_time_org/USampleComponents.cs` | Code-only correction/history schema reference; no shipped calibrated tracer/IC, gains-XLS or .triphis expected-value fixture found. |
| J | `Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/dataFiles/TritonTIMS/ETH/21341_ R9_z2_U_STAT.exp`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/fullReports/TritonTIMS/ETH/Oracle-21341_ R9_z2_U_STAT-report.csv`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/dataFiles/NuTIMS/FC1 E PbF (Individual Answers_553).txt`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/fullReports/NuTIMS/Oracle-FC1 E PbF (Individual Answers_553)-report.csv`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/dataFiles/NeptuneMCICPMS/MK-113z1.exp`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/reporting/fullReports/NeptuneMCICPMS/Oracle-MK-113z1-report.csv` | Real processed vendor data with matching stored report expectations. These are not raw acquisition oracles. |
| K | `Tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/synthetic/twoIsotopeSyntheticData/README.txt`<br>`Tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/synthetic/twoIsotopeSyntheticData/SyntheticDataset_01.txt`<br>`Tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/synthetic/twoIsotopeSyntheticData/SyntheticDataset_02.txt`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/matLab/bspline/bspline_matrix_A.txt`<br>`Tripoli/TripoliCore/src/test/resources/org/cirdles/tripoli/core/matLab/bspline/bspline_answers.txt`<br>`Tripoli/TripoliCore/src/test/java/org/cirdles/tripoli/utilities/mathUtilities/SplineBasisModelTest.java` | Synthetic integration inputs and committed spline matrix answers. README only describes two-isotope demonstrations; generating truth/parameters were not established from it. Recover or create documented truth before posterior-recovery acceptance. |
| L | `Tripoli/productDocs/dataFormatDocs/isotopx_examples/NBS 981 try1-12.TIMSAD`<br>`Tripoli/productDocs/dataFormatDocs/isotopx_examples/NBS 981 try1-12.TIMSDP` | Real paired raw SQLite/processed text. No Tripoli TIMSAD decoder found; raw truth/units/collector mapping require independent acquisition evidence. |
| M | `Tripoli/TripoliCore/src/test/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelUpdaterTest.java` | Stored MATLAB-derived baseline/prior/covariance assertions in the Java test. Not end-to-end production Bayesian validation. |
| N | `Tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/peakShapes/6NHCl dpblank-210204A-169-PKC-208Pb-PM-S5B2C1.TXT`<br>`Tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/peakShapes/DVCC18-9 z9 Pb-570-PKC-205Pb-PM-S2B7C1.TXT` | Peak-centre input scans; expected overlay/width must be generated and pinned using PeakShapeProcess/SingleBlockPeakDriver, not guessed. |
| O | `Tripoli/TripoliCore/src/main/resources/org/cirdles/tripoli/species/nuclides/NuclidesChartData.csv` | Resource data for isotope masses/abundances; verify provenance/version before extending a general instrument catalog. |

For report oracles, reproduce the Java snapshot's **geometric statistics and Java oxide law** only in explicitly selected comparison mode. The normal filament legacy/isobar default must not be changed to agree with a known differing Java denominator ([oxide comparison](oxide-correction.md)). XML/TSV byte expectations should be generated from the named reference implementation and pinned; an input fixture alone is not a stored expected answer. Report fixtures do not validate missing raw acquisition semantics.

## Decisions recorded 2026-11-25 (Yiming Zhang)

- **D1 (F25):** opt-in fractionation preview in filament. The age app (IDTIMS_UPbRPy / UPb Studio) stays authoritative; the /1 fraction exports stay unchanged.
- **First phase:** P1 review diagnostics and presentation.
- **Plot controls in P1:** C3 block-mean overlay and C8 block zoom; C4 stats toggle and band sets; C6 Plot all and C7 INCLUDE/IGNORE/HIDE; C5 display-only inversion. C1 and C2 (mask copy and per-plot reset) are not scheduled. The C8 reduction switch goes with D7.
- **D2 / D3:** the recommended defaults go into P1 (plain notes first; oxygen monitor only for verified UO2 assignments). Yiming can change either before P1 ships.
- The other decisions (D4-D19) stay open until their phase comes up.

## Phase P1 Review diagnostics and presentation (M)

**Rows:** F13, F21, F22, F32, F33, F37, F40, F42, F44, F85, F93.

Add an explicitly labeled frozen-statistics display if needed (F93), accepted/rejected histogram bins, any-function x-y plots, saved recipes/intensity dot scaling, time views of existing cycle columns, editable work-product/session notes, graph/page printing and complete display controls. F13 is a small **new opt-in engine function** for (272/270)/2, only when the molecular assignment is confirmed; a monitor is diagnostic, not an automatic replacement for r18. F22 closes only existing-column time trends here; raw residuals remain P8. F37 closes styling here; physical unit conversion remains P6. Persistent freehand/per-plot annotations would exceed the verified Tripoli notations capability and should follow the plain notes view.

**Layer/modules:** mostly GUI in rawtims_gui (plots, cycle_table, inspector, session presentation); engine F13 in a new diagnostic function beside oxide.py/model.py, never inside the default correction path. Presentation persistence can extend session metadata without changing numerical replay.

**Planned oracles:** A/B for exact displayed mean/bands and masks, C for arithmetic differences; F for unchanged fields on save/reopen. Test histogram counts sum to selected finite samples, x-y coordinates preserve original cycle IDs, note roundtrip, print page order and time units. No stored Tripoli screenshot/annotation oracle was found; use explicit UI acceptance scenarios and reference semantics from inventory F21/F32/F33/F40.

**Invariance:** G0; opening, styling, sorting a view, note edits and printing must leave masks, computed statistics and export hashes unchanged. A diagnostic r18 result never changes acquisition r18 or the export contract.

**Open decisions:** D2: plain notes first or per-plot markup immediately? Recommend plain notes first. D3: should the derived oxygen monitor show only verified UO2 assignments or accept user-mapped masses? Recommend verified assignments first.

## Phase P2 Exchange, reports and saved-work compatibility (L, staged)

**Rows:** F15, F17, F18, F34, F35, F79, F80, F82, F83, F84, F87.

First implement ET_Redux measured-ratio XML/folder exchange and exact cycle/OG text dialects; then configurable report columns/categories/templates, Template 1, settings cascade/recent-file coverage, and inert saved-session/history migration. Native JSON remains the primary session format. Legacy write-back is a separate compatibility deliverable under F18: catalog all serialized fields, preserve untouched opaque data where safe, and verify roundtrip in the reference app before enabling it. Do not imply read-only .trip import already provides .triphis or Java .tripoli support. Complete text interchange before scheduling lower-value binary write-back; the latter depends on real specimens.

**Layer/modules:** new rawtims parser/export/report modules, exports.py, contract.py (adapter only), session.py, readers/trip.py, projects.py; GUI export/table/settings screens. Java migration is a constrained data parser/converter, never Java object execution on untrusted files.

**Planned oracles:** A/B/E for report fields and rejected-value TSV; G for serialization shape/roundtrip scaffolding, **not** a real saved session oracle; H for C# CSV import headers; F for synthetic session defaults. Generate and pin ET_Redux XML from A using ETReduxFraction/MeasuredUserFunction at the snapshot. Need lab .trip/.triphis/.tripoli files plus reference-app reopens for binary compatibility and a controlled ET_Redux folder fixture for F80; no such shipped fixture was found.

**Invariance:** G0; adapters do not rewrite measured /1 columns or force a statistic/oxide mode. Existing JSON files reopen to identical masks/statistics; saving view defaults cannot alter numerical defaults implicitly. Test source-independent text migration and unrecognized-field preservation/refusal.

**Open decisions:** D4: require actual .trip/.triphis/.tripoli write-back or read-only migration plus native JSON? Recommend read-only migration first, retain write-back as a gated parity deliverable. D5: which ET_Redux target/schema and folder overwrite rule? Recommend the pinned snapshot's schema, explicit replace confirmation, completed analyses only. D6: report templates per method or global? Recommend per method with a global fallback.

## Phase P3 Composable deterministic analysis (L)

**Rows:** F19, F20, F23, F45, F49, F92, F95.

Implement explicit acquisition concatenation with member identities/time ordering, constrained expression evaluation/editor/library, species-ratio building and opt-in block reduction/export. Keep original member cycle IDs and source hashes even when displayed together. Block weighting must distinguish statistically conventional inverse-SE² weighting from the Java snapshot's SD-based weighting/chi-square expression. Neither becomes the default cycle estimator. General named covariance models (F95) need measured-correlation conversion, symmetry/positive-semidefinite checks and uncertainty validity reporting; do not assume Java custom expressions propagate those matrices. Expressions need deterministic evaluation order, stable output keys, missing-data/domain checks and dependency-cycle rejection.

**Layer/modules:** rawtims/model.py, analysis.py, stats.py, mapping.py, fractions.py, session.py, exports.py and new expression/concatenation modules; GUI method/expression/block controls. Recompute derived data through undo/replay rather than patching arrays in a plot.

**Planned oracles:** D provides expression expected arrays/operators; A/B/E provide source cycles and report means; F supplies Java block statistics/concatenation behavior. Construct a controlled two-member case by splitting A at a known block boundary, then prove reassembly equals the untouched cycles and masks; it is a generated metamorphic fixture, not a pre-existing Tripoli concat oracle. Independently scalar-check both block conventions and zero-variance/one-block cases; C# examples lack stored per-block statistics ([parity report](tripoli-parity.md)).

**Invariance:** G0; old paths/method maps remain identical, concatenation and expressions are new explicit objects, block reduction is an opt-in versioned statistic. Exports must identify the chosen estimator; [contract mean-statistic meanings](contract-idtims-fractions-v1.md#measured-ratios) need agreement before a new block estimator is sent under /1.

**Open decisions:** D7: block diagnostic only, standard inverse-SE² export, or exact Java comparison export? Recommend standard estimator as an opt-in, Java as labeled diagnostic; agree contract representation first. D8: expression language basic arithmetic/log/exp/sqrt or arbitrary Python? Recommend constrained Java-equivalent operators. D9: concatenate same method/sample/fraction only, or allow explicit heterogeneous merges? Recommend matching method/function/unit identities only initially.

## Phase P4 Calibration history and live ingestion (L, history before watching)

**Rows:** F27, F30, F66, F67, F68, F77, F81.

Build a local cross-run gains/standards history with source/calibration versions, date plots, explicit history exclusions and immutable derived records. Then add completed cycle-folder import and controlled watch workflows with partial-write stabilization, folder changes, provisional identities and final-file reconciliation. Distinguish C# per-cycle folder/most-recent-file behavior from Java LiveDataStatus lifecycle. No new outlier rule or automatic correction occurs merely because another cycle arrives.

**Layer/modules:** new rawtims/history and readers/live adapters; session.py, model.py, reduction_params.py for provenance; GUI history and live status/background workers. A watcher belongs to application I/O, while ingestion/merge validation stays Qt-free.

**Planned oracles:** H template and I gains/standards reader code provide schema expectations only; A/B provide a completed numeric destination for live replay. Replay captured cycle text/status transitions, duplicate events, truncated writes and final merge into that destination; compare all final rows with a manually opened completed run. **Data gate:** obtain representative C# gains XLS, standards .trip/.triphis, IonVantage -B*-C*.txt folders and IsoLinx LiveDataStatus/provisional/final sequences. The clone has no complete checked live acquisition oracle.

**Invariance:** G0; manual completed-file open is unchanged; watch output and history are separate states. Calibration history cannot silently replace as-acquired gains. Final-file merge must preserve auditable mask decisions or request explicit reconciliation.

**Open decisions:** D10: first deployment read-only history/manual refresh, completed-file watching, or provisional live sculpting? Recommend history/manual refresh, then completed files; provisional sculpting after captured lifecycle tests. Which lab exports can supply those captures? Recommend a full non-sensitive acquisition plus gains/standard examples before enabling watches.

## Phase P5 Additional processed-file parsers (L, one dialect per increment)

**Rows:** F29, F69, F70, F71, F72, F73, F74, F75, F76.

Start with the existing-template CSV importer and processed Triton/Nu TIMS/Neptune formats that have stored report oracles. Follow with Sector54, MAT261/262, legacy Nu Plasma and Element2 only when specimens and expected outputs exist. Preserve vendor rejection/missing distinctions, units, timestamps, equations and original function names. A parser can be complete even when downstream fraction export is unavailable for an isotope system; state that limit.

**Layer/modules:** new rawtims/readers modules, common.py/functions.py, model.py and import routing; small GUI import summaries. Keep non-Pb/U reviews usable without inventing a Pb/U contract mapping. This phase does not include Phoenix Full raw interpretation (P6).

**Planned oracles:** H for exact CSV layout; J for Triton, Nu TIMS and Neptune source files plus matching full reports. Compare complete per-cycle arrays and masks before aggregate statistics; use geometric comparison only where the Java function classification requires it. **Data gate:** no Sector54, MAT261/262, legacy Nu Plasma or Element2 input/expected-value pair was found in these clones; obtain one for each claimed dialect/version. C# parser code alone is not a validated instrument oracle.

**Invariance:** G0; content routing of all existing XLS/TIMSDP/raw-folder inputs stays identical, and unsupported dialects retain explicit failures. Each new parser enters through a new dispatch signature, without broad extension-based guessing.

**Open decisions:** D12: which next instrument matters—Triton, Nu TIMS, Neptune, Sector54, MAT261/262, Nu Plasma or Element2? Recommend Triton first because both codebases and committed oracles cover it; confirm actual lab demand before the others.

## Phase P6 Method-driven raw processing and instrument configuration (L)

**Rows:** F24, F36, F37, F46, F47, F48, F78, F89, F90.

Extend method/detector/baseline/sequence representation, typed physical units and Phoenix method import/validation before adding a general Phoenix Full raw reader. Separately investigate the unresolved BSU two-sequence Pb, integration timing and unmatched terminal rows; current refusal/fallback limits remain until validated. Instrument catalog and isotope/abundance resources must carry a version. General calibration fits/Tau response/HT scaling are research work under F24, not switches to expose before their acquisition semantics are recovered.

**Layer/modules:** rawtims/readers/ionvantage_raw.py, new Phoenix Full/method readers, model.py, reduction_params.py, reprocess.py, analysis.py and session.py; GUI detector/method/reduction controls. Keep each supported-method decoder explicit until a general method model proves equivalence.

**Planned oracles:** K synthetic baseline/on-peak files and spline matrix answers test structural parsing/interpolation; A/B verify processed destination statistics; L is real paired TIMSDP/TIMSAD data but provides **no decoded integration truth**. There is no shipped machine-method XML fixture or verified real Phoenix Full output identified here. Obtain Phoenix method XML + Full export + vendor-produced cycles. BSU IsoprobeT raw investigations use the separately available examples documented in [raw-reduction.md](raw-reduction.md#two-sequence-pb-investigation-desktop-g1), not Java synthetic data as an oracle for DAT semantics.

**Invariance:** G0; unchanged workbook route stays bit-identical; existing supported raw default outputs and row keys stay identical. New methods/units/calibrations are opt-in, versioned routes. Do not relax the documented 3 ppm Pb investigation criterion to accept the two-sequence exploratory residuals.

**Open decisions:** D13: prioritize unresolved IsoprobeT methods, Phoenix Full text, or TIMSAD decoding? Recommend IsoprobeT specimens first, then Phoenix Full; TIMSAD only after channel/unit/acquisition semantics are independently documented. D14: general method editor initially read-only or editable? Recommend read-only validated import plus narrow supported overrides.

## Phase P7 Tracer, fractionation and interference capability (L; D1 gate)

**Rows:** F25, F26, F61, F62, F63, F64, F65.

Implement the selected ownership route for tracer XML/library/versioning, U components and 233/236 correction coverage, linear Pb/U fractionation, calibration, correction reports/undo and batch revisions. Add coupled BaPO2/Tl only after independent reference calculations and real validated input data. Even with preview ownership, define a useful filament user workflow for every row and keep any suite-delegated calculation explicit; do not mark absent engine behavior complete just because another app has it.

**Layer/modules:** new rawtims/tracers, calibration and correction-preview functions; oxide.py only via new explicit functions, reduction_params.py/session.py for opt-in records; GUI tracer/alpha/IC preview/report views. If D1 chooses full ownership, coordinate the age engine and contract reader as separate reviewed work outside this repo.

**Planned oracles:** I contains the exact C# correction implementations and U component definitions; A/B offer processed Pb/U inputs but are **not tracer-calibration expected answers**. No shipped applied ET2535, 233/236 or coupled BaPO2/Tl calibration fixture was found. Acquire tracer XML with uncertainties/covariances, applied-model settings and independently checked per-cycle alpha/corrected ratios/calibration results; compare the age app and a scalar reference, including zero-interference and no-fractionation limits. [Existing BSU parity](tripoli-parity.md) explicitly reports no applied tracer/IC correction, so it cannot validate this phase.

**Invariance:** G0 and D1 contract choice; preview cannot change old Analysis values or /1 hashes. Full corrected export needs a separate contract/reader migration. Batched re-correction writes new derived revisions and never overwrites originals.

**Open decisions:** D1 as above. D11: for interference, age-app correction, filament preview, or applied measured-ratio correction? Recommend preview first and a coordinated provenance/contract decision before applying it. Which calibrated ET2535/233–236 specimens can Yiming supply? Recommend one complete independent calibration chain for each enabled family.

## Phase P8 Bayesian model fitting, ensembles and peak shapes (L, several releases)

**Rows:** F22, F28, F50, F51, F52, F53, F54, F55, F56, F57, F58, F59.

After P6 validates the raw/method data model, implement a separately labeled experimental MCMC path: deterministic forward/noise/baseline/gain initialization, linear/cubic intensity basis, adaptive proposals, chain persistence, burn-in/convergence, joint Faraday/photo-multiplier gain and posterior covariance. Then add per-block scheduling, observed/model/residual plots, ensemble histograms/derived ratios and model/vector reports. Treat MCMC2 simulations and peak-shape tools as separate model families with independent validation. Do not promote a demo or a successful chain run to a validated lab reduction.

**Layer/modules:** new rawtims Bayesian/forward-model/peak packages with Qt-free results, seeded RNG/configuration and versioned chain storage; analysis/session interfaces and parser adapters; GUI tasks, convergence/burn-in/residual/peak views. Current deterministic raw reducer remains its own route.

**Planned oracles:** K for synthetic input structure and stored spline matrix answers; recover documented generating parameters or create new independently specified truth before testing posterior recovery. M for updater baseline/prior/covariance assertions; N for peak-centre scans. Compare deterministic forward vectors, initial baselines/gain, matrix dimensions and likelihood first; preserve seeds and pinned RNG implementations for same-engine repeatability. Java/Python chains generally differ even at equal seeds, so compare posterior recovery/coverage, convergence and moment tolerances over replicated chains rather than demanding cross-language chain byte identity. MCMC2 driver references a syntheticData/SyntheticOutToTripoli resource path absent from this clone; obtain or regenerate documented truth before claiming that demo is reproducible. Real BSU Bayesian validation still requires matching integrations/calibrations.

**Invariance:** G0 for all pre-existing routes; old exports must remain byte-identical when MCMC is unused. New chain hashes need same-seed/runtime repeatability; cross-language validation uses scientific acceptance criteria. A posterior-derived export needs explicit estimator/uncertainty/contract agreement before entering a production hand-off.

**Open decisions:** D15: research/preview only or production posterior export first? Recommend research/preview, synthetic truth recovery, then real standards. D16: MCMC1-equivalent first, MCMC2 simulation first, or a new model? Recommend deterministic MCMC1 forward-model equivalence before sampling; defer MCMC2 until its missing resources are resolved. D17: run locally with disk chains or optional remote jobs? Recommend local cancellable jobs and bounded disk storage first.

## Phase P9 Remaining resources and lab-scale integration (L, independent increments)

**Rows:** F31, F39, F41, F60, F94.

Deliver the periodic table/nuclide resource and clearly labeled educational demos after the review workflow. Inspect the unwired C# Excel workfile helper (F94) with a real specimen before offering inert migration; current review XLSX is not that format. Resolve dormant block-sort semantics as a separate feature decision: reproduce the visible no-op, implement a safe display sort, or add an explicit trim rule; do not accidentally activate historical array mutation. In parallel with a separately agreed service design, extend current UPbDB lookup/links into immutable evidence/reduction revisions, role-based approvals, outbox/mirror sync and revision comparisons. These lab/database features are mainly **beyond Tripoli**, but remain under F31's broader existing filament gap.

**Layer/modules:** GUI resources and versioned static data; any block-trim algorithm in rules.py as opt-in; rawtims/upbdb.py plus new revision/blob/mirror adapters, session.py/fractions.py provenance and GUI review/sync state. Server/schema/authorization changes belong to the lab service and require its own implementation scope.

**Planned oracles:** O for nuclide resource shape, K/N for demos where supported; no numerical “expected remote approval” exists in a Tripoli clone. Use existing [database design](database-recalculation.md) and UPbDB mocked transport/identity export fixtures for contract behavior; obtain a controlled service environment for conflict/retry/approval tests. F41's source shows a commented-out toggle body, so a no-op is the actual snapshot reference, not validated scientific trimming.

**Invariance:** G0; resources and sync cannot change local measured values. Upload/download must preserve source/result hashes, approvals bind an immutable revision, and offline edits remain drafts until server verification. Run semantic contract roundtrips for links/chemistry without changing measured columns.

**Open decisions:** D18: implement dormant sort as display-only, literal no-op, or explicit trim rule? Recommend display-only; trimming later as a previewed rule. D19: next lab-service step immutable draft storage, approval workflow, or offline mirrors? Recommend immutable draft storage first. D20: prioritize periodic-table/demos before or after the next lab integration? Recommend after high-value review/export work, independent of numerical engine milestones.

## Plot-control decisions from the controls round (8b045f1)

The 8b045f1 controls round made the supported Tripoli plot controls into explicit buttons (SYNCH, Chauvenet, Restore, Reset data, Log, Fit all, Sculpt). The behaviors below were left out because each one needs a decision first. They belong to P1 unless noted otherwise.

| Id | Tripoli behaviour | Display only? | Question for Yiming |
|---|---|---|---|
| C1 | "Synch to me": copy one plot's mask to the others | No. Means, uncertainties and correlations change when masks differ | Copy only between free functions (GUI only), or also between mapped ratios (breaks the shared-mask contract; engine and policy work)? |
| C2 | Per-plot Reset Data / restore legacy history | No. Restored cycles change statistics | Reset free functions only, or change the shared-mask policy? |
| C3 | Block-mean overlay toggle | Yes, as an overlay | Diagnostic overlay only (recommended), or a reduction-mode switch (P3 / D7)? |
| C4 | Stats toggle / C# Stats Detail band sets | Yes | Add as remembered display preferences? |
| C5 | Display inversion / Invert all | Plotted values change; exports do not | Display-only inversion separate from the Mapping inversion, or leave out? |
| C6 | Plot all / Select All / Show All-Selected rows | Yes, for plot visibility only | Plot visibility shortcuts only (recommended); C# export membership stays out |
| C7 | C# INCLUDE / IGNORE / HIDE display modes | Yes, if the mask stays unchanged | Should HIDE close up the cycle positions? |
| C8 | Ctrl-right-click zoom to one block / block-mean reduction switch | Zoom: yes. Reduction switch: no | Add block zoom now; the reduction switch goes with D7 |

## Beyond Tripoli

“Has” below is scoped to inspected functionality in the inventory and linked filament evidence. “Could add” is a proposal; absence of an equivalent in both source walks is not a claim about every future upstream release.

| Capability | Has/could add and value | Size |
|---|---|---|
| Shared export-cycle consistency and explicit reconciliation | Has: [shared selection](shared-cycle-selection.md) prevents ratios/correlations based on conflicting imported masks; a stronger hand-off guard than legacy per-ratio history or optional SYNCH. | S to extend explanations |
| Portable, inert sessions with source hashes and replay | Has: [session.py](../src/rawtims/session.py) and [raw reduction](raw-reduction.md) preserve audit/reduction provenance without executable object graphs. Add a self-contained content-addressed evidence bundle for reproducible sharing. | M for bundles |
| Deterministic IsoprobeT raw decoder and parameter diff | Has for the [validated subset](raw-reduction.md), beyond the processed-data C# path and different from Java Phoenix Full inference; supports inspectable dead-time/baseline/gain changes. Add independent reference tables for each newly decoded method. | L for each new raw family |
| Cancellable, replayable parameter experiments with age-app comparison | Has staged/undoable reduction and local hand-off ([ui-panels.md](ui-panels.md), [recalculation demo](recalculation-demo.md)). Could add side-by-side parameter sweeps and ratio/date sensitivity charts with a fixed /1 export baseline. | M |
| One operator workflow for grains, chemistry, ratios and dates | Has confirmed lookup/link/chemistry data ([upbdb.py](../src/rawtims/upbdb.py)); could add immutable evidence revisions/approval and linked LA-ICP-MS source context ([design](database-recalculation.md)). Neither inspected Tripoli has this proposed lab service. | L |
| Headless contract verification and reproducible public teaching data | Has [verify.py](../src/rawtims_gui/verify.py), [SITE.md](SITE.md) and numerical allowlisted walkthroughs. Could extend the deterministic processing manifest into a lab-run validation dashboard. | M |
| Correction-state duplicate-application checks | Has cached oxide pass-through/provenance ([oxide note](oxide-correction.md), [raw limits](raw-reduction.md)); could generalize typed “measured / detector corrected / oxide corrected / preview fractionated” states to reject double correction across apps. | M |
| Method coverage and uncertainty-quality dashboard | Could add per-run supported/approximate/unsupported route, calibration age, model identifiability and uncertainty budget with actionable missing inputs, grounded in [raw limits](raw-reduction.md). | M |
| Reproducible encrypted/redacted evidence bundles | Could add lab-controlled packaging with a public numerical summary and separate private identity mapping; useful for external review without copying personal/lab acquisition metadata into this public repo. | M |

## Actual documentation checks for this task

The Makefile has no documentation/link target. The repository does have an offline docs-specific pytest file, tests/test_docs_site.py, and a strict MkDocs build documented in [SITE.md](SITE.md#build-and-preview). Only docs/site enters that build, so it cannot validate these internal roadmap/inventory notes. Run the offline, non-slow docs tests and a direct internal-link/source-reference/row/phase coverage audit for the changed notes. A strict site build would write build/site outside this task's permitted write list; do not run it in this task. No dependencies, network requests, web server, full suite or numerical generator are needed.

Final results are recorded in the scratch inventory-report.md. Future implementation gates remain G0 plus the per-phase oracles.

GUI-only preferences D2 (plain notes first), D6 (per-method reports) and D20 (resource priority) can be settled alongside P1/P2 without authorizing engine changes. The recommendations above are defaults for discussion, not recorded answers from Yiming.

## Decisions needed before engine work

1. **D1 — F25 ownership:** move, stay in age app, or opt-in preview? **Recommend preview, age app authoritative, unchanged /1 exports.**
2. **D3 — Oxygen monitor inputs:** verified UO2 assignments only or user-mapped masses? **Recommend verified assignments.**
3. **D4 — Compatibility:** read-only migration first or binary legacy write-back immediately? **Recommend migration first; supply .trip/.triphis/.tripoli specimens for the remaining gated work.**
4. **D5 — ET_Redux:** which target/schema and replace policy? **Recommend pinned Tripoli schema, completed runs, explicit replacement.**
5. **D7 — Block estimator/contract:** diagnostics, standard inverse-SE² export, or Java-compatible export? **Recommend standard opt-in, labeled Java diagnostic, agreed statistic metadata before export.**
6. **D8 — Expressions:** constrained Java-style operators or arbitrary Python? **Recommend constrained arithmetic/log/exp/sqrt with dependency checks.**
7. **D9 — Concatenation:** matching methods/units/functions only or heterogeneous merge? **Recommend matching identities.**
8. **D10 — Live workflow/data:** history/manual refresh, completed-file watch, or provisional sculpting first; which captures exist? **Recommend that order and representative lifecycle/gains/standards inputs.**
9. **D11 — Interference contract/data:** age app, preview, or applied upstream correction; which independent ET2535/233–236/IC calibration chains exist? **Recommend preview until calibrated oracles and provenance are agreed.**
10. **D12 — Next processed parser:** Triton, Nu TIMS, Neptune, Sector54, MAT261/262, Nu Plasma or Element2? **Recommend Triton, conditioned on actual lab demand.**
11. **D13/D14 — Raw route/method controls:** IsoprobeT gaps, Phoenix Full or TIMSAD; read-only method import or unrestricted editing? **Recommend IsoprobeT first and validated read-only method import; supply method/Full/raw specimens.**
12. **D15/D16/D17 — Bayesian scope:** research preview or production export; MCMC1, MCMC2 or a new model; local or remote execution? **Recommend local MCMC1 forward-model validation and research preview before posterior export.**
13. **D18 — Dormant sort:** display-only, no-op or explicit trim? **Recommend display-only; any scientific trim is a new explicit rule.**
14. **D19 — Lab integration:** immutable drafts, approvals or mirrors first? **Recommend immutable draft storage; agree service ownership and roles.**
