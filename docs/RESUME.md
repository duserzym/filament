# Status note (2026-11-14, end of Phase 1)

Local repository only. No remote, no tags. Working name `filament`, set in `src/rawtims/branding.py` until
Yiming chooses a name.

## Done (all committed; full suite 389 passed; frozen build and smoke test passed at 8aa1094)
- **Contract:** `idtims-fractions/1` with clarifications 1-7, byte-identical with IDTIMS_UPbRPy `app` 9511c9a
  (sha256 470308b8…).
- **Readers:** IonVantage `.xls` and IsoLinx `.TIMSDP`. Per-cycle values equal Tripoli's own cycle reports.
- **Engine:**
  - statistics: arithmetic as the default (legacy C# Tripoli), geometric as an option (Java Tripoli, whose
    reports filament reproduces to ≤ 2e-12);
  - Chauvenet and k-σ, as previews followed by an explicit apply, with history, undo, redo and replay;
  - UO2 oxide correction, `isobar_233_18O` by default. It is identical to legacy Tripoli and ET_Redux
    (`tests/test_oxide_legacy.py`). The Java Tripoli form is a labelled comparison option. Files that already
    carry oxide-corrected columns are passed through, never corrected twice.
- **Exports:** the contract CSV with provenance, `U Oxide Formula` and `Pb/U Mean Statistic`; the legacy
  Tripoli clipboard (two spaces, CRLF, C# E7); cycles CSV; headless `--verify`.
- **GUI:**
  - import and fraction pairing;
  - plot wall with the y-range fitted to accepted cycles and pinned outlier markers;
  - cycle table, hand rejection with SYNCH;
  - Rules, Corrections (project statistics switch, r18, formula, mapping) and Export tabs;
  - session save and restore with recovery copies.
  It fits 1024×640 to 1440×900.

## Waiting for Yiming
- BSU raw files (see `docs/SPEC.md` §9 and `docs/oxide-correction.md`, "What settles it").
- Answers: rejection practice, app name and icon, licence.

## Not validated against real BSU data
- BSU U runs: where the `238/235 oxide R18 0.00206` columns come from, and their formula.
- ET2535 Pb with 202/205.
- filament against the numbers in the Grenville spreadsheets.
- Yiming's rejection habits.
