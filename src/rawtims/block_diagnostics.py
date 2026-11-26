"""Explicitly labeled display-only block estimators; existing cycle reduction is untouched."""
import math
from dataclasses import dataclass

import numpy as np

from rawtims.stats import WeightedMean, block_stats, block_weighted_mean


@dataclass(frozen=True)
class BlockDiagnostic:
    label: str
    dispersion_label: str
    result: WeightedMean
    omitted_blocks: tuple[int, ...]
    notice: str


def _diagnostic(values, include, block, *, is_ratio, ratio_mode, convention):
    stats = block_stats(values, include, block, is_ratio=is_ratio, ratio_mode=ratio_mode)
    omitted = tuple(b for b, s in stats.items() if s.n_used < 2 or not math.isfinite(s.se if convention == 'standard' else s.sd)
                    or (s.se if convention == 'standard' else s.sd) <= 0)
    result = block_weighted_mean(values, include, block, is_ratio=is_ratio, ratio_mode=ratio_mode, convention=convention)
    label, dispersion = ('Standard inverse-SE² block mean', 'MSWD (inverse-SE²)') if convention == 'standard' else (
        'Java 00dc941 inverse-SD² block mean', 'Java chi-square / (blocks − 1)')
    notices = []
    if omitted:
        notices.append('Omitted blocks with fewer than two accepted cycles or zero/nonfinite spread: ' + ', '.join(map(str, omitted)))
    if result.n_blocks < 2:
        notices.append('Dispersion is unavailable with fewer than two usable blocks')
    if result.mode == 'geometric':
        notices.append('Mean is exp(center); 1σ and weighting use ln(ratio)')
    return BlockDiagnostic(label, dispersion, result, omitted, '; '.join(notices))


def standard_block_diagnostic(values, include, block, *, is_ratio=False, ratio_mode='arithmetic'):
    return _diagnostic(values, include, block, is_ratio=is_ratio, ratio_mode=ratio_mode, convention='standard')


def java_snapshot_block_diagnostic(values, include, block, *, is_ratio=False, ratio_mode='arithmetic'):
    return _diagnostic(values, include, block, is_ratio=is_ratio, ratio_mode=ratio_mode, convention='tripoli')


def member_block_indices(run_ids, blocks):
    """Separate repeated block numbers belonging to different member acquisitions."""
    if len(run_ids) != len(blocks):
        raise ValueError('Member and block counts differ')
    identities = {}
    return np.array([identities.setdefault((r, int(b)), len(identities) + 1) for r, b in zip(run_ids, blocks)], dtype=int)
