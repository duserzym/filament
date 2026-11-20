"""Canonical source and vendoring rules for labupdate."""

The canonical copy is in `duserzym/UPbRPy`, at `GUI/labupdate`.
Vendored copies keep a `VENDORED` file containing the source commit.
Do not edit vendored copies: change the canonical one and recopy the folder.

The package uses only the standard library, PySide6 in `qt.py`, and optional
truststore/certifi imports in `tls.py`. Importing the package never loads Qt.
Each app supplies its own UpdateConfig and current version. Asset names are
optional platform-to-local-download-name overrides; URLs and signatures always
come from latest.json. No SHA256-only installation path exists.

Studio port map: `updates.py` supplies install-root detection, replacement
permissions, reducer and button view; `updater.py` supplies scheduling, worker
lifecycle, same-volume staging and detached replacement; `update_widgets.py`
supplies the circular check button, badge, popover and anchored version chip;
`UPbRPy/integration/tls.py` supplies the cached context/opener pattern.

Integration: configure the production Tauri public key and feed, create
Updater(config, version), call start_scheduler() after successful startup, and
connect the application's shutdown to shutdown(). That successful startup is
when the previous installation is removed. Wire the self-test argparse helpers
before creating any windows. Mac and Windows detached helpers require packaged
application smoke tests on those operating systems.
