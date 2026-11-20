# Status note (2026-11-18, real BSU legacy parity)

Private repository `duserzym/filament`, branch `main`.
Working name `filament` remains centralized in `src/rawtims/branding.py`.

## Validated against Yiming's actual BSU data

See [tripoli-parity.md](tripoli-parity.md) for the reproducible method, source
matching, tolerances, all comparisons and exceptions. Run:

```sh
env -u PYTHONPATH .venv/bin/python scripts/tripoli_parity.py
```

Inputs are read-only and remain outside the repository. Override their locations
with `FILAMENT_BOISE_EXAMPLES` and `FILAMENT_BSU_SHEETS` (defaults: the matching folders in a
Google Drive mirror under the home folder, else `~/Data/filament/legacy-projects` and
`~/Data/filament/reference-sheets`). Tests skip unavailable private inputs. No private cycle
values or acquisition fixtures have been added.

- Safe pure-Python MS-NRBF reader: `read_trip(path) -> TripProject`, with inert
  class dictionaries, shared/cyclic references, bounded input/allocations and
  typed project settings. Content sniffing identifies a legacy project without
  dispatching it as a raw run.
- **31 distinct projects** (content deduplicated), all legacy Tripoli **4.10.0.3**;
  **30 have workbook-backed parity**. Ordinary source cycle magnitudes agree
  exactly. Legacy Decimal oxide computations agree within float64 round-off.
  Arithmetic statistics reproduce original stored All* fields within the
  quantified legacy cancellation bound. Accepted statistics are reconstructed
  independently from signed values, with exact per-function masks restored
  through public strict session history replay.
- **126 pasted ratio pairs** (mean and 1σ %SE) match the appropriate acquisition:
  KD33 and KG5 z1–z7, six Pb and three U ratios each. Clipboard comparison allows
  half a unit at eight significant digits (legacy C# E7) plus legacy round-off.
- The two distinct nested `.trip` copies are the Pb reruns actually used in the
  KG5 z4/z7 sheet. The earlier top-level partial projects use different runs;
  their sheet differences are documented rather than treated as numerical passes.
- **Unresolved source:** `KG5_z7_Pb.trip` has KG5/z7 labels but SourceFileInfo names
  `B1609_F12_GA9683326 z3 Pb-56377.xls` (228 cycles, 32 functions), which is absent.
  Its internal statistics can be checked; its raw-reader parity cannot. There
  is no serialized evidence of combining the two available KG5 acquisitions.
- No production arithmetic/oxide correction fix was needed. The report separates
  stored original statistics, reconstructed accepted statistics and independent
  pasted spreadsheet references. Accepted statistics and block means are **not
  serialized** in these legacy files, and must not be claimed as stored oracles.

## Facts resolving SPEC §11 questions

- The 2025 BSU U `.xls` files **already contain** `238/235 oxide R18 0.00206`,
  `233/235 oxide R18 0.00206` and `238/233 oxide` in CYCLE/USER. They match the
  legacy/ET_Redux formula at 0.00206 and must pass through without another
  correction. Earlier uncertainty in SPEC/oxide research notes is now resolved
  for these files; those older notes describe the evidence available then.
- **Upstream input anomaly:** every U workbook's column named `270/267` exactly
  repeats the `270` intensity. Reconstructing the physical ratio as
  `270/265 × 265/267` reproduces the workbook's named corrected columns to
  round-off. Do not use that mislabeled column to infer a different oxide law.
- All 14 U projects also applied Tripoli's correction at **r18=0.0020** to the
  mislabeled raw input, producing inactive `OxideCor` functions. The active
  columns actually pasted into the sheet are the workbook's **0.00206** functions.
  Project-level `AmOxideCorrected` therefore does not identify the clipboard's
  oxide provenance. Per-function activity/settings matter.
- Rejection is encoded in the **sign** of Ratios (negative rejected, zero
  missing), not AcceptedFlags. Block selection changes those signs; independent
  block flags are not saved. U projects pad unfinished blocks with zeros.
- Of 145 active functions, 144 record **2σ** selection; KG5 z7 U `238/233 oxide`
  records manual selection. Masks differ per ratio. This establishes saved
  per-ratio practice, not the chronological hand edits or number of rule passes.
  New analyses still start without automatic rejection and use shared selection.
- Legacy 2σ is a single pass over currently accepted positive points. Its
  Chauvenet action repeatedly rejects the worst point and recalculates while
  n·erfc(z/√2) < threshold; the saved threshold is **0.5** throughout. This is
  distinct from Java's one-pass/minimum-20 implementation. The parity harness
  replays stored masks; it does not claim rule-regeneration parity.
- Across all 33 workbooks, TUNING records **Multiplier/Daly dead time 36.3 ns**,
  Multiplier gain **1.0**; CTRL has Apply Baselines, Correct for STDBL and Correct
  for BLKBL enabled. These are instrument settings/provenance, not evidence to
  apply another correction to the processed CYCLE values. Physical detector
  calibration and baseline quality are not validated by matching those values.
- No project records applied fractionation or BaPO2/Tl correction. Tracer and
  interference-use flags are false; alphaPb is zero. Capability flags can be
  true even when a correction was not applied.
- These acquisitions establish BSU's use of IonVantage `.xls` in April 2025;
  they do not establish which acquisition software BSU uses today.

## Existing Phase 1 implementation

- Contract `idtims-fractions/1`, fraction pairing, mapping and provenance exports.
- IonVantage `.xls` / IsoLinx `.TIMSDP`; arithmetic default, optional geometric
  mode; explicit preview/apply rules, undo/redo/session replay.
- UO2 legacy/ET_Redux default; labeled Java comparison formula; pass-through
  of instrument-corrected functions. Legacy clipboard formatting, cycles CSV.
- GUI import/review/corrections/export, shared masks, saved sessions and recovery.
  Existing compatibility and tests are retained by this work.

## Still open

- Obtain the workbook named inside `KG5_z7_Pb.trip`, or clarify its mislabeled
  sample identity. Do not substitute the similarly named KG5 runs for it.
- ET2535 provenance/reduction validation remains separate: one unavailable-source
  project's 202/205 function alone does not validate a real 2535 reduction.
- Raw `.raw` integrations, calibration and baseline fitting remain Phase 2;
  matching processed workbooks does not validate those operations.
- Historical hand-edit order cannot be recovered from final masks alone.
- App name, license, and any change to default automatic rejection still
  need Yiming's decisions.

# Phase 2 local implementation (2026-11-18)

Versioned immutable numerical parameters, raw four-sequence Pb/static-U decoding,
workbook approximation, undo/redo/replay and session-1 parameter extensions are
implemented. Contract clarification 9 carries canonical parameter JSON, SHA-256
and actual route; the copy in IDTIMS_UPbRPy is byte-identical. No notebook functions
changed. See [raw-reduction.md](raw-reduction.md) for API, supported structures,
anomalies and limits, and [recalculation-demo.md](recalculation-demo.md) for the
headless KD33 z1 demonstration, dates computed only in the separate age-engine venv,
rounding/solver controls, reproducibility and timings. CSV/settings JSON stay in
system scratch. [database-recalculation.md](database-recalculation.md) distinguishes
these local features from proposed UPbDB/UPb Lab storage, review and mirror sync.

Ordinary GUI export continues to enforce shared selection. The demo explicitly
preserves and labels legacy per-ratio masks through an audit-only opt-in. The GUI
can display reprocessed oxide provenance; no general reduction-parameter editor
was added in this engine phase. Parameter changes use the public engine API and
are serialized as history operations. Two-sequence Pb, incomplete Pb cycles and
unmatched cached rows remain explicit raw-route limits; see the supported-run
counts in the reduction note. No server or window was used.

Icon selected 2026-11-19: the v2c rhenium ribbon moved from IDTIMS_UPbRPy,
including its refined 16/32 px renders. Source commit and SHA-256 values are
in `icon-provenance.json`; `icon-small-sizes.png` preserves the size review.
The app name remains a working name. `scripts/make_icon.py` verifies curated
assets and exports the Windows ICO; Qt loads all seven PNG sizes.

Validation: `make test-quick` passed all 565 tests (including branding,
build/spec and user-guide coverage); Ruff passed on changed Python files.
No application bundle was built.
