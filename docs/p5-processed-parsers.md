# P5 processed-file parsers

P5 adds four exact content signatures to `rawtims.readers.open_run`:

| Reader | Signature | Committed coverage |
|---|---|---|
| ID-TIMS template CSV | `EARTHTIME ID-TIMS DATA IMPORT TEMPLATE FOR TRIPOLI`, first cell | OG template layout plus synthetic scalar cycles; the template contains no numeric oracle |
| Triton EXP | `Triton Analysis Data Report`, first line | 15 ETH/UCDavis input/cycle/full-report triples, including Pb, U, Nd, Sr and Cr |
| Nu TIMS individual answers | Ordered seven-field header beginning `Version number`, ending `Caption (1)` | Both Nu 1.1 Pb/U input/cycle/full-report triples |
| Neptune EXP | `Neptune Analysis Data Report`, first line | 17 Run-Block/tail input/cycle/full-report triples, including negative decimal tail functions |

All 103 additions are unmodified public CIRDLES Apache-2.0 files in
`tests/fixtures/tripoli/processed/`, with paths, pinned commits, hashes and byte
counts in [MANIFEST.toml](../tests/fixtures/MANIFEST.toml) and attribution in
[NOTICE](../tests/fixtures/tripoli/NOTICE). No private lab fixtures are used.
Existing committed fixture dispatch signatures/reasons are pinned by
[test_p5_routing.py](../tests/test_p5_routing.py). The existing raw-folder/project
routing tests continue to apply unchanged.

## Native interpretation and comparison boundaries

Native imports retain source function names, duplicate-name identities, equation
captions, header/footer facts, original times and individual cell tokens. Numeric
D payloads remain visible but invalid. X rejections remain metadata until the user
acts; opening a run does not apply them. Blank and `Invalid Norm` values are
missing. Nonpositive ratio values stay invalid, while negative intensity/function
values remain available. Units are assigned only when explicit in a caption;
unknown physical units are not inferred from collector names.

Triton ETH dates follow the snapshot's day-first order; AM/PM UCDavis/Neptune
reports use month-first. Naive dates and original strings are retained. Numeric
vendor seconds remain unchanged. UCDavis `hh:mm:ss:fff` becomes clock seconds;
Nu has unavailable native time. Triton files without a declared block size use
the Java fallback of ten cycles, explicitly marked in metadata/Run info. Neptune
report rows form one review block. Nu uses its declared measurements per block.
Empty Triton planned-cycle placeholders are retained as unmeasured cycle labels,
not fabricated measured rows. This scope does not define raw acquisition blocks.

The template follows C# row-based blocks, zero as single-block setting, maximum
measured block size, final-block zero padding and nonpositive-to-zero behavior.
Original cycle labels and padding count are retained. It rejects malformed widths
rather than shifting numeric cells into neighboring columns. Blank fields remain
missing; malformed inputs are not evidence for reproducing C# exception/swallowing
behavior. Dates support numeric or English abbreviated months. Empty layout
imports fail with a specific request to add cycle data. The declared Fraction
field supplies the proposed fraction ID.

`tripoli_comparison_arrays(run)` is an explicit Python comparison view. It never
replaces native Run/Analysis arrays or masks. It reproduces Java 00dc941 X/D
stripping, blank Neptune/`Invalid Norm` zero conversion, Nu time 1.0, Triton
colon-stripped time, and nonpositive log-ratio masks. Java's dropped degree symbol
is recorded as `Function.metadata['tripoli_name']`; the native name retains it.
The pinned Java regex classification is recorded separately as `tripoli_ratio`.

[test_processed_readers.py](../tests/test_processed_readers.py) compares every
cycle, time, function and mask in all 34 cycle reports, including Nu U's derived
oxide columns, before checking every full-report mean, SE and SD. Tests explicitly
select Java geometric ratios and the already-existing Java oxide law. Java's
singleton zero dispersion is checked separately; native statistics keep their
existing NaN dispersion for one observation. Native arithmetic defaults, invalid
value rules, shared selection and legacy oxide law are unchanged. Synthetic tests
cover flags/missing cells, negative tails, units, clocks, malformed input,
template padding and independent UI review. Pb/U native sessions re-read/replay
these sources without changing arrays or masks.

## Review and export scope

Pb/U runs use the existing workspace, correction/mapping validation and native
session saving. Cr, Sr and Nd runs open independent review windows with existing
plots/table, per-function manual/vendor-X edits, Undo and statistics choices.
These windows are temporary; cycle CSV retains the reviewed values/masks. They
are not persisted in a fraction session. Both themes fit 1280×800 and 1440×900
with synthetic acceptance tests in
[test_p5_processed_ui.py](../tests/test_p5_processed_ui.py).

No new Pb/U contract mapping is invented for other isotope systems. Cycle CSV
is available independently. `/1` remains the existing measured-ratio contract;
each Pb/U run must still have a valid mapping. Vendor equation captions are
retained results, not expressions silently re-evaluated during import. No raw
acquisition reduction, fractionation, interference or physical unit conversion
is introduced here.

F69/F71/F74/F75 are done for these supported processed dialects. Umbrella F29
remains partial. F70 Sector54, F72 MAT261/262, F73 legacy Nu Plasma and F76
Element2 remain **specimen-gated (D12)**: no input/expected-output pair was found
in the supplied clones. No parser was added for those formats. D12's earlier
priority question is superseded for this increment by Yiming's instruction to
build all oracle-backed parsers; future versions need their own public or
synthetic validation specimens and expected answers.
