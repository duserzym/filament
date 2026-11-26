# Fractionation preview: scope and evidence

D1 selects **opt-in preview**, with IDTIMS_UPbRPy authoritative for final
fractionation, tracer stripping and ages. `idtims-fractions/1`, Analysis values,
masks, clipboard, measured reports and cycle exports retain their meanings.
The preview lives only in native session `presentation.fractionation_preview`.
There is no automatic correction, interference correction or `/2` contract.

## Supported workflow

Open **View → Review diagnostics → Fractionation preview (not exported)**.
Read a local C# `Tracer` or `TracerUPbModel` XML. The offline library retains
name, integer version, tracer type, lab, certification date, original UTF-8 XML
and SHA-256. PCT and ABS one-sigma uncertainties become absolute 1σ. Duplicate
names/versions with different XML are refused; edit a separate XML with a new
version and read it to add a revision. No bundled calibrated tracer, web access,
XML editor or schema fetch is provided. Unknown fields, including unrecognized
covariance metadata, fail rather than being silently discarded.

For Pb, supply measured 202/205 and a 202–205 tracer. For U, supply mapped,
oxide-corrected 233/235 and 238/235 plus the explicit component values and
absolute 1σ. The fields use blank pg, tracer g, blank/sample 238/235 and separate
235U/238U molar masses in g/mol. Zero blank is permitted; tracer mass and molar
masses must be positive. No value is inferred from chemistry/spike metadata.
Zero component 1σ explicitly fixes that component for this diagnostic.

**Create preview revision** freezes the mapped measured summaries, alpha,
corrected diagnostic ratios, their absolute 1σ and output covariance, input
covariance, settings, source/mask/mapping and applied XML. Active tracer selection
is distinct from each revision's applied tracer. Changes to raw review or active
tracer do not recalculate old records. Re-run to append a new revision.
The correction report labels the uncertainty assumptions and applied model.

**Batch preview all runs** appends one revision for each valid opened run. To
re-correct saved fractions, reopen their native session first. Batch uses the
same entered components for every U run: use individual previews if tracer
mass, blank or other components differ. Failed runs are counted in the notice and named in the scrollable correction report;
successful revisions remain available. Undo/redo changes visible revision
history and persists through session save/reopen. A new branch after undo retains
all original revision records. Original work products are never overwritten.
No-tracer preview is explicitly an identity diagnostic with alpha zero.

## Numerical scope

New pure functions are in [fractionation_preview.py](../src/rawtims/fractionation_preview.py);
the XML/library model is in [tracers.py](../src/rawtims/tracers.py).
Algorithm identifier: `ogtripoli-linear-preview/1`.

The following references use **OGTripoli d906f70**:

| Capability | Source | Preview convention |
|---|---|---|
| XML and version | `source/earth_time_org/Tracer.cs:40–150`, `TracerUPbModel.cs:40–146`, `ValueModel.cs:28–81` | Strict bounded C# XML; PCT or ABS 1σ; namespace-independent root recognition |
| Pb alpha | `source/TripoliWorkProduct.cs:2025–2035` | `(1 − tracer202_205 / measured202_205) / 3` |
| Pb ratios | `source/TripoliWorkProduct.cs:1683–1710` | Multiply measured ratio by `1 + (numerator mass − denominator mass) × alpha`; retain measured 202/205 as the control, as C# does |
| U components | `source/TripoliWorkProduct.cs:1145–1167`, `source/earth_time_org/USampleComponents.cs:40–85` | Blank isotope moles from separate mass fractions and molar masses; tracer moles from concentration × tracer mass |
| U alpha | `source/TripoliWorkProduct.cs:1292–1347` | Same term1–term5 rational calibration, scaled by tracer 235U moles for numerical conditioning |
| U ratios | `source/TripoliWorkProduct.cs:1351–1372` | 233/235 × `(1−2α)`, 238/235 × `(1+3α)`, measured 238/233 × `(1+5α)`; the last is not the quotient of corrected ratios |
| 233/236 oxide | `source/TripoliWorkProduct.cs:2815–2837` | Separate pure diagnostic: 233/236 = 265/268; 238/236 = 270/268 − 2r18; 238/233 is their quotient |

The GUI uses **measured summaries**, rather than C#'s per-cycle correction
followed by averaging. They differ when alpha varies by cycle and may differ
with geometric summaries. This distinction is recorded in each report. The
GUI does not display a per-cycle fractionation trend or claim calibrated-chain
parity. 233/236 oxide is an API diagnostic only; the GUI does not infer its
molecular assignments. C# explicitly rejects **233/236 fractionation** at
`TripoliWorkProduct.cs:1170–1190`; no replacement fractionation algorithm is guessed.

Uncertainties are a new first-order diagnostic, `J S Jᵀ`, over all explicit
measured, tracer and component primitives. Complex-step derivatives evaluate
the analytic rational laws. The pure APIs accept a symmetric positive-semidefinite
input covariance in documented input order and verify the diagonal against 1σ².
The GUI explicitly uses **independent inputs**; it does not silently infer missing
correlations or claim complete age-engine uncertainty parity. The output carries
that assumption and the full matrices. Nonfinite, singular or nonpositive
corrected results are refused. No automatic spike stripping is performed.

## Java and age-app comparison

Java **00dc941** has only `parameterModels/AbstractRatiosDataModel.java:35–39`
with `XMLSerializationI` commented out, and an empty tracer resource list.
`valueModels/ValueModel.java:41–43` has separate analytical/systematic absolute
uncertainties, unlike the C# ValueModel. No concrete tracer reader/schema or
tracer XML fixture exists in this snapshot. Therefore Java tracer XML import is
still unsupported; accepting an invented serialization would misstate parity.

[check_fractionation_age_app.py](../scripts/check_fractionation_age_app.py) runs
the existing age-app environment read-only with bytecode disabled and synthetic
inputs, records `utils.py` SHA-256, and asserts common-convention checks. No real
lab data or calibration library is opened. P7 observed:

| Quantity | C#-convention preview | Age app |
|---|---:|---:|
| Pb alpha (.303 measured, .3 tracer) | 0.0033003300330033034 | same |
| Pb alpha 1σ (.0006 measured, .0003 tracer) | 0.0007321367075848143 | same |
| Corrected 206/205 from 10, stripping disabled | 10.033003300330032 | same |
| U alpha, zero blank (.6, 70 measured; 1.2, .01 tracer; sample 137.88) | −0.014626369055871408 | same within floating precision |
| U alpha, .1 pg blank, .01 g tracer, 1e-9 mol/g 235U, molar masses 235/238 | −0.014626372855263385 | `calc_FU` remains −0.014626369055871408 (no blank parameter) |

Age source references: `src/IDTIMS_UPbRPy/utils.py:734–749` for Pb alpha/sigma,
`:752–774` for U alpha, `:788–829` for U uncertainty/covariance,
`:72–93` for abundance-weighted blank atomic weight, and `:420–442` for
206Pb correction and subtraction. `UPbR.py:96–114` assigns the fractionation
factors; `UPb_grain.py:1136–1147` derives 2535 Pb alpha. Age `calc_FU` does not
include C#'s blank terms; its later blank handling is separate. The age blank
moles use a weighted atomic weight, while C# splits mass by isotope and divides
by each isotope's molar mass. The age app also uses covariance inferred from
238/233 for U uncertainty. These are recorded convention differences; neither
is selected as a replacement for the other.

## Tests and remaining specimens

[Engine tests](../tests/test_p7_preview.py) transcribe independent scalar C#
references (40-digit Decimal evaluation of U term1–term5), zero-alpha/no-tracer
limits, XML identity/version/uncertainty validation, covariance finite-difference
cross-checks, 233/236 oxide and unsupported-family refusal. [Desktop tests](../tests/test_p7_preview_ui.py)
use only synthetic committed Pb/U data and generated synthetic XML. They verify
batch revision retention, undo/redo/session roundtrip and byte-identical /1,
clipboard and cycle outputs; layouts cover 1280×800 and 1440×900 in both themes.
G0 artifacts and the read-only age-app JSON are recorded in the phase report.
Source-derived tests are not .NET/Java runtime or real-chain validation.

Yiming would need the following **independently calibrated chains**, with
permission to use sanitized/synthetic replicas in regression tests:

1. ET2535 Pb: versioned certified tracer XML, 202/205 and all corrected Pb ratio
   inputs, uncertainties/covariance, accepted cycle masks, collectors, linear-law
   settings and independently checked per-cycle alpha plus final summaries.
   Include zero-fractionation control and low/high alpha and sample-to-spike ratios.
2. 233–235 U: the corresponding tracer concentration/ratios/covariance, weighed
   tracer mass/uncertainty, blank mass and isotope composition, sample 238/235,
   isotope molar masses, verified oxide law/r18, measured 233/235, 238/235 and
   238/233 with joint covariance, and independent corrected values/uncertainties.
   Include zero/low/high blank, changing sample-to-spike ratios and paired Pb/U
   fractions. Both C# and age-engine outputs/settings are needed to resolve
   convention effects without conflating them with numerical mistakes.
3. 233–236: independently verified molecular assignments, 265/268 and 270/268,
   r18/uncertainty and oxide-corrected expected ratios. Enabling fractionation
   additionally requires a separate validated algorithm/reference because the
   supplied C# snapshot does not implement it.

F25/F61/F62/F64 remain partial for the limits above; F63 and F65 have supported
D1 workflows. F26 is unchanged and blocked on **D11** plus independently
validated BaPO₂/Tl/coupled interference specimens. No other D4–D19 decision is
selected by this phase, and no `/2` contract is introduced.
