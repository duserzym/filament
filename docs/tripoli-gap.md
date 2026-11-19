# Tripoli feature gaps

Snapshot for G2 (2026-11-18). **Done** means the stated workflow exists;
**partial** means the limits in the last column still apply; **not done** means
unimplemented, without a delivery promise; **not planned** means outside the
current scope. Numerical parity is narrower than a feature check: see
[the parity report](tripoli-parity.md) and [raw reduction limits](raw-reduction.md).

The comparison uses legacy **C# 4.10.0.3** and the **Java Tripoli** source snapshot
`00dc941` researched in this repository. “Java” below identifies that implementation,
not a claim that every subsequent upstream release is identical. Upstream projects:
[CIRDLES/OGTripoli](https://github.com/CIRDLES/OGTripoli) and
[CIRDLES/Tripoli](https://github.com/CIRDLES/Tripoli).

## Core review and exchange

| SPEC | Feature | Legacy C# 4.10.0.3 | Java Tripoli | filament | Remaining limit or difference |
|---|---|---|---|---|---|
| F1 | IonVantage `.xls` | Import processed functions | Import processed functions | done | Aborted runs, duplicate names and workbook reader anomalies covered; settings are provenance, not instructions to correct cached values twice. |
| F2 | IsoLinx `.TIMSDP` | No equivalent established in this source | Supported | done | Processed functions, not raw integrations. |
| F3 | Many files, folders, content routing | File-oriented imports | Context-specific parsers | done | `.raw` directories open their cached workbook; supported acquisition decoding is separate. |
| F4 | Function classification | Ratios and special functions | Ratios, intensities, user functions | done | Duplicate names retain distinct column keys. |
| F5 | Pb/U pairing and fraction metadata | Separate work products and names | Analysis/session metadata | done | Explicit fraction pairing; review ambiguous names. |
| F6 | Cycle wall, bands, log and inversion | Ratio graphs, display options | Plot wall/sculpting | done | G1b plot-first wall, per-plot block strips, Focus, fit/maximise; inversion is in mapping. |
| F7 | Cycle table and selection | Ratio data views | Cycle views/export | done | Table and plots share edit state. |
| F8 | Point/box/block rejection, SYNCH | Per-ratio selections and synchronisation | Sculpting and SYNCH | done | Mapped export ratios use shared selection; restored legacy per-ratio masks are labeled and export-blocked until reconciled. |
| F9 | Outlier rules | Single-pass 2σ; repeated worst-point Chauvenet | One-pass Chauvenet, default minimum 20 | done | All are explicit preview/apply; iterative k-σ is also available. No automatic rejection on open. |
| F10 | Undo/redo/reset | Per-ratio history | Reset; no general rejection undo | done | Rejections, mapping, settings and reduction changes replay through public history. |
| F11 | Cycle statistics | Arithmetic ratio mean, SD, SE | Geometric/log-ratio statistics | done | Arithmetic default; geometric selectable for Java comparison. Intensities remain arithmetic. |
| F12 | U oxide correction | Legacy/ET_Redux denominator | Different 238/235 denominator in snapshot | done | Legacy default, labeled Java comparison; already-corrected functions pass through with provenance. BSU U `270/267` alias is warned about. |
| F13 | Derived in-run 18O/16O monitor | No dedicated equivalent established | No dedicated equivalent established | not done | Existing `272/270` can be plotted; no dedicated `/2` monitor panel. |
| F14 | Ratio mapping and method defaults | Active ratio selection | ET_Redux names, inversion and defaults | done | Explicit source-column mapping remembered by method; not a general ratio-expression builder. |
| F15 | Fraction hand-off | ET_Redux XML/clipboard | ET_Redux XML and live folders | partial | `idtims-fractions/1` CSV with shared-cycle correlations/provenance and Send to IDTIMS_UPbRPy are done. Native ET_Redux XML and its folder protocol are not implemented. |
| F16 | Legacy clipboard | C# E7 mean and % SE blocks | Full-precision clipboard blocks | done | Legacy two-space header, CRLF, E7 default; optional full precision. |
| F17 | Cycle export | Tabular data exports | TSV, rejected values wrapped in `&` | done | CSV with explicit inclusion flags; not the same TSV encoding. Review XLSX/CSV include fraction, cycles and provenance tables. |
| F18 | Saved work/session | Binary `.trip`, `.triphis` | Java-serialized `.tripoli` | partial | Native JSON sessions, source hashes, recovery and strict replay done; legacy `.trip` read-only import done. No Java `.tripoli` import or legacy format write-back. |
| F19 | Concatenate acquisitions | Supported, including timestamp ordering | Session concatenation | not done | Do not infer concatenation from ambiguous project names or combine unrelated workbooks. |
| F20 | Block statistics/reduction | Block selection/statistics | Weighted block mean and MSWD code | partial | Block means, SE, weighted diagnostic and block MSWD done; fraction exports still use cycle means. No selectable block-based reduction/export. |
| F21 | Any-function x–y plot | No equivalent established here | Supported | not done | Cycle wall and cycle table only. |
| F22 | Intensities and gain trends vs time | Ratio/special-function graphs | OnPeak intensity/residual tabs | partial | Intensities and available gain functions plot against cycle; no dedicated time/residual workspace or integration-level trend editor. |
| F23 | Custom expressions/ratio builder | Special functions and correction functions | Expression editor and species ratio builder | not done | Existing function columns and fixed validated corrections only. |

## Reduction, instrument and database work

| SPEC | Feature | Legacy C# 4.10.0.3 | Java Tripoli | filament | Remaining limit or difference |
|---|---|---|---|---|---|
| F24 | Raw acquisition reduction | Receives instrument-processed ratios | Phoenix Full baseline/gain/intensity models | partial | Deterministic IsoprobeT four-sequence Pb and static U decoding, dead time, baselines, acquired Faraday gains, measured per-cycle Faraday/Daly gain and BI implemented. Editable parameters, diff, undo/replay done. Two-sequence Pb, incomplete/unmatched cycles and non-1 s methods remain unsupported; no `.TIMSAD` reader or generic calibration fit. Workbook dead-time route is an explicit approximation. |
| F25 | Pb/U tracer fractionation | Linear law, Pb 202/205 and U 233/235 double spike | Not applied by the researched export path | not planned | The age app owns fractionation and tracer calibration. Exported ratios are non-fractionation-corrected; spike fields are metadata. No claim of validated real ET2535 reduction. |
| F26 | BaPO2/Tl correction | Combined interference/fractionation solution | No implementation in researched path | not done | Requires a demonstrated lab need, validated inputs and explicit applied-correction provenance. |
| F27 | Live acquisition watching | Historical file-oriented workflows | IsoLinx LiveData ingestion | not planned | Open completed runs manually in the current scope. |
| F28 | MCMC, Bayesian ensembles, peak shapes | No equivalent | MCMC1/MCMC2 and demonstrations | not planned | Deterministic reduction only. |
| F29 | Other instrument formats | Several instrument imports | Triton, Neptune, Nu, Sector 54 and others | not planned | Current scope is IsotopX. |
| F30 | Gains/standards history | `.triphis`, history graphs | Different session/live model | not done | Run-level calibration provenance is present; no cross-run gains/standards database. |
| F31 | Lab/database context and mirrors | ET_Redux workflow integration | ET_Redux live folder protocol | partial | Versioned contract/provenance and local age-app Send exist; UPb Lab context, server storage, approvals, mirror sync and URL-context handling remain design work. Registering a URL scheme is not an implemented database workflow. |

## Other visible Tripoli features

| Feature | Legacy C# | Java | filament | Limit |
|---|---|---|---|---|
| Histogram overlay | Selectable bins | Not established in researched cycle wall | not done | No histogram view. |
| Graph annotations | Annotation tools | Plot settings/customisation | not done | No persistent per-plot annotations. |
| Custom report builder/templates | Reports and special exports | Categories, columns, custom CSV reports | partial | Fixed contract, clipboard, cycles and review tables; no report designer. |
| Per-user/session/analysis defaults | Saved settings and work-product settings | Cascading defaults | partial | Method mappings and UI preferences persist; numerical settings saved per analysis/session, without Java's full cascade editor. |
| Instrument method/detector editor | Run/instrument settings | Method, detector, baseline and sequence tables | partial | Run info plus supported reduction controls; no general instrument method authoring. |
| Plot styling and units | Histogram/stats/discard display choices | Colors, sizes, counts/volts/amps controls | partial | Theme, log, selection, fit and layout tools; no complete Tripoli styling/unit-conversion editor. |
| Help and demonstrations | Help/manual | Manual, videos, demos | done | Bundled user guide and KD33 dead-time walkthrough; KD33 needs the read-only examples folder. |
| Periodic table and MCMC demos | Other tools | Resource/demo menus | not planned | Outside the review/hand-off workflow. |

## Evidence and interpretation

Start with [SPEC §2](SPEC.md#2-feature-inventory),
[research notes §§3–6](tripoli-research-notes.md),
[the current GUI inventory](ui-panels.md) and [raw reduction](raw-reduction.md).
Older statements in SPEC/research notes about unavailable BSU U/raw inputs are
superseded by [RESUME](RESUME.md) and the parity/recalculation reports.

Legacy source was read directly from the supplied OGTripoli `source` directory:

- `RawRatio.cs`: `CalcStats` (around line 804), `HandleOutliers`, `_UndoHistory`,
  `HistogramBinCount`, rule/rejection and synchronisation operations.
- `TripoliWorkProduct.cs`: `PerformFractionationCorrection` (1074), U alpha
  cases (1263–1338), `CalculateAlphaPbForFractionationCorrectionOnly` (2025),
  `CalculateAlphaPbForInterferenceAndFractionationCorrectionBoth` (2038),
  `PerformOxideCorrectionFor233_235Tracer` (2495) and the 233/236 variant (2736).
- `TripoliHistoryFolderGains.cs`, `TripoliHistoryFolderStandards.cs`,
  `GainsFile.cs`, `StandardsFile.cs` and history/work-product serialization.

Java file/class evidence and detailed paths are recorded in the research notes:
`AnalysisStatsRecord`, `BlockStatsRecord`, `MathUtilities`,
`MassSpecOutputBlockRecordLite`, `MeasuredUserFunction`, `Analysis`,
`AnalysisManagerController`, `PhoenixLiveData` and `PlotWallPane`.
A “not established” cell deliberately avoids inferring absence from an incomplete
inventory. Status judgments describe filament's implementation, not a promise of
identical UI or all-method numerical equivalence.
