"""Application identity, public update key, shared TLS and bundled lab notes."""

from pathlib import Path

from rawtims import branding
from rawtims_gui.labupdate import UpdateConfig
from rawtims_gui.labupdate.tls import urlopen

PUBLIC_KEY = 'dW50cnVzdGVkIGNvbW1lbnQ6IG1pbmlzaWduIHB1YmxpYyBrZXk6IEQyRUE0MzNEMURGRTA2RTEKUldUaEJ2NGRQVVBxMHMyUWlMYThIc05ITitNVkdrajVxc0FkMGhmN21xd2tNbGVsMlB1NWNVVUoK'
REPO = f"duserzym/{branding.APP_NAME}"


def release_notes(version: str) -> str | None:
    """Read the same packaged notes in a checkout, wheel or frozen app."""
    if not version or Path(version).name != version or "\\" in version:
        return None
    path = Path(__file__).resolve().parent / "release-notes" / f"{version.removeprefix('v')}.md"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def update_config() -> UpdateConfig:
    return UpdateConfig(branding.DISPLAY_NAME, REPO, PUBLIC_KEY,
                        settings_org=branding.QSETTINGS_ORG, settings_app=branding.QSETTINGS_APP,
                        opener=urlopen, release_notes=release_notes)
