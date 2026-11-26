# Tripoli feature gaps

Snapshot: **2026-11-25**. **Done** means the stated supported-input workflow exists;
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
| F15 | Fraction hand-off | ET_Redux XML/clipboard; `OGTripoli/source/forms/fmrMainTripoli.cs:5288` | ET_Redux XML and live folders; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:785` | partial | E/G: CSV contract and age-app Send exist (docs/ui-panels.md); XML and ET_Redux folder protocol still needed (F80). [P2](tripoli-parity-roadmap.md#phase-p2-exchange-reports-and-saved-work-compatibility-l-staged). [filament evidence](../src/rawtims/fractions.py#L270). |
| F16 | Legacy clipboard | C# E7 mean and % SE blocks; `OGTripoli/source/forms/frmRatioGraph.cs:1726` | Full-precision clipboard blocks; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:801` | done | E/G: C# E7/CRLF header plus full precision option; EXCEEDS: both styles explicit. [filament evidence](../src/rawtims/exports.py#L84). |
| F17 | Cycle export | Tabular data exports; `OGTripoli/source/TripoliWorkProduct.cs:2901` | TSV, rejected values wrapped in `&`; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:737` | partial | E/G: CSV inclusion flags and review XLSX exist (docs/ui-panels.md); exact Java TSV ampersand encoding and OG text interchange missing (F83). Downgraded from done for exact exchange scope. [P2](tripoli-parity-roadmap.md#phase-p2-exchange-reports-and-saved-work-compatibility-l-staged). [filament evidence](../src/rawtims/exports.py#L96). |
| F18 | Saved work/session | Binary `.trip`, `.triphis`; `OGTripoli/source/TripoliWorkProduct.cs:821` | Java-serialized `.tripoli`; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/utilities/stateUtilities/TripoliSerializer.java:34` | partial | E/P: native JSON/hash replay/recovery and inert .trip import (readers/trip.py) done; Java .tripoli import, .triphis import and legacy write-back need work. Do not deserialize executable objects. [P2](tripoli-parity-roadmap.md#phase-p2-exchange-reports-and-saved-work-compatibility-l-staged). [filament evidence](../src/rawtims/session.py#L493). |
| F19 | Concatenate acquisitions | Cycle-folder append with timestamp checks; `OGTripoli/source/forms/fmrMainTripoli.cs:2053` | Session concatenation; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:177` | not done | E/G: retain member sources, ordering, masks and boundaries; C# verified append is cycle-folder-specific, not a general XLS concatenator. [P3](tripoli-parity-roadmap.md#phase-p3-composable-deterministic-analysis-l). [filament evidence](../src/rawtims/model.py#L144). |
| F20 | Block statistics/reduction | Block selection/statistics; `OGTripoli/source/RawRatio.cs:1172` | Weighted block mean and MSWD code; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/AnalysisStatsRecord.java:107` | partial | E/G: block means, SE, weighted diagnostics and MSWD exist; exports use cycles. Java comments abandon block mode; its SD weights/MSWD require explicit compatibility naming. [P3](tripoli-parity-roadmap.md#phase-p3-composable-deterministic-analysis-l). [filament evidence](../src/rawtims/stats.py#L174). |
| F21 | Any-function x–y plot | No equivalent established here | Supported; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:1499` | done | G: P1 any-two-existing-functions x-y view, paired finite original cycle IDs and joint acceptance display; no masks change. Named recipes and intensity radii in F44. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F22 | Intensities and gain trends vs time | Ratio/special-function graphs; `OGTripoli/source/forms/frmRatioGraph.cs:369` | OnPeak intensity/residual tabs; `Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/OGTripoliView.fxml:26` | partial | G: P1 existing cycle columns plot against recorded elapsed seconds, with unavailable-time notice. E: raw model residuals remain F55/P8; no residuals invented for cached ratios. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F23 | Custom expressions/ratio builder | Special functions and correction functions; `OGTripoli/source/vendors_data/IsotopXPhoeniX_ImportedTIMSDPDataFile.cs:85` | Expression editor and species ratio builder; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/AnalysisManagerController.java:2406` | not done | E/G: C# imports instrument-computed functions; no equivalent general authoring editor established. Java has a real expression tree/editor. [P3](tripoli-parity-roadmap.md#phase-p3-composable-deterministic-analysis-l). [filament evidence](../src/rawtims/readers/functions.py#L74). |

## Reduction, instrument and database work

| SPEC | Feature | Legacy C# 4.10.0.3 | Java Tripoli | filament | Remaining limit or difference |
|---|---|---|---|---|---|
| F24 | Raw acquisition reduction | Receives instrument-processed ratios; `OGTripoli/source/vendors_data/MassLynxDataFile.cs:129` | Phoenix Full baseline/gain/intensity models; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelDriver.java:72` | partial | E/P/D: EXCEEDS C#: deterministic IsoprobeT four-sequence Pb/static U decoding and parameter replay. Non-1s, two-sequence, unmatched tails, generic raw formats remain restricted; Java raw path differs. [P6](tripoli-parity-roadmap.md#phase-p6-method-driven-raw-processing-and-instrument-configuration-l). [filament evidence](raw-reduction.md). |
| F25 | Pb/U tracer fractionation | Linear law, Pb 202/205 and U 233/235 double spike; `OGTripoli/source/TripoliWorkProduct.cs:1074` | Not applied by the researched export path; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/outputs/etRedux/MeasuredUserFunction.java:63` | not done | E/D: age app currently owns it; Java measured-export path is not evidence of tracer correction. Decision prominently in roadmap; no corrected ratios may silently enter /1. [P7](tripoli-parity-roadmap.md#phase-p7-tracer-fractionation-and-interference-capability-l-d1-gate). [filament evidence](contract-idtims-fractions-v1.md#purpose). |
| F26 | BaPO2/Tl correction | Combined interference/fractionation solution; `OGTripoli/source/TripoliWorkProduct.cs:2038` | No implementation in researched path | not done | E/D: validated IC/tracer inputs and applied-correction provenance needed; no Java equivalent established. [P7](tripoli-parity-roadmap.md#phase-p7-tracer-fractionation-and-interference-capability-l-d1-gate). [filament evidence](raw-reduction.md). |
| F27 | Live acquisition watching | Live newest-file and cycle-folder workflows; `OGTripoli/source/forms/fmrMainTripoli.cs:6371` | IsoLinx LiveData ingestion; `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/TripoliGUIController.java:884` | not done | E/P/G/D: both versions have live workflows; Java provisional/final merging in F81; C# newest-file workflow explicitly saves/exports. [P4](tripoli-parity-roadmap.md#phase-p4-calibration-history-and-live-ingestion-l-history-before-watching). [filament evidence](../src/rawtims/readers/__init__.py#L1). |
| F28 | MCMC, Bayesian ensembles, peak shapes | No equivalent | MCMC1/MCMC2 and demonstrations; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/MCMCProcess.java:254` | not done | E/D: production-style MCMC1 plus exploratory MCMC2 and peak tools are distinct F50-F60; deterministic reduction is not Bayesian parity. [P8](tripoli-parity-roadmap.md#phase-p8-bayesian-model-fitting-ensembles-and-peak-shapes-l-several-releases). [filament evidence](raw-reduction.md). |
| F29 | Other instrument formats | Several instrument imports; `OGTripoli/source/forms/fmrMainTripoli.cs:838` | Triton, Neptune, Nu TIMS; Sector54 not registered; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/constants/MassSpectrometerContextEnum.java:46` | not done | E/P/D: split vendor rows F69-F78; Java has no Sector54 parser in its context registry. Parser existence does not prove every instrument version. [P5](tripoli-parity-roadmap.md#phase-p5-additional-processed-file-parsers-l-one-dialect-per-increment). [filament evidence](../src/rawtims/readers/__init__.py#L1). |
| F30 | Gains/standards history | `.triphis`, history graphs; `OGTripoli/source/TripoliHistoryFolderGains.cs:151` | Different session/live model | not done | E/P/G/D: gains XLS, tripolized standards and history graphs are F66-F68; run-level calibration provenance is already present (raw-reduction.md). [P4](tripoli-parity-roadmap.md#phase-p4-calibration-history-and-live-ingestion-l-history-before-watching). [filament evidence](raw-reduction.md). |
| F31 | Lab/database context and mirrors | ET_Redux workflow integration; `OGTripoli/source/forms/fmrMainTripoli.cs:6427` | ET_Redux live folder protocol; `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/utilities/stateUtilities/liveWorkFlow/SampleMetaDataUnmarshaller.java:36` | partial | E/G: UPbDB lookup/cache/confirmed links and chemistry exist (src/rawtims/upbdb.py), CSV provenance and local Send exist. Remote storage/approvals/mirrors are proposals; Tripoli evidence covers local ET_Redux context, not a remote database. [P9](tripoli-parity-roadmap.md#phase-p9-remaining-resources-and-lab-scale-integration-l-independent-increments). [filament evidence](database-recalculation.md). |

## Other visible Tripoli features

Previously unnumbered rows now have stable IDs. Full source/status evidence and
all detailed subfeatures are in [the inventory](tripoli-inventory.md).

| Feature | Legacy C# | Java | filament | Limit |
|---|---|---|---|---|
| F32 Histogram overlay | `OGTripoli/source/forms/frmRatioGraph.cs:905` | `Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/plots/histograms/HistogramBuilder.java:39` | done | G: P1 separate cycle histogram with selectable bins, shared accepted/rejected edges, Tripoli epsilon/right-endpoint binning. Counts retain all finite cycles (including zero); no cycle-wall overlay or ensemble claim. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F33 Annotations/notations | `OGTripoli/source/forms/fmrMainTripoli.cs:4047` | `Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/SessionManager.fxml:74` | done | G: D2 plain session/work-product/fraction/sample notes, edited as plain text and roundtripped in optional native session presentation metadata. No freehand/per-plot markup. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F34 Custom report builder/templates | `OGTripoli/source/TripoliWorkProduct.cs:2901` | `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/reports/ReportBuilderController.java:781` | partial | E/G: fixed review tables exist; configurable columns/order/visibility, save/delete report templates and custom CSV absent. C# tabular report is not equivalent designer. Roadmap P2. [filament evidence](../src/rawtims_gui/table_exports.py#L13). |
| F35 Per-user/session/analysis defaults | `OGTripoli/source/TripoliRegistry.cs:30` | `Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/settings/SettingsWindow.fxml:437` | partial | E/G: UI preferences/method maps/per-analysis settings exist; editable cascade/restore with explicit effective value missing. Roadmap P2. [filament evidence](ui-panels.md). |
| F36 Instrument method/detector editor | `OGTripoli/source/RunParameters.cs:23` | `Tripoli/TripoliApp/src/main/resources/org/cirdles/tripoli/gui/AnalysesManager.fxml:233` | partial | E/G/D: staged supported parameters + run info exist; Java tables are partly display, not evidence of unrestricted instrument authoring. Detailed method features F46-F49/F90. Roadmap P6. [filament evidence](raw-reduction.md#desktop-reduction-controls). |
| F37 Plot styling and units | `OGTripoli/source/forms/frmRatioGraph.cs:2054` | `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/SpeciesIntensityAnalysisPlot.java:234` | partial | G: P1 remembered per-function point colors/sizes plus existing themes/log/fit/layout; diagnostic recipe styling. E: physical counts/V/A conversion remains P6/F90 and requires verified metadata. [Implementation](../src/rawtims_gui/diagnostics.py). |
| F38 Help and demonstrations | `OGTripoli/source/forms/fmrMainTripoli.cs:5831` | `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/TripoliGUIController.java:880` | done | G/docs: bundled guide, KD33 walkthrough (ui-panels.md) and numerical site (SITE.md); walkthrough needs read-only examples. Tripoli-specific video links are not parity requirements. [filament evidence](user-guide.md). |
| F39 Periodic table and nuclide resource | No equivalent established | `Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/TripoliGUIController.java:748` | not done | G + resource data: low lab priority; isotope/abundance source version must be identified. MCMC demos split to F60. Roadmap P9. [filament evidence](user-guide.md). |

## Long tail and scope changes

P1 additionally closes F40 (graph PNG/native printing and four-graph sheets), F42
(INCLUDE/IGNORE/HIDE with original cycle identities), F44 (saved recipes and
intensity-scaled dots), F85 (plain notes/descriptions), and F93 (labeled display
freeze). C3–C8 are implemented as presentation controls. C1/C2 remain unscheduled;
the C8 reduction switch remains D7/P3. F22 raw model residuals and F37 physical
unit conversion remain partial for P8 and P6 respectively. Source-semantic and
synthetic acceptance tests are in [test_p1_window.py](../tests/test_p1_window.py).

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
The age app currently owns fractionation/calibration; existing
[idtims-fractions/1](contract-idtims-fractions-v1.md) ratios remain uncorrected for
mass fractionation. Planning now includes this functionality, but that does not
change the implemented export contract.

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
