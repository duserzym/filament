"""One run under review: derived functions, the include mask, settings and the edit history (SPEC F8-F12, section 3).

An :class:`Analysis` wraps an immutable :class:`~rawtims.model.Run`. It adds

* derived functions (the UO2 oxide correction, :mod:`rawtims.oxide`) after the
  run's own columns;
* ``included[n_cycles, n_functions]`` (cycle flags), one flag per block, and
  the run's ``invalid`` flags extended to the derived columns. The effective
  inclusion is cycle flag AND block flag AND not invalid;
* settings (statistics mode, r18, oxide formula, Chauvenet P and n, k, synced);
* an edit history with undo, redo and reset. Every operation stores what was
  asked (enough to redo it) and exactly which flags it changed (enough to
  undo it). ``history`` is plain JSON-serialisable data, and :func:`replay`
  rebuilds the same mask from the run and that history; the session file
  will store it.

Opening an analysis applies no rejection (SPEC section 0, decision 3): every
valid cycle starts included. Rules run only through :meth:`Analysis.apply_rule`.

Cycle positions are 0-based row indices into the run; ``run.cycle[row]`` is the
instrument's cycle number. Functions are named by their unique key.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import copy
from dataclasses import asdict, dataclass, fields, replace
import math
from typing import Any

import numpy as np

from rawtims import rules as _rules
from rawtims import stats as _stats
from rawtims.branding import APP_NAME
from rawtims.model import Function, Run
from rawtims.oxide import DEFAULT_R18, DERIVED_NAMES, FORMULA_TEXT, FORMULAS, OxideResult, oxide_correction

HISTORY_VERSION = 1


@dataclass(frozen=True)
class AnalysisSettings:
    """Per-analysis settings. Changing one through :meth:`Analysis.set_setting` is an undoable operation."""

    stat_mode: str = "geometric"
    r18: float = DEFAULT_R18
    oxide_formula: str = "isobar_233_18O"
    chauvenet_probability: float = _rules.CHAUVENET_PROBABILITY
    chauvenet_min_n: int = _rules.CHAUVENET_MIN_N
    k_sigma: float = _rules.K_SIGMA
    k_sigma_max_iterations: int = _rules.K_SIGMA_MAX_ITERATIONS
    synced: bool = True

    def __post_init__(self) -> None:
        for item in fields(self):
            _validate_setting(item.name, getattr(self, item.name))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


SETTING_NAMES = tuple(item.name for item in fields(AnalysisSettings))


def _validate_setting(name: str, value: Any) -> None:
    if name == "stat_mode":
        if value not in _stats.STAT_MODES:
            raise ValueError(f"stat_mode must be one of {_stats.STAT_MODES}")
    elif name == "oxide_formula":
        if value not in FORMULAS:
            raise ValueError(f"oxide_formula must be one of {FORMULAS}")
    elif name == "r18":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value < 0.1:
            raise ValueError("r18 must be a number in [0, 0.1)")
    elif name == "chauvenet_probability":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 1.0:
            raise ValueError("chauvenet_probability must be in [0, 1]")
    elif name in ("chauvenet_min_n", "k_sigma_max_iterations"):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    elif name == "k_sigma":
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not value > 0:
            raise ValueError("k_sigma must be a positive number")
    elif name == "synced":
        if not isinstance(value, bool):
            raise ValueError("synced must be true or false")
    else:
        raise KeyError(f"unknown setting {name!r}")


class ReplayMismatch(ValueError):
    """Raised by :func:`replay` when an operation no longer changes the flags it recorded."""


class Analysis:
    """A run with derived functions, include flags, settings and an undoable history."""

    def __init__(self, run: Run, settings: AnalysisSettings | None = None) -> None:
        self.run = run
        self._settings = settings or AnalysisSettings()
        self._row_block = np.searchsorted(np.unique(run.block), run.block)
        self.blocks = np.unique(run.block).astype(np.int64)
        self.block_included = np.ones(self.blocks.size, dtype=bool)
        self._ops: list[dict[str, Any]] = []
        self._applied = 0
        self._derive()
        self.included = np.ones(self.values.shape, dtype=bool)

    # ------------------------------------------------------------------ data
    def _derive(self) -> None:
        """(Re)compute the derived columns from the current oxide settings."""
        run = self.run
        self.oxide: OxideResult = oxide_correction(run, self._settings.r18, self._settings.oxide_formula)  # type: ignore[arg-type]
        derived: list[Function] = []
        columns: list[np.ndarray] = []
        if self.oxide.status == "computed":
            used = set(run.keys)
            for offset, name in enumerate(DERIVED_NAMES):
                key = name
                while key in used:
                    key = f"{key} ({APP_NAME})"
                used.add(key)
                numerator, denominator = name[:-2].split("/")
                derived.append(
                    Function(
                        index=run.n_functions + offset,
                        name=name,
                        key=key,
                        kind="ratio",
                        numerator=numerator,
                        denominator=denominator,
                        numerator_mass=int(numerator),
                        denominator_mass=int(denominator),
                        metadata={
                            "derived": "oxide",
                            "formula": self.oxide.formula,
                            "formula_text": FORMULA_TEXT[self.oxide.formula][name],
                            "r18": self.oxide.r18,
                            "inputs": dict(self.oxide.inputs),
                        },
                    )
                )
                columns.append(self.oxide.values[name])
        self.derived: tuple[Function, ...] = tuple(derived)
        self.functions: tuple[Function, ...] = run.functions + self.derived
        self._index = {function.key: function.index for function in self.functions}
        if columns:
            extra = np.column_stack(columns)
            with np.errstate(invalid="ignore"):
                extra_invalid = ~np.isfinite(extra) | ~(extra > 0)
            self.values = np.hstack([run.values, extra])
            self.invalid = np.hstack([run.invalid, extra_invalid])
        else:
            self.values = run.values
            self.invalid = run.invalid
        if hasattr(self, "included") and self.included.shape != self.values.shape:
            raise RuntimeError("derived columns changed shape; this should not happen")

    @property
    def settings(self) -> AnalysisSettings:
        return self._settings

    @property
    def n_cycles(self) -> int:
        return self.run.n_cycles

    @property
    def keys(self) -> list[str]:
        return [function.key for function in self.functions]

    def function(self, key: str) -> Function:
        return self.functions[self.index(key)]

    def index(self, key: str) -> int:
        try:
            return self._index[key]
        except KeyError:
            raise KeyError(f"no function {key!r} in this analysis") from None

    def column(self, key: str) -> np.ndarray:
        return self.values[:, self.index(key)]

    @property
    def ratio_keys(self) -> list[str]:
        return [function.key for function in self.functions if function.is_ratio]

    @property
    def effective(self) -> np.ndarray:
        """Cycle flag AND block flag AND not invalid, ``n_cycles × n_functions``."""
        return self.included & self.block_included[self._row_block][:, None] & ~self.invalid

    def included_for(self, key: str) -> np.ndarray:
        return self.effective[:, self.index(key)]

    # ----------------------------------------------------------- statistics
    def stats(self, key: str) -> _stats.Stats:
        """Statistics of one function over its effectively included cycles."""
        function = self.function(key)
        return _stats.function_stats(self.column(key), self.included_for(key), is_ratio=function.is_ratio, ratio_mode=self._settings.stat_mode)  # type: ignore[arg-type]

    def block_stats(self, key: str) -> dict[int, _stats.Stats]:
        """Per-block statistics (an excluded block has ``n_used == 0``)."""
        function = self.function(key)
        return _stats.block_stats(self.column(key), self.included_for(key), self.run.block, is_ratio=function.is_ratio, ratio_mode=self._settings.stat_mode)  # type: ignore[arg-type]

    def block_weighted_mean(self, key: str, convention: str = "tripoli") -> _stats.WeightedMean:
        """Block-mode weighted mean (not the default statistic)."""
        function = self.function(key)
        return _stats.block_weighted_mean(
            self.column(key), self.included_for(key), self.run.block,
            is_ratio=function.is_ratio, ratio_mode=self._settings.stat_mode, convention=convention,  # type: ignore[arg-type]
        )

    def correlation(self, key_a: str, key_b: str) -> _stats.Correlation:
        """Pearson r over the cycles included for both functions, on the scale the statistics use."""
        mode = self._settings.stat_mode
        fa, fb = self.function(key_a), self.function(key_b)
        return _stats.correlation(
            self.column(key_a), self.column(key_b), self.included_for(key_a), self.included_for(key_b),
            mode_a=_stats.mode_for(fa.is_ratio, mode), mode_b=_stats.mode_for(fb.is_ratio, mode),  # type: ignore[arg-type]
        )

    # ---------------------------------------------------------------- rules
    def _proposal(self, rule: str, keys: Sequence[str] | None, mapping: Any, scope: str, synced: bool | None, params: dict[str, Any]) -> _rules.RuleProposal:
        mapped: set[str] = set()
        if mapping is not None:
            mapped = set(mapping.function_keys)
        if keys is None:
            keys = list(mapping.function_keys) if mapping is not None else self.ratio_keys
            if not keys:
                raise ValueError("the mapping has no functions to examine")
        keys = list(keys)
        columns = [self.index(key) for key in keys]
        effective = self.effective
        return _rules.propose(
            rule,
            self.values[:, columns],
            effective[:, columns],
            keys,
            # Mapped functions are contract ratios even when the file names them in shorthand (IsoLinx ``R64``).
            [self.functions[c].is_ratio or self.functions[c].key in mapped for c in columns],
            self.run.block,
            scope=scope,  # type: ignore[arg-type]
            synced=self._settings.synced if synced is None else synced,
            **params,
        )

    def propose_chauvenet(self, keys: Sequence[str] | None = None, *, mapping: Any = None, scope: str = "run", synced: bool | None = None, log_ratios: bool = False) -> _rules.RuleProposal:
        """Preview Chauvenet's criterion with the current settings.

        ``keys`` default to the functions mapped to contract ratios when a
        ``mapping`` (:class:`rawtims.mapping.ElementMapping`) is given, else to
        every ratio function. Explicit ``keys`` always win.
        """
        params = {"probability": self._settings.chauvenet_probability, "min_n": self._settings.chauvenet_min_n, "log_ratios": log_ratios}
        return self._proposal("chauvenet", keys, mapping, scope, synced, params)

    def propose_k_sigma(self, keys: Sequence[str] | None = None, *, mapping: Any = None, scope: str = "run", synced: bool | None = None, log_ratios: bool = True) -> _rules.RuleProposal:
        """Preview iterative k-σ rejection with the current settings. ``keys`` default as in :meth:`propose_chauvenet`."""
        params = {"k": self._settings.k_sigma, "max_iterations": self._settings.k_sigma_max_iterations, "log_ratios": log_ratios}
        return self._proposal("k_sigma", keys, mapping, scope, synced, params)

    # ------------------------------------------------------------ operations
    def _rows(self, cycles: Iterable[int]) -> list[int]:
        rows = sorted({int(row) for row in cycles})
        for row in rows:
            if not 0 <= row < self.n_cycles:
                raise IndexError(f"cycle row {row} outside 0..{self.n_cycles - 1}")
        return rows

    def _set_cells(self, cells: list[tuple[int, int]], value: bool) -> list[list[Any]]:
        changed = [(row, col) for row, col in cells if self.included[row, col] != value]
        for row, col in changed:
            self.included[row, col] = value
        return [[row, self.functions[col].key] for row, col in changed]

    def _push(self, op: dict[str, Any]) -> dict[str, Any]:
        del self._ops[self._applied :]
        self._ops.append(op)
        self._applied += 1
        return copy.deepcopy(op)

    def toggle_cycles(self, cycles: Iterable[int], keys: Sequence[str] | None = None, include: bool | None = None) -> dict[str, Any]:
        """Include or exclude cycles, in the given functions or (``keys=None``, synced) in every function.

        With ``include=None`` it toggles: if every addressed flag is on, all are
        turned off; otherwise all are turned on. Returns the recorded operation.
        """
        rows = self._rows(cycles)
        columns = list(range(len(self.functions))) if keys is None else [self.index(key) for key in keys]
        cells = [(row, col) for row in rows for col in columns]
        if include is None:
            include = not all(self.included[row, col] for row, col in cells) if cells else False
        changed = self._set_cells(cells, bool(include))
        return self._push({"op": "toggle_cycles", "cycles": rows, "keys": None if keys is None else list(keys), "include": bool(include), "changed": changed})

    def toggle_block(self, block: int, include: bool | None = None) -> dict[str, Any]:
        """Include or exclude a whole block (by block number). ``include=None`` flips it."""
        position = np.flatnonzero(self.blocks == int(block))
        if position.size == 0:
            raise KeyError(f"no block {block} in this run")
        position = int(position[0])
        old = bool(self.block_included[position])
        new = (not old) if include is None else bool(include)
        self.block_included[position] = new
        return self._push({"op": "toggle_block", "block": int(block), "include": new, "changed": old != new})

    def apply_rule(self, proposal: _rules.RuleProposal) -> dict[str, Any]:
        """Apply a rule proposal: synced rejects its union of cycles in every function, otherwise each key's own cycles."""
        for key in proposal.keys:
            self.index(key)
        if proposal.synced:
            cells = [(row, col) for row in self._rows(proposal.cycles) for col in range(len(self.functions))]
        else:
            cells = [(row, self.index(key)) for key, rows in proposal.rejected.items() for row in self._rows(rows)]
        changed = self._set_cells(cells, False)
        op = {"op": "apply_rule", "description": proposal.describe(), **proposal.to_dict(), "changed": changed}
        return self._push(op)

    def set_setting(self, name: str, value: Any) -> dict[str, Any]:
        """Change one setting (undoable). Changing ``r18`` or ``oxide_formula`` recomputes the derived columns."""
        if name not in SETTING_NAMES:
            raise KeyError(f"unknown setting {name!r}")
        if name in ("chauvenet_min_n", "k_sigma_max_iterations") and isinstance(value, float) and value.is_integer():
            value = int(value)
        _validate_setting(name, value)
        old = getattr(self._settings, name)
        self._apply_setting(name, value)
        return self._push({"op": "set_setting", "name": name, "old": old, "new": value})

    def _apply_setting(self, name: str, value: Any) -> None:
        self._settings = replace(self._settings, **{name: value})
        if name in ("r18", "oxide_formula"):
            self._derive()

    def reset(self) -> dict[str, Any]:
        """Include every cycle and block again (settings are kept). Undoable."""
        rows, cols = np.nonzero(~self.included)
        changed = [[int(r), self.functions[int(c)].key] for r, c in zip(rows, cols)]
        self.included[:] = True
        blocks = [int(b) for b in self.blocks[~self.block_included]]
        self.block_included[:] = True
        return self._push({"op": "reset", "changed": changed, "blocks_changed": blocks})

    # ----------------------------------------------------------- undo / redo
    @property
    def can_undo(self) -> bool:
        return self._applied > 0

    @property
    def can_redo(self) -> bool:
        return self._applied < len(self._ops)

    def _cells(self, changed: list[list[Any]]) -> list[tuple[int, int]]:
        return [(int(row), self.index(key)) for row, key in changed]

    def undo(self) -> dict[str, Any] | None:
        """Revert the last applied operation; returns it, or None when there is nothing to undo."""
        if not self.can_undo:
            return None
        self._applied -= 1
        op = self._ops[self._applied]
        kind = op["op"]
        if kind == "toggle_cycles":
            for row, col in self._cells(op["changed"]):
                self.included[row, col] = not op["include"]
        elif kind == "apply_rule":
            for row, col in self._cells(op["changed"]):
                self.included[row, col] = True
        elif kind == "toggle_block":
            if op["changed"]:
                self.block_included[int(np.flatnonzero(self.blocks == op["block"])[0])] = not op["include"]
        elif kind == "set_setting":
            self._apply_setting(op["name"], op["old"])
        elif kind == "reset":
            for row, col in self._cells(op["changed"]):
                self.included[row, col] = False
            for block in op["blocks_changed"]:
                self.block_included[int(np.flatnonzero(self.blocks == block)[0])] = False
        return copy.deepcopy(op)

    def redo(self) -> dict[str, Any] | None:
        """Re-apply the next undone operation; returns it, or None when there is nothing to redo."""
        if not self.can_redo:
            return None
        op = self._ops[self._applied]
        kind = op["op"]
        if kind in ("toggle_cycles", "apply_rule"):
            value = op["include"] if kind == "toggle_cycles" else False
            for row, col in self._cells(op["changed"]):
                self.included[row, col] = value
        elif kind == "toggle_block":
            self.block_included[int(np.flatnonzero(self.blocks == op["block"])[0])] = op["include"]
        elif kind == "set_setting":
            self._apply_setting(op["name"], op["new"])
        elif kind == "reset":
            self.included[:] = True
            self.block_included[:] = True
        self._applied += 1
        return copy.deepcopy(op)

    @property
    def history(self) -> list[dict[str, Any]]:
        """The applied operations, oldest first, as JSON-serialisable dicts (undone operations are not included)."""
        return copy.deepcopy(self._ops[: self._applied])

    @property
    def redo_history(self) -> list[dict[str, Any]]:
        """Undone operations, next to redo first, for lossless session restoration."""
        return copy.deepcopy(self._ops[self._applied :])

    def rejected_summary(self) -> dict[str, Any]:
        """Counts for provenance: excluded cycle flags per function and excluded blocks."""
        return {
            "excluded_flags": {key: int((~self.included[:, i]).sum()) for i, key in enumerate(self.keys) if not self.included[:, i].all()},
            "excluded_blocks": [int(b) for b in self.blocks[~self.block_included]],
            "invalid": {key: int(self.invalid[:, i].sum()) for i, key in enumerate(self.keys) if self.invalid[:, i].any()},
        }


def replay(run: Run, history: Sequence[dict[str, Any]], settings: AnalysisSettings | None = None, *, strict: bool = True) -> Analysis:
    """Rebuild an analysis from a run and a recorded history.

    Each operation is re-executed from what was asked (cycles and include
    state, the rule's recorded rejected cycles, setting values), never by
    re-running a rule, so the result does not depend on code changes in the
    rules. With ``strict`` every re-executed operation must change exactly the
    flags it recorded; otherwise :class:`ReplayMismatch` is raised.
    """
    analysis = Analysis(run, settings)
    for position, op in enumerate(history):
        kind = op.get("op")
        if kind == "toggle_cycles":
            result = analysis.toggle_cycles(op["cycles"], op["keys"], op["include"])
        elif kind == "toggle_block":
            result = analysis.toggle_block(op["block"], op["include"])
        elif kind == "apply_rule":
            result = analysis.apply_rule(_rules.RuleProposal.from_dict(op))
        elif kind == "set_setting":
            result = analysis.set_setting(op["name"], op["new"])
        elif kind == "reset":
            result = analysis.reset()
        else:
            raise ValueError(f"history entry {position}: unknown operation {kind!r}")
        if strict:
            for field_name in ("changed", "blocks_changed"):
                if field_name in op and _normalise(result.get(field_name)) != _normalise(op[field_name]):
                    raise ReplayMismatch(f"history entry {position} ({kind}) changed different flags on replay")
            if kind == "set_setting" and op.get("old") is not None and not _same(result["old"], op["old"]):
                raise ReplayMismatch(f"history entry {position}: setting {op['name']} was {result['old']!r}, recorded {op['old']!r}")
    return analysis


def _normalise(value: Any) -> Any:
    if isinstance(value, list):
        return sorted((_normalise(item) for item in value), key=repr)
    return value


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, float) and isinstance(b, float):
        return a == b or (math.isnan(a) and math.isnan(b))
    return a == b


__all__ = ["HISTORY_VERSION", "SETTING_NAMES", "Analysis", "AnalysisSettings", "ReplayMismatch", "replay"]
