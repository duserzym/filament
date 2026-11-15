# Tripoli plot colours

`rawtims_gui/plot_palette.py` defines the `plot.*` tokens for the resolved active
application theme. Both the default wall and classic fallback use the same
`CyclePlot`; the shared block header reads the same palette. Existing theme
tokens provide the white light background (`plot_background=#FFFFFF`) and dark
background (`#121926`). No colour literals belong in `plots.py` or
`review_layouts.py`; a ripgrep test enforces this.

The legacy references below are **CIRDLES/OGTripoli 4.10.0.3**,
`source/forms/frmRatioGraph.cs` (abbreviated `frmRatioGraph.cs` in the table),
as established by the supervising source audit. Java values are the comparison
palette in `TripoliConstants.java:26–31`; a dash means no counterpart was
supplied by that audit. Filament follows the legacy convention.

| Token | Legacy colour and file:line | Java colour | Filament light | Filament dark |
| --- | --- | --- | --- | --- |
| `plot.band2sigma` | Pink `#FFC0CB`, `frmRatioGraph.cs:466,473,540` | `#FFBFCB` | `#FFC0CB` | `rgba(166,65,100,0.30)` |
| `plot.band1sigma` | LemonChiffon `#FFFACD`, `frmRatioGraph.cs:470,552` (printer: Yellow) | `#FFEA00` | `#FFFACD` | `rgba(177,153,42,0.34)` |
| `plot.bandSE` | LightGreen `#90EE90`, `frmRatioGraph.cs:472,564`, ±1 SE | `#90EE8F`, ±2 SE | `#90EE90`, ±1 SE | `rgba(48,157,83,0.42)`, ±1 SE |
| `plot.mean` | Blue `#0000FF`, `frmRatioGraph.cs:718–721`, 1 px auto mean | `#FF0000` | `#0000FF` | `#7AA7FF` |
| `plot.meanFrozen` | Red `#FF0000`, `frmRatioGraph.cs:727`, 4 px frozen mean | — | `#FF0000` (reserved) | `#FF7B72` (reserved) |
| `plot.included` | Black `#000000`, filled square, `frmRatioGraph.cs:774` | `#0000FF` | `#000000`, filled square | `#E7ECF4`, filled square |
| `plot.excluded` | Red `#FF0000`, filled square, `frmRatioGraph.cs:791` | `#FF0000` | `#FF0000`, hollow square | `#FF7B72`, hollow square |
| `plot.selection` | Red `#FF0000`, open square, `frmRatioGraph.cs:802` | — | `#FF0000` | `#FF7B72` |
| `plot.blockSeparator` | Grey `#808080`, dash-dot, `frmRatioGraph.cs:437–438,822` | — | `#808080` | `#7A879B` |
| `plot.blockOff` | Reuses MistyRose `#FFE4E1` selection hue, `frmRatioGraph.cs:1833` | — | `rgba(255,228,225,0.60)` | `rgba(153,79,87,0.25)` |
| `plot.blockSelecting` | MistyRose `#FFE4E1`, `frmRatioGraph.cs:1833` | — | `rgba(255,228,225,0.60)` | `rgba(153,79,87,0.25)` |
| `plot.hoverGuide` | — (shared cross-ratio guide) | — | `rgba(70,80,100,0.30)` | `rgba(190,205,230,0.28)` |
| `plot.frame` | Black rectangle `#000000`, `frmRatioGraph.cs:574` | — | `#000000` | `#A3AEC0` |
| `plot.preview` | — (Filament rule preview) | — | `#D97706` | `#F0B429` |

## Rendering and deviations

Light bands, mean, data and frame use the exact legacy RGB values, without
contrast tuning. The only light legacy-colour tuning is MistyRose at 60%
opacity: this lets the block-off tint cover the **entire** block, including the
bands, while leaving their three statistical meanings visible. Header cells
use the same token. This adapts legacy's in-progress selection tint to disabled
blocks; the disabled header also says `0/n` and has an unchecked state.
The drag-selection rectangle uses `plot.blockSelecting` with a selection-colour
outline.

Excluded squares are deliberately hollow rather than legacy's filled red, so
inclusion is communicated by fill as well as hue. Existing edge-pinned hollow
triangles retain `plot.excluded`, with a tooltip reporting the true value.
The selected-cycle outline is red and square. Invalid cycles retain the theme's
faint crosses; this task does not introduce legacy's missing-value axis ticks.
The frozen-mean token is reserved: Filament does not currently offer frozen means.

Dark fills use the explicit darker RGB and lower alpha values above, retaining
pink, yellow/ochre and green hue meanings over the dark background. The nested
translucent fills composite in order: ±2σ, ±1σ, then ±1 SE. Blue is lifted for
the auto mean, included squares become light, and excluded/selected outlines
use a lighter red for visibility. The dark frame and separators are also lifted.
All lines remain cosmetic screen widths; the mean is 1 px.

Grey dash-dot separators replace alternating block shading. This makes block
boundaries readable without adding a fourth broad fill that competes with the
three uncertainty bands. Disabled-block tint overlays the bands, under points
and the mean, across every group plot.

The green band is now **±1 SE**, labelled **SE** in the legend (formerly ±2 SE).
For geometric statistics, the existing log-space bounds and exponentiation
are preserved. The sigma bands remain ±1σ and ±2σ.

## Colour-vision check

Run `env -u PYTHONPATH .venv/bin/python scripts/check_plot_colours.py`.
The script decodes sRGB to linear light, applies the severity-1 matrices from
[Machado, Oliveira and Fernandes (2009)](https://profs.ic.uff.br/~laffernandes/content/publications/journal/2009_tvcg_15%286%29/machado_oliveira_fernandes-tvcg-15%286%29-2009-corrected.pdf),
clips channels, and measures relative-luminance contrast. Matrix provenance:
[authors' simulation data](https://www.inf.ufrgs.br/~oliveira/pubs_files/CVD_Simulation/CVD_Simulation.html).
These numbers compare token colours, not anti-aliased screenshot pixels or
individual vision; they are not a claim of colour-only accessibility.

| Theme / simulation | Included vs excluded | Included vs background | Excluded vs background |
| --- | ---: | ---: | ---: |
| Light / protanopia | 3.285:1 | 21.000:1 | 6.392:1 |
| Light / deuteranopia | 6.568:1 | 21.000:1 | 3.197:1 |
| Dark / protanopia | 2.649:1 | 14.777:1 | 5.579:1 |
| Dark / deuteranopia | 1.879:1 | 14.880:1 | 7.917:1 |

The lower dark included/excluded contrast reinforces the need for filled versus
hollow markers. Tests enforce both the contrast bounds and actual marker fill.

## Fit and screenshot evidence

The wall chooses columns from available plot width and ratio count: three at
960 px or more with at least five ratios, two at 700 px or more, otherwise one.
At 1280×800 with the inspector collapsed, six ratios use two rows and seven use
three; all fit without scrolling. At 1024×640, two complete rows (four cards)
fit. Card heights adapt to an integral number of complete visible rows.
Maximising one card still hides the inspector and uses the full work area.

Cycle axes share the full run's x range, even if a function lacks an endpoint.
The fixed 62 px y-axis width aligns cycle positions within each card column;
x zooms are linked. Hovering a cycle displays `plot.hoverGuide` on every card,
clearing when the pointer leaves the plot.

Reproduce with `QT_QPA_PLATFORM=offscreen env -u PYTHONPATH .venv/bin/python
scripts/capture_plot_colours.py OUTPUT`. The capture uses B998, rejects cycles
22–24 through the normal shared-mask operation, and disables block 4. It saves
all eight requested PNGs and a geometry report, with isolated settings/recovery
under OUTPUT. Captures use logical pixel dimensions, normalizing Retina output.
