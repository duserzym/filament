# filament (working name)

Raw ID-TIMS data review for the UPb Lab suite: ingest IsotopX IsoprobeT output, review and filter cycles, hand reduced ratios to the ID-TIMS reduction app. Local repository only; the name is a working name until Yiming confirms it.

Read the [user guide](docs/user-guide.md) for the review workflow and KD33 dead-time walkthrough,
and the [Tripoli feature gaps](docs/tripoli-gap.md) for current limits.

## Development

```sh
/opt/homebrew/bin/python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[gui,dev,build]'
make test-quick   # affected tests after each change (skips slow tests)
make test         # full suite, before any build or install
make build        # PyInstaller app outside the repository, lab-sign when available, then offscreen checks
make build BUILD_ARGS=--archive  # add a ZIP with a SHA256 sidecar
make install      # verify a staged copy, then atomically swap it into /Applications (quit the app first)
make clean-build  # remove the PyInstaller output afterwards
```

The engine is `src/rawtims/` (no Qt), the GUI `src/rawtims_gui/`; every user-visible name is in
`src/rawtims/branding.py`. Test fixtures under `tests/fixtures/tripoli/` come from CIRDLES Tripoli and the
Tripoli manual; see the `NOTICE` there and `tests/fixtures/MANIFEST.toml`.

Builds stamp the version from the checkout's `pyproject.toml`, independent of the
venv's editable metadata. A frozen version mismatch fails even with
`BUILD_ARGS=--no-smoke-test`, before any archive is created. `--version-output FILE`
writes the bare package version without opening a window. Set
`APPLE_SIGNING_IDENTITY=-` to retain PyInstaller's ad hoc signing for a local check;
normal builds automatically use **UPb Lab Code Signing** if its certificate exists.
`RAWTIMS_BUILD_ROOT` can select another disposable folder outside the checkout.

Verify the chosen ribbon icon and regenerate its Windows `.ico` with `.venv/bin/python scripts/make_icon.py`
and guide screenshots with `.venv/bin/python scripts/capture_guide.py`. Both use
existing development dependencies; they do not install packages. The SVG, seven PNGs
(including refined 16/32 px artwork) and macOS ICNS are copied unchanged from
IDTIMS_UPbRPy v2c; [provenance and SHA-256](docs/icon-provenance.json) and the
[small-size comparison](docs/icon-small-sizes.png) record the selection.
