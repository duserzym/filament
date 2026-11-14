"""PyInstaller recipe for the desktop app.

Every user-visible name comes from src/rawtims/branding.py and the version
from pyproject.toml, so renaming the app never touches this file.
"""

from __future__ import annotations

from pathlib import Path
import sys
import tomllib

from PyInstaller.utils.hooks import copy_metadata


PACKAGING_DIRECTORY = Path(SPECPATH).resolve()
PROJECT_ROOT = PACKAGING_DIRECTORY.parent
SOURCE_ROOT = PROJECT_ROOT / "src"
PROJECT_VERSION = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]

sys.path.insert(0, str(SOURCE_ROOT))
from rawtims import branding  # noqa: E402

if branding.VERSION != PROJECT_VERSION:
    raise SystemExit(
        f"Installed rawtims metadata says {branding.VERSION}, pyproject.toml says {PROJECT_VERSION}; "
        "reinstall with `pip install -e .` before building."
    )
APPLICATION_NAME = branding.DISPLAY_NAME
EXECUTABLE_NAME = branding.EXECUTABLE_NAME
BUNDLE_ID = branding.BUNDLE_ID
URL_SCHEME = branding.URL_SCHEME

data_files = [
    (str(SOURCE_ROOT / "rawtims_gui" / "studio" / "assets" / "icons"), "rawtims_gui/studio/assets/icons"),
]
# importlib.metadata.version("rawtims") must work in the frozen app.
data_files += copy_metadata("rawtims")

analysis = Analysis(
    [str(SOURCE_ROOT / "rawtims_gui" / "main.py")],
    pathex=[str(SOURCE_ROOT)],
    binaries=[],
    datas=data_files,
    hiddenimports=["PySide6.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "IPython",
        "PyQt5",
        "PyQt6",
        "bokeh",
        "jedi",
        "jupyterlab",
        "keyring",
        "matplotlib",
        "nbformat",
        "notebook",
        "pandas",
        "panel",
        "pygments",
        "pytest",
        "requests",
        "scipy",
        "tkinter",
        "traitlets",
        "zmq",
    ],
    noarchive=False,
    optimize=1,
)

python_archive = PYZ(analysis.pure)

executable = EXE(
    python_archive,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=EXECUTABLE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

application_directory = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=EXECUTABLE_NAME,
)

if sys.platform == "darwin":
    application_bundle = BUNDLE(
        application_directory,
        name=f"{APPLICATION_NAME}.app",
        icon=None,
        bundle_identifier=BUNDLE_ID,
        version=PROJECT_VERSION,
        info_plist={
            "CFBundleDisplayName": APPLICATION_NAME,
            "CFBundleName": APPLICATION_NAME,
            "CFBundleShortVersionString": PROJECT_VERSION,
            "CFBundleVersion": PROJECT_VERSION,
            "LSApplicationCategoryType": "public.app-category.education",
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            "NSRequiresAquaSystemAppearance": False,
            # <scheme>:// links (later, from UPb Lab) open the app.
            "CFBundleURLTypes": [
                {
                    "CFBundleURLName": f"{BUNDLE_ID}.link",
                    "CFBundleURLSchemes": [URL_SCHEME],
                    "CFBundleTypeRole": "Viewer",
                }
            ],
        },
    )
