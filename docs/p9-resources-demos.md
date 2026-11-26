# P9 resources and educational sessions

P9 implements the authorized resource/demo subset. It does not resolve D18,
D19 or D20. The existing reduction core, measured `/1` contract and user-session
routes are unchanged.

| Row | Status | Implemented scope / remaining boundary |
|---|---|---|
| F39 | done | Read-only periodic table, 118 elements and all 3,365 P6 nuclides, including the free neutron |
| F60 | partial | Four isolated educational choices: two upstream synthetic two-isotope datasets and two public peak scans. No sampling, posterior recovery, MCMC2 or fitted peak-shape demonstration |
| F55 | partial | P8 arrays now viewable in synthetic educational sessions; production observed/model/residual workspace remains P8 |
| F59 | partial | Strict recorded-column peak-scan parser and two bundled scan views only; beam inversion, collector overlays, widths and general acquisition import remain P8 |
| F41 | not done | Dormant sorting/trim unchanged; D18 remains open |
| F31 | partial, unchanged | UPbDB/service/revisions/approvals/mirrors untouched; D19 remains open |
| F94 | not done | Legacy C# Excel workfile migration needs an actual specimen and reference-app interpretation |

## Reference resources

`rawtims.reference_data` reads the unmodified Java
`TripoliCore/src/main/resources/org/cirdles/tripoli/elements/PeriodicTableOfElements.csv`
at commit `00dc94109f572c22bb3f357c0f7b1bb5347f62f5`. Element names, symbols,
atomic numbers and grid positions follow `ElementsFactory.java:42-68`, including
its trimming of trailing spaces. Nuclides reuse P6's unchanged
`rawtims.methods.nuclides()` and `NuclidesChartData.csv` (oracle O).

Both resources have version `java-tripoli-00dc941/1`; original bytes and SHA-256
digests are recorded in `src/rawtims/resources/NOTICE`, alongside Apache-2.0
attribution and license. This identifies the upstream snapshot, not independent
certification of its isotope abundances or atomic masses. Stable and unavailable
half-life/abundance values retain the P6 sentinels, displayed as words. All 118
elements are selectable by grid or atomic-number/name/symbol list. The neutron is
available in the list so every nuclide row is accessible.

The GUI follows `TripoliApp/src/main/java/org/cirdles/tripoli/gui/PeriodicTableController.java:120-131`:
select an element to inspect its nuclides. There are no write or apply controls.

## Educational scope and isolation

**Resources → Educational demos · read-only** opens a new `DemoSession` and
independent window on every selection, including repeated opens of one example.
Bundled resources are digest-checked before parsing. No lab files, user-selected
paths, Workspace, Analysis, native session persistence or export writer participates.
Plot export/context menus are disabled. Closing the window discards its view.
Display selections only choose a channel or intensity basis; original observations
and initialized result arrays remain read-only. Themes follow the active lab UI.

`educational-manifest.json` records schema `rawtims-educational/1`, upstream
commit, license, original path and hash for every packaged input:

- Oracle K `SyntheticDataset_01.txt` and `_02.txt`, byte-identical to the committed
  P6 fixtures, run through P6 structural parsing and P8 deterministic MCMC1
  initialization. Six channels expose baseline, Faraday and PM observations;
  linear/cubic bases show initial model, observed-minus-model residual and noise
  variance. Tables and source/limits accompany plots. Source generating truth is
  unavailable. Literal Java indexing/noise conventions remain documented in
  [P8](p8-mcmc1-forward-model.md); these are initial models, not posterior fits.
- Oracle N `6NHCl dpblank-210204A-169-PKC-208Pb-PM-S5B2C1.TXT` and
  `DVCC18-9 z9 Pb-570-PKC-205Pb-PM-S2B7C1.TXT`, public upstream reference scans.
  A bounded parser displays their 92 mass/intensity pairs and original header
  metadata without inventing intensity units or fitting a beam/collector model.
  Parser column semantics follow
  `TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PeakShapeProcessor_PhoenixTextFile.java:53-92`.

The upstream menu at `TripoliApp/src/main/resources/org/cirdles/tripoli/gui/TripoliGUI.fxml:103-106`
is hidden and disabled, with two-isotope RJ MMC and PeakShapes entries.
`TripoliGUIController.java:754-762` opens their separate plot windows. P9 exposes
only the reproducible educational prerequisites. Full algorithms still require
P8 decisions D15/D16/D17 and independent expected results/truth. The MCMC2
resource referenced by its driver is absent from the supplied clone; oracle N
does not contain stored fitted beam-shape/width answers.

## Verification

[Resource tests](../tests/test_p9_resources.py) pin element bytes/positions,
complete nuclide coverage, upstream synthetic/P8 array equality, recorded scan
scalar answers, synthetic scan columns/refusals, immutable arrays, independent
opens, digest guards and Qt-free imports. Source paths and line numbers are in
test docstrings; Java is not executed. Inputs are committed synthetic/public
resources only. [Desktop tests](../tests/test_p9_resources_ui.py) exercise menu
actions, all channels/bases, read-only controls, empty work products, live theme
changes and before/after user-workspace values/history/settings/presentation,
clipboard/cycle and measured `/1` bytes.

All resource/demo tabs are checked at 1280×800 and 1440×900 in light/dark themes,
with no horizontal table overflow. G0 outputs, screenshots, exact suite counts
and first self-review findings are recorded in the P9 scratch gate report.
The desktop spec and package-data declarations include the static resources;
no desktop build, install or release is performed in this phase.
