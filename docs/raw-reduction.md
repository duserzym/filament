# Versioned acquisition reduction

`ReductionParameters.as_acquired(path_or_run)` captures TUNING/CTRL and accompanying
`_AcqParams.000`/`.ipf` inputs. `dataclasses.replace(params, route="raw",
daly_dead_time_ns=40)` creates a new immutable record. `reprocess(source, params)`
returns a new Run with the workbook's cycle keys, function keys and row count.
`Analysis.set_reduction_parameters(params)` applies this as an undoable/replayable
operation. Sessions keep schema-1 initial/current records plus source hashes, using
the existing session format 1; older sessions keep their cached workbook numbers.

Canonical parameter JSON uses sorted keys, compact separators, UTF-8 and Python's
shortest roundtrip finite floats; SHA-256 identifies the exact record, including route.
Missing calibration values remain null/absent. Source TUNING/acquisition disagreements
are errors. The conversion constants are explicit, recovered vendor conventions:
ADC zero 8388608, V/code 1.192092896e-6, electron charge 1.6021892e-19 C.

## Validated format subset

The four-sequence method `Pb 205 Daly 150 ratios wo 208` and static Faraday U with
269.5/270.5 baselines and 270 peak are recognized from `.ief` and checked against
scan masses. Only 1000 ms integrations are supported. Unknown methods, incomplete
integrations, malformed DAT/IDX/STS and unsupported status types raise
`UnsupportedFile` with the method name. `reprocess_with_fallback` explicitly retries
workbook reduction and records the error/actual route; raw-only controls still fail.
A workbook accompanies the raw folder to establish the existing function/row keys.
No general MassLynx or two-sequence Pb decoder is claimed. Short terminal U
integrations use the scans actually acquired and produce an explicit warning;
unfinished baseline-only tails are ignored with a warning. A Pb cycle missing
one or more sequences cannot supply all ratios. Such tails, and workbooks with
an extra row but no corresponding peak acquisition, refuse raw reprocessing.
Of the 33 example runs, 27 currently have safe raw/workbook row correspondence;
two use the undecoded two-sequence method, two have incomplete terminal Pb
cycles and two U workbooks have an extra row without a peak acquisition. Their
acquired workbook values remain readable. Unknown workbook function formulas
also refuse changed-parameter recalculation instead of leaving stale columns.

DAT has 32 float32 (value,time) pairs per scan (256 bytes). IDX has 22-byte records,
with DAT offsets at byte 0, point-count/flags at 4 and time in minutes at 12. The
verified STS header has a 32-byte prefix and 126 × 48-byte descriptors; each descriptor
starts with uint16 ID, type and record offset, then its name. Records are 618 bytes;
Set Mass is float32 at 38, Event Type and Acquisition Type are uint16 at 58/60.
This subset verifies the Set Mass descriptor, dimensions and event/acquisition types.
Collector channels come from `_AcqParams.000`, not hardcoded ADC identities.

Pb corrects individual Daly scans non-paralysably, converts Faradays to cps, rejects
all >sigma sample-SD points per pass while prior loss is below max_percent, averages,
OLS-interpolates every beam over three histories to a common midpoint, subtracts the
mean of the two 30-scan half-mass baselines, then rebuilds all functions. A rejection
pass can exceed the configured percent. Pb always consumes the first two histories
before emitting rows, including when BI is disabled or shortened to two histories,
so row IDs/masks remain stable. Static U converts Faradays to V and uses ten scans
per cycle with no BI. Acquisition count is inferred from masses, not scan-group IDs.

Baseline `as_acquired` follows the file's apply-baselines flag; `measured` explicitly
requests the same measured half-mass baseline procedure; `offset` additionally
subtracts specified collector offsets in output units (Pb cps, U V). The raw route
requires the measured baseline acquisitions for every mode. Tau Time/Gain and HT
Scaling response models have not been decoded; this implementation does not expose
unverified controls for them.

The unchanged workbook route returns cached values bit-identically. Changes in
baseline measurement, BI, integration rejection or conversion require raw data.
Workbook gain changes rescale intensity columns and rebuild functions. Dead-time
changes use `(I+B)/(1-(I+B)*delta_tau)-B`, with measured block baselines when available;
without raw data the route records that the full baseline history is unavailable
and uses B=0. This is explicitly a cycle-level approximation, not raw reduction.

## Anomalies and limits

U `270/267` repeats mass-270 intensity in these workbooks. Readers flag the alias;
the physical oxide path uses intensities or `270/265 × 265/267`. Reprocessing a changed
r18 rebuilds corrected columns from intensities, updates their metadata and retains
their original keys for masks. The run's parameter record is authoritative if the
legacy display name contains an older r18. Unchanged cached oxide values still pass
through exactly. Duplicated terminal timestamps are warnings. Raw U emits the actual
last acquisition while preserving row count; it intentionally differs from the cached
terminal duplicate.

The read-only investigation on KD33 z1/z2 established maximum per-cycle relative
bounds of 3e-6 for Pb functions (sub-ms common-time residual) and 1e-10 for U, excluding
the cached duplicate terminal row. Constants in the decoder state these bounds.
For 36.3→40 ns, workbook intrinsic approximation error was ≤0.174 ppm/cycle on those
two runs. These are evidence-specific tolerances, not guarantees for all methods or
beam strengths. See `recalculation-demo.md` for measured aggregate comparisons and
scratch-only hand-off reproduction.

## Two-sequence Pb investigation (desktop G1)

The method `Pb Fara-Daly_2 sequence_200 ratios` is still unavailable for raw
reduction. A read-only probe of `B1607_F18_KG5 z1 Pb-56242.xls` (250 cycles,
10 × 25; 5600 scans) and `B1608_F12_KG5 z7 Pb_2-56314.xls` (150 cycles,
6 × 25; 3360 scans) recovered the two 30-scan half-mass baselines at 203.5
and 204.5, followed by ten 1-second integrations at each of masses 204 and
205. STS uses the same 618-byte records. Unlike the four-sequence method,
the output row counts match without discarding two interpolation histories.
Both workbooks have beam interpolation disabled.

The observed collector assignment is S1: 204 Multiplier, 205 High1,
206 High2, 207 High3, 208 High4; S2: 205 Multiplier, 206 High1,
207 High2, 208 High3. The workbook intensities are in V (including the Daly),
with 10^12-ohm resistors. Applying the validated four-sequence acquisition
rejection/dead-time/baseline recipe and converting its cps to V recovered
row counts but left maximum per-cycle intensity residuals of approximately
0.637% and 2.347% respectively. This fails the 3 ppm acceptance criterion;
the two-sequence averaging/correction history has not been recovered. The
exploratory recipe is deliberately not enabled in the production decoder.
Direct Faraday ratio reconstruction also fails: for example, maximum per-cycle
206/207 S2 errors are 2833 ppm (z1) and 451 ppm (z7); 206/208 S2 errors are
1116 ppm and 114 ppm. Thus the discrepancy is not merely a common intensity
scale that cancels in the exported ratios.
The desktop displays the method, this validation limit and the workbook route.

## Desktop reduction controls

Corrections contains Mapping, Reduction and Run info pages. Reduction stages
edits until Apply; a thread-pool worker computes a new Run, then validates the
source, row/function identities and unchanged analysis before installing it.
Cancel or an intervening edit discards the result. Undo/redo caches both Runs,
checks source hashes, and restores the parameter/ratio diff. Sessions preserve
the diff with the operation. Reset stages the acquisition record.

The panel exposes Daly dead time and acquisition multiplier, per-collector
Faraday gains (apply/unity), baseline mode/offsets, interpolation, acquisition
rejection, U r18 and route. Raw availability is checked off-thread. The verified
Faraday/Daly cross-calibration is measured per cycle from the 206 beams; alternate
Tau Time/Gain/HT response modes remain unavailable, rather than unverified
numerical controls. Fractionation and spike calibration remain in the age app.
