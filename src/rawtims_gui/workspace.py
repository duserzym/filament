"""The open fractions of one window, without Qt (SPEC F3, F5).

Opening files goes through :func:`rawtims.readers.open_paths` and the pairing
through :func:`rawtims.fractions.pair_analyses`. A later batch joins the
fractions already open: a run whose suggested fraction ID matches an open
fraction with a free slot fills that slot; a second run of the same element
gets its own fraction (``<id> #2``). A file opened twice (same SHA-256) is
reported as skipped, not opened again.

Fraction IDs are the user's to edit (:meth:`Workspace.rename`). Renaming a
fraction to the ID of another one merges the two when their runs fit (one Pb,
one U); otherwise the rename is refused with the reason.

**Mappings.** :meth:`Workspace.mapping` gives the function-to-contract mapping
of a run, from the first of: the user's edit for that run
(:meth:`Workspace.set_mapping`), the mapping remembered for the run's method
(:attr:`Workspace.remembered`, applied only when it resolves completely), or a
fresh proposal (:func:`rawtims.mapping.propose_mapping`, with the fraction's
Collector for Pb). The result is also stored on the fraction
(``Fraction.pb_mapping`` / ``u_mapping``), so the export uses exactly the
mapping shown. It is recomputed when the run's settings (statistics mode,
oxide formula, r18), the fraction's Collector or the edits change.

**Export.** :meth:`Workspace.fraction_status` says whether a fraction is
``ready`` (both runs, a valid contract row), ``attention`` (a row cannot be
made or has problems) or ``incomplete`` (a run is missing), with the reasons;
:meth:`Workspace.export_rows` returns the rows of every exportable fraction and
the reasons for the others. Nothing here imports Qt, so ``--verify`` runs
without a window. A ``session_info`` (:class:`rawtims.fractions.SessionInfo`)
fills ``Raw App Session`` and its SHA-256; the window passes one only while the
saved session file matches what is open.

**Sessions.** :meth:`Workspace.session_state` gives what
:func:`rawtims.session.save_session` writes (the mapping in effect of every run
and the user's edits, keyed by run_id), and :meth:`Workspace.restore` takes what
:func:`rawtims.session.load_session` read. A run the session could not open is
kept in :attr:`Workspace.missing` with its saved record: its fraction needs
attention and is left out of the export, and saving writes the record back.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from rawtims.analysis import Analysis
from rawtims.contract import FractionRow
from rawtims.fractions import (
    Fraction,
    FractionError,
    SessionInfo,
    fraction_row,
    pair_analyses,
    suggested_fraction_id,
)
from rawtims.mapping import ElementMapping, MappingError, MethodMapping, propose_mapping
from rawtims.readers import open_paths
from rawtims.session import MissingRun, SessionProblem, SessionState, same_ratios
from rawtims.stats import STAT_MODES

ELEMENTS = ("Pb", "U")
MAPPING_SOURCES = ("edited", "remembered", "proposed")


@dataclass
class ImportResult:
    """What one import did: the analyses added, the fractions touched and the files skipped (path, reason)."""

    added: list[Analysis] = field(default_factory=list)
    fractions: list[Fraction] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    reviewed: list[Analysis] = field(default_factory=list)


def read_paths(paths: Sequence[str | os.PathLike[str]]) -> tuple[list[Analysis], list[tuple[str, str]]]:
    """Read files and folders into analyses (no rejection applied). Safe to run on a worker thread."""
    from rawtims.projects import open_project
    projects = [Path(p) for p in paths if Path(p).suffix.lower() == ".trip" and Path(p).is_file()]
    runs, skipped = open_paths([p for p in paths if Path(p) not in projects])
    analyses = []
    for path in projects:
        try:
            analyses.append(open_project(path))
        except (ValueError, OSError) as error:
            skipped.append((path, str(error)))
    analyses.extend(Analysis(run) for run in runs)
    return analyses, [(str(path), reason) for path, reason in skipped]


class Workspace:
    """The fractions open in one window, in the order they were added."""

    def __init__(self, remembered: dict[str, MethodMapping] | None = None) -> None:
        self.fractions: list[Fraction] = []
        # Mappings remembered per instrument method name (the GUI keeps them in QSettings).
        self.remembered: dict[str, MethodMapping] = dict(remembered or {})
        self._edits: dict[int, MethodMapping] = {}
        self._mappings: dict[int, tuple[Any, ElementMapping | None, str]] = {}
        # Runs of a loaded session that could not be opened (kept for the next save).
        self.missing: list[MissingRun] = []
        self.stat_mode = "arithmetic"
        self.presentation: dict = {}
        self.composition: dict = {}
        self.calibration_history: dict = {}
        self._restoring = False

    def set_stat_mode(self, mode: str) -> None:
        """Set the project default and update every run through its undoable history.

        Run-level undo remains available; export checks agreement with this
        default, so a partial undo must be reconciled with the project switch.
        """
        if mode not in STAT_MODES:
            raise ValueError(f"stat_mode must be one of {STAT_MODES}")
        self.stat_mode = mode
        for analysis in self.analyses():
            if analysis.settings.stat_mode != mode:
                analysis.set_setting("stat_mode", mode)

    def statistics_problem(self) -> str | None:
        if any(a.settings.stat_mode != self.stat_mode for a in self.analyses()):
            return ("Mixed statistics modes: runs disagree with the project setting. "
                    "Choose Statistics for this project in Corrections to make all runs agree before exporting.")
        return None

    # ------------------------------------------------------------ queries
    def analyses(self) -> list[Analysis]:
        return [a for fraction in self.fractions for a in (fraction.pb, fraction.u) if a is not None]

    def find(self, fraction_id: str) -> Fraction | None:
        for fraction in self.fractions:
            if fraction.fraction_id == fraction_id:
                return fraction
        return None

    def fraction_of(self, analysis: Analysis) -> Fraction | None:
        for fraction in self.fractions:
            if analysis is fraction.pb or analysis is fraction.u:
                return fraction
        return None

    def _cache_key(self, analysis: Analysis) -> Any:
        fraction = self.fraction_of(analysis)
        method = analysis.run.metadata.method
        remembered = self.remembered.get(method) if method else None
        return (
            analysis.settings,
            id(fraction),
            fraction.collector if fraction is not None else None,
            id(self._edits.get(id(analysis))),
            id(remembered),
        )

    def _resolve(self, analysis: Analysis) -> tuple[ElementMapping | None, str]:
        fraction = self.fraction_of(analysis)
        element = analysis.run.element
        if element not in ELEMENTS:
            return None, "proposed"
        edit = self._edits.get(id(analysis))
        if edit is not None:
            return edit.apply(analysis), "edited"
        method = analysis.run.metadata.method
        collector = fraction.collector if fraction is not None and element == "Pb" else None
        if method and method in self.remembered:
            mapping = self.remembered[method].apply(analysis)
            if mapping.complete and not any(issue.kind in ("refused", "missing") for issue in mapping.issues):
                return mapping, "remembered"
        return propose_mapping(analysis, element, collector=collector), "proposed"

    def mapping(self, analysis: Analysis) -> ElementMapping | None:
        """The function-to-contract mapping of a run (None when the element is unknown); see the module docstring."""
        key = self._cache_key(analysis)
        cached = self._mappings.get(id(analysis))
        if cached is not None and cached[1] is not analysis.mapping:
            # Mapping undo/redo takes precedence even if a setting changed before
            # the next workspace query.
            resolved = _ratios_of(analysis.mapping)
            if resolved is not None:
                self._edits[id(analysis)] = resolved
            key = self._cache_key(analysis)
            self._mappings[id(analysis)] = cached = (key, analysis.mapping, "edited")
        if cached is None or cached[0] != key:
            try:
                mapping, source = self._resolve(analysis)
            except MappingError:
                mapping, source = None, "proposed"
            if self._restoring:
                data = _ratios_of(mapping)
                analysis.restore_mapping(data.to_dict() if data is not None else None)
            else:
                analysis.set_mapping(mapping)
            self._mappings[id(analysis)] = (key, analysis.mapping, source)
        fraction = self.fraction_of(analysis)
        if fraction is not None and analysis.run.element in ELEMENTS:
            setattr(fraction, "pb_mapping" if analysis.run.element == "Pb" else "u_mapping", analysis.mapping)
        return analysis.mapping

    def mapping_source(self, analysis: Analysis) -> str:
        """``edited``, ``remembered`` or ``proposed``: where :meth:`mapping` took the run's mapping from."""
        self.mapping(analysis)
        return self._mappings[id(analysis)][2]

    def set_mapping(self, analysis: Analysis, ratios: dict[str, dict[str, Any] | None]) -> ElementMapping | None:
        """The user's choice for a run: contract ratio → ``{"function": key, "inverted": bool}`` (None: no function)."""
        element = analysis.run.element
        if element not in ELEMENTS:
            raise MappingError(f"cannot map a run whose element is {element!r}")
        fraction = self.fraction_of(analysis)
        chosen = {ratio: dict(entry) for ratio, entry in ratios.items() if entry is not None}
        edit = MethodMapping(
            method=analysis.run.metadata.method or "",
            element=element,
            ratios=chosen,
            collector=fraction.collector if fraction is not None and element == "Pb" else None,
        )
        if analysis.legacy_pending or not analysis.group_consistent():
            raise MappingError("per-ratio selection (legacy): use the union of rejections before changing the mapping")
        self._edits[id(analysis)] = edit
        return self.mapping(analysis)

    def clear_mapping_edit(self, analysis: Analysis) -> ElementMapping | None:
        """Drop the user's edit: back to the remembered mapping or a proposal."""
        self._edits.pop(id(analysis), None)
        return self.mapping(analysis)

    def remember(self, analysis: Analysis) -> MethodMapping:
        """Remember the run's current mapping for its method name (raises MappingError without a method)."""
        mapping = self.mapping(analysis)
        if mapping is None:
            raise MappingError("this run has no mapping to remember")
        remembered = mapping.to_method_mapping()
        self.remembered[remembered.method] = remembered
        return remembered

    def forget(self, method: str) -> bool:
        return self.remembered.pop(method, None) is not None

    # ------------------------------------------------------------- export
    def sync_mappings(self, fraction: Fraction) -> None:
        for analysis in (fraction.pb, fraction.u):
            if analysis is not None:
                self.mapping(analysis)

    def missing_of(self, fraction: Fraction) -> list[MissingRun]:
        return [m for m in self.missing if m.fraction is fraction]

    def fraction_row(self, fraction: Fraction, exported_at: datetime, session_info: SessionInfo | None = None) -> FractionRow:
        """The contract row of one fraction with the mappings shown (raises FractionError).

        A fraction with a run the session could not open has no row: exporting
        only the other block would silently change it.
        """
        lost = self.missing_of(fraction)
        problem = self.statistics_problem()
        if problem:
            raise FractionError(problem)
        if lost:
            raise FractionError("; ".join(m.problem.message for m in lost))
        self.sync_mappings(fraction)
        return fraction_row(fraction, exported_at, session_info)

    def fraction_report(self, fraction: Fraction, exported_at: datetime,
                        session_info: SessionInfo | None = None) -> tuple[str, list[str], FractionRow | None, str | None]:
        """``(state, reasons, row or None, FractionError text or None)``; states as in :meth:`fraction_status`."""
        try:
            row = self.fraction_row(fraction, exported_at, session_info)
        except FractionError as error:
            return "attention", [str(error)], None, str(error)
        problems = row.problems()
        if problems:
            return "attention", problems, row, None
        missing = [element for element, analysis in (("Pb", fraction.pb), ("U", fraction.u)) if analysis is None]
        if missing:
            return "incomplete", [f"no {element} run in this fraction" for element in missing], row, None
        return "ready", [], row, None

    def fraction_status(self, fraction: Fraction, exported_at: datetime | None = None) -> tuple[str, list[str]]:
        """``(state, reasons)``: ``ready``, ``attention`` or ``incomplete`` (see the module docstring)."""
        state, reasons, _row, _error = self.fraction_report(fraction, exported_at or datetime.now().astimezone())
        return state, reasons

    def export_rows(self, exported_at: datetime, fractions: Sequence[Fraction] | None = None,
                    session_info: SessionInfo | None = None) -> tuple[list[FractionRow], list[tuple[str, str]]]:
        """Rows of every exportable fraction, and ``(fraction ID, reason)`` for each one left out."""
        rows: list[FractionRow] = []
        left_out: list[tuple[str, str]] = []
        for fraction in self.fractions if fractions is None else fractions:
            try:
                row = self.fraction_row(fraction, exported_at, session_info)
            except FractionError as error:
                left_out.append((fraction.fraction_id, str(error)))
                continue
            problems = row.problems()
            if problems:
                left_out.append((fraction.fraction_id, "; ".join(problems)))
                continue
            rows.append(row)
        return rows, left_out

    def _unique_id(self, base: str) -> str:
        if self.find(base) is None:
            return base
        number = 2
        while self.find(f"{base} #{number}") is not None:
            number += 1
        return f"{base} #{number}"

    # ------------------------------------------------------------- import
    def add(self, analyses: Iterable[Analysis], skipped: Iterable[tuple[str, str]] = ()) -> ImportResult:
        """Pair new analyses into fractions and join them to the open ones."""
        result = ImportResult(skipped=list(skipped))
        open_hashes = {a.run.raw.sha256: a.run.raw.name for a in self.analyses()}
        fresh: list[Analysis] = []
        for analysis in analyses:
            raw = analysis.run.raw
            if raw.sha256 in open_hashes:
                result.skipped.append((raw.path, f"already open (same content as {open_hashes[raw.sha256]})"))
                continue
            open_hashes[raw.sha256] = raw.name
            fresh.append(analysis)
        pairing = pair_analyses(fresh)
        placed: list[tuple[Fraction, Analysis]] = []
        for new in pairing.fractions:
            existing = self.find(new.fraction_id)
            runs = [a for a in (new.pb, new.u) if a is not None]
            if existing is not None and all(self._slot_free(existing, a.run.element) for a in runs):
                for analysis in runs:
                    setattr(existing, _slot(analysis), analysis)
                placed += [(existing, a) for a in runs]
                continue
            if existing is not None:
                new.fraction_id = self._unique_id(new.fraction_id)
            self.fractions.append(new)
            placed += [(new, a) for a in runs]
        for analysis, reason in pairing.unplaced:
            if analysis.run.element not in ELEMENTS:
                result.skipped.append((analysis.run.raw.path, f"not placed in a fraction: {reason}"))
                continue
            fraction = Fraction(fraction_id=self._unique_id(suggested_fraction_id(analysis)), sample=analysis.run.metadata.sample_id)
            setattr(fraction, _slot(analysis), analysis)
            self.fractions.append(fraction)
            placed.append((fraction, analysis))
        for fraction, analysis in placed:
            if analysis.settings.stat_mode != self.stat_mode:
                analysis.set_setting("stat_mode", self.stat_mode)
            result.added.append(analysis)
            if fraction not in result.fractions:
                result.fractions.append(fraction)
        return result

    def open(self, paths: Sequence[str | os.PathLike[str]]) -> ImportResult:
        """Read and add in one call (the synchronous path: tests, scripted export)."""
        analyses, skipped = read_paths(paths)
        return self.add(analyses, skipped)

    # ------------------------------------------------------------- rename
    def rename(self, fraction: Fraction, new_id: str) -> tuple[bool, str, Fraction]:
        """Set a fraction's ID. Returns ``(ok, message, fraction now holding the runs)``.

        An ID already used by another fraction merges the two when the runs fit
        in one fraction (one Pb and one U); otherwise nothing changes.
        """
        new_id = new_id.strip()
        if not new_id:
            return False, "A fraction needs a Fraction ID.", fraction
        if new_id == fraction.fraction_id:
            return True, "", fraction
        other = self.find(new_id)
        if other is None:
            old = fraction.fraction_id
            fraction.fraction_id = new_id
            self._rename_notes(old, new_id)
            return True, f"Renamed fraction {old} to {new_id}.", fraction
        runs = [a for a in (fraction.pb, fraction.u) if a is not None]
        clash = [a for a in runs if getattr(other, _slot(a)) is not None]
        if clash:
            element = clash[0].run.element
            return False, f"Fraction {new_id} already has a {element} run ({getattr(other, _slot(clash[0])).run.raw.name}).", fraction
        lost = self.missing_of(fraction)
        elements = [a.run.element for a in runs] + [m.element for m in lost]
        blocked = [e for e in elements if not self._slot_free(other, e)]
        if blocked:
            return False, f"Fraction {new_id} already has a {blocked[0]} run (one the session could not open).", fraction
        if fraction.database_link is not None and other.database_link is not None:
            a, b = fraction.database_link, other.database_link
            if (a.server, a.fraction_uid) != (b.server, b.fraction_uid):
                return False, "These fractions have different database links. Unlink one before merging.", fraction
        if other.database_link is None:
            other.database_link = fraction.database_link
        for entry in lost:
            entry.fraction = other
        for analysis in runs:
            setattr(other, _slot(analysis), analysis)
            self._mappings.pop(id(analysis), None)
            # The stored mapping belonged to the old fraction (its Collector): resolve it again for the new one.
            setattr(other, "pb_mapping" if analysis.run.element == "Pb" else "u_mapping", None)
        self.fractions.remove(fraction)
        self._rename_notes(fraction.fraction_id, new_id)
        return True, f"Merged {fraction.fraction_id} into fraction {new_id}.", other

    def _rename_notes(self, old: str, new: str) -> None:
        notes = self.presentation.get('notes', {})
        source = notes.pop('fraction:' + old, '')
        if source:
            key = 'fraction:' + new
            notes[key] = '\n\n'.join(text for text in (notes.get(key, ''), source) if text)


    def _slot_free(self, fraction: Fraction, element: str | None) -> bool:
        if element not in ELEMENTS:
            return False
        return fraction.analysis(element) is None and not any(m.element == element for m in self.missing_of(fraction))

    # ------------------------------------------------------------ session
    def session_state(self) -> SessionState:
        """What a session save writes: fractions, missing runs, and every run's mapping edit and source."""
        edits: dict[str, MethodMapping] = {}
        sources: dict[str, str] = {}
        for fraction in self.fractions:
            self.sync_mappings(fraction)
            for analysis in (fraction.pb, fraction.u):
                if analysis is None:
                    continue
                run_id = analysis.run.run_id
                sources[run_id] = self.mapping_source(analysis)
                if id(analysis) in self._edits:
                    edits[run_id] = self._edits[id(analysis)]
        return SessionState(fractions=list(self.fractions), mapping_edits=edits, mapping_sources=sources,
                            missing=list(self.missing), stat_mode=self.stat_mode, presentation=self.presentation,
                            composition=self.composition, calibration_history=self.calibration_history)

    def restore(self, state: SessionState) -> list[SessionProblem]:
        """Take the fractions of a loaded session (replacing what is open). Returns the mapping problems found.

        Edits come back as edits. A mapping that was remembered or proposed is
        resolved again here; when that gives other functions than the session
        saved (for example a remembered mapping this viewer does not have), the
        saved mapping is restored as an edit and reported, so the export does
        not change silently.
        """
        self._restoring = True
        self.fractions = list(state.fractions)
        self.stat_mode = state.stat_mode
        self.presentation = state.presentation
        self.composition = state.composition
        self.calibration_history = state.calibration_history
        self.missing = list(state.missing)
        self._edits.clear()
        self._mappings.clear()
        problems: list[SessionProblem] = []
        for fraction in self.fractions:
            for element in ELEMENTS:
                analysis = fraction.analysis(element)
                if analysis is None:
                    continue
                run_id = analysis.run.run_id
                edit = state.mapping_edits.get(run_id)
                if edit is not None:
                    self._edits[id(analysis)] = edit
                saved = state.saved_mappings.get(run_id)
                current = self.mapping(analysis)
                if saved is None or same_ratios(saved, _ratios_of(current)):
                    continue
                source = state.mapping_sources.get(run_id, "proposed")
                self._edits[id(analysis)] = MethodMapping(method=analysis.run.metadata.method or "", element=saved.element,
                                                          ratios=dict(saved.ratios), collector=saved.collector)
                self.mapping(analysis)
                problems.append(SessionProblem(
                    "mapping",
                    f"{fraction.fraction_id} {element}: the {source} mapping resolves to other functions here; "
                    "the session's mapping is restored as an edit",
                    fraction.fraction_id, element, run_id))
        self._restoring = False
        for analysis in self.analyses():
            analysis.remember_legacy_masks()
        return problems


def _ratios_of(mapping: ElementMapping | None) -> MethodMapping | None:
    if mapping is None:
        return None
    return MethodMapping(method=mapping.method or "", element=mapping.element,
                         ratios={ratio: mapped.to_dict() for ratio, mapped in mapping.ratios.items()}, collector=mapping.collector)


def _slot(analysis: Analysis) -> str:
    return "pb" if analysis.run.element == "Pb" else "u"


def describe_path(path: str) -> str:
    return Path(path).name or path


__all__ = ["ELEMENTS", "MAPPING_SOURCES", "ImportResult", "Workspace", "describe_path", "read_paths"]
