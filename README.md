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
make build BUILD_ARGS=--archive  # ZIP, update tarball and SHA256 checksums
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

## In-app updates and releases

The circular-arrows button and version chip sit at the right of the review
toolbar (beside the app name in the classic layout). The button opens the update
popover; the chip opens Update settings. Supported installed apps check after
8 seconds and every 6 hours, follow the latest stable GitHub release, and verify
its signature before replacement. Source checkouts can check manually and offer
the GitHub download page. A previous beta preference migrates silently to stable.
After an in-app update or manual reinstall, an existing installation shows
“What's new” once. Its notes can be reopened from the popover.

For each version, write `release-notes/<version>.md`: plain lab-user text or at
most five `- ` bullets, no headings, at most 600 characters. The feed generator
rejects missing, empty or oversized notes. The root files are authoritative;
`src/rawtims_gui/release-notes` links to them for setuptools package data, and the
PyInstaller recipe bundles them in the same package location. This lets both
wheels and frozen apps show notes after manual reinstalls.

To publish a macOS arm64 release:

```sh
.venv/bin/python -m pip install -e '.[gui,dev,build]'
make test
make build BUILD_ARGS="--archive --sign-with $HOME/.tauri/filament-updater.key"
# Alternatively: FILAMENT_UPDATER_KEY=/path/to/key make build BUILD_ARGS=--archive
```

Install `cargo-tauri` for the signing command. The update key is independent of
the Apple code-signing identity. The build keeps the existing
`filament-<version>-darwin-arm64.zip` and `.zip.sha256`, and also creates
`filament-<version>-macOS-arm64.app.tar.gz` with bundle symlinks preserved.
With an update key, the vendored `labupdate.release` signs the tarball and verifies
it against this app's embedded public key before writing `.app.tar.gz.sig` and
`latest.json`. `SHA256SUMS.txt` covers the release assets. Upload the ZIP, tarball,
signature, `latest.json`, and checksum files to the public GitHub release tagged
`v<version>` in `duserzym/filament`; copy the short lab notes into the release
description too. Without an update key, `--archive` still produces the archives
and checksums, but no signed feed.

The frozen smoke test runs `--update-self-test file:///.../latest.json` with a
disposable signed archive, verifies positive and tampered signature vectors,
and requires a valid production public key. It sets nonexistent `SSL_CERT_FILE`
and `SSL_CERT_DIR` paths and uses `sandbox-exec`, when available, to hide both
Homebrew OpenSSL certificate folders. Every verification must pass; only an
offline github.com reachability result is allowed with a warning. The command
also supports `--update-self-test-output FILE` for windowed executables.
Before publishing, test replacement and relaunch from an installed frozen app
on each target OS. The canonical package and its source hashes are recorded in
`src/rawtims_gui/labupdate/VENDORED`; change its upstream copy and recopy it,
without editing the vendored sources here.

Verify the chosen ribbon icon and regenerate its Windows `.ico` with `.venv/bin/python scripts/make_icon.py`
and guide screenshots with `.venv/bin/python scripts/capture_guide.py`. Both use
existing development dependencies; they do not install packages. The SVG, seven PNGs
(including refined 16/32 px artwork) and macOS ICNS are copied unchanged from
IDTIMS_UPbRPy v2c; [provenance and SHA-256](docs/icon-provenance.json) and the
[small-size comparison](docs/icon-small-sizes.png) record the selection.
