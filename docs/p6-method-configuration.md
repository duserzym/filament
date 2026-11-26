# Read-only method and instrument references (P6)

P6 adds independent, opt-in inspection APIs and a **View → Review diagnostics →
Method / instrument references / intensity units…** window. Imported methods,
reference resources and matrices never enter the existing readers, reduction,
session replay, masks or `idtims-fractions/1` writer. D13/D14 remain open.

The versioned immutable model is `rawtims-method/1`; the catalog version is
`java-tripoli-00dc941/1`. Sources below refer to the supplied Java Tripoli commit
`00dc94109f572c22bb3f357c0f7b1bb5347f62f5`; they are source/schema or stored-resource
oracles, not a claim that Java was executed. Source paths are relative to Tripoli.

| Inventory row | P6 result | Remaining boundary |
|---|---|---|
| F24 | Partial: isolated structural/matrix prerequisites | No new raw reduction or calibration/inference route |
| F36 | Partial: read-only method, baseline, sequence, detector and resource inspection | Method/detector authoring remains D14 |
| F37 / F90 | Partial: transient, typed counts/s, V and A display for verified existing raw Faraday columns | No cached-workbook, ambiguous/unmapped-column or multiplier conversion; no integrated counts |
| F46 | Partial: strict Phoenix XML import, reference validation and Java name-only data-method comparison | Synthetic source-schema specimen only; no real vendor XML/Full pairing |
| F47 | Partial: immutable detector fields and pinned synthetic reference setup | No editable or independently calibrated generic hardware configuration |
| F48 | Partial: original string rows, isotope assignment, baseline/on-peak cell tables | No method-driven integration allocation or general acquisition decoder |
| F78 | Partial: Java synthetic Version 1.00 structural parser | No Phoenix Full 1.2/2.x or TIMSAD reader |
| F89 | Done for the pinned reference catalog/resource scope | Independent abundance provenance is not established; no interactive periodic table (F39) |

## Method import and model

`rawtims.methods` contains frozen tuple-based records for detectors, instruments,
nuclides, method rows, baseline cells and sequence cells. Original method strings,
SHA-256, schema and catalog version are retained. `rawtims.phoenix_method` exposes
`read_method_xml(path, detectors=...)` and `parse_method_xml(bytes, detectors=...)`.
The optional detector argument is an explicit tuple; the default is clearly labeled
**Java synthetic reference setup**, never an assertion about a run's hardware.

The entire field vocabulary/order is transcribed from
`TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/machineMethods/phoenixMassSpec/PhoenixAnalysisMethod.java:261-270,418-440,721-733,910-918,1165-1197,1628-1690`.
All leaves are strings in JAXB. Header, settings, one or more baseline rows,
optional on-peak rows and equilibration are required in that order. The JAXB API
uses a baseline list even though its generated schema comment omits `maxOccurs`;
this importer accepts the list represented by that API. Empty string fields remain
empty. The locally generated `synthetic_phoenix_method.xml` is written to this
source schema, **not exported by vendor software**.

Mapping follows `TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:200-303`:
isotopes accept `206Pb` and `Pb206`; blank/MASS baseline references use AxMass,
isotope references use their mass number; AxMassOffset is added; other detectors
use their ordinal minus the **Ax ordinal**, including when PM is axial. Both
Enabled strings are preserved; Java's mapper does not filter disabled rows.
Its active data consistency check is only case-insensitive method-name comparison
(`AnalysisMethod.java:306-322`). The commented-out baseline/sequence count checks
are not presented as implemented upstream validation.

This adapter additionally refuses unknown elements, attributes, namespaces,
duplicate/missing/reordered fields, mixed/nested text, DTDs/entities, malformed XML,
files above 2 MB, unknown species/collectors, non-finite consumed numeric fields,
duplicate collectors/sequences/references, noncontiguous baseline IDs, inconsistent
collector sequence suffixes and missing referenced axial baseline cells. UTF-8 is
the supported encoding. These are explicit import validation limits, not new
scientific rules or claims about all vendor XML versions. A failed import retains
the previous valid inspection and displays the refusal. There is no method writer,
editor, application of a method, or method persistence into a reduction session.

## Catalog and nuclides

Instrument geometry is transcribed from
`TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/MassSpectrometerBuiltinModelFactory.java:35-46`:
Phoenix collector width 0.95135 mm, magnet radius 540 mm, theoretical beam width
0.35 mm; UNKNOWN geometry remains zero. The factory contains only these two
models, not a catalog entry for every processed-file context.

The ten-collector synthetic setup is transcribed from
`TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/detectorSetups/DetectorSetupBuiltinModelFactory.java:39-61`:
L5, L4, L3, L2, Ax, PM, H1, H2, H3, H4, ordinals 0–9, reference resistances
10^11 Ω, gain **0**, efficiency 1, dead time 0; PM is Daly/VIRTUAL and the others
Faraday/Resistance. Zero reference gains do not authorize physical conversion.
Detector fields/types follow `detectorSetups/Detector.java:35-55,156-185`.

`src/rawtims/resources/NuclidesChartData.csv` is an unmodified, SHA-256-pinned copy
of `TripoliCore/src/main/resources/org/cirdles/tripoli/species/nuclides/NuclidesChartData.csv`
(3,365 rows). Apache attribution/license and the exact digest ship beside it.
Parsing follows `TripoliCore/src/main/java/org/cirdles/tripoli/expressions/species/nuclides/NuclidesFactory.java:60-98`:
blank/unparseable mass, abundance or half-life become 0; STABLE half-life becomes
−1. The inspector renders missing sentinels as Unavailable. Abundance is percent.
This is a pinned upstream reference, not newly certified isotope-abundance data.
No catalog default feeds a live run or correction.

## Synthetic structures and matrix conventions

`rawtims.synthetic_acquisition.read_java_synthetic` parses only `Version,1.00`,
`#START`, ID/Block/Cycle/Integ/Time/Mass and detector columns. It returns immutable
structural records with baseline/on-peak rows, original identities, timestamps,
masses, intensities and cycle-start indices. Units and species are not inferred.
The terminal baseline-only block is explicitly flagged as omitted, matching Java;
malformed rows, unsupported versions/sections, gaps, non-finite data and unordered
cycles/times are refused rather than silently skipped.

Source: `TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PhoenixMassSpec.java:163-231,420-449,488-590`.
Both oracle K `SyntheticDataset_01.txt` and `_02.txt` are copied unmodified as
`tests/fixtures/tripoli/p6/JavaDataset_01.txt` and `_02.txt`; each contains one block,
300 baseline and 1,500 on-peak records over 15 cycles. They are **upstream synthetic
resources**, with no recovered generating truth or posterior acceptance claim.
The fixture manifest records their original names, hashes and Apache provenance;
they are distinct from locally generated synthetic fixtures.

`rawtims.intensity_matrices` provides new matrix functions only:

- `linear_cycle_matrix(times, cycle_starts)`: rows are original times, columns are
  knots at cycle starts plus the final observed time. Each row has two complementary
  linear weights; the last row selects the final knot. Source:
  `TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelDriver.java:189-233`.
- `java_spline_basis`: literal truncated-power/difference/sign convention from
  `TripoliCore/src/main/java/org/cirdles/tripoli/utilities/mathUtilities/SplineBasisModel.java:38-160`.
- `spline_basis`: positive MATLAB/oracle K convention, explicitly multiplying the
  literal Java result by `(-1) ** (degree + 1)`. The Java formula omits that factor;
  **even-degree literal Java results have the opposite sign from its stored
  answers**. This discrepancy is tested, not hidden with an absolute-value step.
  The upstream stored-answer comparison is disabled in
  `TripoliCore/src/test/java/org/cirdles/tripoli/utilities/mathUtilities/SplineBasisModelTest.java:111-168`;
  its active test compares two overloads, not the stored answers.

All 100 input/parameter/answer triples in oracle K's `core/matLab/bspline/` resources
are checked. Inputs, bounds and answers are serialized to six decimals; the new
absolute tolerance is 4×10^-6 (maximum observed residual 3.469×10^-6). Hand-computed
synthetic spline/linear cases have much tighter tolerances. The linear matrix has
no independent stored K answer; it is checked against source-derived scalar
expectations and structural invariants on both K acquisitions. No Java runtime was
installed or invoked, and no existing test tolerance was changed.

## Typed physical display

`rawtims.physical_units` exposes `IntensityUnit`, immutable calibration/availability
records, `convert_intensity` and the run-gated `display_intensity`. Counts means
**count rate (counts/s)**, not integrated counts. Reference formulas and SI charge
come from `TripoliCore/src/main/java/org/cirdles/tripoli/constants/TripoliConstants.java:63-67,150-173`;
selection/gain presentation comes from
`TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/SpeciesIntensityAnalysisPlot.java:219-245`.

The inspector starts on Acquired values and never saves a unit choice into a run.
Conversion requires an existing successful raw-route Run with a matching parameter
hash, raw-input provenance, a verified Faraday mapping and positive recorded
resistor/gain metadata. It reads existing records only. Existing supported raw Pb
Faraday columns are cps; U columns are V. Their selected gain has already been
applied or explicitly disabled, so display conversion never applies it again.
The raw route's **recorded vendor charge 1.6021892×10^-19 C** remains authoritative
for those values; Java-reference tests separately use 1.602176634×10^-19 C. Signed
values and missing samples remain signed/missing. Returned arrays are independent.

Cached-workbook values, ratios, unverified/missing mapping or calibration and
multiplier-to-V/A conversions are unavailable with a displayed reason. No dwell
or multiplier efficiency is guessed. No data, masks, statistics, row/function keys,
parameters, export fields or units on the original Run are changed.

## Specimens and decisions still needed

D13 must choose the next raw acquisition family; D14 must choose any future editing
scope. This phase makes neither decision. Yiming would need to supply:

- Phoenix method XML with software/version, intended detector setup, baseline and
  sequence/species tables, paired Phoenix Full text and vendor-produced processed
  cycles/reports from the same acquisition, including gains/resistors/units and
  acceptance masks; a multi-baseline/peak-hopping case and an aborted/tail case.
- For TIMSAD, a paired raw SQLite/processed/method set with independently documented
  channel-to-collector mapping, acquisition order, timestamps, integration duration,
  intensity units, amplifier type/resistance/gain/dead time and vendor reductions.
  The public paired file alone supplies no decoded integration truth.
- For additional physical display coverage, per-function/sequence collector and
  unit evidence, resistor/gain application state, and calibrated multiplier response
  or dwell times where relevant, with independently checked V/A/cps equivalents.
- For generic abundance certification, an identified authoritative source/version
  and policy for unknown or radioactive abundance/half-life values.

The BSU two-sequence Pb investigation, 3 ppm criterion, existing IonVantage/workbook
routes and Phoenix Full/TIMSAD refusal remain as documented in [raw reduction](raw-reduction.md).
Tests: [engine/source/resource/synthetic](../tests/test_p6_methods.py),
[desktop isolation and both-theme layout](../tests/test_p6_methods_ui.py).
