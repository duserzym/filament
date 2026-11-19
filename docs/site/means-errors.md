# Means and errors

!!! abstract "In short"
    The run result averages the included cycle ratios. Their scatter gives an estimate of the uncertainty in that mean. Dead time changes the cycle ratios, so we recalculate both the mean and its uncertainty.

A **cycle** is one pass through the measured masses. A **mask** marks which cycle values to include. The reported run ratio is their **arithmetic mean**: their sum divided by their count.

The **standard deviation (SD)** describes the spread of individual values. The **standard error (SE)** estimates the uncertainty in their mean from that spread. **%SE** expresses SE as a percentage of the mean. Reporting both the mean and its error distinguishes a well-repeated ratio from a noisy one.

\[
\bar R=\frac{1}{n}\sum_i R_i,\quad
s=\sqrt{\frac{\sum_i(R_i-\bar R)^2}{n-1}},\quad
SE=\frac{s}{\sqrt n},\quad \%SE=100\frac{SE}{\bar R}.
\]

Where:

- \(R_i,\bar R\): cycle ratios and arithmetic mean (dimensionless).
- \(n\): included usable cycles; \(s\): sample SD; \(SE\): standard error, both in ratio units.
- \(\%SE\): **one-sigma** percent standard error. It is not two-sigma uncertainty or percent SD.

## Worked example

For 206/207, \(n\) = {{ v.stats.worked.n_used }}, mean = **{{ v.stats.worked.mean | fmt(8) }}**, SD = {{ v.stats.worked.sd | fmt(4) }}, SE = {{ v.stats.worked.se | fmt(4) }} and **{{ v.stats.worked.se_pct | fmt(4) }}% SE**. These come directly from `Analysis.stats`.

The independent BSU-pasted values have fewer significant digits. All measured ratios and errors are shown for comparison:

| Ratio | Engine mean | BSU pasted mean | Engine 1σ %SE | BSU pasted 1σ %SE | Used |
|---|---:|---:|---:|---:|---:|
{% for row in v.stats.rows %}| {{ row.ratio }} | {{ row.mean | fmt(8) }} | {{ row.sheet_mean | fmt(8) }} | {{ row.se_pct | fmt(4) }} | {{ row.sheet_se_pct | fmt(4) }} | {{ row.n }} |
{% endfor %}

## Geometric option

The **geometric mean** averages logarithms instead of ratios. filament can work on \(\ell_i=\ln R_i\), where ln is the natural logarithm. It reports \(R_g=\exp(\bar\ell)\), with the smaller asymmetric percent error \(100[1-\exp(-SE_\ell)]\). Here \(\ell,SE_\ell\) are dimensionless. This is the geometric comparison option; the saved legacy workflow uses arithmetic run statistics.

## Blocks and MSWD

A **block** groups cycles that share background measurements. Comparing block means helps reveal slow drift. Tripoli reports the run mean over included cycles here. A weighted mean of blocks is a separate calculation. More precise blocks receive more weight. The **mean square of weighted deviates (MSWD)** compares their scatter with their estimated errors:

\[
M=\frac{\sum_b w_b m_b}{\sum_b w_b},\quad
\sigma_M=(\sum_b w_b)^{-1/2},\quad
MSWD_{\rm standard}=\frac{\sum_b (m_b-M)^2/SE_b^2}{q-1}.
\]

Where:

- \(m_b,s_b,SE_b\): block mean, sample SD and standard error (ratio units).
- \(q\): number of usable blocks; \(w_b\): weight (inverse squared ratio units).
- \(M,\sigma_M\): weighted mean and its **internal error**, calculated from the block errors (ratio units).
- MSWD: scatter relative to the stated errors (dimensionless).

`standard` uses \(w_b=1/SE_b^2\). The historical `tripoli` comparison convention instead uses \(w_b=1/s_b^2\) **and** computes dispersion as \(\sum_b(m_b-M)^2/[\sigma_M^2(q-1)]\). Its denominator is the variance of the weighted mean, not each block's variance. Do not treat that dispersion as the standard textbook MSWD.

| Convention | Weighted mean | Internal 1σ % | Dispersion |
|---|---:|---:|---:|
{% for name, row in v.stats.blocks.items() %}| {{ name }} | {{ row.mean | fmt(8) }} | {{ row.sigma_pct | fmt(4) }} | {{ row.mswd | fmt(4) }} |
{% endfor %}

## Correlation

\[
\rho=\frac{\sum_i(x_i-\bar x)(y_i-\bar y)}{\sqrt{\sum_i(x_i-\bar x)^2\sum_i(y_i-\bar y)^2}}.
\]

Where:

- \(x_i,y_i\): two cycle ratios, over cycles usable in both (dimensionless).
- \(\bar x,\bar y\): their arithmetic means (dimensionless).
- \(\rho\): **Pearson correlation**, describing how the ratios rise or fall together (dimensionless).

 For 206/205 and 206/207, \(\rho\) = **{{ v.stats.rho.r | fmt('.4f') }}**, based on {{ v.stats.rho.n }} shared cycles. If cycles are independent and both masks match, this also describes the correlation of the means. With different masks, it only approximates the correlation between means based on different cycle sets. The contract records the distinction.

**In filament:** `rawtims.stats.describe`, `block_weighted_mean`, `correlation`; `rawtims.analysis.Analysis.stats`.
