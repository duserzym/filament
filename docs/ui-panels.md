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
