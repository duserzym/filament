"""Exact source matching for legacy projects; project labels never select a run."""
from pathlib import Path

from rawtims.parity import drive_path, replay_project
from rawtims.readers import open_run
from rawtims.readers.trip import read_trip


class MissingProjectSource(ValueError):
    """A source that the user may locate explicitly."""


def open_project(path, source=None):
    project = read_trip(path)
    if len(project.sources) != 1:
        raise ValueError("Tripoli project must identify exactly one source workbook")
    expected = project.sources[0].name
    if source is None:
        roots = [Path(path).parent, drive_path()]
        matches = {p.resolve() for root in roots if root.is_dir() for p in root.rglob(expected) if p.is_file()}
        if not matches:
            raise MissingProjectSource(f"Source workbook missing: {expected}. Locate the exact acquisition to import {Path(path).name}.")
        # Copies with identical content are safe; conflicting files need an explicit choice.
        from hashlib import sha256
        if len({sha256(p.read_bytes()).digest() for p in matches}) != 1:
            raise MissingProjectSource(f"Ambiguous source workbook: {expected}. Locate the exact acquisition.")
        source = min(matches, key=lambda p: (len(p.parts), str(p)))
    if Path(source).name != expected:
        raise ValueError(f"Expected source workbook {expected}; no similarly named acquisition can be substituted")
    return replay_project(open_run(source), project, workbook=True)
