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

import copy
import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, fields, replace
from typing import Any

import numpy as np

from rawtims import rules as _rules
from rawtims import stats as _stats
from rawtims.branding import APP_NAME
from rawtims.model import Function, Run
from rawtims.oxide import (
    DEFAULT_R18,
    DERIVED_NAMES,
    FORMULA_TEXT,
    FORMULAS,
    OxideResult,
    oxide_correction,
)

HISTORY_VERSION = 1


@dataclass(frozen=True)
class AnalysisSettings:
    """Per-analysis settings. Changing one through :meth:`Analysis.set_setting` is an undoable operation."""

    stat_mode: str = "arithmetic"
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
        from rawtims.reduction_params import as_acquired
        self.initial_reduction_parameters = run.reduction_parameters or as_acquired(run)
        self.initial_reduction_provenance = copy.deepcopy(run.provenance)
        if run.reduction_parameters is None:
            run.reduction_parameters = self.initial_reduction_parameters
        self._settings = settings or AnalysisSettings()
        self._row_block = np.searchsorted(np.unique(run.block), run.block)
        self.blocks = np.unique(run.block).astype(np.int64)
        self.block_included = np.ones(self.blocks.size, dtype=bool)
        self._ops: list[dict[str, Any]] = []
        self._applied = 0
        self._stat_cache = {}
        self._reduction_cache = {}
        self._derive()
        self.included = np.ones(self.values.shape, dtype=bool)
        # Analysis owns the resolved mapping. The workspace supplies remembered/edited
        # mappings through set_mapping; standalone analyses start with the proposal.
        from rawtims.mapping import propose_mapping
        self.mapping = propose_mapping(self) if run.element in ("Pb", "U") else None
        self._replaying = False
        self.legacy_masks: dict[str, np.ndarray] = {}
        self.legacy_pending = False

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
        effective = self.included & self.block_included[self._row_block][:, None] & ~self.invalid
        columns = [self.index(k) for k in self.group_keys]
        if columns and self.group_consistent():
            effective[:, columns] &= ~self.invalid[:, columns].any(axis=1)[:, None]
        return effective

    def included_for(self, key: str) -> np.ndarray:
        column = self.index(key)
        effective = self.included[:, column] & self.block_included[self._row_block] & ~self.invalid[:, column]
        group = self.group_keys
        if key in group and self.group_consistent():
            effective &= ~self.invalid[:, [self.index(k) for k in group]].any(axis=1)
        return effective

    @property
    def group_keys(self) -> list[str]:
        """Contract functions plus the actual U oxide inputs and derived outputs."""
        keys = list(self.mapping.function_keys) if self.mapping is not None else []
        if self.run.element == "U":
            from rawtims.oxide import find_inputs
            inputs = find_inputs(self.run)
            if inputs is not None:
                keys.extend(inputs[1])
            keys.extend(f.key for f in self.derived)
        return list(dict.fromkeys(keys))

    def group_consistent(self) -> bool:
        """Whether the group's user selection flags agree (validity is shared too)."""
        columns = [self.index(k) for k in self.group_keys]
        return not columns or bool((self.included[:, columns] == self.included[:, columns[0], None]).all())

    def expanded_keys(self, keys: Sequence[str]) -> list[str]:
        keys = list(dict.fromkeys(keys))
        if not self._replaying and set(keys).intersection(self.group_keys):
            keys = list(dict.fromkeys([*self.group_keys, *keys]))
        return keys

    def _mapping_data(self) -> dict | None:
        if self.mapping is None:
            return None
        from rawtims.mapping import MethodMapping
        return MethodMapping(self.mapping.method or "", self.mapping.element,
                             {r: m.to_dict() for r, m in self.mapping.ratios.items()},
                             self.mapping.collector).to_dict()

    def restore_mapping(self, data: dict | None) -> None:
        """Bind saved mapping without mask changes; only for exact session restoration."""
        from rawtims.mapping import MethodMapping
        self.mapping = MethodMapping.from_dict(data).apply(self) if data is not None else None

    def set_mapping(self, mapping: Any) -> dict[str, Any] | None:
        """Change mapping and adopt the previous group mask in one undoable entry.

        Leaving functions retain their flags. A legacy mismatch must first be
        reconciled explicitly, so a mapping change cannot silently resolve it.
        """
        old = self._mapping_data()
        previous = self.mapping
        old_keys = self.group_keys
        self.mapping = mapping
        new = self._mapping_data()
        if old == new:
            return None
        self.mapping = previous
        if self.legacy_pending or not self.group_consistent():
            raise ValueError("per-ratio selection (legacy): use the union of rejections before changing the mapping")
        mask = self.included[:, self.index(old_keys[0])].copy() if old_keys else np.ones(self.n_cycles, dtype=bool)
        self.mapping = mapping
        changes = []
        for key in self.group_keys:
            col = self.index(key)
            for row in np.flatnonzero(self.included[:, col] != mask):
                changes.append([int(row), key, bool(self.included[row, col]), bool(mask[row])])
            self.included[:, col] = mask
        return self._push({"op": "set_mapping", "old": old, "new": new, "mask_changes": changes})

    def remember_legacy_masks(self) -> None:
        if not self.group_consistent():
            self.legacy_pending = True
        if self.legacy_pending and not self.legacy_masks:
            self.legacy_masks = {k: self.included_for(k).copy() for k in self.group_keys}

    def group_differences(self) -> dict[str, list[int]]:
        """Instrument cycle numbers rejected here but accepted by another group member."""
        if self.group_consistent():
            return {}
        columns = [self.index(k) for k in self.group_keys]
        masks = self.included[:, columns]
        differing = masks.any(axis=1) & ~masks.all(axis=1)
        return {k: self.run.cycle[differing & ~masks[:, j]].astype(int).tolist()
                for j, k in enumerate(self.group_keys)}

    def use_union_of_rejections(self) -> dict[str, Any]:
        self.remember_legacy_masks()
        columns = [self.index(k) for k in self.group_keys]
        rows = np.flatnonzero(~self.included[:, columns].all(axis=1)) if columns else []
        pending_before = self.legacy_pending
        self.toggle_cycles(rows, self.group_keys, False)
        self._ops[-1]["legacy_resolution"] = True
        self._ops[-1]["legacy_pending_before"] = pending_before
        self.legacy_pending = False
        return copy.deepcopy(self._ops[-1])

    # ----------------------------------------------------------- statistics
    def _cached_stat(self, key, kind, calculate):
        # Per-function signatures also respect direct NumPy mask edits in notebooks.
        # Retain one entry per statistic/key, rather than every edit's arrays.
        signature = (self.settings.stat_mode, self.column(key).tobytes(),
                     self.included_for(key).tobytes(), self.run.block.tobytes())
        cache_key = (key, kind)
        cached = self._stat_cache.get(cache_key)
        if cached is None or cached[0] != signature:
            self._stat_cache[cache_key] = (signature, calculate())
        return self._stat_cache[cache_key][1]

    def stats(self, key: str) -> _stats.Stats:
        """Statistics of one function over its effectively included cycles."""
        function = self.function(key)
        return self._cached_stat(key, "cycle", lambda: _stats.function_stats(self.column(key), self.included_for(key), is_ratio=function.is_ratio, ratio_mode=self._settings.stat_mode))  # type: ignore[arg-type]

    def block_stats(self, key: str) -> dict[int, _stats.Stats]:
        """Per-block statistics (an excluded block has ``n_used == 0``)."""
        function = self.function(key)
        return self._cached_stat(key, "blocks", lambda: _stats.block_stats(self.column(key), self.included_for(key), self.run.block, is_ratio=function.is_ratio, ratio_mode=self._settings.stat_mode))  # type: ignore[arg-type]

    def block_weighted_mean(self, key: str, convention: str = "tripoli") -> _stats.WeightedMean:
        """Block-mode weighted mean (not the default statistic)."""
        function = self.function(key)
        return self._cached_stat(key, ("weighted", convention), lambda: _stats.block_weighted_mean(
            self.column(key), self.included_for(key), self.run.block,
            is_ratio=function.is_ratio, ratio_mode=self._settings.stat_mode, convention=convention,  # type: ignore[arg-type]
        ))

    def correlation(self, key_a: str, key_b: str) -> _stats.Correlation:
        """Pearson r over the cycles included for both functions, on the scale the statistics use."""
        mode = self._settings.stat_mode
        fa, fb = self.function(key_a), self.function(key_b)
        return _stats.correlation(
            self.column(key_a), self.column(key_b), self.included_for(key_a), self.included_for(key_b),
            mode_a=_stats.mode_for(fa.is_ratio, mode), mode_b=_stats.mode_for(fb.is_ratio, mode),  # type: ignore[arg-type]
        )

    # ---------------------------------------------------------------- rules
    def _proposal(self, rule: str, keys: Sequence[str] | None, mapping: Any, scope: str, synced: bool | None, params: dict[str, Any], *, per_ratio=False) -> _rules.RuleProposal:
        mapped = set(self.mapping.function_keys) if self.mapping is not None else set()
        if mapping is not None:
            mapped.update(mapping.function_keys)
        requested = list(keys) if keys is not None else (self.group_keys or self.ratio_keys)
        if not requested:
            raise ValueError("the mapping has no functions to examine")
        group = self.group_keys if set(requested).intersection(self.group_keys) else []
        # Every group ratio gets an independent diagnostic count, even in one-ratio
        # mode. Only the chosen ratio's flags enter the proposed rejection then.
        examined = list(dict.fromkeys([*group, *requested]))
        columns = [self.index(key) for key in examined]
        proposal = _rules.propose(
            rule, self.values[:, columns], self.effective[:, columns], examined,
            [self.functions[c].is_ratio or self.functions[c].key in mapped for c in columns],
            self.run.block, scope=scope,
            synced=True if group else (self._settings.synced if synced is None else synced),
            **params,
        )
        selected = requested if len(requested) == 1 or not group else examined
        rejected = {k: proposal.rejected[k] for k in selected}
        proposal = replace(proposal, keys=tuple(selected), rejected=rejected,
                           group_keys=tuple(group), evaluation="one" if group and len(selected) == 1 else "union" if group else "per_function",
                           flagged=dict(proposal.rejected),
                           free_synced=self._settings.synced if synced is None else synced)
        if per_ratio:
            proposal = replace(proposal, synced=False, evaluation="legacy_per_ratio")
        targets = self.rule_targets(proposal)
        # Dry run: manipulate a private mask only, never an Analysis or its history.
        effective = self.effective
        after = effective.copy()
        for key, rows in targets.items():
            after[list(rows), self.index(key)] = False
        comparison = {}
        for key in group:
            col = self.index(key)
            before_stat = _stats.describe(self.column(key), effective[:, col], mode=self.settings.stat_mode)
            after_stat = _stats.describe(self.column(key), after[:, col], mode=self.settings.stat_mode)
            def summary(stat):
                return {"n": stat.n_used, "se_pct": stat.se_pct if math.isfinite(stat.se_pct) else None}
            comparison[key] = {"before": summary(before_stat), "after": summary(after_stat)}
        return replace(proposal, targets=targets, before_after=comparison)

    def propose_chauvenet(self, keys: Sequence[str] | None = None, *, mapping: Any = None, scope: str = "run", synced: bool | None = None, log_ratios: bool = False) -> _rules.RuleProposal:
        """Preview Chauvenet's criterion with the current settings.

        By default evaluate every group function and reject the union in the
        group. One explicit group key evaluates that ratio only. Every group
        member still gets a diagnostic count and before/after statistics.
        Free functions retain their SYNCH behaviour.
        """
        params = {"probability": self._settings.chauvenet_probability, "min_n": self._settings.chauvenet_min_n, "log_ratios": log_ratios}
        return self._proposal("chauvenet", keys, mapping, scope, synced, params)

    def propose_k_sigma(self, keys: Sequence[str] | None = None, *, mapping: Any = None, scope: str = "run", synced: bool | None = None, log_ratios: bool = True) -> _rules.RuleProposal:
        """Preview iterative k-σ rejection with the current settings. ``keys`` default as in :meth:`propose_chauvenet`."""
        params = {"k": self._settings.k_sigma, "max_iterations": self._settings.k_sigma_max_iterations, "log_ratios": log_ratios}
        return self._proposal("k_sigma", keys, mapping, scope, synced, params)

    def propose_legacy_two_sigma(self, keys=None, *, mapping=None, scope="run", synced=None, per_ratio=False):
        return self._proposal("legacy_two_sigma", keys, mapping, scope, synced, {}, per_ratio=per_ratio)

    def propose_legacy_chauvenet(self, keys=None, *, mapping=None, scope="run", synced=None, per_ratio=False):
        return self._proposal("legacy_chauvenet", keys, mapping, scope, synced,
                              {"probability": self.settings.chauvenet_probability}, per_ratio=per_ratio)

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
        keys = None if keys is None else self.expanded_keys(keys)
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
        """Apply a preview's group union and the free-function SYNCH targets."""
        for key in proposal.keys:
            self.index(key)
        targets = self.rule_targets(proposal)
        cells = [(row, self.index(key)) for key, rows in targets.items() for row in self._rows(rows)]
        changed = self._set_cells(cells, False)
        op = {"op": "apply_rule", "description": proposal.describe(), **proposal.to_dict(), "targets": {k: list(v) for k, v in targets.items()}, "changed": changed}
        return self._push(op)

    def rule_targets(self, proposal: _rules.RuleProposal) -> dict[str, tuple[int, ...]]:
        if self._replaying:
            if proposal.targets is not None:
                return proposal.targets
            # Pre-shared-mask sessions retain the historical SYNCH semantics.
            return ({k: proposal.cycles for k in self.keys} if proposal.synced else dict(proposal.rejected))
        if proposal.evaluation == "legacy_per_ratio" and proposal.rule in ("legacy_two_sigma", "legacy_chauvenet"):
            return dict(proposal.rejected)
        group = set(self.group_keys)
        targets = {}
        if group.intersection(proposal.keys):
            union = tuple(sorted({r for k, rows in proposal.rejected.items() if k in group for r in rows}))
            targets.update({k: union for k in self.group_keys})
        free = {k: v for k, v in proposal.rejected.items() if k not in group}
        free_synced = proposal.synced if proposal.free_synced is None else proposal.free_synced
        if free and free_synced:
            union = tuple(sorted({r for rows in free.values() for r in rows}))
            targets.update({k: union for k in self.keys if k not in group})
        else:
            targets.update(free)
        return targets

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

    def set_reduction_parameters(self, params, *, prepared_run=None, diff=None):
        """Re-reduce with explicit inputs, preserving masks; one undoable operation."""
        old = self.run.reduction_parameters.to_dict()
        old_inputs = self.run.provenance.get("raw_inputs", {})
        before = self.run
        self._apply_reduction_parameters(params, prepared_run=prepared_run)
        self._reduction_cache[self._applied] = (before, self.run)
        op = {"op": "set_reduction_parameters", "old": old, "new": params.to_dict(),
              "old_raw_inputs": old_inputs, "raw_inputs": self.run.provenance.get("raw_inputs", {})}
        if diff is not None:
            op["diff"] = diff
        return self._push(op)

    def _apply_reduction_parameters(self, params, *, prepared_run=None):
        from rawtims.reprocess import reprocess
        self._verify_reduction_sources(self.run.provenance)
        run = reprocess(self.run, params) if prepared_run is None else prepared_run
        if run.raw.sha256 != self.run.raw.sha256 or run.reduction_parameters != params:
            raise ValueError("prepared reduction does not match this source and parameter set")
        if run.keys != self.run.keys or not np.array_equal(run.cycle, self.run.cycle):
            raise ValueError("reprocessing changed row/function identities; masks cannot safely apply")
        mapping = self._mapping_data()
        self.run = run
        self._derive()
        self.restore_mapping(mapping)

    def _verify_reduction_sources(self, record):
        import hashlib
        from pathlib import Path

        from rawtims.readers.ionvantage_raw import input_hashes, raw_folder
        source = Path(self.run.raw.path)
        if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() != self.run.raw.sha256:
            raise ValueError("workbook source changed (SHA-256); reopen as a new run")
        expected = [record[k] for k in ("raw_inputs", "old_raw_inputs") if record.get(k)]
        if expected:
            folder = raw_folder(Path(self.run.raw.path))
            actual = input_hashes(folder) if folder is not None else {}
            if any(actual != value for value in expected):
                raise ValueError("raw acquisition sources changed (SHA-256); reopen as a new run")

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
        op = self._ops[self._applied - 1]
        if op["op"] == "set_reduction_parameters":
            self._verify_reduction_sources(op)
            from rawtims.reduction_params import ReductionParameters
            cached = self._reduction_cache.get(self._applied - 1)
            self._apply_reduction_parameters(ReductionParameters.from_dict(op["old"]),
                                             prepared_run=cached[0] if cached else None)
        self._applied -= 1
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
        elif kind == "set_mapping":
            self.restore_mapping(op["old"])
            for row, key, before, _after in op["mask_changes"]:
                self.included[row, self.index(key)] = before
        elif kind == "set_setting":
            self._apply_setting(op["name"], op["old"])
        elif kind == "set_reduction_parameters":
            pass  # Applied before advancing history, so source failures are atomic.
        elif kind == "reset":
            for row, col in self._cells(op["changed"]):
                self.included[row, col] = False
            for block in op["blocks_changed"]:
                self.block_included[int(np.flatnonzero(self.blocks == block)[0])] = False
        if op.get("legacy_resolution"):
            self.legacy_pending = op.get("legacy_pending_before", True)
        return copy.deepcopy(op)

    def redo(self) -> dict[str, Any] | None:
        """Re-apply the next undone operation; returns it, or None when there is nothing to redo."""
        if not self.can_redo:
            return None
        op = self._ops[self._applied]
        if op["op"] == "set_reduction_parameters":
            self._verify_reduction_sources(op)
            from rawtims.reduction_params import ReductionParameters
            cached = self._reduction_cache.get(self._applied)
            self._apply_reduction_parameters(ReductionParameters.from_dict(op["new"]),
                                             prepared_run=cached[1] if cached else None)
        kind = op["op"]
        if kind in ("toggle_cycles", "apply_rule"):
            value = op["include"] if kind == "toggle_cycles" else False
            for row, col in self._cells(op["changed"]):
                self.included[row, col] = value
        elif kind == "toggle_block":
            self.block_included[int(np.flatnonzero(self.blocks == op["block"])[0])] = op["include"]
        elif kind == "set_mapping":
            self.restore_mapping(op["new"])
            for row, key, _before, after in op["mask_changes"]:
                self.included[row, self.index(key)] = after
        elif kind == "set_setting":
            self._apply_setting(op["name"], op["new"])
        elif kind == "set_reduction_parameters":
            pass  # Applied before advancing history, so source failures are atomic.
        elif kind == "reset":
            self.included[:] = True
            self.block_included[:] = True
        self._applied += 1
        if op.get("legacy_resolution"):
            self.legacy_pending = False
        return copy.deepcopy(op)

    @property
    def history(self) -> list[dict[str, Any]]:
        """The applied operations, oldest first, as JSON-serialisable dicts (undone operations are not included)."""
        return copy.deepcopy(self._ops[: self._applied])

    def _history_view(self):
        """Internal read-only iteration; consumers must never mutate operations.

        Rendering provenance must not deep-copy every imported cycle mask on
        each mouse edit. The public history property remains a defensive copy.
        """
        return iter(self._ops[:self._applied])

    @property
    def history_count(self) -> int:
        return self._applied

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
    analysis._replaying = True
    for position, op in enumerate(history):
        kind = op.get("op")
        if kind == "toggle_cycles":
            result = analysis.toggle_cycles(op["cycles"], op["keys"], op["include"])
        elif kind == "toggle_block":
            result = analysis.toggle_block(op["block"], op["include"])
        elif kind == "apply_rule":
            result = analysis.apply_rule(_rules.RuleProposal.from_dict(op))
        elif kind == "set_mapping":
            analysis.restore_mapping(op["old"])
            from rawtims.mapping import MethodMapping
            result = analysis.set_mapping(MethodMapping.from_dict(op["new"]).apply(analysis))
        elif kind == "set_setting":
            result = analysis.set_setting(op["name"], op["new"])
        elif kind == "set_reduction_parameters":
            from rawtims.reduction_params import ReductionParameters
            result = analysis.set_reduction_parameters(ReductionParameters.from_dict(op["new"]))
            if strict and result["old"] != op["old"]:
                raise ReplayMismatch(f"history entry {position}: reduction parameters differ before replay")
            if strict and result["raw_inputs"] != op.get("raw_inputs", {}):
                raise ReplayMismatch(f"history entry {position}: raw acquisition hashes changed")
        elif kind == "reset":
            result = analysis.reset()
        else:
            raise ValueError(f"history entry {position}: unknown operation {kind!r}")
        if strict:
            for field_name in ("changed", "blocks_changed", "mask_changes"):
                if field_name in op and _normalise(result.get(field_name)) != _normalise(op[field_name]):
                    raise ReplayMismatch(f"history entry {position} ({kind}) changed different flags on replay")
            if kind == "set_setting" and op.get("old") is not None and not _same(result["old"], op["old"]):
                raise ReplayMismatch(f"history entry {position}: setting {op['name']} was {result['old']!r}, recorded {op['old']!r}")
        # Keep old histories verbatim after checking their recorded effects.
        analysis._ops[-1] = copy.deepcopy(op)
        if op.get("legacy_resolution"):
            analysis.legacy_pending = False
    analysis._replaying = False
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
