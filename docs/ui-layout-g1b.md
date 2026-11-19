# Review layout G1b validation

The design follows UPbRPy `780498c` and `17c970a` (toolbar/popovers, overflow,
contained Focus) and IDTIMS_UPbRPy `7f30833` (remembered, maximisable panels).
`studio/review_toolbar.py` vendors the small responsive-toolbar helper with its
source commits. There are no runtime imports from either sibling repository.
The existing `f05b970`, `697e532` and `e91ae97` toolbar-drag, splitter and natural
sort ports remain. Studio's offscreen concordia captures were inspected before
implementing the wall. No visible Qt windows, commit or push was used.

## Space and captures

Inputs: read-only KD33 z1 Pb and U workbooks from `FILAMENT_BOISE_EXAMPLES`
(or the existing Drive default). Fresh isolated settings, light theme, no
rejections applied. All images and their data stay outside the repository.
“Plot panel” means the plot wall's viewport, including card headers and axes;
it excludes the application toolbar, inspector, side handles and status bar.
This is the same geometry measured before and after.

| Window | Before plot panel | After plot panel | After with Focus |
| --- | ---: | ---: | ---: |
| 1512×982 | 58.2% (1160×745) | 66.6% (1160×853) | 80.9% (1408×853) |
| 1440×900 | 55.7% (1088×663) | 64.7% (1088×771) | 79.5% (1336×771) |
| 1280×800 | 51.0% (928×563) | 60.8% (928×671) | 77.1% (1176×671) |
| 1024×640 | 40.8% (664×403) | 51.8% (664×511) | 71.7% (920×511) |

The first two requested pairs are `before-1512x982.png` /
`after-1512x982.png` and `before-1280x800.png` / `after-1280x800.png`.
They are in the system temporary directory's `review-g1b/` folder, together
with all four sizes, `after-focus-*.png`, `before-cli.png` and geometry JSON.
Resolve the scratch root with Python's `tempfile.gettempdir()`; this machine's
root is `/var/folders/j4/v8c8np455q11xr02p484d7bc0000gn/T`.
Before images were captured before editing, including the requested normal
`python -m rawtims_gui.main --open … --export png …` path. After images can
be reproduced with:

```sh
QT_QPA_PLATFORM=offscreen env -u PYTHONPATH .venv/bin/python \
  scripts/capture_review_layout.py "$TMPDIR/review-g1b" \
  --open "$FILAMENT_BOISE_EXAMPLES/B1606_F15_KD33 z1 Pb-56136.xls" \
         "$FILAMENT_BOISE_EXAMPLES/B1606_F15_KD33 z1 U-56137.xls"
```

The script isolates settings/recovery under its output directory, normalises
Retina captures to logical pixels, and counts only visible canvases when a
wall scrolls. Six ratios now fit at 1280×800 with the inspector open; the open
1024×640 wall scrolls complete rows, and Focus fits all six.

## Validation

Coverage includes all four window sizes, 40 long fraction IDs and 20 blocks,
classic and wall, exact splitter restore/reset, Focus keyboard and independent
handles, persistence, maximise nesting with an open rail, shared block toggles,
physical block dragging and Shift-click, no analysis refresh on mouse motion,
cycle-axis alignment during zoom, content-sized persistent Functions popover,
Options and overflow reachability, local log/y-fit/double-click reset, unchanged
selection and preview/reduction/export tests. Existing tests follow the moved
widgets; no covered scenario was removed.

A separate offscreen KD33 measurement at 1512×982 sampled 30 shared single-cycle
edits, processing paints between edits: median synchronous edit time 11.9 ms,
95th percentile 12.4 ms, maximum 13.4 ms. Sixty block drag previews measured
median 0.012 ms, maximum 0.022 ms, with no analysis refresh or full replot per
move. These are local observations, not hardware-independent timing promises.

## Files changed

- `src/rawtims_gui/review_layouts.py`: compact wall, axis strips, plot headers,
  local tools, Focus, panel/rail restore and responsive columns.
- `src/rawtims_gui/studio/review_toolbar.py`: vendored overflow helper.
- `src/rawtims_gui/main.py`: toolbar/action integration, shared range edits,
  status bar, persistent function checks and inspector navigation.
- `src/rawtims_gui/plots.py`: local scale override, y-only fit, double-click reset.
- `scripts/capture_review_layout.py`: repeatable scratch-only offscreen captures.
- `tests/test_review_layouts.py`, `tests/test_g1_gui.py`,
  `tests/test_review_window.py`: new interaction/fit checks and moved-widget coverage.
- `docs/ui-panels.md` and this report: controls, choices and validation.

The shared docs-site files are untouched by this work. The full suite detects
application-name literals in the protected `scripts/docs_site_data.py:350,352`.
Its fixed JavaScript global/comment violate the existing branding check. This
is left for the docs-site session; the branding test has not been weakened.


Final checks: `make test-quick` passed **160 tests**. The final `make test`
(with `QT_QPA_PLATFORM=offscreen` and `RAWTIMS_CACHE_DIR` directed to scratch)
finished **578 passed, 1 failed, 0 skipped/errors** in 113.1 seconds. The sole
failure is the protected docs-site branding issue above. Ruff on every changed
Python file and `git diff --check` both passed. Full logs are in the system
temporary directory at `filament-full-m95am8i6/`; quick logs are at
`filament-quick-v7u92upr/`. No layout failure remains accepted. At 1024×640,
scrolling with the inspector open is intentional; Focus shows all six ratios.
