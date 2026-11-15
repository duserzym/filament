"""Tripoli plot semantics, separate from the vendored application chrome.

CSS rgba values are consumed by theme_color for painters and by Qt stylesheets.
See docs/plot-colours.md for provenance and deliberate accessibility deviations.
"""
from dataclasses import dataclass

from rawtims_gui.studio.theme import ThemeSpec, active_theme


@dataclass(frozen=True)
class PlotPalette:
    band2sigma: str
    band1sigma: str
    bandSE: str
    mean: str
    meanFrozen: str
    included: str
    excluded: str
    selection: str
    blockSeparator: str
    blockOff: str
    blockSelecting: str
    hoverGuide: str
    frame: str
    preview: str


PALETTES = {
    'light': PlotPalette(
        band2sigma='#FFC0CB', band1sigma='#FFFACD', bandSE='#90EE90',
        mean='#0000FF', meanFrozen='#FF0000', included='#000000',
        excluded='#FF0000', selection='#FF0000', blockSeparator='#808080',
        blockOff='rgba(255,228,225,0.60)', blockSelecting='rgba(255,228,225,0.60)',
        hoverGuide='rgba(70,80,100,0.30)', frame='#000000', preview='#d97706',
    ),
    'dark': PlotPalette(
        band2sigma='rgba(166,65,100,0.30)', band1sigma='rgba(177,153,42,0.34)',
        bandSE='rgba(48,157,83,0.42)', mean='#7AA7FF', meanFrozen='#FF7B72',
        included='#E7ECF4', excluded='#FF7B72', selection='#FF7B72',
        blockSeparator='#7A879B', blockOff='rgba(153,79,87,0.25)',
        blockSelecting='rgba(153,79,87,0.25)', hoverGuide='rgba(190,205,230,0.28)',
        frame='#A3AEC0', preview='#f0b429',
    ),
}


def plot_palette(theme: ThemeSpec | None = None) -> PlotPalette:
    """Return the plot.* tokens for the currently resolved application theme."""
    return PALETTES[(theme or active_theme()).name]
