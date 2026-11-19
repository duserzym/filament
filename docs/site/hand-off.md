# Age-engine hand-off

!!! abstract "In short"
    filament sends measured ratios, errors and correlations to the age engine in a defined table. Reduction settings explain how those numbers were obtained. IDTIMS_UPbRPy then applies the chemical corrections and calculates the dates shown in the dead-time experiment.

filament exports one table row for each fraction. It contains the measured Pb and U ratios, their errors and their **correlations**: how pairs of ratios vary together. **%SE** means the standard error of a mean as a percentage of that mean. The row also records the reduction settings. These distinguish a processing change from a change in the age model.

The **contract** is the agreed table format, named `idtims-fractions/1`. IDTIMS_UPbRPy reads it. Where needed, its reader inverts a Pb ratio to obtain the reciprocal. It preserves the relative error to first order and changes the relevant correlation signs.

\[
\sigma_R=R\,(\%SE)/100,\qquad
\operatorname{cov}(R_i,R_j)=\rho_{ij}\sigma_i\sigma_j,\qquad
R_{a/b}^{-1}=R_{b/a}.
\]

Where:

- \(R\): ratio mean (dimensionless); \(\%SE\): one-sigma percent standard error.
- \(\sigma\): absolute one-sigma uncertainty (ratio units); \(\rho\): dimensionless correlation.
- Covariance has squared ratio units. Reciprocals refer to reported means, not re-averaging inverted cycles.

## Worked contract values

| Contract ratio | Mean | 1σ %SE |
|---|---:|---:|
{% for row in v.stats.rows %}| {{ row.ratio }} | {{ row.mean | fmt(8) }} | {{ row.se_pct | fmt(4) }} |
{% endfor %}

| Numerical reduction context | Value |
|---|---|
{% for column, value in v.handoff.columns.items() %}| {{ column }} | `{{ value }}` |
{% endfor %}

| Correlation column | Value |
|---|---:|
{% for row in v.handoff.correlations %}| {{ row.column }} | {{ row.value | fmt('.4f') }} |
{% endfor %}

The **parameter hash** is a fingerprint of the consistently formatted numerical settings, including the reduction route. The **route** says whether filament used exported workbook cycles or reconstructed raw scans. A **scan** is one timed reading; a **cycle** is a complete set of mass measurements. A **mask** marks which cycle values contribute to a ratio. **Provenance** records where the source evidence came from. This public walkthrough retains only numerical settings, masks and calculations. No source identities or calendar times are included in the public data.

## From ratios to dates

After fractionation and chemical corrections, the age engine forms radiogenic ratios and solves:

\[
R_{68,r}=e^{\lambda_{238}t}-1,\quad
R_{75,r}=e^{\lambda_{235}t}-1,\quad
R_{76,r}=\frac{1}{Q}\frac{e^{\lambda_{235}t}-1}{e^{\lambda_{238}t}-1}.
\]

Where:

- \(R_{68,r},R_{75,r},R_{76,r}\): radiogenic 206Pb/238U, 207Pb/235U and 207Pb/206Pb (dimensionless). **Radiogenic** means the component produced by radioactive decay.
- \(Q\): natural 238U/235U (dimensionless).
- \(\lambda\): decay constants (yr⁻¹); \(t\): age (yr).

The displayed 206/238 and 207/206 dates also include the selected **D-mode Th correction**. It allows for initial thorium disequilibrium. The correction leaves 207/235 unchanged. U acquisition reduction and all laboratory settings are held fixed in the dead-time experiment.

At the acquired dead time, the raw-route dates are:

| Date | Ma |
|---|---:|
{% for row in v.depth.dates %}| {{ row.ratio }} | {{ row.base | fmt('.3f') }} |
{% endfor %}

**In filament:** `rawtims.contract.mean_column`, `se_column`, `rho_column`, `rawtims.fractions.fraction_row`; the docs generator follows `rawtims.recalculation.AGE_WORKER` in a subprocess. **In IDTIMS_UPbRPy:** `fractions.read_fractions`, `UPb_grain.calc_sample`, `utils.calc_t68`, `calc_t75`, `calc_t76`; `dates.py` aggregates already reduced fraction dates. No browser or documentation Python code computes a date.
