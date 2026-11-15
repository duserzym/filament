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

## Step 7 complete (uncommitted, 2026-11-14; supervising audit pending)
- Session save/restore is implemented in `src/rawtims/session.py` and the GUI. Atomic JSON saves keep raw
  paths/hashes, settings, history (including redo), fraction fields and mappings, without raw values or results. Loading
  resolves relative, absolute, then adjacent paths; a changed first-resolved file is reported rather than
  bypassed. Unrestorable runs stay out of exports and retain their records for subsequent saves.
- File actions, content routing (Open, drop, `--open`), title/dirty state, injected unsaved prompts, recent
  sessions (eight, missing paths pruned), saved-session export provenance and cache recovery are complete.
- `tests/test_gui_session.py` covers the B998/KU GHR1 round trip, prompts, recent sessions, export linkage,
  content routing, CLI and recovery. GUI tests reject unexpected dialogs and have a 45-second deadline on
  platforms supporting SIGALRM. `tests/test_session.py` also covers atomic failure and path precedence.
- `make test`: 340 passed, 14.9 s wall time; `make test-quick`: 340 passed, 10.0 s. Both test targets support the cache override through
  `RAWTIMS_CACHE_DIR`; validation used repository-local temporary/cache folders under `.venv/step7`.
- Screenshot: `session_export_light_1280x800.png` in the requested screenshot folder's `step7/`, rendered
  offscreen with `export_window` after loading a saved session; Export shows the filename and hash.
- No commit or packaging build was made. Step 8 and the legacy-Tripoli follow-up below remain separate.

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
