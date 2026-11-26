"""Saved sessions: fractions, runs, settings, histories and mappings as JSON (SPEC F18, section 3 "Session").

A session file holds no raw values and no results. It names each raw file
(path relative to the session file, absolute path, size, SHA-256), and keeps
what is needed to rebuild the review exactly: the run's element, the
analysis settings before and after its history, the history itself
(:attr:`rawtims.analysis.Analysis.history`), a SHA-256 of the resulting
include flags, the fraction identity and setup fields, and the
function-to-contract mapping of each run (the user's edit, if any, and the
mapping in effect). New mapping changes also live in the analysis history,
including the flags adopted by joining functions. Optional legacy comparison
masks preserve the original per-ratio selections after reconciliation.

Unlinked sessions write version 1; sessions with database links write version 2.
Readers accept both. Each fraction’s optional ``database_link`` is a
:data:`rawtims.branding.DATABASE_LINK_FORMAT` version 1 snapshot (including confirmation and chemistry).

Format (``format`` = :data:`rawtims.branding.SESSION_FORMAT`)::

    {
      "format": "rawtims session", "format_version": 1,
      "app": "<app> <version>", "saved_at": "2026-11-14T21:05:09+00:00",
      "runs": [{
        "run_id": "0193…", "element": "Pb",
        "raw": {"name": "…xls", "relative": "data/…xls", "absolute": "/…/data/…xls",
                "size": 1234, "sha256": "…", "format": "ionvantage_xls", "format_version": null},
        "initial_settings": {…}, "settings": {…},
        "history_version": 1, "history": [{"op": "apply_rule", …}, …],
        "redo_history": [{"op": "toggle_cycles", …}],
        "mask_sha256": "…"
      }],
      "fractions": [{
        "fraction_id": "z1", "runs": {"Pb": "0193…", "U": "0194…"},
        "fields": {"sample": "…", "timezone": "America/Boise", "collector": "D", …},
        "mappings": {"Pb": {"source": "edited", "edit": {MethodMapping}, "resolved": {MethodMapping}}}
      }]
    }

:func:`load_session` resolves each raw file (the relative path first, then
the absolute path, then a file of the same name next to the session),
checks its SHA-256, reads it again and replays the history with
``strict=True``. A missing file, a changed file (hash mismatch), a file that
no longer reads, or a history that does not replay to the saved flags is a
:class:`SessionProblem` for that run. Such a run is **not** opened (never
silently different); its saved record is kept in :attr:`SessionState.missing`,
so saving the session again writes it back unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from rawtims.analysis import (
    HISTORY_VERSION,
    SETTING_NAMES,
    Analysis,
    AnalysisSettings,
    ReplayMismatch,
    replay,
)
from rawtims.branding import (
    RAW_APP_LABEL,
    SESSION_EXTENSION,
    SESSION_FORMAT,
    SESSION_FORMAT_VERSION,
)
from rawtims.fractions import Fraction
from rawtims.mapping import ElementMapping, MappingError, MethodMapping
from rawtims.readers import UnsupportedFile, open_run
from rawtims.stats import STAT_MODES
from rawtims.upbdb import DatabaseError, DatabaseLink

ELEMENTS = ("Pb", "U")
# Fraction attributes saved under "fields" (identity, setup and provenance fields of the contract).
FRACTION_FIELDS = (
    "sample", "beaker", "source_mount", "source_grain", "source_spot", "aliquot",
    "sample_weight_mg", "spike_weight_g", "spike_type", "spike", "collector",
    "pb_collector_detail", "instrument", "timezone", "notes",
)
PROBLEM_KINDS = ("missing", "changed", "unreadable", "replay", "mapping", "composition")
# Largest session file read (a session holds no per-cycle values, so real ones are far smaller).
MAX_SESSION_BYTES = 32 * 1024 * 1024


class SessionError(ValueError):
    """The file is not a session this version can read; the message says why."""


@dataclass(frozen=True)
class SessionProblem:
    """Something in a session that could not be restored as saved (shown to the user, never ignored)."""

    kind: str
    message: str
    fraction_id: str | None = None
    element: str | None = None
    run_id: str | None = None
    path: str | None = None


@dataclass
class MissingRun:
    """A run of the session that was not opened, with its saved records kept verbatim for the next save."""

    fraction: Fraction
    element: str
    record: dict[str, Any]
    mapping: dict[str, Any] | None
    problem: SessionProblem


@dataclass
class SessionState:
    """What a session holds, in memory.

    ``mapping_edits`` maps run_id to the user's mapping edit; ``mapping_sources``
    run_id to where the mapping in effect came from (``edited``, ``remembered``,
    ``proposed``). On load, ``saved_mappings`` has the mapping that was in
    effect when the session was saved, so the caller can check its own
    resolution against it. ``recovery`` is the optional block of a crash
    recovery copy (see ``save_session(extra=…)``). ``stat_mode`` is the project
    default, including for later imports. Loading preserves run settings;
    the workspace checks agreement before export, including old mixed sessions.
    """

    fractions: list[Fraction] = field(default_factory=list)
    mapping_edits: dict[str, MethodMapping] = field(default_factory=dict)
    mapping_sources: dict[str, str] = field(default_factory=dict)
    saved_mappings: dict[str, MethodMapping] = field(default_factory=dict)
    missing: list[MissingRun] = field(default_factory=list)
    recovery: dict[str, Any] | None = None
    stat_mode: str = "arithmetic"
    presentation: dict[str, Any] = field(default_factory=dict)
    composition: dict[str, Any] = field(default_factory=dict)

    def analyses(self) -> list[Analysis]:
        return [a for fraction in self.fractions for a in (fraction.pb, fraction.u) if a is not None]


# ----------------------------------------------------------------- helpers
def session_sha256(path: str | os.PathLike[str]) -> str:
    """SHA-256 of a saved session file (the contract's ``Raw App Session SHA256``)."""
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def mask_sha256(analysis: Analysis) -> str:
    """SHA-256 of the include flags (cycle flags and block flags), to check a replay end to end."""
    digest = hashlib.sha256()
    digest.update(f"{analysis.included.shape[0]}x{analysis.included.shape[1]};".encode())
    digest.update(np.packbits(analysis.included, axis=None).tobytes())
    digest.update(b";")
    digest.update(np.packbits(analysis.block_included, axis=None).tobytes())
    return digest.hexdigest()


def initial_settings(analysis: Analysis) -> AnalysisSettings:
    """The settings before the history: the current ones with every recorded setting change undone."""
    values = analysis.settings.to_dict()
    for op in reversed(analysis.history):
        if op["op"] == "set_setting":
            values[op["name"]] = op["old"]
    return AnalysisSettings(**values)


def _mapping_record(mapping: ElementMapping | None) -> dict[str, Any] | None:
    if mapping is None:
        return None
    return MethodMapping(
        method=mapping.method or "",
        element=mapping.element,
        ratios={ratio: mapped.to_dict() for ratio, mapped in mapping.ratios.items()},
        collector=mapping.collector,
    ).to_dict()


def same_ratios(a: MethodMapping | Mapping[str, Any] | None, b: MethodMapping | Mapping[str, Any] | None) -> bool:
    """Whether two mappings choose the same function (and inversion) for every contract ratio."""
    def ratios(m: Any) -> dict[str, Any] | None:
        if m is None:
            return None
        data = m.to_dict() if isinstance(m, MethodMapping) else MethodMapping.from_dict(m).to_dict()
        return {"element": data["element"], "ratios": data["ratios"]}

    return ratios(a) == ratios(b)


def _raw_record(analysis: Analysis, session_dir: Path | None) -> dict[str, Any]:
    raw = analysis.run.raw
    absolute = Path(raw.path).expanduser().resolve(strict=False)
    relative: str | None = None
    if session_dir is not None:
        try:
            relative = Path(os.path.relpath(absolute, session_dir)).as_posix()
        except ValueError:  # another drive on Windows
            relative = None
    return {
        "name": raw.name,
        "relative": relative,
        "absolute": str(absolute),
        "size": raw.size,
        "sha256": raw.sha256,
        "format": raw.format,
        "format_version": raw.format_version,
    }


def _run_record(analysis: Analysis, session_dir: Path | None) -> dict[str, Any]:
    return {
        "run_id": analysis.run.run_id,
        "element": analysis.run.element,
        "raw": _raw_record(analysis, session_dir),
        "initial_reduction_parameters": analysis.initial_reduction_parameters.to_dict(),
        "initial_reduction_provenance": analysis.initial_reduction_provenance,
        "reduction_parameters": analysis.run.reduction_parameters.to_dict(),
        "reduction_provenance": analysis.run.provenance,
        "initial_settings": initial_settings(analysis).to_dict(),
        "settings": analysis.settings.to_dict(),
        "history_version": HISTORY_VERSION,
        "history": analysis.history,
        "redo_history": analysis.redo_history,
        "mask_sha256": mask_sha256(analysis),
        "legacy_pending": analysis.legacy_pending,
        "legacy_masks": {k: np.flatnonzero(~v).astype(int).tolist() for k, v in analysis.legacy_masks.items()},
    }


# ------------------------------------------------------------------ saving
def session_document(state: SessionState, path: str | os.PathLike[str] | None, *, saved_at: datetime | None = None,
                     extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The JSON document :func:`save_session` writes (``path`` sets the relative raw paths; None leaves them empty).

    The caller makes sure each fraction's ``pb_mapping`` / ``u_mapping`` is the
    mapping in effect (the GUI workspace syncs them); a fraction without one
    falls back to :meth:`rawtims.fractions.Fraction.mapping`.
    """
    session_dir = Path(path).expanduser().resolve(strict=False).parent if path is not None else None
    stamp = saved_at or datetime.now(UTC)
    if stamp.tzinfo is None:
        raise ValueError("saved_at must be timezone-aware")
    missing = {(id(m.fraction), m.element): m for m in state.missing}
    runs: list[dict[str, Any]] = []
    fractions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for fraction in state.fractions:
        slots: dict[str, str | None] = {}
        mappings: dict[str, Any] = {}
        for element in ELEMENTS:
            analysis = fraction.analysis(element)
            lost = missing.get((id(fraction), element))
            if analysis is not None:
                run_id = analysis.run.run_id
                if run_id not in seen:
                    runs.append(_run_record(analysis, session_dir))
                    seen.add(run_id)
                slots[element] = run_id
                stored = fraction.pb_mapping if element == "Pb" else fraction.u_mapping
                resolved = stored if stored is not None else _safe_mapping(fraction, element)
                edit = state.mapping_edits.get(run_id)
                mappings[element] = {
                    "source": state.mapping_sources.get(run_id, "edited" if edit is not None else "proposed"),
                    "edit": edit.to_dict() if edit is not None else None,
                    "resolved": _mapping_record(resolved),
                }
            elif lost is not None:
                run_id = str(lost.record.get("run_id"))
                if run_id not in seen:
                    runs.append(lost.record)
                    seen.add(run_id)
                slots[element] = run_id
                if lost.mapping is not None:
                    mappings[element] = lost.mapping
            else:
                slots[element] = None
        fractions.append({
            "fraction_id": fraction.fraction_id,
            "runs": slots,
            "fields": {name: getattr(fraction, name) for name in FRACTION_FIELDS},
            "mappings": mappings,
            **({"database_link": fraction.database_link.to_dict()} if fraction.database_link is not None else {}),
        })
    document: dict[str, Any] = {
        "format": SESSION_FORMAT,
        "format_version": SESSION_FORMAT_VERSION if any(f.database_link is not None for f in state.fractions) else 1,
        "app": RAW_APP_LABEL,
        "saved_at": stamp.astimezone(UTC).isoformat(timespec="seconds"),
        "runs": runs,
        "fractions": fractions,
        "stat_mode": state.stat_mode,
    }
    if state.presentation:
        document["presentation"] = state.presentation
    if state.composition:
        from rawtims.composition import CompositionBook
        document["composition"] = CompositionBook.from_dict(state.composition).to_dict()
    if extra:
        document.update({key: value for key, value in extra.items() if key not in document})
    return document


def _safe_mapping(fraction: Fraction, element: str) -> ElementMapping | None:
    try:
        return fraction.mapping(element)
    except MappingError:
        return None


def session_fingerprint(state: SessionState, path: str | os.PathLike[str] | None) -> str:
    """Digest the applied state, excluding the timestamp and transient redo stack.

    Undoing to the saved state is clean even when another edit can be redone.
    Explicit saves still preserve that redo stack.
    """
    document = session_document(state, path, saved_at=datetime(2000, 1, 1, tzinfo=UTC))
    del document["saved_at"]
    # Missing-run records belong to the workspace; never mutate them here.
    document["runs"] = [{k: v for k, v in record.items() if k != "redo_history"} for record in document["runs"]]
    if "composition" in document:
        history = document["composition"]
        history["events"] = history["events"][:history["applied"]]
        if not history["events"]:
            del document["composition"]
    return hashlib.sha256(json.dumps(document, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _write_atomic(path: Path, text: str) -> None:
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def save_session(state: SessionState, path: str | os.PathLike[str], *, extra: Mapping[str, Any] | None = None) -> Path:
    """Write the session as JSON, atomically (temporary file in the same folder, then replace). Returns the path.

    A path without the session extension gets it. ``extra`` adds top-level
    blocks that readers ignore (the GUI's crash-recovery copy uses it).
    """
    target = Path(path).expanduser()
    if target.suffix.lower() != SESSION_EXTENSION:
        target = target.with_name(target.name + SESSION_EXTENSION)
    document = session_document(state, target, extra=extra)
    _write_atomic(target, json.dumps(document, indent=1, ensure_ascii=False, allow_nan=False) + "\n")
    return target


# ----------------------------------------------------------------- loading
def looks_like_session(path: str | os.PathLike[str]) -> bool:
    """Whether the file is JSON whose ``format`` is the session format (content, not extension)."""
    try:
        return _read_document(Path(path)).get("format") == SESSION_FORMAT
    except SessionError:
        return False


def _read_document(path: Path) -> dict[str, Any]:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise SessionError(f"{path.name}: cannot read ({error.strerror or error})") from None
    if size > MAX_SESSION_BYTES:
        raise SessionError(f"{path.name}: {size // (1024 * 1024)} MB is too large for a session file")
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError) as error:
        raise SessionError(f"{path.name}: not a readable JSON file ({error})") from None
    if not isinstance(document, dict):
        raise SessionError(f"{path.name}: not a session file (the JSON is not an object)")
    return document


def check_document(document: Mapping[str, Any], name: str = "the file") -> None:
    """Raise :class:`SessionError` for an unknown format or a newer format version."""
    fmt = document.get("format")
    if fmt != SESSION_FORMAT:
        raise SessionError(f"{name} is not a session file (format {fmt!r}, expected {SESSION_FORMAT!r})")
    version = document.get("format_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise SessionError(f"{name}: format_version {version!r} is not a version number")
    if version > SESSION_FORMAT_VERSION:
        raise SessionError(
            f"{name} was saved by a newer version (session format {version}; this version reads up to "
            f"{SESSION_FORMAT_VERSION}). Open it with an up-to-date app ({document.get('app') or 'version not recorded'})."
        )


def _file_sha256(path: Path) -> str | None:
    try:
        return session_sha256(path)
    except OSError:
        return None


def _candidates(raw: Mapping[str, Any], session_dir: Path) -> list[Path]:
    paths: list[Path] = []
    if raw.get("relative"):
        paths.append(session_dir / str(raw["relative"]))
    if raw.get("absolute"):
        paths.append(Path(str(raw["absolute"])).expanduser())
    if raw.get("name"):
        paths.append(session_dir / Path(str(raw["name"])).name)
    unique: list[Path] = []
    for candidate in paths:
        resolved = candidate.resolve(strict=False)
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _restore_run(record: Mapping[str, Any], session_dir: Path, where: str) -> tuple[Analysis | None, SessionProblem | None]:
    """Find, check, read and replay one run. Returns the analysis, or None and the problem."""
    run_id = str(record.get("run_id"))
    raw = record.get("raw") or {}
    if not isinstance(raw, dict):
        return None, SessionProblem("unreadable", f"{where}: invalid raw file record; the run is not opened", run_id=run_id)
    name = str(raw.get("name") or "?")
    expected = raw.get("sha256")

    def problem(kind: str, message: str, path: Path | None = None) -> tuple[None, SessionProblem]:
        return None, SessionProblem(kind, f"{where}: {message}; the run is not opened", run_id=run_id,
                                    path=str(path) if path is not None else name)

    candidates = _candidates(raw, session_dir)
    chosen = next((c for c in candidates if c.is_file()), None)
    if chosen is None:
        tried = ", ".join(str(c) for c in candidates) or "no path saved"
        return problem("missing", f"{name} not found (tried {tried})")
    if _file_sha256(chosen) != expected:
        return problem("changed", f"{name} has changed since the session was saved (SHA-256 differs at {chosen})", chosen)
    try:
        run = open_run(chosen)
    except (UnsupportedFile, OSError, ValueError) as error:
        return problem("unreadable", f"{name} no longer reads ({error})", chosen)
    if run.raw.sha256 != expected:
        return problem("changed", f"{name} changed while it was being read", chosen)
    run.run_id = run_id
    element = record.get("element")
    if element in ELEMENTS:
        run.element = element
    try:
        if record.get("history_version", HISTORY_VERSION) != HISTORY_VERSION:
            raise ReplayMismatch(f"history version {record.get('history_version')!r} is not {HISTORY_VERSION}")
        from rawtims.readers.ionvantage_raw import input_hashes, raw_folder
        from rawtims.reduction_params import ReductionParameters, as_acquired
        records = [record.get("initial_reduction_provenance", {}), record.get("reduction_provenance", {}), *record.get("history", []), *record.get("redo_history", [])]
        hashes = [r[k] for r in records for k in ("raw_inputs", "old_raw_inputs") if r.get(k)]
        if hashes:
            folder = raw_folder(chosen)
            actual = input_hashes(folder) if folder is not None else {}
            if any(actual != h for h in hashes):
                raise ReplayMismatch("raw acquisition source files are missing or changed (SHA-256)")
        initial_params = ReductionParameters.from_dict(record["initial_reduction_parameters"]) if "initial_reduction_parameters" in record else as_acquired(run)
        if initial_params != as_acquired(run):
            from rawtims.reprocess import reprocess
            run = reprocess(run, initial_params)
        start = AnalysisSettings(**{k: v for k, v in dict(record.get("initial_settings") or {}).items() if k in SETTING_NAMES})
        history = list(record.get("history") or [])
        redo_history = list(record.get("redo_history") or [])
        analysis = replay(run, history + redo_history, start, strict=True)
        for _ in redo_history:
            analysis.undo()
        if "reduction_parameters" in record and analysis.run.reduction_parameters.to_dict() != record["reduction_parameters"]:
            raise ReplayMismatch("reduction parameters after history differ from saved ones")
        saved_settings = record.get("settings")
        if saved_settings is not None and analysis.settings.to_dict() != {k: saved_settings.get(k) for k in SETTING_NAMES}:
            raise ReplayMismatch("the settings after the history differ from the saved ones")
        if record.get("mask_sha256") is not None and mask_sha256(analysis) != record["mask_sha256"]:
            raise ReplayMismatch("the include flags after the history differ from the saved ones")
    except (ReplayMismatch, KeyError, IndexError, TypeError, ValueError, AttributeError) as error:
        return problem("replay", f"the edit history of {name} does not replay exactly ({error})", chosen)
    try:
        analysis.legacy_pending = bool(record.get("legacy_pending", False))
        for key, rejected in record.get("legacy_masks", {}).items():
            analysis.index(key)
            mask = np.ones(analysis.n_cycles, dtype=bool)
            mask[analysis._rows(rejected)] = False
            analysis.legacy_masks[key] = mask
    except (KeyError, IndexError, TypeError, ValueError) as error:
        return problem("replay", f"the legacy comparison masks of {name} cannot be read ({error})", chosen)
    return analysis, None


def load_session(path: str | os.PathLike[str]) -> tuple[SessionState, list[SessionProblem]]:
    """Read a session: re-read and check every raw file and replay its history (see the module docstring).

    Raises :class:`SessionError` when the file is not a session this version
    reads. Per-run trouble does not raise: it is returned as problems, and the
    run is not opened.
    """
    path = Path(path).expanduser()
    document = _read_document(path)
    check_document(document, path.name)
    for key in ("runs", "fractions"):
        if not isinstance(document.get(key), list):
            raise SessionError(f"{path.name}: {key} must be a list")
    session_dir = path.resolve(strict=False).parent
    runs = {}
    for record in document["runs"]:
        if not isinstance(record, dict) or not isinstance(record.get("run_id"), str) or not record["run_id"]:
            raise SessionError(f"{path.name}: a run without a run_id")
        if record["run_id"] in runs:
            raise SessionError(f"{path.name}: duplicate run_id {record['run_id']!r}")
        runs[record["run_id"]] = record
    state = SessionState(recovery=document.get("recovery") if isinstance(document.get("recovery"), dict) else None)
    if "presentation" in document:
        if not isinstance(document["presentation"], dict):
            raise SessionError(f"{path.name}: presentation must be an object")
        state.presentation = document["presentation"]
        for name in ("notes", "recipes"):
            group = state.presentation.get(name, {})
            if not isinstance(group, dict) or not all(isinstance(key, str) for key in group):
                raise SessionError(f"{path.name}: presentation {name} must be an object")
            expected = str if name == "notes" else dict
            if not all(isinstance(value, expected) for value in group.values()):
                raise SessionError(f"{path.name}: invalid presentation {name}")
    if "stat_mode" in document:
        if document["stat_mode"] not in STAT_MODES:
            raise SessionError(f"{path.name}: invalid project stat_mode {document['stat_mode']!r}")
        state.stat_mode = document["stat_mode"]
    problems: list[SessionProblem] = []
    restored: dict[str, Analysis | None] = {}
    used: set[str] = set()
    fraction_ids: set[str] = set()
    for entry in document.get("fractions") or []:
        if not isinstance(entry, dict) or not entry.get("fraction_id"):
            raise SessionError(f"{path.name}: a fraction without a Fraction ID")
        fid = str(entry["fraction_id"])
        if fid in fraction_ids:
            raise SessionError(f"{path.name}: duplicate Fraction ID {fid!r}")
        fraction_ids.add(fid)
        for key in ("runs", "mappings", "fields"):
            if not isinstance(entry.get(key, {}), dict):
                raise SessionError(f"{path.name}: fraction {fid!r} {key} must be an object")
        slots = dict(entry.get("runs") or {})
        mappings = dict(entry.get("mappings") or {})
        analyses: dict[str, Analysis | None] = {}
        lost: list[tuple[str, dict[str, Any], SessionProblem]] = []
        for element in ELEMENTS:
            run_id = slots.get(element)
            if run_id is None:
                analyses[element] = None
                continue
            record = runs.get(str(run_id))
            if record is None:
                raise SessionError(f"{path.name}: fraction {fid!r} names run {run_id!r}, which the file does not hold")
            if str(run_id) in used:
                raise SessionError(f"{path.name}: run {run_id!r} is assigned to more than one fraction slot")
            used.add(str(run_id))
            if str(run_id) not in restored:
                analysis, problem = _restore_run(record, session_dir, f"{fid} {element}")
                restored[str(run_id)] = analysis
                if problem is not None:
                    problem = SessionProblem(problem.kind, problem.message, fid, element, problem.run_id, problem.path)
                    problems.append(problem)
                    lost.append((element, record, problem))
            analyses[element] = restored[str(run_id)]
        fields = {name: value for name, value in dict(entry.get("fields") or {}).items() if name in FRACTION_FIELDS}
        try:
            link = DatabaseLink.from_dict(entry["database_link"]) if "database_link" in entry else None
            fraction = Fraction(fraction_id=fid, database_link=link, **fields)
            fraction.pb, fraction.u = analyses["Pb"], analyses["U"]
        except (ValueError, TypeError, KeyError, DatabaseError) as error:
            raise SessionError(f"{path.name}: fraction {fid!r} cannot be restored ({error})") from None
        state.fractions.append(fraction)
        for element, record, problem in lost:
            state.missing.append(MissingRun(fraction, element, dict(record), mappings.get(element), problem))
        for element in ELEMENTS:
            analysis = analyses[element]
            saved = mappings.get(element)
            if analysis is None or not isinstance(saved, dict):
                continue
            run_id = analysis.run.run_id
            state.mapping_sources[run_id] = str(saved.get("source") or "proposed")
            try:
                if saved.get("edit") is not None:
                    state.mapping_edits[run_id] = MethodMapping.from_dict(saved["edit"])
                if saved.get("resolved") is not None:
                    state.saved_mappings[run_id] = MethodMapping.from_dict(saved["resolved"])
                    analysis.restore_mapping(saved["resolved"])
                    setattr(fraction, "pb_mapping" if element == "Pb" else "u_mapping", analysis.mapping)
            except (MappingError, KeyError, TypeError) as error:
                problems.append(SessionProblem("mapping", f"{fid} {element}: the saved mapping cannot be read ({error}); "
                                                          "the mapping is proposed again", fid, element, run_id))
    for analysis in state.analyses():
        analysis.remember_legacy_masks()
    if "composition" in document:
        from rawtims.composition import CompositionBook, compose
        try:
            book = CompositionBook.from_dict(document["composition"])
        except (ValueError, TypeError) as error:
            raise SessionError(f"{path.name}: invalid composition history ({error})") from None
        state.composition = book.to_dict()
        sources = {a.run.run_id: a for a in state.analyses()}
        for recipe in book.objects:
            try:
                compose(recipe, sources)
            except (ValueError, KeyError) as error:
                problems.append(SessionProblem("composition", f"{recipe.name}: diagnostic unavailable ({error}); recipe retained"))
    if set(runs) != used:
        raise SessionError(f"{path.name}: runs without a fraction: {', '.join(sorted(set(runs) - used))}")
    if "stat_mode" not in document:
        modes = {a.settings.stat_mode for a in state.analyses()}
        if len(modes) == 1:
            state.stat_mode = modes.pop()
    return state, problems


__all__ = [
    "FRACTION_FIELDS",
    "PROBLEM_KINDS",
    "MissingRun",
    "SessionError",
    "SessionProblem",
    "SessionState",
    "check_document",
    "initial_settings",
    "load_session",
    "looks_like_session",
    "mask_sha256",
    "same_ratios",
    "save_session",
    "session_document",
    "session_fingerprint",
    "session_sha256",
]
