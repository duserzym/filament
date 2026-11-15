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
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
import os
from pathlib import Path

from rawtims.analysis import Analysis
from rawtims.fractions import Fraction, pair_analyses, suggested_fraction_id
from rawtims.mapping import ElementMapping, MappingError, propose_mapping
from rawtims.readers import open_paths

ELEMENTS = ("Pb", "U")


@dataclass
class ImportResult:
    """What one import did: the analyses added, the fractions touched and the files skipped (path, reason)."""

    added: list[Analysis] = field(default_factory=list)
    fractions: list[Fraction] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def read_paths(paths: Sequence[str | os.PathLike[str]]) -> tuple[list[Analysis], list[tuple[str, str]]]:
    """Read files and folders into analyses (no rejection applied). Safe to run on a worker thread."""
    runs, skipped = open_paths(paths)
    return [Analysis(run) for run in runs], [(str(path), reason) for path, reason in skipped]


class Workspace:
    """The fractions open in one window, in the order they were added."""

    def __init__(self) -> None:
        self.fractions: list[Fraction] = []
        self._mappings: dict[int, ElementMapping | None] = {}

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

    def mapping(self, analysis: Analysis) -> ElementMapping | None:
        """The proposed function-to-contract mapping of a run (None when the element is unknown)."""
        key = id(analysis)
        if key not in self._mappings:
            fraction = self.fraction_of(analysis)
            try:
                if fraction is not None and analysis.run.element in ELEMENTS:
                    self._mappings[key] = fraction.mapping(analysis.run.element)
                else:
                    self._mappings[key] = propose_mapping(analysis)
            except MappingError:
                self._mappings[key] = None
        return self._mappings[key]

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
            if existing is not None and all(getattr(existing, _slot(a)) is None for a in runs):
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
            return True, f"Renamed fraction {old} to {new_id}.", fraction
        runs = [a for a in (fraction.pb, fraction.u) if a is not None]
        clash = [a for a in runs if getattr(other, _slot(a)) is not None]
        if clash:
            element = clash[0].run.element
            return False, f"Fraction {new_id} already has a {element} run ({getattr(other, _slot(clash[0])).run.raw.name}).", fraction
        for analysis in runs:
            setattr(other, _slot(analysis), analysis)
            self._mappings.pop(id(analysis), None)
        self.fractions.remove(fraction)
        return True, f"Merged {fraction.fraction_id} into fraction {new_id}.", other


def _slot(analysis: Analysis) -> str:
    return "pb" if analysis.run.element == "Pb" else "u"


def describe_path(path: str) -> str:
    return Path(path).name or path


__all__ = ["ELEMENTS", "ImportResult", "Workspace", "describe_path", "read_paths"]
