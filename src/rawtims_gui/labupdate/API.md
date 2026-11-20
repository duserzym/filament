"""Public interfaces and Studio port origins for labupdate."""

All paths accept `str` or `pathlib.Path` unless annotated otherwise. Core modules
load without Qt. Studio delegates application updates to this package and retains its standards checks.

| Module | Public API |
| --- | --- |
| `config` | `UpdateConfig(app_name: str, repo: str, pubkey: str, feed_url: str \| None = None, asset_names: dict[str, str] \| None = None, download_page: str \| None = None, max_manifest_bytes: int = 262144, max_archive_bytes: int = 1073741824, release_notes: Callable[[str], str \| None] \| None = None, opener: Callable \| None = None, *, settings_org: str, settings_app: str)`; `platform_key() -> str` |
| `tls` | `https_context() -> ssl.SSLContext`; `urlopen(request, *, timeout)`; `reset_cache() -> None`; `describe() -> dict`; `is_certificate_error(exc) -> bool` |
| `minisign` | `SignatureError(ValueError)`; `TrustedInfo(comment: str)`; `PublicKey(key_id: bytes, key: bytes)`; `parse_public_key(pubkey: str) -> PublicKey`; `ed25519_verify(public_key: bytes, message: bytes, signature: bytes) -> bool`; `verify_bytes(data: bytes, signature_text: str, pubkey: str) -> TrustedInfo`; `verify_file(path, signature_text: str, pubkey: str) -> TrustedInfo` |
| `manifest` | `NoPublicRelease(ValueError)`; `NoUpdateForPlatform(ValueError)`; `Release(version: str, notes: str, pub_date: str \| None, url: str, signature: str)`; `parse_version(value: str) -> tuple`; `compare_versions(a: str, b: str) -> int`; `validate_url(url: str) -> str`; `parse_manifest(data, config, *, target=None) -> Release`; `fetch_manifest(config, opener=tls.urlopen) -> Release` |
| `install` | `NotConfiguredError(ValueError)`; `is_frozen() -> bool`; `install_root() -> Path \| None`; `can_replace(root) -> bool`; `previous_path(root) -> Path`; `cleanup_previous(root) -> None`; `download_archive(release, config, opener=tls.urlopen, *, progress=None, cancelled=None) -> Path`; `prepare_install(archive, root, release, config, runner=detached_runner) -> Path`; `detached_runner(command)` |
| `state` | `STATES`; `UpdateState(status='idle', info=None, progress=0, total=0, path=None, message='', manual=False, kind='', app_name='Application', host='github.com')`; `transition(state: UpdateState, event) -> UpdateState`; `classify_error(exc, *, app='Application', host='github.com') -> tuple[str, str]`; `ButtonView(text: str, action: str \| None, badge: bool, busy: bool)`; `button_view(state: UpdateState, version: str, auto_download=True) -> ButtonView` |
| `qt` | `Updater(config, version: str, parent=None, *, opener=None, runner=None, preview=None, settings=None, root=None)`; `CheckUpdatesButton(updater, open_settings=None, parent=None)`; `VersionChip(updater, parent=None)`; `UpdatePopover(button, open_settings=None)`; `WhatsNewCard(button)`; `NotesLabel(parent=None)`; `release_notes_url(updater) -> str` |
| `selftest` | `run_self_test(config, manifest_url=None, archive_dir=None) -> dict`; `add_self_test_argument(parser)`; `handle_self_test(args, config) -> int \| None`; `SELF_TEST_DATA`, `SELF_TEST_PUBKEY`, `SELF_TEST_SIGNATURE` |

`labupdate.__init__` re-exports only `UpdateConfig` and `platform_key`.

`Updater` exposes `stateChanged(state)`, `whatsNew(version, text)`, `config`, `version`, `root`, read-only
`state`, `prefs`, `auto_download`, and these methods:

```python
start()                            # record version, announce upgrade, start scheduling
start_scheduler()                  # compatibility alias for start()
current_notes() -> str              # bundled, matching pending, or fallback
show_whats_new()                    # emit running-version notes again
check(manual=False)
download()
install()                          # launch detached helper, then request Qt quit
set_auto_download(enabled)
shutdown()                         # join workers before destroying the updater
```

`VersionChip.anchor_to(parent_widget)` follows a canvas's geometry.
`VersionChip.open_dialog(manual=False)` opens the popover and optionally checks.
`UpdatePopover.reanchor()` clamps it to the available screen. The check button's
`badge` and `busy` dynamic properties reflect the current state.

Injected openers have the `opener(request, *, timeout)` signature and return a
context-managed binary stream with `read(n)` and `headers`. The timeout is a
socket stall timeout, with no total-transfer deadline. Injected runners take a
command list and must launch (or execute, in tests) the helper. Download progress
receives `(received_bytes, total_bytes)`, with total zero when unknown.
Cancellation callbacks return true to stop. `download_archive` owns a fresh temp
folder; its caller must remove `path.parent` after use. Updater does that during
shutdown. Installation staging lives beside the app and is removed by the helper
on success. A failed swap rolls the old app back; a successful swap retains its
backup until `cleanup_previous`, called by `start_scheduler` on successful start.

Manifest fields are type-checked. An empty signature is parseable but cannot be
installed. URLs accept HTTPS and local `file://` smoke-test input. `asset_names`
overrides only local download names by platform; the feed supplies URLs and
signatures. Source checkouts and unsupported install roots can check manually;
they cannot install. Linux can parse a feed and download using the core API, but
replacement is supported only for macOS bundles and Windows app folders.

The reducer accepts the Studio event forms: `check_started` (optional manual
boolean), `no_update`, `found` (Release or a version-bearing dict),
`download_started`, `progress` (received, total), `downloaded` (Path), `failed`
(exception, preserving its raw text), `install_started`, and `unsupported` (raw reason, optional
kind). Illegal events are ignored. `state.message` supplies the Details line;
`button_view` supplies the friendly message with app/host substitution.

Self-test results include `ok`, `verification_ran`, `tls`, `https`, `signature`,
`public_key` and an optional `manifest` result. Offline HTTPS is reported as
`network` and does not fail. Certificate errors and unexpected transport errors
fail. The positive and tampered embedded vectors must both behave correctly.
An unconfigured production key is reported without failing; a malformed key
fails. `archive_dir`, when provided, contains the manifest archive's basename;
otherwise the self-test downloads it to a temporary folder. That path always
verifies with the embedded disposable key and never installs anything. Neither
`install.py` nor the production updater imports that key.

Studio port origins:

| New code | Studio source |
| --- | --- |
| `install.is_frozen`, `install_root`, `can_replace` | Same functions in `GUI/updates.py`, with no app identity assumptions |
| `state.UpdateState`, `transition`, `button_view` | `UpdateState`, `transition`, `check_button_view` in `GUI/updates.py`; nine canonical states, typed error classification, app/host substitution, raw Details preserved |
| `install.previous_path`, `cleanup_previous`, `detached_runner`, `prepare_install` | `previous_path`, `cleanup_previous`, `_detached_runner`, `_prepare_install` in `GUI/updater.py`; generic names, minisign verification, tar/zip extraction with safe links |
| `qt._Worker`, `Updater` | `UpdateWorker`, `Updater` in `GUI/updater.py`; Tauri feed, no standards checks, no shiboken dependency, explicit shutdown |
| Qt controls | `CheckUpdatesButton`, `UpdatePopover`, `VersionChip` in `GUI/update_widgets.py`; palette roles and embedded QPainter arrows, shared compact popover |
| TLS caching | `https_context`, `_https_opener`, `reset_cache`, `urlopen`, `is_certificate_error` in `UPbRPy/integration/tls.py`; adds optional OS truststore, valid environment overrides and trust-source diagnostics |
| `minisign`, `manifest`, `selftest` | New Tauri-compatible verification, feed parsing and frozen-build checks |

Cryptographic references: [RFC 8032 sections 5.1 and 7.1](https://www.rfc-editor.org/rfc/rfc8032.txt),
[minisign's verifier](https://github.com/jedisct1/minisign/blob/master/src/minisign.c),
and [Tauri updater feed/signature format](https://v2.tauri.app/plugin/updater/).
The checked-in cargo-tauri fixture cross-checks the actual signing format.

Integration remains in the host apps: provide their production public keys,
feed/settings identities and current versions; create the controls; start the
scheduler only after successful startup; wire the CLI smoke-test path before GUI
startup; include optional truststore/certifi in each frozen build. Run packaged
macOS and Windows restart/relaunch tests on the target systems. Vendored copies
must record the canonical source commit as specified in SOURCE.md.

Release tooling (not imported by the running package):

```python
release.build_feed(*, repo, version, notes_file, archives, pubkey_file, out,
                   sign_with=None) -> dict
release.main(argv=None) -> int
```

`archives` maps Tauri targets to local archive paths. The CLI requires
`--repo`, `--version`, `--notes-file`, `--darwin-aarch64`, `--pubkey-file`, and
`--out`; `--windows-x86_64` and `--sign-with` are optional. Missing signatures
can be created with cargo-tauri; all signatures must verify before the feed is
written. Notes must contain 1–600 characters and the version must be stable.

`UpdateConfig.opener` supplies the default transport; the `Updater(opener=...)`
argument overrides it. The self-test uses the same configured transport.
`release_notes(version)` returns bundled text or None. `start()` records
`updates/last_seen_version` on first install; a higher running version emits
`whatsNew` once on the next event-loop turn, with bundled notes, matching
`updates/pending_notes`, or `Updated to v<current>.` Installation saves and
syncs pending version/notes before staging. The popover's What's new link
re-emits the running-version notes. A check button owns its `whats_new_card`.
The card closes on ✕, Escape, or an outside click. Notes in update views are
plain text, limited to four rendered lines, with a version-tag Release notes
link opened by QDesktopServices. `VersionChip` always displays `v<current>`.
