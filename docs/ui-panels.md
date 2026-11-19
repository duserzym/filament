# Panel conventions for the TIMS apps

Status: agreed on 2026-11-14 between the raw-data app (filament) and the ID-TIMS reduction app
(IDTIMS_UPbRPy). The same text is kept in both repositories as `docs/ui-panels.md`.

These conventions build on UPbRPy Studio's pattern, so the suite behaves the same:
- `QSplitter` panels whose sizes are saved per user in QSettings (`saveState` and `restoreState`);
- View › Reset Layout;
- a compact mode for narrow windows;
- panels that cannot collapse to zero unless they are meant to hide.

There are no dock widgets.

## 1. Maximise and restore

- **Shortcut.** Cmd+Shift+Return (Ctrl+Shift+Return on Windows and Linux) maximises the work panel
  that has keyboard focus, or else the one under the mouse, to the full work area.
- **Restore.** Pressing the shortcut again restores the panel, and so does Esc.
- **Header controls.** Each work panel's header has a small maximise button that does the same, and
  double-clicking the header also toggles it.
- **Keys left alone.** Cmd+M stays macOS Minimise, and F stays with macOS full screen.
- **Nested panels.** A work panel can contain work panels: in filament, the plot wall and each plot
  card in it. With focus or the mouse on an inner panel, the shortcut maximises that panel within the
  work area. Pressing it on the outer panel's header maximises the outer panel.
- **Esc.** Esc restores one level at a time, and only while something is maximised. Otherwise Esc
  keeps its existing role, such as discarding a preview or cancelling an inline edit.

## 2. Splitters

Double-clicking a splitter handle resets that splitter to its default sizes.

## 3. Sizes

- Each work panel declares a default, a minimum and a maximum size.
- Hiding a panel keeps the other panels' proportions, with no jump.
- Layouts are checked at 1280×800, 1440×900 and 1024×640, and against worst-case data (for example
  40 fractions with long identifiers).

## 4. Motion

- Showing and hiding panels animates in under 300 ms with ease-out.
- There is no animation on keyboard actions or tab switches.
- Presses give visible feedback.
- Reduced motion is respected. Any of these turns animation off: Qt's or the operating system's
  reduced-motion setting, `UPBRPY_REDUCE_MOTION`, or the suite-neutral `UPBLAB_REDUCE_MOTION`.

## 5. Issues lists

This applies wherever an app has an issues list:
- In the reduction app, the Issues inspector.
- In filament, the fraction state dot and the Export tab's problem list.

When nothing needs fixing, the list collapses to a count badge and gives its space to the work
panels. It opens when a fraction gets a problem (the "attention" state).

## Desktop raw-review additions (G1)

The four primary inspector tabs remain Stats / Rules / Corrections / Export.
Corrections contains scrollable Mapping / Reduction / Run info pages. Reduction
uses staged fields, Apply, Discard/Cancel and Reset; its diff is shown after Apply
with the editor collapsed (the editor can be reopened). Run info holds method
availability, acquisition metadata and full warnings; a persistent warning chip
opens it from every workflow step. Missing Tripoli sources have a separate Locate
banner containing the exact expected workbook name.

Rules retains Java Chauvenet and iterative k-sigma alongside the legacy C#
single-pass 2σ and repeated single-worst Chauvenet options. The legacy options
offer explicit per-ratio masks; differing masks block ordinary exports until
the union is adopted. Shared application remains the default. Faraday/Daly
cross-calibration retains the verified measured-per-cycle mode; alternative
Tau Time/Gain and HT Scaling response models remain unavailable.

The review wall has draggable Review / Pan / Zoom / Reset tools. A ghost follows
the pointer during dragging and the real tools move on release; their position is
remembered. Ten-pixel splitter handles hold the resize cursor during dragging and
scale a raster plot preview until release. Review boxes coalesce motion at 16 ms
and change the analysis only on release. Run/fraction pickers use natural ordering.

Help offers the five-step KD33 z1 dead-time walkthrough. The examples folder is a
setting (Help → Choose walkthrough examples folder); missing data disables the
walkthrough with an explanation. Screenshots can use `--walkthrough-step 1..5
--export png PATH` with `QT_QPA_PLATFORM=offscreen`. Headless step 5 adopts shared
cycles as the preceding export step requires, and never launches the age app.

Export adds XLSX (Fractions, Cycles with include flags, Provenance), three CSV
tables, and Send to IDTIMS_UPbRPy. The send command is an argv list, accepts `~`,
and has `--open PATH` appended without a shell. Its folder/command are remembered;
macOS bundle discovery uses the age app's name or bundle identifier. Absence or
launch failure retains the CSV and reveals it. Ordinary exports keep the shared
selection requirement. XLSX requires `openpyxl`, now in the GUI extra and frozen
build imports; the engine does not import it.

## Review layout G1b

The wall uses one 34 px toolbar: workflow/fractions handle, naturally sorted
run picker, Ratios / Intensities / Table, Functions, Options, Undo/Redo,
Focus, run information/warnings and ⋯. Secondary groups move into content-sized
submenus under ⋯ when they do not fit; they retain their original widgets and
actions. Options contains global scale/fit/shared-mask and mouse-mode controls.
Warnings stay in reach as a compact count, with full details in Run info.
Cycles used, history and the selection legend share the 24 px status bar.

Each plot has a two-line live header (name, mean ± 1σ % SE, n and standard
MSWD of block means), local log and y-fit controls, and maximise/restore.
The draggable Review / Pan / Zoom / Reset tools appear over the hovered plot;
positions are remembered per function. Double-click in the plot resets its view.
Y-fit preserves the linked x zoom; global Log resets each plot's local override.
The Tripoli colours and meanings are unchanged.

The 18 px block strip under each cycle axis uses the ViewBox transform, so
segment edges align with cycles and remain aligned when zoomed. Strips share
Analysis masks, rather than separate selections. Click/Space/Return toggles a
block; Shift-click extends the last anchor and drag spans a range. A range sets
all its blocks to the inverse of the first block's state. Hover and accessibility
labels give cycles and n used. Mouse motion changes only a pressed border; the
range commits on release, refreshes once and keeps one history entry per block.
Arrow/Home/End keys navigate the strip. Existing point/box/⌘/Shift gestures,
Delete, B, Esc and Undo/Redo remain available.

View › Focus on the plot (Cmd/Ctrl+Shift+F) folds both side panels inside the
window, retaining thin handles. Each handle unfolds its panel alone. Turning
Focus off restores the previous visibility and splitter widths, including an
already collapsed inspector. Focus geometry is transient and cannot overwrite
the normal panel preferences. Focus itself is a viewer setting. Maximise also
folds an open rail, and restores rail/Focus handles on return.

The inspector retains Stats / Rules / Corrections / Export, including staged
Reduction and Run info under Corrections. It defaults to 300 px, resizes with
the remembered splitter, and collapses to 30 px. Run info and workflow links
unfold it when needed. Rules preview/Apply and Reduction Apply/diff are unchanged.
Table remains a full-area view: a permanently open drawer would reduce every
plot's height, while the toolbar and Cmd/Ctrl+3 already provide immediate access.
At 1280 px, six ratios fit three columns by two rows with the inspector open.
At 1024 px the open inspector uses two plot columns with complete rows and
vertical scrolling; Focus fits six ratios without scrolling. Long identities
and summaries elide with full tooltips. Classic retains its original layout.

See [G1b validation](ui-layout-g1b.md) for captures, area measurements and checks.
