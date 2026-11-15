"""Read-only legacy Tripoli comparison, independent of contract exports and history."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rawtims.analysis import Analysis
from rawtims.exports import CLIPBOARD_SEPARATOR, CLIPBOARD_SUFFIX, legacy_e7
from rawtims.mapping import ElementMapping
from rawtims.rules import propose
from rawtims.stats import Stats, describe


@dataclass(frozen=True)
class LegacyRow:
    ratio: str
    key: str
    name: str
    stats: Stats


@dataclass(frozen=True)
class LegacyComparison:
    rows: tuple[LegacyRow, ...]
    masks: dict[str, np.ndarray]
    source: str

    @property
    def clipboard_text(self) -> str:
        return ''.join(f'{r.name}{CLIPBOARD_SEPARATOR}{CLIPBOARD_SUFFIX}\r\n'
                       f'{legacy_e7(r.stats.mean)}\r\n{legacy_e7(r.stats.se_pct)}\r\n\r\n'
                       for r in self.rows)


def legacy_comparison(analysis: Analysis, mapping: ElementMapping, rule: str | None = None) -> LegacyComparison:
    """Arithmetic per-ratio statistics on private masks; never edits Analysis.

    A selected rule starts from all individually valid cycles in included blocks,
    independent of shared hand/rule rejections. Without a rule, saved legacy masks
    take precedence, falling back to the shared selection for any other key.
    """
    entries = list(mapping.ratios.values())
    values, masks = {}, {}
    for entry in entries:
        key = entry.key
        col = analysis.index(key)
        v = analysis.column(key).copy()
        if entry.inverted:
            with np.errstate(divide='ignore', invalid='ignore'):
                v = 1.0 / v
        values[key] = v
        if rule is None:
            masks[key] = analysis.legacy_masks.get(key, analysis.included_for(key)).copy()
        else:
            masks[key] = (~analysis.invalid[:, col] & analysis.block_included[analysis._row_block]).copy()
    if rule is not None and entries:
        keys = list(dict.fromkeys(e.key for e in entries))
        settings = analysis.settings
        params = ({'probability': settings.chauvenet_probability, 'min_n': settings.chauvenet_min_n,
                   'log_ratios': False} if rule == 'chauvenet' else
                  {'k': settings.k_sigma, 'max_iterations': settings.k_sigma_max_iterations, 'log_ratios': True})
        proposal = propose(rule, np.column_stack([values[k] for k in keys]),
                           np.column_stack([masks[k] for k in keys]), keys, [True] * len(keys),
                           analysis.run.block, synced=False, **params)
        for key, rows in proposal.rejected.items():
            masks[key][list(rows)] = False
    rows = tuple(LegacyRow(e.ratio, e.key, f'1/({e.name})' if e.inverted else e.name,
                           describe(values[e.key], masks[e.key], mode='arithmetic')) for e in entries)
    for mask in masks.values():
        mask.setflags(write=False)
    source = (f'{rule} per ratio, from individually valid cycles in included blocks' if rule else
              'Saved legacy masks (shared selection for other ratios)' if analysis.legacy_masks else 'Shared selection')
    return LegacyComparison(rows, masks, source)
