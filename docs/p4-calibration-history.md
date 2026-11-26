# P4 first read-only increment

This increment provides local evidence, explicit history exclusions and manual
completed-folder snapshots. F27/F30/F66/F67/F68/F77/F81 remain **partial** against
their full inventory scope. No history value replaces as-acquired gains, enters
a correction or changes `idtims-fractions/1`. All existing defaults are retained.

## Source schema and oracle boundaries

References are to read-only OGTripoli **d906f70**; Java remains **00dc941**.

| Evidence | Native subset and limitation |
|---|---|
| `OGTripoli/source/GainsFile.cs:132-278` | CTRL/Gains validity, named ranges `ILV_ErrorMessage`, `CCG_TotalCycles`, `ILV_StartTime`, `ILV_NoCollectors`, `CCG_Gains`, `ILV_CollNames`; High/Low Faraday or newer `-` with positive collector number; negatives become missing zero. Preserve the source's unusual doubled one-based start-column loop. Only BIFF8 constant absolute named references and unambiguous instrument date text are accepted. Numeric OLE dates, unknown formulas/layouts and ambiguous names are refused. |
| `OGTripoli/source/TripoliHistoryFolderGains.cs:151-192` | Per-file identity and collector history membership; native records use content hashes, not filename-only identity. |
| `OGTripoli/source/StandardsFile.cs:88-138,164-201` | Inert `.trip` work-product parsing, positive-cycle arithmetic block means and equal-block summary. Source `.triphis` accidentally opened as a standard is refused. Complete rectangular blocks required. |
| `OGTripoli/source/TripoliHistoryFolderStandards.cs:124-143,173-194,209-253` | Folder/ratio histories/settings and file membership. Source reacquires acquisition dates from an external vendor workbook; native import never follows that path or substitutes save/file dates. Existing open-run snapshots retain known acquisition dates. |
| `OGTripoli/source/forms/frmHistoryGraph.cs:408-427` | Explicit history selection/exclusion. Native reasons and undo/redo are additive; historical records remain immutable. |
| `OGTripoli/source/vendors_data/IonVantageLiveDataCyclesFolder.cs:25-36,75-216` | `-Bblock-Ccycle.txt`, positional header/function table, third CSV data field after `#START`. Source sorts by creation time and treats result as partial because no ending flag exists. Native completed-only path orders explicit numeric block/cycle IDs and requires manual completion attestation; no zeros are invented for absent cycles. |

[Engine tests](../tests/test_p4_history.py) generate **synthetic source-schema
specimens**, not reference-app-generated or vendor-produced fixtures. The gains
BIFF8 fixture extends the existing synthetic writer with absolute named-range
records. NRBF standard bytes use the existing inert-parser test scaffolding.
Scalar expected means/SEs are independently specified in tests. No real lab data
or new external fixtures are used.

Folder replay serializes the committed synthetic Pb workbook to the exact
source-consumed text positions, arrives in batches, and matches every final
function/cycle/block value, invalid/effective mask and summary to opening the
completed workbook. Portable snapshot/session reopening preserves its own cycle
export exactly. Full workbook metadata/time/export byte equality is impossible:
the text layout does not specify those fields. Missing elapsed times stay NaN;
unknown physical units and method name stay unavailable. Acquisition `Method`
path and source-file hashes remain evidence. A single full block or uniformly
shortened folder cannot establish planned completion; attestation is essential.

[UI tests](../tests/test_p4_history_ui.py) exercise exclusions/undo/reopen,
unchanged measured exports, explicit completion, folder switching and both themes
at 1280×800 and 1440×900. No upstream screenshot oracle exists.

## Implementation and persistence

- [history.py](../src/rawtims/history.py): immutable canonical JSON records,
  source/calibration/review versions, deterministic identities and strict
  reasoned exclusion replay. Acquisition wall dates sort first; unknown dates last.
- [calibration_formats.py](../src/rawtims/calibration_formats.py): strict explicit
  legacy gains/standard adapters. Unknown correction/tracer graph members remain
  inert evidence; they are never interpreted as a calibrated model.
- [completed_folder.py](../src/rawtims/completed_folder.py): Qt-free observations,
  size/mtime settling, read-time rechecks, duplicate/conflict/gap/truncation
  validation, explicit completed snapshots. A new folder gets new observations.
- [history GUI](../src/rawtims_gui/history.py): separate date plots and membership,
  manual Refresh and chosen snapshot file. Native sessions optionally store
  `calibration_history`; unused sessions have no new field. Snapshots carry a
  file manifest, values and source metadata and reopen through content dispatch.

History standard capture uses accepted-cycle arithmetic block means regardless
of the current cycle estimator; its derivation and original review settings are
recorded. Gains capture uses initial as-acquired gains and unfiltered acquired
gain columns. Neither is a re-reduction. Unknown uncertainties stay unavailable.

## Specimens needed to proceed

Yiming would need to supply a non-sensitive, complete set of:

1. Representative gains `.xls` from each instrument/software version, with
   named ranges intact, dates/collector mapping, aborted and older/newer forms,
   and independently checked collector means/exclusions.
2. Paired standards `.trip` and `.triphis`, their referenced processed workbooks,
   acquisition dates, masks, tracer/correction settings, and screenshots or
   exported history statistics from the pinned C# app. Include excluded records,
   multiple revisions, missing external sources and a partial final block.
3. C# IonVantage cycle-folder captures through creation, partial writes,
   truncation/retry, duplicate/conflicting files, termination and aborted runs,
   paired with the final processed workbook and expected cycle/block mapping.
   Preserve timestamps, software version and any completion/status protocol.
4. IsoLinx `LiveDataStatus` plus provisional/final files through a full acquisition,
   restart/folder change and termination; include a review with manual exclusions
   and the expected final reconciliation behavior.

D10 must settle watcher/provisional/final-merge policy before those workflows.
D4 binary write-back remains open. Aggregate history numerical migration, vendor
variants, calibration application, automatic history rejection, watches and
provisional sculpting are outside this increment. No decision is inferred here.
