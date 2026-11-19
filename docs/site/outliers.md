# Outlier rejection

!!! abstract "In short"
    An inclusion mask records which cycle values contribute to a result. Rejecting unusual values can change both the mean ratio and its error. We hold the saved masks fixed when changing dead time so selection changes do not obscure its effect.

A **cycle** is one complete pass through the measured masses. An inclusion **mask** marks each cycle value as included or excluded. An **outlier** is a value that a statistical rule identifies as unusually far from the others.

A saved mask tells us which values contributed to a ratio. It does not tell us every action that produced the selection. We restore that mask to reproduce the result. This matters because excluding a cycle changes the mean, and different ratios can have different masks.

## Legacy sigma rule

The legacy Tripoli version written in C# makes **one strict pass on the ratio values themselves**. It does not take their logarithms and does not iterate this rule automatically.

\[
J=\{i\in K:x_i>0,\ |x_i-\bar x|>2s\},\qquad
\text{apply only if } n>2+|J|.
\]

Where:

- \(x_i\): cycle ratio (dimensionless); \(K\): finite, included, positive values.
- \(n\): number of those values; \(\bar x\): their arithmetic mean; \(s\): sample standard deviation, the spread of the values (ratio units).
- \(J\): proposed rejected indices. The live-count guard preserves enough positive points.

## Chauvenet variants

\[
z_i=|x_i-\bar x|/s,\quad C_i=n\,\operatorname{erfc}(z_i/\sqrt 2),\quad C_i<P.
\]

Where:

- \(z_i\): distance from the mean in standard deviations (dimensionless).
- \(C_i\): expected count of values at least this far from the mean under a normal distribution (dimensionless).
- \(P\): rejection threshold (dimensionless); \(n,\bar x,s\) have the meanings above.
- \(\operatorname{erfc}\): complementary error function, used here to calculate the normal-distribution tail probability.

 The legacy C# rule considers positive ratios. It removes **one value farthest from the mean**, then recalculates the mean and scatter. It repeats while the **live-count guard** leaves enough included values. The Java comparison rule instead tests all current values in one pass. It requires a configured minimum number of values. filament also has an iterative sigma comparison option; that is a different rule from the legacy single pass.

## Worked example

For 206/207, the saved project excludes **{{ v.rejection.saved }}** cycles, leaving **{{ v.rejection.used }}**. A single legacy sigma pass starting from all positive workbook values excludes **{{ v.rejection.single_pass }}**. Do the masks match exactly? **{{ v.rejection.same | fmt }}**. Their symmetric difference contains **{{ v.rejection.different }}** cycle positions. Counts alone cannot establish how a saved mask was made.

Tripoli's saved masks are **per ratio**. Ordinary filament export uses the same selection for all ratios in the output contract. This keeps ratios and their joint uncertainty based on the same cycles. This walkthrough uses the legacy audit route. It retains each ratio's saved mask and labels that choice `per_ratio`. The interactive slider holds those masks fixed; it does not reject again at each dead time.

**In filament:** `rawtims.rules.legacy_two_sigma_rejections`, `legacy_chauvenet_rejections`, `chauvenet_rejections`; `rawtims.parity.replay_project`; `rawtims.fractions.require_shared_selection`.
