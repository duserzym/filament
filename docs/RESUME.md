# Resume note (paused 2026-11-14 on Yiming's "pause all")

## Committed (main, local only, no remote)
- Spec and decisions: `docs/SPEC.md` (§0 review decisions, §11 unvalidated list).
- Contract `idtims-fractions/1` with clarifications 1-6: `docs/contract-idtims-fractions-v1.md`, byte-identical
  with IDTIMS_UPbRPy `app` adc17c3 (sha256 a630843f…).
- Phase 1 steps 1-6:
  - skeleton and packaging;
  - readers for IonVantage `.xls` and IsoLinx `.TIMSDP`;
  - engine: statistics, rules, oxide correction, history;
  - contract writer and reader, mapping, exports;
  - GUI A: import, plots, table, hand rejection;
  - GUI B: rules with preview, corrections, export, `--verify`, frozen smoke test.
  Last full suite before the pause: 291 passed. The frozen build passed its smoke test at step 6.
- Oxide documentation: `docs/oxide-correction.md`. It covers the mechanism, the Java vs derived form, real-file
  gaps, and the facts on legacy C# Tripoli (Yiming's numbers come from it: two-space `(Mean, %StdErr)` clipboard,
  E7 values, arithmetic statistics). Last commit 3628bd3.

## Half-done (uncommitted, in the working tree; do not discard)
- **Step 7, session save/restore**, by a subagent stopped at the pause.
  - New: `src/rawtims/session.py`, `src/rawtims_gui/recovery.py`, `tests/test_session.py` (11 engine tests,
    passing per the subagent; tidy `test_a_same_named_file_next_to_the_session_is_found`).
  - Modified: `src/rawtims/readers/__init__.py`, `src/rawtims_gui/{main,workspace,export_panel}.py`,
    `tests/{conftest,test_gui_step_b,test_review_window}.py`.
  - Not yet audited or tested as a whole. One GUI test run hung while these edits were in progress (probably a
    modal prompt).
  - Missing: GUI session tests (recent files, prompt, export session columns, `--open`, recovery) and a
    screenshot.
  - Next: read the diff, run `make test` with a per-test timeout, finish round-trip, problems, recent files and
    the unsaved-changes prompt, then commit.

## Not started
- **Legacy-Tripoli oxide confirmation** (asked 2026-11-14, after Yiming said BSU uses the older Windows Tripoli):
  - Quote from OGTripoli `source/TripoliWorkProduct.cs` `PerformOxideCorrectionFor233_235Tracer`
    (lines ~2495-2733) exactly what it computes and how R18 enters (`_r18O_16O`, from
    `USampleComponents.DefaultR18O_16O`, set in `forms/frmOxideCorrection.cs`).
  - From the reading so far: the corrected 233/235 = 1/(1/R265_267 − 2·R18) and the corrected
    238/235 = (R270_267/R265_267)/(1/R265_267 − 2·R18). Algebraically both are the same as `isobar_233_18O`.
  - Still to do:
    - confirm this with a numeric test;
    - find where "0.00206" in the function name comes from (no legacy code builds "oxide R18"; check legacy
      user-function / sample-components naming and ask Yiming);
    - then update docs and naming ("matches legacy Tripoli and ET_Redux");
    - make legacy behaviour the reference where the two Tripolis differ: arithmetic statistics default?
      clipboard E7 values? default rejection? Report the numbers before changing defaults;
    - tell the reduction session.
- **Mechanism note:** largely done in `docs/oxide-correction.md`. Still to add: the legacy line quotes.
- **Step 8:** fit checks, the 1280×800 screenshots for Yiming, the full suite, the packaged build and smoke
  test, and cleaning the build leftovers.
- **Reduction session:** asked to reword its `instrument` note after Yiming's retraction. Check that it did.
