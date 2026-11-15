# Why one cycle selection?

All ratios mapped for export from one run use the same accepted cycles.

Pb ratios share the 205Pb spike signal, or share another isotope with a ratio
that uses it. U ratios and their oxide correction share the mass 267 beam.
Their measurement errors therefore move together. Keeping different cycles for
each ratio can make the exported errors disagree with the measured correlations.
A shared selection keeps those errors and correlations on the same footing.
Pb and U are separate runs and keep separate selections.

Clicking, dragging a box, rejecting a block, or applying a rule updates the whole
group. SYNCH is locked for this group. It remains available for other functions.
Rules always show a preview first. The default evaluates every group ratio and
rejects any cycle flagged by at least one. You can also evaluate one chosen ratio;
its flagged cycles still leave the whole group. Undo brings the selection back.

## Evidence from real measurements

Chauvenet selection, P = 0.5 and at least 20 cycles; arithmetic statistics.
The two correlation columns compare 206/205 with 206/207. They should agree:
one is measured from common cycles, the other is inferred from exported errors.

| Run | Selection | Cycles used per ratio | Measured correlation | Correlation implied by errors |
|---|---|---|---|---|
| KU GHR1 F08b (TIMSDP) | Per ratio | 99 / 98 / 97 / 97 / 99 / 97 | 0.0426 | 0.1117 |
| | Shared | 97 for all | 0.0426 | 0.0475 |
| KU GHR1 2020 (IonVantage) | Per ratio | 87 / 86 / 87 / 87 / 87 / 87 | 0.1468 | 0.0854 |
| | Shared | 85 for all | 0.1543 | 0.1524 |
| Purdue WH233B z3 | Per ratio | 20 / 19 / 20 / 20 / 20 / 20 | 0.1836 | 0.0229 |
| | Shared | 19 for all | 0.1836 | 0.1927 |
| BSU B998 | Per ratio | 94 for all; 208/205 drops cycle 22 instead of 23 | 0.4476 | 0.4458 |
| | Shared | 93 for all | 0.4468 | 0.4452 |

Shared cycles bring the two correlations into agreement within the expected
scatter. Small differences remain because the instrument computes each ratio
from its own sequence of integrations.

Old sessions keep their original selections until you choose **Use the union
of rejections**. The Export tab's **Compare with legacy Tripoli (per-ratio)**
view keeps the old arithmetic numbers available for comparison. Those comparison
numbers never enter the contract export.
