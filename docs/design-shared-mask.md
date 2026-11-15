# Design: one shared cycle mask for correlated ratios (proposed 2026-11-14, awaiting confirmation)

Yiming's requirement, in their words: "the new tripoli equivalent needs to implement auto correlated data
block selection particularly related to 205 Pb because if not synchronously selected the data error
correlation would be odd. the old tripoly does not force that but we should".

## 1. Rule

**All contract-mapped ratios of a run share one accepted-cycle mask.** The app enforces this; it is not a
setting the user can switch off.

- **Pb run, the correlated group:** the functions mapped to 206/204, 206/207, 206/205, 207/205, 204/205,
  208/205 and 202/205. They share 205 (the spike) or a numerator with another exported ratio.
- **U run, the correlated group:** the mapped 238/235, 233/235 and 238/233, together with the inputs of
  filament's oxide correction (270/267, 265/267, or 267/265 and 270/265 in Purdue-style files) and the derived
  `oc` functions. All of them share the 267 beam (235U16O2 plus the 233U16O18O isobar).
- **Free functions, outside the group:** intensities (`204 D`, `i265`, `Tl205 S2 int` …), diagnostics such as
  `Daly/Faraday Gain`, raw duplicates (`… raw`), unmapped Faraday equivalents, and any ratio not mapped to the
  contract. For these alone, SYNCH keeps its present meaning.
- **When the mapping changes,** the newly mapped function joins the group and adopts the group mask. This is
  one undoable history entry. The function that left the group keeps the mask it had and becomes free.
- **Pb and U runs of a fraction are independent:** they are separate acquisitions with no common cycles, so
  each has its own group mask.

## 2. Behaviour

- **By hand:** rejecting or restoring a cycle, a box of cycles or a block in any group ratio applies to the
  whole group at once. This is one history entry, so undo and redo move the whole group.
- **By rule:** the Rules tab offers two ways to evaluate Chauvenet or k-σ.
  - Default: evaluate on every group ratio and reject the union.
  - Option: evaluate on one chosen ratio.
  In both cases the preview states that the flagged cycles will be removed from **all** group ratios, lists
  which ratio flagged which cycle, and highlights them in every group plot. Apply rejects them group-wide.
  Rules on free functions behave as today.
- **SYNCH:** for group ratios the toggle shows as locked on, with the tooltip "Correlated ratios share one
  cycle selection: their errors are correlated through 205Pb (Pb) or the 267 beam (U)." It stays active for
  free functions.
- **Engine:**
  - `Analysis` gets `group_keys`, derived from the mapping and the oxide inputs.
  - Every operation that touches a group key is expanded to all group keys before it is recorded, so replay
    reproduces the same mask exactly.
  - An invariant check, `group_consistent()`, runs in the tests and before every export.

## 3. Old sessions, imports and the legacy comparison

- **Opening a session saved before this change** whose group ratios have different masks:
  - a non-modal notice lists, per ratio, the cycles excluded in some group ratios but not in others;
  - one button, "Use the union of rejections", applies the union as a single history entry, and only when
    Yiming clicks it;
  - until then the run is marked "per-ratio selection (legacy)", and its contract export is blocked with that
    reason. Nothing changes silently.
- **Legacy Tripoli comparison view** (labelled, never exported to the contract):
  - It reproduces legacy Tripoli's per-ratio numbers: arithmetic statistics, per-ratio masks.
  - Its per-ratio rejections come from the run's own legacy masks (old sessions), from a per-ratio rule
    evaluation, or from hand edits made inside the view.
  - It shows the legacy clipboard block for side-by-side checks against Yiming's old spreadsheets.
  - It lives in the Export tab as "Compare with legacy Tripoli (per-ratio)"; "Copy legacy clipboard" there is
    marked "comparison only".

## 4. Evidence: what goes wrong without it

The reduction app checks the linked identities. For example 207/205 = (206/205)/(206/207) implies
ρ(206/205, 206/207) = (s65² + s67² − s75²)/(2·s65·s67) from the exported % SEs. That implied value must match
the ρ measured from shared cycles.

The table below shows Chauvenet (P = 0.5, n ≥ 20) on real runs, first per ratio as legacy Tripoli does it, then
with one shared mask. The numbers come from `rawtims`, arithmetic statistics; the script is
`corr_evidence.py` in the supervisor's scratchpad.

| run | selection | n used per ratio | ρ(206/205, 206/207) from shared cycles | ρ implied by the exported % SEs |
|---|---|---|---|---|
| KU GHR1 F08b (TIMSDP) | per ratio | 99 / 98 / 97 / 97 / 99 / 97 | 0.0426 | **0.1117** |
| | shared mask | 97 for all | 0.0426 | 0.0475 |
| KU GHR1 2020 (IonVantage) | per ratio | 87 / 86 / 87 / 87 / 87 / 87 | 0.1468 | **0.0854** |
| | shared mask | 85 for all | 0.1543 | 0.1524 |
| Purdue WH233B z3 | per ratio | 20 / 19 / 20 / 20 / 20 / 20 | 0.1836 | **0.0229** |
| | shared mask | 19 for all | 0.1836 | 0.1927 |
| BSU B998 | per ratio | 94 for all (208/205 drops cycle 22 instead of 23) | 0.4476 | 0.4458 |
| | shared mask | 93 for all | 0.4468 | 0.4452 |

- With per-ratio selection the means and errors rest on different cycles. The correlation implied by the
  exported errors then disagrees with the measured one: by a factor 2.6 (KU F08b), by about half (KU 2020),
  and by a factor 8 (Purdue).
- Error propagation in the reduction would therefore use an inconsistent covariance, and in worse cases the
  reduction app's quality check rejects the fraction (implied |ρ| > 1).
- With one shared mask the two agree to within the expected scatter. The small remaining difference comes
  from the instrument computing each function from its own sequence integrations.
- Other correlations change too. ρ(206/205, 207/205) on Purdue goes from 0.660 (intersection of mismatched
  masks) to 0.693, and ρ(206/205, 204/205) from 0.539 to 0.594.

## 5. Contract

The export already writes `rho A|B` from shared accepted cycles and `Cycles Used` as the intersection, which
with a shared mask equals each ratio's n. Proposal for the reduction session: new optional provenance columns
`Pb Cycle Selection` and `U Cycle Selection`, values `shared` (one mask for all exported ratios of the run,
enforced) or `per_ratio`. filament always writes `shared`. Missing is read as unknown, which covers legacy
files and the current MA1 layout. The addition is optional, so the version stays /1.

## 6. Build plan (after confirmation)

Codex builds it and the supervisor audits.

1. Engine: `group_keys`, op expansion, invariant check, mapping-change adoption.
2. Rules: union evaluation and the preview text.
3. GUI: the locked SYNCH and the group-wide hand and block edits.
4. Session migration notice, the union button and the export block.
5. The legacy comparison view.
6. The contract columns, after the reduction session agrees.

Tests cover the hand, block and rule paths, undo/redo, replay, mapping change, session migration, the
comparison view reproducing per-ratio numbers, and the export block. Quick check per commit, full check at the
end, then re-shoot 01_review.
