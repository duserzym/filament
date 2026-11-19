# Dead time in depth

!!! abstract "The short answer"
    The counter misses a larger fraction of a strong beam than of a weak beam.
    Changing dead time \(\tau\) changes a ratio by a fraction of about \((N_a-N_b)\Delta\tau\), where \(N_a,N_b\) are the two beam rates.
    For the example zircon fraction (z1), mass 206 is about {{ v.depth.rates['206'] | sci }} counts per second (cps) versus {{ v.depth.rates['207'] | sci }} cps at mass 207.
    Adding {{ v.depth.delta_ns | fmt('.1f') }} ns raises 206/207 by about {{ v.depth.ratios[1].scan_pct | fmt('.2f') }}%, but 206/205 by only about {{ v.depth.ratios[2].scan_pct | fmt('.2f') }}%.
    For the same percentage change in ratio, the 207/206 date moves about {{ v.depth.sensitivity_factor | fmt(1) }} times more than the 206/238 date.
    Together, the larger ratio change and larger date response give shifts of {{ v.depth.dates[2].shift | fmt('+.2f') }} Ma for 207/206 versus {{ v.depth.dates[0].shift | fmt('+.2f') }} Ma for 206/238.

!!! abstract "In short"
    This page follows dead time from individual pulses to ratios and dates. The worked example and sliders show why unequal beam strengths matter. The browser recalculates ratios and looks up dates already calculated by the age engine.

**Changing the Daly dead time changes strong and weak beams by different amounts.** In the example zircon fraction (z1), increasing it from **{{ v.depth.tau0 | fmt(4) }} to {{ v.depth.tau1 | fmt(4) }} ns** raises measured 206/207 and 206/205, but lowers 207/205. After the age engine's chemical corrections, 206/238 becomes older while 207/235 and 207/206 become younger.

We start with a recorded pulse, then compare two beams, then follow the ratio into the date calculation. **cps** means counts per second. A **scan**, or **integration**, is one timed reading. A **sequence** groups scans at one mass setting. **Peak hopping** changes settings; a **cycle** visits each setting once. A **block** groups cycles with shared background measurements.

The **baseline** is the signal measured away from an isotope peak, at a **half-mass** setting between integer isotope masses. A **gross** rate includes that background. A **net** rate has it subtracted. An inclusion **mask** marks which cycle values contribute to a ratio. **%SE** is the standard error of the mean as a percentage of that mean.

## A counter briefly goes blind

A Daly detector converts an arriving ion into a pulse. The counter needs a short recovery interval after recording it. An ion arriving during that interval cannot be counted separately. A stronger beam puts more arrivals into these blind intervals.

<svg class="pulse-timeline" viewBox="0 0 680 200" role="img" aria-labelledby="pulse-title pulse-desc" xmlns="http://www.w3.org/2000/svg">
<title id="pulse-title">A missed ion during the counter's blind interval</title>
<desc id="pulse-desc">Time runs from left to right. A recorded pulse starts a shaded interval of width tau. An ion inside it is missed and does not extend that interval. A later ion starts another recorded pulse.</desc>
<g fill="currentColor" font-family="sans-serif" font-size="16">
<text x="12" y="52">Arriving ions</text><text x="12" y="127">Recorded</text>
<text x="600" y="183">Time →</text>
<rect class="blind-interval" x="170" y="83" width="155" height="62" rx="4"/>
<rect class="blind-interval" x="455" y="83" width="155" height="62" rx="4"/>
<g fill="none" stroke="currentColor" stroke-width="2">
<path d="M150 58 H640 M150 137 H640"/>
<path d="M170 58 V30 M235 58 V30 M455 58 V30"/>
<path d="M170 137 V103 M455 137 V103"/>
<path d="M170 158 H325 M170 153 V163 M325 153 V163"/>
</g>
<text x="225" y="108" font-size="26">×</text><text x="215" y="78">missed</text>
<text x="210" y="183">blind for τ</text><text x="357" y="120">live</text>
</g>
</svg>

In the **non-paralysable** model, a missed arrival does not extend the blind interval. In the **paralysable** model, any arrival restarts it. These are idealized models. Agreement with the acquisition workbook identifies the software's correction. It does not fully characterize the detector's physical response.

Textbook reference: Knoll, G. F. (2010) *Radiation Detection and Measurement*, 4th ed., Wiley, chapter 4 (dead time models).

## Derive the non-paralysable correction

Suppose the counter records \(n\) pulses during elapsed time \(T\). Each recorded pulse makes it blind for \(\tau\). Its **live time**, when it can accept pulses, is therefore \(T-n\tau\). Estimate the incoming rate by dividing the recorded count by that live time:

\[
N=\frac{n}{T-n\tau}
=\frac{n/T}{1-(n/T)\tau}
=\frac{N_{\rm obs}}{1-N_{\rm obs}\tau}.
\]

Rearranging gives a useful reciprocal form:

\[
\frac{1}{N}=\frac{1}{N_{\rm obs}}-\tau.
\]

Where:

- \(n\): recorded pulse count; \(T\): elapsed scan duration (s).
- \(\tau\): non-paralysable dead time (s).
- \(N_{\rm obs}=n/T\): observed rate (cps); \(N\): corrected gross rate (cps).
- \(T-n\tau\): live time (s). The formula requires \(N_{\rm obs}\tau<1\).

For contrast, the ideal paralysable response is \(N_{\rm obs}=N\exp(-N\tau)\). A pulse can be registered only if no earlier arrival occupies its recovery interval. At very high rates, the same observed rate can describe two different incoming rates in this model. We solve for the lower incoming rate, on the **low-rate branch**. filament does not use this model for the acquisition correction.

### Worked scan and software evidence

The first listed real mass-206 scan has observed rate **{{ v.scan.rows[0].observed | fmt('.1f') }} cps**. At {{ v.scan.tau | fmt(4) }} ns the non-paralysable correction gives **{{ v.scan.rows[0].corrected | fmt('.1f') }} cps**. [The scan page](daly-scans.md) shows every integration used in that sequence.

Follow correction, scan rejection, interpolation and baseline subtraction for the first exported mass-206 cycle:

| Model | Net cycle intensity (cps) | Relative difference from workbook |
|---|---:|---:|
| Acquisition workbook | {{ v.cycle.workbook | fmt('.1f') }} | — |
| Non-paralysable per scan | {{ v.cycle.net | fmt('.1f') }} | {{ v.cycle.nonpar_relative_error | sci }} |
| Paralysable per scan | {{ v.cycle.paralysable_net | fmt('.1f') }} | {{ v.cycle.par_relative_error | sci }} |

The alternative calculation applies the paralysable model to the same peak and background scans. All other steps stay the same. Its error is much larger. Across all Pb functions/cycles, filament's non-paralysable raw reconstruction differs from the workbook by at most **{{ v.depth.max_relative_error | sci }} relative**, below the established **{{ v.depth.pb_bound | sci }}** bound. This is the numerical evidence for IonVantage's model on this method. It does not establish a model for every IsotopX instrument or acquisition method.

**Tripoli adds no dead-time correction.** Legacy Tripoli accepts IonVantage/IsoLinx's exported cycles and then selects cycles and computes statistics. In filament, raw reduction calls `rawtims.readers.ionvantage_raw.dead_time` before any averaging.

## Change dead time after acquisition

Both dead-time values describe the same recorded pulses; only the correction differs. Write the reciprocal equation for each correction, then subtract:

\[
\frac{1}{N_1}=\frac{1}{N_0}-(\tau_1-\tau_0)
\quad\Longrightarrow\quad
N_1=\frac{N_0}{1-N_0\Delta\tau}.
\]

Where:

- \(N_0,N_1\): old and new gross corrected rates (cps).
- \(\tau_0,\tau_1\): old and new dead times (s).
- \(\Delta\tau=\tau_1-\tau_0\): change in dead time (s).

The equation is exact **for one observed rate** with the non-paralysable model and unit multiplier gain. **Multiplier gain** is an additional calibration factor applied to the Daly rate. The example's gain is {{ v.scan.multiplier_gain | fmt(5) }}. If it differed from unity, we would remove that factor before using the reciprocal equation.

Exported cycle intensities have already had their background subtracted. Add that baseline back before changing the dead-time correction. Then subtract it again:

\[
D_1=\frac{D_0+B}{1-(D_0+B)\Delta\tau}-B.
\]

Where:

- \(D_0,D_1\): old and new net Daly rates (cps).
- \(B\): acquired block Daly baseline (cps).
- \(\Delta\tau\): new minus old dead time (s).

A background pulse occupies the counter just like a peak pulse, so adding \(B\) back is necessary. The workbook route holds this acquired baseline fixed. The raw route reprocesses every baseline scan too.

A cycle value combines scans and estimates them at a shared time. The dead-time correction is nonlinear: correcting a combined value does not give exactly the same answer as combining corrected scans. The workbook route is therefore a **cycle approximation**. Its single-rate equation is exact. The interactive uses the workbook route; the tables also show the separate raw-scan result.

**In filament:** `rawtims.reprocess.change_dead_time` and `reprocess`.

## Why a ratio changes

Call the numerator rate \(N_a\) and the denominator rate \(N_b\). Both initially use dead time \(\tau_0\). Correct each rate with the new dead time, then divide:

\[
R_1=\frac{N_a/(1-N_a\Delta\tau)}{N_b/(1-N_b\Delta\tau)}
=R_0\frac{1-N_b\Delta\tau}{1-N_a\Delta\tau}.
\]

Subtract the original ratio to find the fractional change. If \(N_a\Delta\tau\) is small, the denominator is close to unity:

\[
\frac{R_1}{R_0}-1
=\frac{(N_a-N_b)\Delta\tau}{1-N_a\Delta\tau}
\approx (N_a-N_b)\Delta\tau.
\]

Where:

- \(R_0,R_1\): old and new ratios (dimensionless).
- \(N_a,N_b\): **old gross** numerator and denominator rates (cps).
- \(\Delta\tau\): new minus old dead time (s).

The fractional change has no units. Multiply it by one hundred for percent.

If numerator and denominator have equal rates, their corrections cancel. A stronger numerator makes the ratio rise as dead time increases. A weaker numerator makes it fall. The difference between beam rates controls this bias. Their isotope mass separation does not enter this equation.

The omitted term for this gross-rate ratio is exactly:

\[
\epsilon=\frac{N_a(N_a-N_b)(\Delta\tau)^2}{1-N_a\Delta\tau}.
\]

This term depends on the square of the dead-time change. It becomes small quickly as the change shrinks. For net rates, we must also allow for adding and subtracting the fixed baseline. The rate of change of each net ratio is:

\[
q_i=\left.\frac{d\ln R_i}{d\tau}\right|_0
=\frac{(D_{a,i}+B_i)^2}{D_{a,i}}
-\frac{(D_{b,i}+B_i)^2}{D_{b,i}},\qquad
\frac{\Delta\bar R}{\bar R}\approx
\frac{\sum_{i\in K}R_i q_i}{\sum_{i\in K}R_i}\Delta\tau.
\]

Where:

- \(i\): cycle index; \(K\): included cycles in the ratio's saved mask.
- \(D_{a,i},D_{b,i}\): old net numerator and denominator rates (cps); \(B_i\): acquired baseline (cps).
- \(R_i,\bar R\): cycle ratio and its included-cycle mean (dimensionless).
- \(q_i\): initial fractional ratio change per second of dead-time change (s⁻¹).
- \(\Delta\tau\): dead-time change (s).

The sum finds the change in the **arithmetic mean of included cycle ratios**. This differs from dividing average intensities. Each ratio uses its own saved mask. For 208/205, substitute Daly 206 for the numerator in \(q_i\), because the inverse gain supplies that beam.

### Worked ratio changes

Mean acquired net Daly rates are:

| Mass | Rate (cps) |
|---|---:|
{% for mass, rate in v.depth.rates.items() %}| {{ mass }} | {{ rate | fmt('.0f') }} |
{% endfor %}

For **{{ v.depth.tau0 | fmt(4) }} → {{ v.depth.tau1 | fmt(4) }} ns**, a change of **{{ v.depth.delta_ns | fmt(4) }} ns**:

| Ratio | Raw engine change (%) | Workbook exact (%) | First order (%) | Exact − first (ppm) |
|---|---:|---:|---:|---:|
{% for row in v.depth.ratios %}| {{ row.ratio }} | {{ row.scan_pct | fmt('+.4f') }} | {{ row.exact_pct | fmt('+.4f') }} | {{ row.first_pct | fmt('+.4f') }} | {{ row.residual_ppm | fmt('+.2f') }} |
{% endfor %}

“Exact” means applying the workbook equation to every cycle, then averaging the included ratios. “First order” uses the slope at the acquired dead time. It ignores how that slope changes as dead time changes. The last column shows what this approximation leaves out, in **ppm**, or parts per million of the original ratio. It also includes tiny differences from retaining the workbook's stored values at the acquired setting. Raw scan reduction gives the separate results in the first numerical column.

## Faradays and the gain cancellation

The Faraday-only 206/208 ratios do not depend on Daly dead time. Changing \(\tau\) does not change their intensities. A **gain** is the calibration factor relating the Faraday and Daly signal scales. The 208/205 ratio divides a Faraday signal by a Daly signal multiplied by this gain:

\[
R_{208/205}=\frac{F_{208}}{(F_{206}/D_{206})D_{205}}
=\frac{F_{208}}{F_{206}}\frac{D_{206}}{D_{205}}.
\]

Where:

- \(F_{208},F_{206}\): High1 Faraday rates (cps).
- \(D_{206},D_{205}\): net Daly rates (cps).
- \(R\): ratio (dimensionless).

The Faraday quotient stays fixed while Daly 206/205 changes. The **run mean** averages the included cycle ratios. Its percent change differs slightly from that of 206/205 because the Faraday quotient varies between cycles. The saved masks can also include different cycles.

## Why the Pb/Pb date moves so much

Two effects multiply. First, the rate difference between 206 and 207 is larger than that between 206 and 205. This gives 206/207 about **{{ v.depth.bias_factor | fmt(3) }} times** the first-order bias of 206/205. Taking the reciprocal to get 207/206 reverses the sign.

Second, the same percentage ratio change moves a Pb/Pb date farther than a Pb/U date. Here we mean **radiogenic** ratios, after the age engine removes tracer, blank and initial common Pb. Define **date sensitivity** as the age change per fractional ratio change:

\[
S_{68}\equiv\frac{dt}{d\ln R_{68}}=
\frac{R_{68}}{\lambda_{238}(1+R_{68})},\qquad
S_{75}=\frac{R_{75}}{\lambda_{235}(1+R_{75})},
\]

\[
S_{76}=\left[
\frac{\lambda_{235}e^{\lambda_{235}t}}{e^{\lambda_{235}t}-1}
-\frac{\lambda_{238}e^{\lambda_{238}t}}{e^{\lambda_{238}t}-1}
\right]^{-1},\qquad \Delta t\approx S\,\Delta\ln R.
\]

Where:

- \(R_{68},R_{75},R_{76}\): **radiogenic**, chemically corrected 206/238, 207/235 and 207/206 ratios (dimensionless).
- \(t\): uncorrected age (yr); \(\lambda_{238},\lambda_{235}\): engine decay constants (yr⁻¹).
- \(S\): years per unit change in ln ratio, converted to Myr in the table; \(\Delta\ln R\): fractional ratio perturbation to first order.

The engine constants are \(\lambda_{238}\) = {{ v.depth.constants.lambda_238 | sci(6) }} yr⁻¹ and \(\lambda_{235}\) = {{ v.depth.constants.lambda_235 | sci(6) }} yr⁻¹. We evaluate these sensitivities at the engine's radiogenic ratios and age before the Th correction. The final dates include the selected correction for initial thorium disequilibrium.

| Date | Sensitivity (Myr) | Engine shift (Ma) | First-order prediction (Ma) | Engine − prediction (Ma) |
|---|---:|---:|---:|---:|
{% for row in v.depth.dates %}| {{ row.ratio }} | {{ row.sensitivity | fmt('.1f') }} | {{ row.shift | fmt('+.3f') }} | {{ row.first | fmt('+.3f') }} | {{ row.residual | fmt('+.3f') }} |
{% endfor %}

For the first-order prediction, we give radiogenic 206/238 the same fractional change as measured 206/205. We use the inverse change of measured 206/207 for radiogenic 207/206. We combine those changes for 207/235.

These approximations explain the size and sign of the date shifts. Tracer subtraction, blank subtraction and the Th correction change the response. The finite dead-time step also adds curvature. The **residual** is the engine shift minus the prediction; the table shows that they do not agree exactly.

For the same percentage change in ratio, the Pb/Pb date moves **{{ v.depth.sensitivity_factor | fmt(3) }} times** farther than the 206/238 date. That is what a larger \(dt/d\ln R\) means. Looked at the other way round, the Pb/Pb ratio changes more slowly with age.

This larger date response multiplies the larger ratio bias. Together they explain the observed age-shift factor of **{{ v.depth.age_shift_factor | fmt(3) }}**. U reduction, tracer settings, blank, mass fractionation and the saved masks stay fixed throughout this experiment. **Mass fractionation** is the instrument's mass-dependent preference for transmitting one isotope over another.

**In filament:** `rawtims.recalculation.AGE_WORKER` sends the fraction contracts to IDTIMS_UPbRPy. The documentation generator calculates only analytical sensitivities and comparisons; it never solves a date.

## Interactive: move the dead time

Move the slider to change the Daly dead time. **The browser** adds the baseline back to each acquired net rate, applies the new correction, then subtracts the baseline. It recalculates the gain, cycle ratios, included-cycle means and one-sigma %SE.

At the acquired setting, it retains the original stored ratios, just as the engine does. The first-order column predicts the mean change from the initial slope, including the fixed-baseline effect.

Dates and their two-sigma errors are **looked up from IDTIMS_UPbRPy**. The age engine calculated them beforehand at all **{{ v.depth.grid_count }}** slider positions. The slider snaps to the **{{ v.depth.step | fmt(3) }} ns** grid, so every date comes from that grid. The browser does not interpolate or calculate dates. This interactive uses workbook cycles. The raw-route column above comes from correcting individual scans.

<div id="deadtime-lab" class="lab">
<label for="tau-slider">Daly dead time: <output id="tau-value" for="tau-slider" aria-live="polite">{{ v.depth.tau0 | fmt(4) }} ns</output></label>
<input id="tau-slider" type="range" min="{{ v.depth.minimum }}" max="{{ v.depth.maximum }}" step="{{ v.depth.step }}" value="{{ v.depth.tau0 }}">
<button type="button" data-tau="{{ v.depth.tau0 }}">Acquired · {{ v.depth.tau0 | fmt(4) }} ns</button>
<button type="button" data-tau="{{ v.depth.tau1 }}">Compare · {{ v.depth.tau1 | fmt(4) }} ns</button>
<div class="table-scroll"><table><thead><tr><th>Ratio</th><th>Mean at τ</th><th>1σ %SE</th><th>Change (%)</th><th>First order (%)</th></tr></thead><tbody id="ratio-results"></tbody></table></div>
<p><strong>Each cycle's change tracks its beam intensity.</strong> Each dot compares a cycle at the selected dead time with the same acquired cycle. The horizontal axis uses its acquired gross numerator-minus-denominator rate. Both ratios share the same first-order line, 100·x·Δτ (Δτ in seconds). Net background subtraction and higher-order terms explain small departures from that line. All cycles are shown; the means above still use the saved masks.</p>
<p id="change-status" role="status" aria-live="polite">Move the slider to see how each cycle changes.</p>
<div id="change-plot" class="plot" role="img" aria-label="Per-cycle changes in 206/207 and 206/205 versus acquired gross rate difference"></div>
<div id="cycle-plot" class="plot" role="img" aria-label="Cycle 206/207 ratios at acquired and selected dead time"></div>
<div class="table-scroll"><table><thead><tr><th>Date</th><th>Ma ± 2σ</th><th>Shift (Ma)</th></tr></thead><tbody id="date-results"></tbody></table></div>
<div id="date-plot" class="plot" role="img" aria-label="Three age-engine date shifts across the dead-time grid"></div>
<p id="plot-status" role="status"></p>
</div>

## Interactive: count loss versus beam strength

The first plot has logarithmic rate axes: equal spacing means equal factors in rate. The second shows the percentage added to an observed rate, using \(100(N/N_{\rm obs}-1)\). Curves use {{ v.depth.plot_taus | join(', ') }} ns. Markers show the example's mean gross rates at the acquired correction, with corresponding observed rates recovered by the reciprocal identity. The markers include background. They illustrate mean rates, rather than individual scan measurements. Zoom or hover to inspect them.

<div class="lab">
<div id="rate-plot" class="plot" role="img" aria-label="Corrected versus observed count rate for several dead times"></div>
<div id="percent-plot" class="plot" role="img" aria-label="Percent dead-time correction versus observed rate"></div>
</div>

## Interactive: ratio bias and intensity contrast

Choose a denominator gross rate. Solid lines use the exact gross-rate ratio identity; dashed lines use its first-order expansion. They use dead-time changes {{ v.depth.plot_deltas | map('fmt', 4) | join(', ') }} ns. The horizontal axis varies the numerator-to-denominator rate ratio, \(N_a/N_b\). Equal-rate beams meet at zero bias.

The labelled markers use the example's 204/205, 206/205 and 207/205 **net intensity proportions**, scaled to the chosen denominator and evaluated at the comparison dead-time change. At the default denominator they approximate the example's actual rate pairs, with its small background omitted for this idealized panel. Changing the input scales this pattern as a hypothetical example. It does not change the real-fraction results above. The baseline-aware first interactive remains the quantitative example calculation.

<div class="lab">
<label for="denominator-rate">Denominator rate (cps)</label>
<input id="denominator-rate" type="number" min="1" max="1999999" value="{{ v.depth.rates['205'] }}" step="1000">
<p id="bias-status" role="status"></p>
<div id="bias-plot" class="plot" role="img" aria-label="Exact and first-order ratio bias versus numerator to denominator intensity ratio"></div>
</div>

## How to check your dead time

Measure a reference Pb material, such as NBS 981, over a range of beam intensities using the **same Daly and counting electronics**. With a suitable dead time, corrected ratios should not trend with intensity difference. Repeat blocks or runs to separate count-rate effects from slow drift and changing mass fractionation.

Define \(\Delta\tau_{\rm error}=\tau_{\rm true}-\tau_{\rm used}\). An under-correction gives approximately:

\[
\ln R_{\rm meas}\approx \ln R_{\rm reference}
-(N_a-N_b)\Delta\tau_{\rm error}.
\]

Where:

- \(N_a,N_b\): gross numerator and denominator rates (cps).
- \(R_{\rm meas},R_{\rm reference}\): measured and reference ratios (dimensionless).
- \(\Delta\tau_{\rm error}\): true minus used dead time (s).

Regress ln ratio on the rate difference. Under these assumptions, the slope is approximately **minus the dead-time error**, in seconds. The sign depends on this explicit definition of error.

Use enough intensity range to distinguish a trend from scatter. Keep collector configuration and processing consistent. Check Faraday/Daly gain behavior and detector linearity as well: a rate-dependent response need not be described fully by one dead-time parameter. Stable fractionation mainly shifts the regression intercept. Changing fractionation can distort the intensity trend. There are no synthetic “calibration results” hidden in this page.

**In filament:** the reproducible numerical experiment is `scripts/docs_site_data.py`; browser functions are in `javascripts/deadtime.js`. Changing a displayed slider is an exploration, not an instrument calibration.
