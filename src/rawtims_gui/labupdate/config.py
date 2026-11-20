"""Application identity, feed limits and Tauri platform keys."""

from dataclasses import dataclass, field
import platform
from typing import Callable


@dataclass(frozen=True)
class UpdateConfig:
    """Per-application settings; settings identity is required by keyword."""

    app_name: str
    repo: str
    pubkey: str
    feed_url: str | None = None
    settings_org: str = field(kw_only=True)
    settings_app: str = field(kw_only=True)
    asset_names: dict[str, str] | None = None
    download_page: str | None = None
    max_manifest_bytes: int = 256 * 1024
    max_archive_bytes: int = 1024 * 1024 * 1024
    release_notes: Callable[[str], str | None] | None = None
    opener: Callable | None = None

    def __post_init__(self):
        if self.max_manifest_bytes <= 0 or self.max_archive_bytes <= 0:
            raise ValueError("Update size limits must be positive")
        if self.feed_url is None:
            object.__setattr__(self, "feed_url", f"https://github.com/{self.repo}/releases/latest/download/latest.json")
        if self.download_page is None:
            object.__setattr__(self, "download_page", f"https://github.com/{self.repo}/releases/latest")
        if self.asset_names is not None:
            object.__setattr__(self, "asset_names", dict(self.asset_names))


def platform_key() -> str:
    """Return a supported Tauri target, rejecting unknown architectures."""
    system = {"Darwin": "darwin", "Windows": "windows", "Linux": "linux"}.get(platform.system())
    machine = platform.machine().lower()
    arch = {"arm64": "aarch64", "aarch64": "aarch64", "amd64": "x86_64", "x86_64": "x86_64"}.get(machine)
    key = f"{system}-{arch}"
    if key not in {"darwin-aarch64", "darwin-x86_64", "windows-x86_64", "linux-x86_64"}:
        raise ValueError(f"Unsupported update platform: {platform.system()} {machine}")
    return key
