# Tripoli feature gaps

Snapshot: **2026-11-25**, P9 resource/demo update **2026-11-26**. **Done** means the stated supported-input workflow exists;
**partial** means the limits in the last column still apply; **not done** means
unimplemented. All incomplete rows are now in scope in the
[phased roadmap](tripoli-parity-roadmap.md), subject to its data and ownership decisions.
The [complete inventory](tripoli-inventory.md) provides 95 numbered rows, source-area
coverage, work tags (G GUI, E engine, P parser, D data), and scoped advantages over
Tripoli. Numerical parity is narrower than a feature check: see
[the parity report](tripoli-parity.md) and [raw reduction limits](raw-reduction.md).

The comparison uses legacy **C# 4.10.0.3** and the **Java Tripoli** source snapshot
`00dc941` researched in this repository. “Java” below identifies that implementation,
not a claim that every subsequent upstream release is identical. Upstream projects:
[CIRDLES/OGTripoli](https://github.com/CIRDLES/OGTripoli) and
[CIRDLES/Tripoli](https://github.com/CIRDLES/Tripoli).

## Core review and exchange

| SPEC | Feature | Legacy C# 4.10.0.3 | Java Tripoli | filament | Remaining limit or difference |
|---|---|---|---|---|---|
| F1 | IonVantage `.xls` | Import processed functions; `OGTripoli/source/vendors_data/MassLynxDataFile.cs:98` | Import processed functions; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PhoenixMassSpec.java:45` | done | E/P: cached functions; source correction flags are provenance, never instructions to correct twice. [filament evidence](../src/rawtims/readers/ionvantage.py#L151). |
| F2 | IsoLinx `.TIMSDP` | Supported processed functions; `OGTripoli/source/vendors_data/IsotopXPhoeniX_ImportedTIMSDPDataFile.cs:85` | Supported; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PhoenixMassSpec.java:334` | done | E/P: supported in BOTH versions; earlier gap understated C#. Not raw integrations. [filament evidence](../src/rawtims/readers/timsdp.py#L118). |
| F3 | Many files, folders, content routing | File-oriented imports; `OGTripoli/source/forms/fmrMainTripoli.cs:820` | Context-specific parsers; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:312` | done | E/P: done for supported formats. EXCEEDS: content routing and duplicate-hash protection (workspace.py); not every vendor. [filament evidence](../src/rawtims/readers/__init__.py#L109). |
| F4 | Function classification | Ratios and special functions; `OGTripoli/source/RawRatio.cs:1063` | Ratios, intensities, user functions; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:91` | done | E: duplicate column names retain stable unique keys; imported user functions are not an expression authoring tool. [filament evidence](../src/rawtims/readers/functions.py#L74). |
| F5 | Pb/U pairing and fraction metadata | Separate work products and names; `OGTripoli/source/TripoliWorkProduct.cs:3052` | Analysis/session metadata; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:418` | done | E/G: explicit paired fractions and ambiguous-name review; this is not automatic database identity. [filament evidence](../src/rawtims/fractions.py#L168). |
| F6 | Cycle wall, bands, log and inversion | Ratio graphs, display options; `OGTripoli/source/forms/frmRatioGraph.cs:369` | Plot wall/sculpting; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/PlotWallPane.java:282` | done | G: existing wall/Focus/block strips; display inversion is separate from Mapping inversion. Scope is review of available functions. [filament evidence](ui-panels.md). |
| F7 | Cycle table and selection | Ratio data views; `OGTripoli/source/TripoliWorkProduct.cs:2901` | Cycle views/export; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:737` | done | G: shared analysis state links table and plots; C# evidence is tabular export, not an identical editable grid. [filament evidence](../src/rawtims_gui/cycle_table.py#L30). |
| F8 | Point/box/block rejection, SYNCH | Per-ratio selections and synchronisation; `OGTripoli/source/RawRatio.cs:942` | Sculpting and SYNCH; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/PlotWallPane.java:263` | done | E/G: EXCEEDS: mapped export ratios enforce shared selection; imported per-ratio masks require explicit reconciliation. [filament evidence](shared-cycle-selection.md). |
| F9 | Outlier rules | Single-pass 2σ; repeated worst-point Chauvenet; `OGTripoli/source/forms/frmRatioGraph.cs:2412` | One-pass Chauvenet, default minimum 20; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/utilities/mathUtilities/MathUtilities.java:63` | done | E/G: C# one-pass 2σ/repeated worst-point Chauvenet and Java one-pass variant; EXCEEDS: explicit preview/apply and iterative k-sigma. [filament evidence](../src/rawtims/rules.py#L124). |
| F10 | Undo/redo/reset | Per-ratio history; `OGTripoli/source/forms/frmRatioGraph.cs:1644` | Reset; no general rejection undo; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/PlotWallPane.java:231` | done | E/G: EXCEEDS: public replayable undo/redo includes mapping, settings and reduction; Java expression undo is separately F45. [filament evidence](../src/rawtims/analysis.py#L578). |
| F11 | Cycle statistics | Arithmetic ratio mean, SD, SE; `OGTripoli/source/RawRatio.cs:804` | Geometric/log-ratio statistics; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/AnalysisStatsRecord.java:68` | done | E: arithmetic default, selectable log-ratio/geometric comparison, arithmetic intensities. This does not assert all-method numerical parity. [filament evidence](../src/rawtims/stats.py#L111). |
| F12 | U oxide correction | Legacy/ET_Redux denominator; `OGTripoli/source/TripoliWorkProduct.cs:2495` | Different 238/235 denominator in snapshot; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/MassSpecOutputBlockRecordLite.java:29` | done | E: legacy default and Java comparison; cached corrected functions pass through. Wider 233/236 family is F62. [filament evidence](oxide-correction.md). |
| F13 | Derived in-run 18O/16O monitor | No dedicated panel established | Inputs may contain 272/270; no dedicated /2 panel established; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PhoenixMassSpec.java:334` | done | E/G: P1 opt-in (272/270)/2 diagnostic after explicit UO2 molecular/units verification. Never joins Analysis, r18 correction or export mapping. Extension; no dedicated upstream monitor oracle. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F14 | Ratio mapping and method defaults | Active ratio selection; `OGTripoli/source/RawRatio.cs:1063` | ET_Redux names, inversion and defaults; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/expressions/userFunctions/UserFunction.java:250` | done | E/G: explicit source-column mapping and remembered method maps; arbitrary ratio building remains F23/F49. [filament evidence](../src/rawtims/mapping.py#L481). |
| F15 | Fraction hand-off | ET_Redux XML/clipboard; `OGTripoli/source/forms/fmrMainTripoli.cs:5288` | ET_Redux XML and live folders; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:785` | partial | E/G: P2 separate completed-analysis ET_Redux measured XML with chosen filename and explicit overwrite confirmation; native /1 and Send unchanged. Folder/service protocol remains D5; runtime-generated XML from A still needs a Java runtime. [Implementation](../src/rawtims/tripoli_exchange.py). |
| F16 | Legacy clipboard | C# E7 mean and % SE blocks; `OGTripoli/source/forms/frmRatioGraph.cs:1726` | Full-precision clipboard blocks; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:801` | done | E/G: C# E7/CRLF header plus full precision option; EXCEEDS: both styles explicit. [filament evidence](../src/rawtims/exports.py#L84). |
| F17 | Cycle export | Tabular data exports; `OGTripoli/source/TripoliWorkProduct.cs:2901` | TSV, rejected values wrapped in `&`; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:737` | partial | E/G: native cycle CSV/XLSX unchanged; P2 separate Java padded TSV (two committed full-byte oracles) and Windows/en-US OG signed-mask ratio text. OG three-row correction labels follow the source; runtime snapshot coverage remains bounded (F83). [Implementation](../src/rawtims/tripoli_exchange.py). |
| F18 | Saved work/session | Binary `.trip`, `.triphis`; `OGTripoli/source/TripoliWorkProduct.cs:821` | Java-serialized `.tripoli`; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/utilities/stateUtilities/TripoliSerializer.java:34` | partial | E/P/G: native JSON/replay and existing .trip migration retained. P2 inert .trip/.triphis inspection preserves source bytes and unknown graph members; Java Session scaffold refuses non-null analysis maps/custom classes. No binary write-back (D4); saved specimens/reference reopens needed. [Implementation](../src/rawtims/readers/legacy_saved.py). |
| F19 | Concatenate acquisitions | Cycle-folder append with timestamp checks; `OGTripoli/source/forms/fmrMainTripoli.cs:2053` | Session concatenation; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:177` | done | E/G: P3 explicit matching-method/element/function/unit/settings compositions; original cycle/block/time IDs, source hashes, member masks and boundaries retained. Recorded time orders members; overlaps, duplicate cycles, mixed clocks and missing dates across acquisitions are refused. Separate diagnostic objects only; heterogeneous merging remains D9. [Implementation](../src/rawtims/composition.py). |
| F20 | Block statistics/reduction | Block selection/statistics; `OGTripoli/source/RawRatio.cs:1172` | Weighted block mean and MSWD code; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/AnalysisStatsRecord.java:107` | partial | E/G: P3 labeled standard inverse-SE² mean/MSWD and Java 00dc941 inverse-SD² mean/chi-square diagnostics, per-block scale/counts and omission notices. Cycle estimator unchanged. Block reduction/export and its contract metadata remain D7. [Implementation](../src/rawtims/block_diagnostics.py). |
| F21 | Any-function x–y plot | No equivalent established here | Supported; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1499` | done | G: P1 any-two-existing-functions x-y view, paired finite original cycle IDs and joint acceptance display; no masks change. Named recipes and intensity radii in F44. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F22 | Intensities and gain trends vs time | Ratio/special-function graphs; `OGTripoli/source/forms/frmRatioGraph.cs:369` | OnPeak intensity/residual tabs; `Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/OGTripoliView.fxml:26` | partial | G: P1 existing cycle columns plot against recorded elapsed seconds, with unavailable-time notice. E: P8 adds headless synthetic model residuals (F55); desktop raw residual workspace remains absent. No residuals invented for cached ratios. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F23 | Custom expressions/ratio builder | Special functions and correction functions; `OGTripoli/source/vendors_data/IsotopXPhoeniX_ImportedTIMSDPDataFile.cs:85` | Expression editor and species ratio builder; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:2406` | done | E/G: P3 constrained safe parser/editor over existing function keys, arithmetic/right-associative powers, log10/ln/exp/sqrt, dependency ordering and per-cycle domain/missing flags. New explicit diagnostic columns only, saved/replayed separately; no /1 mapping. Wider language remains D8. [Implementation](../src/rawtims/expressions.py). |

## Reduction, instrument and database work

| SPEC | Feature | Legacy C# 4.10.0.3 | Java Tripoli | filament | Remaining limit or difference |
|---|---|---|---|---|---|
| F24 | Raw acquisition reduction | Receives instrument-processed ratios; `OGTripoli/source/vendors_data/MassLynxDataFile.cs:129` | Phoenix Full baseline/gain/intensity models; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelDriver.java:72` | partial | E/P/D: P6 prerequisites plus P8 isolated synthetic MCMC1 forward/noise/baseline/gain initialization. Existing deterministic IsoprobeT routes unchanged; no Phoenix Full/TIMSAD reader or new raw calibration (D13). [P8 evidence](p8-mcmc1-forward-model.md). |
| F25 | Pb/U tracer fractionation | Linear law, Pb 202/205 and U 233/235 double spike; `OGTripoli/source/TripoliWorkProduct.cs:1074` | Not applied by the researched export path; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/outputs/etRedux/MeasuredUserFunction.java:63` | partial | E/G: D1 opt-in C# linear Pb and 233/235 U mean-level calibration preview with first-order uncertainty propagation; age app authoritative, /1 unchanged. Per-cycle/calibrated-chain validation remains open. [P7 evidence](p7-fractionation-preview.md). |
| F26 | BaPO2/Tl correction | Combined interference/fractionation solution; `OGTripoli/source/TripoliWorkProduct.cs:2038` | No implementation in researched path | not done | E/D: deferred under D11; no BaPO2, Tl or coupled interference correction or /2 contract. Independent validated specimens/provenance required. [P7 evidence](p7-fractionation-preview.md). |
| F27 | Live acquisition watching | Live newest-file and cycle-folder workflows; `OGTripoli/source/forms/fmrMainTripoli.cs:6371` | IsoLinx LiveData ingestion; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/TripoliGUIController.java:884` | partial | E/P/G/D: P4 manual completed-folder Refresh and explicit completion attestation only. No watcher/newest-file workflow, provisional sculpting or automatic new-cycle rules; D10 and lifecycle captures remain open. [P4 evidence](p4-calibration-history.md). |
| F28 | MCMC, Bayesian ensembles, peak shapes | No equivalent | MCMC1/MCMC2 and demonstrations; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/MCMCProcess.java:254` | partial | E/D: P8 deterministic MCMC1 research prerequisite only; no sampler, posterior fitting, ensembles or production values. D15/D16/D17 remain open; MCMC2 and peak tools remain separate. [P8 evidence](p8-mcmc1-forward-model.md). |
| F29 | Other instrument formats | Several instrument imports; `OGTripoli/source/forms/fmrMainTripoli.cs:838` | Triton, Neptune, Nu TIMS; Sector54 not registered; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/constants/MassSpectrometerContextEnum.java:46` | partial | E/P/D: P5 template CSV and processed Triton/Nu TIMS/Neptune, validated against all 34 public input/cycle/full-report sets. Sector54, MAT261/262, legacy Nu Plasma and Element2 remain specimen-gated (D12). [P5 scope and limits](p5-processed-parsers.md). |
| F30 | Gains/standards history | `.triphis`, history graphs; `OGTripoli/source/TripoliHistoryFolderGains.cs:151` | Different session/live model | partial | E/P/G/D: P4 local immutable gains/standards revisions, source/calibration/settings/mask versions, date plots and reasoned undoable history exclusions. Never feeds correction. Broader legacy/live coverage remains gated. [P4 evidence](p4-calibration-history.md). |
| F31 | Lab/database context and mirrors | ET_Redux workflow integration; `OGTripoli/source/forms/fmrMainTripoli.cs:6427` | ET_Redux live folder protocol; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/utilities/stateUtilities/liveWorkFlow/SampleMetaDataUnmarshaller.java:36` | partial | E/G: UPbDB lookup/cache/confirmed links and chemistry exist (src/rawtims/upbdb.py), CSV provenance and local Send exist. Remote storage/approvals/mirrors are proposals; Tripoli evidence covers local ET_Redux context, not a remote database. [P9](tripoli-parity-roadmap.md#phase-p9-remaining-resources-and-lab-scale-integration-l-independent-increments). [filament evidence](database-recalculation.md). |

## Other visible Tripoli features

Previously unnumbered rows now have stable IDs. Full source/status evidence and
all detailed subfeatures are in [the inventory](tripoli-inventory.md).

| Feature | Legacy C# | Java | filament | Limit |
|---|---|---|---|---|
| F32 Histogram overlay | `OGTripoli/source/forms/frmRatioGraph.cs:905` | `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/plots/histograms/HistogramBuilder.java:39` | done | G: P1 separate cycle histogram with selectable bins, shared accepted/rejected edges, Tripoli epsilon/right-endpoint binning. Counts retain all finite cycles (including zero); no cycle-wall overlay or ensemble claim. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F33 Annotations/notations | `OGTripoli/source/forms/fmrMainTripoli.cs:4047` | `Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/SessionManager.fxml:74` | done | G: D2 plain session/work-product/fraction/sample notes, edited as plain text and roundtripped in optional native session presentation metadata. No freehand/per-plot markup. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F34 Custom report builder/templates | `OGTripoli/source/TripoliWorkProduct.cs:2901` | `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/reports/ReportBuilderController.java:781` | done | E/G: P2 processed-analysis report columns, categories, order/visibility, preview/custom CSV and save/load/delete named method templates with global fallback. Full-model fields/Template 1 are separately F87. Preferences never change numerical defaults. [Implementation](../src/rawtims_gui/report_builder.py). |
| F35 Per-user/session/analysis defaults | `OGTripoli/source/TripoliRegistry.cs:30` | `Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/settings/SettingsWindow.fxml:437` | partial | E/G: P2 report preference cascade analysis > session > method > global > built in, effective-source display and restore inherited. Session/analysis preferences roundtrip in presentation metadata. Broader reduction/default cascades remain outside P2; no numerical-default change. [Implementation](../src/rawtims_gui/report_builder.py). |
| F36 Instrument method/detector editor | `OGTripoli/source/RunParameters.cs:23` | `Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/AnalysesManager.fxml:233` | partial | E/G/D: P6 immutable versioned method/detector/baseline/sequence model and read-only inspector; no method editor (D14). Existing supported parameter controls unchanged. [P6 evidence](p6-method-configuration.md). |
| F37 Plot styling and units | `OGTripoli/source/forms/frmRatioGraph.cs:2054` | `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/SpeciesIntensityAnalysisPlot.java:234` | partial | G/E: existing styling retained; P6 separate opt-in typed counts/s, V, A display on verified existing raw Faraday columns. Cached/ambiguous/multiplier conversions remain unavailable with reasons (F90). [P6 evidence](p6-method-configuration.md). |
| F38 Help and demonstrations | `OGTripoli/source/forms/fmrMainTripoli.cs:5831` | `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/TripoliGUIController.java:880` | done | G/docs: bundled guide, KD33 walkthrough (ui-panels.md) and numerical site (SITE.md); walkthrough needs read-only examples. Tripoli-specific video links are not parity requirements. [filament evidence](user-guide.md). |
| F39 Periodic table and nuclide resource | No equivalent established | `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/TripoliGUIController.java:748` | done | G/resource: P9 read-only 118-element table reuses all 3,365 versioned P6 nuclides; exact upstream grid, source hash and Apache attribution. Missing values stay unavailable; independent abundance provenance unestablished. [P9 evidence](p9-resources-demos.md). |

## P5 processed imports (2026-11-26)

| Row | Status | Supported scope and remaining limit |
|---|---|---|
| F69 | done | E/P: exact OG template CSV signature; sample/fraction/date, row-based blocks, single-block zero setting and zero-clamp/final-block padding. Empty committed template plus synthetic scalar tests; fractions CSV is distinct. [P5](p5-processed-parsers.md). |
| F71 | done | E/P/G: P5 processed Triton ETH/UCDavis report dialects (15 input/cycle/full-report pairs). X rejection and D missing remain separate; equations/captions, units when explicit, footer and original clocks retained. Java comparison is opt-in. Other isotope systems have independent review/cycle export. [P5 limits](p5-processed-parsers.md). |
| F74 | done | E/P/G: P5 Nu TIMS 1.1 individual answers, both committed Pb/U pairs; captions, units and declared blocks retained. Native time unavailable; Java comparison alone uses 1.0. Legacy Nu Plasma remains separate. [P5 limits](p5-processed-parsers.md). |
| F75 | done | E/P/G: P5 Neptune processed Run-Block reports and decimal tail scans (17 input/cycle/full-report pairs). Blank versus numeric/negative cells retained; source names and tail functions preserved; Java zero/log-mask view is opt-in. No generic raw acquisition reduction. [P5 limits](p5-processed-parsers.md). |
| F70 | not done | E/P/D: specimen-gated (D12): no public Sector54 input/expected-output pair in supplied clones. C# code alone does not validate a new parser. |
| F72 | not done | E/P/D: specimen-gated (D12): no public MAT261/262 input/expected-output pair in supplied clones. No parser added. |
| F73 | not done | E/P/D: specimen-gated (D12): no public legacy Nu Plasma input/expected-output pair in supplied clones. Distinct from Nu TIMS (F74); no parser added. |
| F76 | not done | E/P/G/D: specimen-gated (D12): no public Element2 input/expected-output pair in supplied clones. No folder parser or LA review invented. |

The four done rows cover the represented processed dialects, not raw acquisition
reduction or unrestricted vendor versions. Complete cycle arrays and masks are
checked before every full report's mean, SE and SD. Native missing-data and
arithmetic-default rules remain in force; Java comparison semantics are explicit.
Non-Pb/U independent reviews export cycle CSV and are not native fraction-session
entries. See [P5 evidence and limits](p5-processed-parsers.md).

## Long tail and scope changes

P2 closes F34 for processed-analysis summary reports. F15/F17/F18/F35 remain
partial with their P2 subsets described above. F79 now has inert OG processed-text
import/inspection; F80 has completed-analysis chosen-file XML, with folder/service
policy still D5. F82 has a bounded scalar Java Session parser scaffold, not full
saved-session migration. F83 has separate Java TSV and Windows/en-US plain-name OG
text writers, including source-pinned three-row correction labels. F84 adds recent data and
directory coverage; method/tracer file recents await those workflows. F87 has a
source-pinned typed Template 1 renderer, but its GUI action remains unavailable
until Phoenix Full species/weighted-ratio/gain results exist. Binary write-back
remains D4. Source-derived synthetic XML/OG/Template 1 byte expectations and two
committed Java cycle-byte oracles are covered by
[exchange tests](../tests/test_p2_exchange.py),
[inert-parser tests](../tests/test_p2_legacy.py) and
[report/UI tests](../tests/test_p2_reports_ui.py). Runtime-generated XML from A
still needs a Java runtime; no runtime was installed for P2.

P1 additionally closes F40 (graph PNG/native printing and four-graph sheets), F42
(INCLUDE/IGNORE/HIDE with original cycle identities), F44 (saved recipes and
intensity-scaled dots), F85 (plain notes/descriptions), and F93 (labeled display
freeze). C3–C8 are implemented as presentation controls. C1/C2 remain unscheduled;
the C8 reduction switch remains D7; P3 adds diagnostic comparison only. F22 raw model residuals and F37 wider physical
unit coverage remain partial; P6 adds the verified raw-Faraday display subset. Source-semantic and
synthetic acceptance tests are in [test_p1_window.py](../tests/test_p1_window.py).

P3 closes the constrained existing-column expression editor/library and matching-identity
concatenation workflows. These are separate opt-in diagnostic objects with saved
recipe history; they never join an Analysis or its fraction mapping. The current
scope of all seven P3 rows is recorded below and in the inventory.

| Row | Status | P3 result and remaining boundary |
|---|---|---|
| F19 | done | E/G: P3 explicit matching-method/element/function/unit/settings compositions; original cycle/block/time IDs, source hashes, member masks and boundaries retained. Recorded time orders members; overlaps, duplicate cycles, mixed clocks and missing dates across acquisitions are refused. Separate diagnostic objects only; heterogeneous merging remains D9. [Implementation](../src/rawtims/composition.py). |
| F20 | partial | E/G: P3 labeled standard inverse-SE² mean/MSWD and Java 00dc941 inverse-SD² mean/chi-square diagnostics, per-block scale/counts and omission notices. Cycle estimator unchanged. Block reduction/export and its contract metadata remain D7. [Implementation](../src/rawtims/block_diagnostics.py). |
| F23 | done | E/G: P3 constrained safe parser/editor over existing function keys, arithmetic/right-associative powers, log10/ln/exp/sqrt, dependency ordering and per-cycle domain/missing flags. New explicit diagnostic columns only, saved/replayed separately; no /1 mapping. Wider language remains D8. [Implementation](../src/rawtims/expressions.py). |
| F45 | done | E/G: P3 named per-object expression library, stable explicit output keys, dependency/missing/cycle validation and separate strict composition undo/redo history persisted in native sessions. Sources are re-read/hash-checked; unavailable recipes are retained. No arbitrary code execution. [Implementation](../src/rawtims_gui/composition.py). |
| F49 | partial | E/G: P3 explicit ratio/inverse builder from existing columns of matching kind/unit, positive-ratio/domain flags and derived cycle display. No species inference or uncertainty propagation; generic raw species assignment remains P6. Derived columns never enter /1 mapping. [Implementation](../src/rawtims_gui/composition.py). |
| F92 | partial | E: P3 bounded + - * / ^, log (base ten), ln, exp, sqrt and parentheses; exact 200-cycle Java expression-array oracle and source-pinned operator tests. ln is an explicit inverse-exp extension. Broader utility vocabulary/implicit multiplication are outside the constrained D8 subset. [Implementation](../src/rawtims/expressions.py). |
| F95 | partial | E: P3 unused-by-default labeled symmetry/PSD validation, absolute-1σ measured-correlation conversion in both directions and explicit validity/unknown/zero-uncertainty errors. No named-model editor, sub-covariance recalculation, expression propagation or export wiring. [Implementation](../src/rawtims/covariance.py). |

[Engine/oracle tests](../tests/test_p3_composition.py) include the committed Java
200-cycle expression array, scalar source formulas, A/B block-split reassembly,
and synthetic edge cases. [Desktop tests](../tests/test_p3_composition_ui.py)
cover both themes at 1280×800 and 1440×900. D7, D8 and D9 remain open; P3 does
not select block exports, an unrestricted expression language or heterogeneous merging.

F40–F95 are listed individually with verified path:line references in
[tripoli-inventory.md](tripoli-inventory.md). They include printing; x–y recipes;
expression libraries; generic method XML, detector/baseline/sequence/species models;
intensity splines, baseline/noise and Faraday/photo-multiplier gain inference;
ensembles, convergence/burn-in, model residuals, processing states, vector exports,
MCMC2 and peak centres; tracer libraries/U components/batch correction; gains and
standards histories; individual vendor parsers; live final-file reconciliation;
Java session migration; exact export dialects, recent files, notes and reports;
manual statistics display freeze, dormant Excel workfile helpers and named covariance models.
The [roadmap phase row lists](tripoli-parity-roadmap.md) assign every incomplete row.

The inventory preserves F1–F31 while correcting several earlier interpretations:
legacy C# supports TIMSDP and live workflows; Java does not register Sector54;
C# Annotate edits notations rather than established per-plot markup; the legacy
block-sort toggle is dormant. F17 is partial when exact Tripoli exchange dialects
are included, although native CSV/XLSX exports work. F13 is a requested extension,
not a demonstrated dedicated Tripoli panel. Java demo menus are disabled/hidden;
experimental code is tracked separately from validated lab workflows.

**F25 ownership is a decision, not a silent change in scope:** see the prominent
[three-option contract discussion](tripoli-parity-roadmap.md#priority-decision-f25-ownership-and-the-fraction-contract).
D1 selects an opt-in diagnostic preview; the age app owns final fractionation/calibration. Existing
[idtims-fractions/1](contract-idtims-fractions-v1.md) ratios remain uncorrected for
mass fractionation. P7 adds isolated preview revisions and never changes this export contract.

## Evidence and interpretation

Use [the inventory source-area audit](tripoli-inventory.md#source-area-audit-and-coverage-limits)
and [roadmap fixture ledger](tripoli-parity-roadmap.md#fixture-and-oracle-ledger)
for source paths, file names, missing specimens and reference-code-versus-oracle distinctions.
The source snapshots are OGTripoli d906f70 and Java Tripoli 00dc941; references
were opened in those read-only clones. A source entry identifies the cited
implementation or related primitive, not an assertion of identical UIs.

[SPEC §2](SPEC.md#2-feature-inventory) and
[research notes](tripoli-research-notes.md) remain historical evidence. This gap
snapshot, inventory and roadmap supersede their planning exclusions; their
unmodified historical text does not override the current contract or validated
[raw reduction limits](raw-reduction.md). Existing database lookup/confirmed
links/chemistry provenance are implemented in [upbdb.py](../src/rawtims/upbdb.py);
server storage, approvals and mirror synchronization remain
[proposed work](database-recalculation.md).

P4 implements the first read-only subset of F27/F30/F66/F67/F68/F77/F81; all
remain **partial** against full parity. Local immutable calibration/review
revisions, date plots and reasoned undoable exclusions persist in native sessions.
Strict gains BIFF8 and standard .trip parsers are tested only with synthetic
source-schema specimens. Manual completed C# folder Refresh checks settling,
duplicates, gaps and truncated rows; explicit completion creates a portable
independent snapshot. Synthetic replay matches all representable cycle values,
identities, masks and statistics to the committed completed workbook; metadata
absent from the source dialect stays unavailable. D10 watches/provisional/final
merge and real acquisition/calibration validation remain open. See
[P4 source evidence, boundaries and specimen list](p4-calibration-history.md).

P6 completes F89 for the pinned reference catalog/resource scope. F24/F36/F37/F46/F47/F48/F78/F90 remain **partial** with independent read-only method XML/model inspection, Java synthetic structural parsing, explicit literal-Java versus stored-oracle spline conventions, and verified raw-Faraday display conversion. No existing raw/workbook route or /1 export changes. D13/D14 and real method/Full/TIMSAD specimens remain open; see [P6 scope, source citations and specimen list](p6-method-configuration.md).

| Row | Status | P6 scope and remaining limit |
|---|---|---|
| F46 | partial | Strict Phoenix XML import and Java name-only comparison; synthetic source-schema specimen only; real XML/Full pairing needed. |
| F47 | partial | Immutable detector/amplifier/resistor records and reference setup; generic calibrated editing remains D14/specimen-gated. |
| F48 | partial | Read-only baseline/on-peak/species cells; no integration allocation from methods. |
| F78 | partial | Synthetic Version 1.00 structural parsing and isolated oracle K matrices; real Phoenix Full/TIMSAD readers remain D13/specimen-gated. |
| F89 | done | Pinned Java Phoenix/UNKNOWN instrument geometry, synthetic detector setup and 3,365 nuclide/abundance records; reference provenance and limits disclosed. |
| F90 | partial | Typed transient display on verified existing raw Faraday columns; cached, ambiguous and multiplier conversions unavailable with reasons. |

## P7 fractionation preview (D1)

[Scope, formulas, convention differences and validation specimens](p7-fractionation-preview.md).

| Row | Status | Result and remaining boundary |
|---|---|---|
| F25 | partial | E/G: D1 opt-in C# linear Pb and 233/235 U mean-level calibration preview with first-order uncertainty propagation; age app authoritative, /1 unchanged. Per-cycle/calibrated-chain validation remains open. |
| F26 | not done | E/D: deferred under D11; no BaPO2, Tl or coupled interference correction or /2 contract. Independent validated specimens/provenance required. |
| F61 | partial | E/P/G: strict offline C# Tracer/TracerUPbModel XML, PCT/ABS uncertainty, versioned session library and active/applied identities. Web/editor absent; Java 00dc941 supplies no concrete tracer XML dialect or shipped XML. |
| F62 | partial | E: new pure opt-in C# 233/236 oxide diagnostic and propagated uncertainty, separate from the default core/mapping. No GUI molecular-assignment path or 233/236 fractionation (explicitly unsupported in C#); calibrated specimens needed. |
| F63 | done | E/G: explicit U blank pg, tracer g, sample/blank 238/235 and isotope molar masses, each with absolute 1σ, frozen with preview revisions. C# isotope-specific moles; zero-blank limit tested. Supported 233/235 preview only, never metadata-driven automatic calibration. |
| F64 | partial | E/G: frozen preview report with alpha, measured/corrected ratios and absolute 1σ, source/mask/settings/mapping/XML hashes, active/applied identity and separate persistent preview undo/redo. IC reports remain D11. |
| F65 | done | E/G: D1 batch preview over opened runs (including reopened saved sessions) appends new derived revisions with applied tracer/components; preserves all originals and prior revisions. Invalid runs are reported individually. No saved work-product overwrites. |

## P8 first increment: deterministic research model (2026-11-26)

F50 is done for the supported opt-in research model scope. F28/F55 become partial;
F24/F51/F52 stay partial. At P8, inventory totals were **40 done, 41 partial, 14 not done**; current P9 counts are below.

| Row | Status | Supported subset / remaining limit |
|---|---|---|
| F50 | done | Linear/cubic bases, knot initialization and forward evaluation on explicit prepared vectors / pinned K synthetic method; no production inference claim |
| F28 | partial | Deterministic MCMC1 prerequisite only; sampling/production choices remain D15/D16/D17 |
| F51 | partial | Baseline/noise/priors and literal oracle-M covariance update; initializer grid-search covariance and noise hierarchy absent |
| F52 | partial | Interior-knot PM/Faraday gain initialization; no joint posterior covariance |
| F55 | partial | Headless observed/model/residual/variance/inclusion/likelihood vectors; no desktop residual workspace |

At the P8 commit, no Analysis, session, reader, GUI or export route used the new model. F22/F56 stay
partial; at P8, F53/F54/F57/F58/F59 stayed not done. P9 adds the bounded recorded-scan subset of F59. See [P8 evidence, source quirks,
validation limits and missing truth](p8-mcmc1-forward-model.md). No sampling or
posterior-recovery acceptance is implied by deterministic source parity.
## P9 resources and educational sessions (2026-11-26)

Current inventory totals, recomputed across all 95 unique rows: **41 done,
43 partial, 11 not done**. F39 is done. F60 and F59 become partial; F55 remains
partial with synthetic educational desktop views added. F31 stays partial;
F41 and F94 stay not done.

| Row | Status | Supported scope / remaining boundary |
|---|---|---|
| F39 | done | Read-only versioned periodic table with all 118 elements and 3,365 P6 nuclides, including free neutron; attributed upstream bytes and missing-value semantics |
| F60 | partial | Two upstream synthetic two-isotope examples, linear/cubic deterministic P8 initialization/model/residuals, and two public recorded Pb scans in independent read-only sessions; sampling/posterior/MCMC2 and fitted beam shapes remain P8 decisions/truth gates |
| F55 | partial | Synthetic educational views of P8 arrays only; general production model/residual workspace remains unavailable |
| F59 | partial | Bounded raw-column scan reader/viewer for two bundled N resources; no beam inversion, collector overlays, widths or generic acquisition import |
| F41 | not done | Dormant block sort/trim untouched; D18 |
| F31 | partial, unchanged | No UPbDB/service/sync/approval/mirror changes; D19 |
| F94 | not done | Actual C# Excel workfile specimen and reference interpretation needed; review XLSX is different |

[P9 evidence and limits](p9-resources-demos.md), [resource/source tests](../tests/test_p9_resources.py)
and [synthetic UI/isolation/layout tests](../tests/test_p9_resources_ui.py).
D20 remains open for broader prioritization; the explicitly authorized resource/demo
subset does not decide lab-service sequencing. No new lab specimen is needed for
this bundled educational subset. Existing measured /1 exports and processing
routes remain unchanged.
