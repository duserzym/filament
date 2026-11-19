"""Every user-visible name of the application, in one place.

Renaming the app means editing this file, the README title and the
``[project.scripts]`` entry in ``pyproject.toml``; a test checks that the
literal app name appears nowhere else under ``src/``, ``scripts/`` or
``packaging/``.

The session format name and file extension are deliberately neutral and do
not follow ``APP_NAME``, so a rename does not orphan saved sessions.
"""

from __future__ import annotations

from rawtims._version import package_version

APP_NAME = "filament"
DISPLAY_NAME = APP_NAME
EXECUTABLE_NAME = APP_NAME
VERSION = package_version()

# macOS bundle identifier and the URL scheme for links from UPb Lab.
BUNDLE_ID = f"org.upblab.{APP_NAME}"
URL_SCHEME = APP_NAME

# QSettings(QSETTINGS_ORG, QSETTINGS_APP) holds per-viewer preferences.
QSETTINGS_ORG = "UPbLab"
QSETTINGS_APP = APP_NAME

# Folder name under the platform cache root (build output, test map).
CACHE_DIR_NAME = APP_NAME

# The `Raw App` provenance value written into exports.
RAW_APP_LABEL = f"{APP_NAME} {VERSION}"

# Saved session files.
SESSION_FORMAT = "rawtims session"
SESSION_FORMAT_VERSION = 1
SESSION_EXTENSION = ".rawtims"

# Chosen ribbon artwork; source bytes and hashes are in docs/icon-provenance.json.
ICON_BASENAME = APP_NAME
ICON_FILENAME = f"{ICON_BASENAME}.icns"
ICO_FILENAME = f"{ICON_BASENAME}.ico"
GUI_ICON_FILENAME = f"{ICON_BASENAME}_256.png"
ICON_SIZES = (16, 32, 64, 128, 256, 512, 1024)
GUI_ICON_FILENAMES = {size: f"{ICON_BASENAME}_{size}.png" for size in ICON_SIZES}
