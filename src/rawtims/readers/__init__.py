"""Read supported processed run files into :class:`~rawtims.model.Run` objects.

Formats are recognised by content, never by extension alone:

* IsoLinx ``.TIMSDP``: text whose first line is ``#HEADER`` with ``Version``
  and ``MethodName`` keys and a ``#CYCLES`` table (:mod:`rawtims.readers.timsdp`);
* IonVantage ``.xls``: an OLE2 (Excel 97-2003) workbook with a ``CYCLE`` sheet
  whose A1 is ``CYCLE Data`` (:mod:`rawtims.readers.ionvantage`).

* Triton/Neptune EXP: exact ``<instrument> Analysis Data Report`` first line;
* Nu TIMS TXT: the seven-field individual-answers header signature;
* OGTripoli ID-TIMS cycle CSV: the exact EARTHTIME template heading.

``open_run(path)`` reads one file; ``open_paths(paths)`` reads files and
folders (recursively, skipping hidden and temporary files) and returns the
runs plus ``(path, reason)`` for everything it did not read.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from rawtims.branding import SESSION_FORMAT
from rawtims.model import FORMAT_IONVANTAGE_XLS, FORMAT_ISOLINX_TIMSDP, Run
from rawtims.readers._xls import OLE2_MAGIC, open_xls
from rawtims.readers.functions import suggest_fraction_id
from rawtims.readers.ionvantage import is_ionvantage_book, read_ionvantage
from rawtims.readers.timsdp import decode, looks_like_timsdp, read_timsdp

MAX_TEXT_BYTES = 64 * 1024 * 1024
_TEMP_SUFFIXES = (".tmp", ".temp", ".bak", ".swp", ".part", ".crdownload")


@dataclass(frozen=True)
class Sniff:
    """The detected format (None when unsupported) and, when unsupported, why."""

    format: str | None
    reason: str = ""

    @property
    def supported(self) -> bool:
        return self.format is not None


class UnsupportedFile(ValueError):
    """Raised by :func:`open_run` for a file no reader handles; the message is the reason."""


def _sniff_bytes(data: bytes) -> Sniff:
    if not data:
        return Sniff(None, "empty file")
    # Projects have a BinaryFormatter header and an inert class-name label.
    # Keep them out of run dispatch; read_trip is an explicit project API.
    if (len(data) >= 17 and data[0] == 0 and int.from_bytes(data[1:5], "little", signed=True) > 0
            and data[5:17] == b"\xff\xff\xff\xff\x01\x00\x00\x00\x00\x00\x00\x00"
            and b"Tripoli.TripoliWorkProduct" in data[:4096]):
        return Sniff(None, "legacy Tripoli project, not a raw run file (use read_trip)")
    if data.startswith(OLE2_MAGIC):
        try:
            book = open_xls(file_contents=data, on_demand=True)
        except Exception as error:  # noqa: BLE001 - any parse failure is a reason, not a crash
            return Sniff(None, f"OLE2 file that cannot be read as an Excel 97-2003 workbook ({type(error).__name__}: {error})")
        try:
            ok, reason = is_ionvantage_book(book)
        finally:
            book.release_resources()
        return Sniff(FORMAT_IONVANTAGE_XLS) if ok else Sniff(None, reason)
    if data.startswith(b"PK\x03\x04"):
        return Sniff(None, "zip container (for example .xlsx); IonVantage writes Excel 97-2003 .xls")
    if data.startswith(b"SQLite format 3\x00"):
        return Sniff(None, "SQLite database (for example IsoLinx .TIMSAD raw integrations); not read")
    if b"\x00" in data[:4096]:
        return Sniff(None, "binary file of unknown format")
    text = decode(data)
    head = text.lstrip()[:200]
    if head.startswith(("New Tripoli", "Tripoli")):
        return Sniff(None, "Tripoli report, not a raw run file")
    if head.startswith("{") and SESSION_FORMAT in text[:4096]:
        return Sniff(None, "saved session, not a run file (open it on its own, or with File > Open Session…)")
    if head.startswith('{') and 'rawtims completed cycle snapshot' in text[:4096]:
        from rawtims.completed_folder import FORMAT
        return Sniff(FORMAT)
    from rawtims.readers.processed import signature as processed_signature
    from rawtims.readers.idtims_template import FORMAT as TEMPLATE, signature as template_signature
    processed = processed_signature(text)
    if processed:
        return Sniff(processed)
    if template_signature(text):
        return Sniff(TEMPLATE)
    ok, reason = looks_like_timsdp(text)
    return Sniff(FORMAT_ISOLINX_TIMSDP) if ok else Sniff(None, reason)


def _read_limited(path: Path) -> bytes:
    with open(path, "rb") as handle:
        head = handle.read(8)
        if head.startswith(OLE2_MAGIC) or len(head) < 8:
            return head + handle.read()
        data = head + handle.read(MAX_TEXT_BYTES)
        if handle.read(1):
            raise UnsupportedFile(f"text file larger than {MAX_TEXT_BYTES // (1024 * 1024)} MB")
        return data


def sniff(path: str | os.PathLike[str]) -> Sniff:
    """Detect the format of ``path`` from its content."""
    path = Path(path)
    if not path.is_file():
        return Sniff(None, "not a file")
    try:
        data = _read_limited(path)
    except UnsupportedFile as error:
        return Sniff(None, str(error))
    except OSError as error:
        return Sniff(None, f"cannot read: {error.strerror or error}")
    return _sniff_bytes(data)


def open_run(path: str | os.PathLike[str]) -> Run:
    """Read one run file. Raises :class:`UnsupportedFile` with the reason when no reader applies."""
    path_obj = Path(path)
    if path_obj.is_dir() and path_obj.suffix.lower() == ".raw":
        from rawtims.readers.ionvantage_raw import workbook_path
        return open_run(workbook_path(path_obj))
    if not path_obj.is_file():
        raise UnsupportedFile(f"{path}: not a file")
    data = _read_limited(path_obj)
    detected = _sniff_bytes(data)
    if detected.format == FORMAT_IONVANTAGE_XLS:
        return read_ionvantage(path, data)
    if detected.format == FORMAT_ISOLINX_TIMSDP:
        return read_timsdp(path, data)
    from rawtims.readers.processed import FORMATS, read_processed
    from rawtims.readers.idtims_template import FORMAT as TEMPLATE, read_template
    if detected.format in FORMATS:
        return read_processed(path, data)
    if detected.format == TEMPLATE:
        return read_template(path, data)
    from rawtims.completed_folder import FORMAT, read_snapshot
    if detected.format == FORMAT:
        return read_snapshot(path, data)
    raise UnsupportedFile(f"{path_obj.name}: {detected.reason}")


def is_ignored(path: Path) -> bool:
    """Hidden files and folders, Office lock files (``~$…``) and editor/temporary files."""
    name = path.name
    return name.startswith((".", "~$")) or name.endswith("~") or name.lower().endswith(_TEMP_SUFFIXES) or name in {"Thumbs.db", "desktop.ini"}


def _walk(root: Path) -> Iterable[Path]:
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if is_ignored(entry):
            continue
        if entry.is_dir() and entry.suffix.lower() == ".raw":
            from rawtims.readers.ionvantage_raw import workbook_path
            try:
                yield workbook_path(entry)
            except UnsupportedFile:
                yield entry
        elif entry.is_dir():
            yield from _walk(entry)
        elif entry.is_file():
            yield entry


def open_paths(paths: Iterable[str | os.PathLike[str]]) -> tuple[list[Run], list[tuple[Path, str]]]:
    """Read every run among files and folders (folders recursively, in name order).

    Returns ``(runs, skipped)``; ``skipped`` lists ``(path, reason)`` for files
    that are not run files or failed to read. Hidden and temporary files are
    ignored silently; a path given explicitly that does not exist is skipped.
    """
    runs: list[Run] = []
    skipped: list[tuple[Path, str]] = []
    seen: set[Path] = set()
    for given in paths:
        root = Path(given)
        if root.is_dir() and root.suffix.lower() == ".raw":
            candidates = [root]
        elif root.is_dir():
            candidates = list(_walk(root))
        elif root.is_file():
            candidates = [root]
        else:
            skipped.append((root, "does not exist"))
            continue
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            try:
                runs.append(open_run(path))
            except UnsupportedFile as error:
                reason = str(error)
                prefix = f"{path.name}: "
                skipped.append((path, reason.removeprefix(prefix)))
            except Exception as error:  # noqa: BLE001 - one bad file must not stop a folder import
                skipped.append((path, f"could not be read ({type(error).__name__}: {error})"))
    return runs, skipped


__all__ = ["Sniff", "UnsupportedFile", "is_ignored", "open_paths", "open_run", "sniff", "suggest_fraction_id"]
