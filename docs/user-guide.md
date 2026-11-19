# User guide

Use filament to review measured cycles, then send ratios to your age reduction app.
Dates are calculated in IDTIMS_UPbRPy. The name and icon are placeholders.

## Open a run

Choose **File → Open Files…** for an IonVantage `.xls`, IsoLinx `.TIMSDP`, or legacy
`.trip` project. You can drag files into the window. Choose **Open Folder…** for an
acquisition folder or a `.raw` directory; the app finds its cached workbook.
A `.raw` directory needs that workbook to open.

Choose a fraction and **Pb** or **U** in the top picker. Opening a new run does not
reject cycles. A `.trip` restores its saved, per-ratio rejections as undoable edits.
If its source is missing, use **Locate…** and choose the named workbook. Do not
substitute a similarly named acquisition.

![Open a run or folder](guide/open-run.png)

## Review the plots

Choose **Ratios**, **Intensities**, or **Table** in the top bar. Use **Functions** to
choose what you plot. Each plot shows its mean, 1σ % SE, accepted count and block
MSWD. Filled points are used; hollow red points are excluded; crosses are invalid.
The line is the mean, and the bands show SE, 1σ and 2σ.

Use **ln** for a plot's log scale, **↕** to fit its vertical range, and **⤢** to
maximise it. Drag the inspector splitter to resize it. **Focus** (⌘⇧F) folds the
inspector; click it again to restore it. Use the left menu to unfold fractions.

![Plot-first review wall](guide/review-wall.png)

## Reject cycles

Click a point or drag a box to toggle cycles. Use ⌘-click or ⇧-drag to select
without toggling; Delete rejects the selection. Click a numbered block in the
strip below a plot to toggle that block; drag across the strip for several blocks.
The mapped ratios share a selection so their correlations remain meaningful.
**Undo** restores your previous selection; **Redo** reapplies it.

![Cycle rejection](guide/reject-cycles.png)

## Read block statistics

Choose **Stats** in the inspector. Select a function under **Blocks of** to see its
block means, SE, % SE and accepted counts. Double-click a row to toggle its block.
The weighted block mean and **MSWD of block means** are diagnostics. The fraction
export continues to use the cycle mean, even when you inspect block statistics.

## Check acquisition information

Choose **Run info** in the top bar, or **Corrections → Run info**. Read the method,
source, acquisition settings and current route before changing parameters.

![Run information](guide/run-info.png)

## Check warnings

Select the U run and read **Run info**. A warning can describe the mislabeled U
`270/267` intensity column, a duplicated terminal workbook row, or an unavailable
raw method. Warnings also travel into export provenance. A successful workbook
comparison does not validate the physical detector calibration.

![U run warnings](guide/run-warnings.png)

## Preview a 2σ rule

Choose **Rules → Legacy 2σ (one pass)**. Choose **Whole run** or **Per block**, then
**Group union** for shared rejection. Press **Preview**. Amber points mark the
proposal; the accepted cycles have not changed. **Discard** removes the preview.

Legacy 2σ compares currently accepted positive values with their arithmetic mean
and SD once. It differs from the separate iterative k-σ option.

![Legacy 2 sigma preview](guide/rules-2sigma.png)

## Apply Chauvenet rejection

Choose **Legacy Chauvenet (repeated)**, set P (normally 0.5), then **Preview**.
Inspect the proposed exclusions and press **Apply** to record exactly that proposal.
Use **Undo** to reverse it. This rule removes the worst point and recalculates
repeatedly; **Java Chauvenet (one pass)** is a different option, with a minimum count.

Leave **Per-ratio masks (legacy)** off for shared export. If a restored `.trip` has
different masks, **Use the union of rejections** adopts shared cycles and changes
the means. You can undo it. Ordinary contract and review-table exports require it.

![Chauvenet preview](guide/rules-chauvenet.png)

![Applied rule and history](guide/rules-applied.png)

## Change reduction parameters

Choose **Corrections → Reduction**. Expand **Edit parameters (staged)**. Select
**Raw acquisitions** only when the panel reports verified raw/workbook correspondence.
Otherwise read the reason and use the labeled workbook approximation where supported.

Edit dead time, gain, baseline, beam interpolation, acquisition rejection or oxide
settings, then press **Apply**. Editing fields alone does not change the result.
Scroll to read the parameter and ratio diff. Collapse the editor to give the diff
more room. **Discard** drops staged edits; **Reset** stages the acquired settings
for another Apply. Undo/Redo restores calculated values and parameters together.

![Reduction parameters](guide/reduction-parameters.png)

## Save your session

Choose **File → Save Session…** (⌘S) before export. The session records selection,
mapping, parameters and history, and checks source hashes when reopened. Keep your
source files available. An unchanged saved session adds its link to the contract;
unsaved edits leave that link empty. **Save session first** saves both in sequence.

## Export ratios and review tables

Choose **Export**. Resolve every listed problem, confirm the fraction ID, spike,
weights, collector and time zone, and check the preview. Scroll inside the panel
for metadata fields. Choose **Save contract CSV…** for `idtims-fractions/1`,
**Save review XLSX…** for Fractions/Cycles/Provenance sheets, or **Save review CSV
tables…** for the same tables as files. **Save cycles CSV…** writes the current run
with inclusion flags. **Copy Tripoli clipboard** uses the legacy eight-significant-
digit format unless you choose full precision.

![Export controls](guide/export-send.png)

## Send to IDTIMS_UPbRPy

Choose **Send to IDTIMS_UPbRPy…** and a destination folder. The app saves a contract
CSV and opens the age app when it finds it. If it cannot, it reveals the saved file
so you can open it yourself. To choose a specific command, scroll to **IDTIMS_UPbRPy
command (optional)**. It runs without a shell and receives `--open PATH`.

![Optional age app command](guide/send-command.png)

## Walkthrough: open KD33 z1

Choose **Help → Walkthrough: change the dead time**. If unavailable, choose
**Help → Choose walkthrough examples folder…** and point to the read-only Boise
examples. Step 1 opens KD33 z1 Pb and U with the exact legacy per-ratio masks.
Keep those masks while comparing the reference numbers below.

![Walkthrough step 1](guide/walkthrough-1.png)

## Walkthrough: stage 36.3 → 40 ns

Press **Next**. In **Corrections → Reduction**, select **Raw acquisitions** and
change **Pb Daly dead time (ns)** from **36.3** to **40**. Leave U as acquired.
Press **Apply**, then **Next**.

![Walkthrough step 2](guide/walkthrough-2.png)

## Walkthrough: compare the changes

Collapse **Edit parameters (staged)** and read the diff. Undo and Redo to compare.
The GUI compares the acquired workbook with raw reprocessing at 40 ns. With the
legacy masks, the means are:

| Pb ratio | Acquired workbook, 36.3 ns | Raw, 40 ns |
|---|---:|---:|
| 206/204 | 9506.74273898 | 9522.91320034 |
| 206/207 | 16.8481791298 | 16.8753245427 |
| 206/205 | 1.85288460605 | 1.85434498117 |
| 207/205 | 0.109977609179 | 0.109887251956 |
| 204/205 | 0.000194922464478 | 0.000194743834362 |
| 208/205 | 0.331843285849 | 0.332104897448 |

The raw-to-raw mean changes are about +0.17010%, +0.16112%, +0.07882%, −0.08216%,
−0.09165% and +0.07883%, respectively. U means and % SE stay identical.

![Walkthrough step 3: parameter and ratio diff](guide/walkthrough-3.png)

## Walkthrough: compare reference dates

Read these dates from the separate age engine, with the same legacy masks and
fixed tracer/blank/fractionation/Th-correction settings. They are reference results,
not live dates calculated by this viewer.

| Date (Ma) | Acquired workbook, 36.3 ns | Raw, 40 ns | Change (Ma) |
|---|---:|---:|---:|
| 206/238 | 545.723740 | 546.137511 | +0.413772 |
| 207/235 | 545.751695 | 545.409137 | −0.342557 |
| 207/206 | 545.868422 | 542.366971 | −3.501450 |

See [the recalculation demonstration](recalculation-demo.md) for 2σ uncertainties,
raw 36.3 ns controls, settings, route differences and reproducibility.

## Walkthrough: adopt shared cycles

Press **Next** for step 4, then **Use shared cycles for export**. This takes the
union of rejections in Pb and U. It changes the means and dates from the reference
tables above; do not treat those legacy-mask dates as your shared-cycle result.
Check the Export preview, save the session and export CSV or XLSX.

![Walkthrough step 4](guide/walkthrough-4.png)

## Walkthrough: hand off the result

Press **Next** for step 5 and choose **Send to IDTIMS_UPbRPy…** when ready.
Calculate dates there using your intended reduction settings. Starting or capturing
the walkthrough never launches the age app automatically.

![Walkthrough step 5](guide/walkthrough-5.png)

## Recreate these screenshots

Run `env -u PYTHONPATH .venv/bin/python scripts/capture_guide.py` in the checkout.
The script forces Qt offscreen, uses isolated settings, and writes 1440×900 PNGs
under `docs/guide/` (each at most 250 KB). It reads Drive inputs without writing
there. Without the examples it uses public fixtures and skips walkthrough shots;
those image links then have no local image. `--fixtures-only --output /tmp/guide`
checks that fallback without replacing this guide's KD33 screenshots.

For remaining differences from Tripoli, read [the feature gap list](tripoli-gap.md).
