"""Opt-in analysis compositions with replayable recipes, never fraction analyses.

Tables retain member cycle/block/time identities. No composition is a Run or an
Analysis, so mapping and all existing exports remain limited to measured inputs.
"""
from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import timedelta
from itertools import pairwise

import numpy as np

from rawtims.analysis import Analysis
from rawtims.expressions import (
    DerivedColumn,
    ExpressionSpec,
    dependency_order,
    evaluate,
)
from rawtims.model import Function


@dataclass(frozen=True)
class Member:
    run_id: str
    blocks: tuple[int, ...] = ()  # empty selects the whole member

    def __post_init__(self):
        if not isinstance(self.run_id, str) or not self.run_id:
            raise ValueError('A member needs a run identity')
        if not isinstance(self.blocks, tuple) or any(type(b) is not int for b in self.blocks) or len(set(self.blocks)) != len(self.blocks):
            raise ValueError('Member blocks must be unique integers')

    def to_dict(self):
        return {'run_id': self.run_id, 'blocks': list(self.blocks)}


@dataclass(frozen=True)
class Composition:
    key: str
    name: str
    members: tuple[Member, ...]
    expressions: tuple[ExpressionSpec, ...] = ()

    def __post_init__(self):
        if not isinstance(self.key, str) or not self.key or len(self.key) > 100:
            raise ValueError('A composition needs a stable key of at most 100 characters')
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 200:
            raise ValueError('A composition needs a name of at most 200 characters')
        if not 1 <= len(self.members) <= 128 or len(self.expressions) > 128:
            raise ValueError('A composition needs 1–128 members and at most 128 expressions')
        dependency_order(self.expressions)

    def to_dict(self):
        return {'key': self.key, 'name': self.name, 'members': [m.to_dict() for m in self.members],
                'expressions': [s.to_dict() for s in self.expressions]}

    @classmethod
    def from_dict(cls, record):
        try:
            return cls(record['key'], record['name'], tuple(Member(m['run_id'], tuple(m['blocks'])) for m in record['members']),
                       tuple(ExpressionSpec(**s) for s in record['expressions']))
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(f'Invalid composition record: {error}') from None


@dataclass(frozen=True)
class ComposedTable:
    functions: tuple[Function, ...]
    values: np.ndarray
    invalid: np.ndarray
    included: np.ndarray  # effective member masks, diagnostic only
    cycle: np.ndarray
    block: np.ndarray
    time: np.ndarray  # unchanged member elapsed time, never fabricated continuous time
    run_ids: tuple[str, ...]
    source_hashes: tuple[str, ...]
    acquisition_times: tuple[str | None, ...]
    boundaries: tuple[int, ...]
    derived: tuple[DerivedColumn, ...] = ()

    @property
    def block_keys(self):
        """Member-scoped blocks prevent repeated block numbers being pooled."""
        return tuple(zip(self.run_ids, (int(b) for b in self.block)))


def _identity(analysis):
    return (analysis.run.metadata.method, analysis.run.metadata.instrument,
            analysis.run.metadata.cycles_per_block, analysis.run.element,
            [asdict(f) for f in analysis.functions], analysis.settings.to_dict(),
            analysis.run.reduction_parameters.to_dict())


def concatenate(members: tuple[Member, ...], analyses: Mapping[str, Analysis]) -> ComposedTable:
    """Match identities strictly, order by recorded acquisition time, reject overlaps.

    Without a start date, only disjoint block selections from one acquisition
    can be composed: its elapsed time already supplies an unambiguous clock.
    Across acquisitions all dates must share naive/aware status. Missing method,
    nonfinite/decreasing time, duplicate rows and interleaved acquisitions fail
    explicitly. Functions and units must match in order, including metadata.
    """
    if not 1 <= len(members) <= 128:
        raise ValueError('Select 1–128 members')
    pieces, identity, seen = [], None, set()
    run_ids = {m.run_id for m in members}
    dated = []
    for member in members:
        if member.run_id not in analyses:
            raise ValueError(f'Missing member run {member.run_id}; restore its source first')
        analysis = analyses[member.run_id]
        run = analysis.run
        current = _identity(analysis)
        if len(members) > 1 and not run.metadata.method:
            raise ValueError('Concatenation requires a recorded method identity')
        if identity is None:
            identity = current
        if current != identity:
            raise ValueError('Members must have identical method, element, functions, units and reduction settings')
        if set(member.blocks) - {int(b) for b in run.block}:
            raise ValueError(f'Unknown member block in {member.run_id}')
        rows = np.flatnonzero(np.isin(run.block, member.blocks)) if member.blocks else np.arange(run.n_cycles)
        if not rows.size:
            raise ValueError('Empty member selection')
        ids = {(member.run_id, int(row)) for row in rows}
        if seen & ids:
            raise ValueError('Duplicate member cycles')
        seen |= ids
        elapsed = run.time[rows]
        if len(members) > 1 and (not np.all(np.isfinite(elapsed)) or np.any(np.diff(elapsed) < 0)):
            raise ValueError('Concatenation requires finite nondecreasing member times')
        start = run.metadata.analysis_start
        if len(run_ids) > 1 and start is None:
            raise ValueError('Different acquisitions require recorded start dates')
        dated.append(start is not None and start.utcoffset() is not None)
        try:
            times = tuple((start + timedelta(seconds=float(t))).isoformat() if start is not None and np.isfinite(t) else None for t in elapsed)
            first = start + timedelta(seconds=float(elapsed[0])) if start is not None and np.isfinite(elapsed[0]) else float(elapsed[0])
            last = start + timedelta(seconds=float(elapsed[-1])) if start is not None and np.isfinite(elapsed[-1]) else float(elapsed[-1])
        except OverflowError:
            raise ValueError('Member elapsed time exceeds the supported date range') from None
        pieces.append((first, last, member.run_id, rows, analysis, times))
    if len(set(dated)) != 1:
        raise ValueError('Cannot compare zoned and unzoned acquisition times')
    if len(members) > 1:
        pieces.sort(key=lambda p: (p[0], p[2], int(p[3][0])))
        if any(left[1] >= right[0] for left, right in pairwise(pieces)):
            raise ValueError('Member time ranges overlap or interleave')
    functions = pieces[0][4].functions
    def stack(attribute):
        return np.concatenate([getattr(p[4], attribute)[p[3]] for p in pieces], axis=0).copy()
    def run_stack(attribute):
        return np.concatenate([getattr(p[4].run, attribute)[p[3]] for p in pieces]).copy()
    counts = [len(p[3]) for p in pieces]
    return ComposedTable(functions, stack('values'), stack('invalid'), stack('effective'),
                         run_stack('cycle'), run_stack('block'), run_stack('time'),
                         tuple(p[2] for p in pieces for _ in p[3]),
                         tuple(p[4].run.raw.sha256 for p in pieces for _ in p[3]),
                         tuple(t for p in pieces for t in p[5]), tuple(int(n) for n in np.cumsum(counts)[:-1]))


def compose(recipe: Composition, analyses: Mapping[str, Analysis]) -> ComposedTable:
    base = concatenate(recipe.members, analyses)
    keys = [f.key for f in base.functions]
    derived = evaluate(recipe.expressions, {key: base.values[:, i] for i, key in enumerate(keys)},
                       masks={key: base.included[:, i] for i, key in enumerate(keys)},
                       invalid={key: base.invalid[:, i] for i, key in enumerate(keys)})
    functions = tuple(Function(len(keys) + i, d.spec.name, d.spec.key, d.spec.kind, unit=d.spec.unit,
                               metadata={'derived': 'expression', 'expression': d.spec.expression}) for i, d in enumerate(derived))
    return ComposedTable(base.functions + functions,
                         np.column_stack([base.values] + [d.values for d in derived]),
                         np.column_stack([base.invalid] + [d.invalid for d in derived]),
                         np.column_stack([base.included] + [d.included for d in derived]),
                         base.cycle, base.block, base.time, base.run_ids, base.source_hashes,
                         base.acquisition_times, base.boundaries, derived)


class CompositionBook:
    """Separate undo/redo for explicit composition objects; JSON stores recipes only.

    Each event records its before and after objects; strict replay verifies that
    chain, including the redo tail. Evaluation always reads current source values
    and masks. No arrays are patched into an Analysis or stored in a session.
    """
    def __init__(self):
        self._events = []
        self._applied = 0
        self._objects = {}

    @property
    def objects(self):
        return tuple(self._objects[key] for key in sorted(self._objects))

    @property
    def can_undo(self):
        return self._applied > 0

    @property
    def can_redo(self):
        return self._applied < len(self._events)

    def put(self, recipe: Composition, analyses: Mapping[str, Analysis]):
        compose(recipe, analyses)  # validate completely before mutating history
        self._record(recipe.key, recipe.to_dict())

    def remove(self, key):
        if key not in self._objects:
            raise ValueError(f'No composition {key}')
        self._record(key, None)

    def _record(self, key, after):
        before = self._objects[key].to_dict() if key in self._objects else None
        if before == after:
            return
        self._events[self._applied:] = [{'key': key, 'before': before, 'after': after}]
        self._apply(key, after)
        self._applied += 1

    def _apply(self, key, record):
        if record is None:
            self._objects.pop(key, None)
        else:
            recipe = Composition.from_dict(record)
            if recipe.key != key:
                raise ValueError('History key differs from object key')
            self._objects[key] = recipe

    def undo(self):
        if not self.can_undo:
            return False
        event = self._events[self._applied - 1]
        self._apply(event['key'], event['before'])
        self._applied -= 1
        return True

    def redo(self):
        if not self.can_redo:
            return False
        event = self._events[self._applied]
        self._apply(event['key'], event['after'])
        self._applied += 1
        return True

    def to_dict(self):
        return {'version': 1, 'events': copy.deepcopy(self._events), 'applied': self._applied}

    @classmethod
    def from_dict(cls, document):
        book = cls()
        if not isinstance(document, dict):
            raise ValueError('Composition history must be an object')  # noqa: TRY004 - invalid JSON schema
        if not document:
            return book
        if type(document.get('version')) is not int or document['version'] != 1:
            raise ValueError('Unknown composition history version')
        events, applied = document.get('events'), document.get('applied')
        if not isinstance(events, list) or len(events) > 4096 or type(applied) is not int or not 0 <= applied <= len(events):
            raise ValueError('Invalid composition history position')
        for event in events:
            if not isinstance(event, dict) or set(event) != {'key', 'before', 'after'} or not isinstance(event['key'], str):
                raise ValueError('Invalid composition history event')
            key = event['key']
            before = book._objects[key].to_dict() if key in book._objects else None
            if before != event['before']:
                raise ValueError('Composition history does not replay exactly')
            book._apply(key, event['after'])
        book._events, book._applied = copy.deepcopy(events), len(events)
        while book._applied > applied:
            book.undo()
        return book
