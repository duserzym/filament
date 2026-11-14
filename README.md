# filament (working name)

Raw ID-TIMS data review for the UPb Lab suite: ingest IsotopX IsoprobeT output, review and filter cycles, hand reduced ratios to the ID-TIMS reduction app. Local repository only; the name is a working name until Yiming confirms it.

## Development

```sh
/opt/homebrew/bin/python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[gui,dev,build]'
make test-quick   # affected tests after each change (skips slow tests)
make test         # full suite, before any build or install
make build        # PyInstaller app outside the repository, then the frozen smoke test
make clean-build  # remove the PyInstaller output afterwards
```

The engine is `src/rawtims/` (no Qt), the GUI `src/rawtims_gui/`; every user-visible name is in
`src/rawtims/branding.py`. Test fixtures under `tests/fixtures/tripoli/` come from CIRDLES Tripoli and the
Tripoli manual; see the `NOTICE` there and `tests/fixtures/MANIFEST.toml`.
