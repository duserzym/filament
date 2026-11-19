"""Rejection rules (SPEC F9 and section 0, decision 3).

Each rule is a pure function that returns the cycles it *would* reject: a
proposal. Nothing is applied here; :meth:`rawtims.analysis.Analysis.apply_rule`
applies a proposal and records it in the history. Cycle positions are 0-based
row indices into the run (``Run.cycle[i]`` is the instrument's cycle number).

Chauvenet's criterion, as current CIRDLES Tripoli applies it (read at commit
00dc941):

* ``TripoliCore/.../utilities/mathUtilities/MathUtilities.java:63-110``
  (``applyChauvenetsCriterion``): only when the number of included values is
  at least the minimum count (default 20, ``TripoliConstants.java:84``), take
  the mean and the sample standard deviation (n − 1) of the included values,
  and for every value compute C = n · erfc(|x − mean| / SD / √2) with n the
  number of included values. Values with C < P (default 0.5,
  ``TripoliConstants.java:83``) are rejected. One pass: the statistics are not
  recomputed and the rule is not iterated.
* The values are the function's **cycle values as they are, not ln(ratio)**:
  the cycle-mode branch of
  ``TripoliApp/.../analysisPlots/AnalysisBlockCyclesPlotOG.java:1058-1081``
  passes ``analysisStatsRecord.cycleModeData()``, which
  ``AnalysisStatsRecord.java:84`` and ``136-141`` fill from each block's
  ``cycleMeansData``, the raw column values assembled in
  ``AllBlockInitForDataLiteOne.java:62-71``. (The statistics themselves use
  ln r; the rejection does not.)
* **Per function, never synced**: the Chauvenet action of the plot wall
  (``PlotWallPane.java:239-245``) calls each plot's own ``performChauvenets``
  (``TripoliPlotPane.java:400-411``), and each plot records its result only in
  its own function's column (``SingleBlockRawDataLiteSetRecord.recordChauvenets``).
* Scope: the whole run in cycle mode (the default); in block mode each block
  separately (``AnalysisBlockCyclesPlotOG.java:1044-1056``).

These semantics are the defaults of :func:`chauvenet_rejections`
(``log_ratios=False``). Syncing (one union of rejected cycles applied to every
function) is this engine's own option, on by default to match the app's SYNCH default;
the proposal records which was used.

The iterative k-σ comparison option is separate from legacy single-pass 2σ: on the included values (ln r for ratios by default), reject every
value with |x − mean| > k · SD (n − 1), recompute on what is left and repeat
until nothing new is rejected or ``max_iterations`` passes have run.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from rawtims.stats import transform

Scope = Literal["run", "block"]
RULES = ("chauvenet", "k_sigma", "legacy_two_sigma", "legacy_chauvenet")

CHAUVENET_PROBABILITY = 0.5
CHAUVENET_MIN_N = 20
K_SIGMA = 2.0
K_SIGMA_MAX_ITERATIONS = 10


def _prepare(values, include) -> tuple[np.ndarray, np.ndarray]:
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError("values must be one-dimensional")
    include = np.ones(values.shape, dtype=bool) if include is None else np.asarray(include, dtype=bool)
    if include.shape != values.shape:
        raise ValueError("include mask shape does not match values")
    return values, include & np.isfinite(values)


def chauvenet_rejections(values, include=None, *, probability: float = CHAUVENET_PROBABILITY, min_n: int = CHAUVENET_MIN_N) -> np.ndarray:
    """Indices of included values that Chauvenet's criterion rejects (one pass; see the module docstring).

    Returns an empty array when fewer than ``min_n`` values are included or the
    standard deviation is zero or undefined.
    """
    if not 0.0 <= probability <= 1.0:
        raise ValueError("Chauvenet probability must be within [0, 1]")
    values, ok = _prepare(values, include)
    n = int(ok.sum())
    if n < max(min_n, 2):
        return np.array([], dtype=np.int64)
    data = values[ok]
    mean = data.mean()
    sd = data.std(ddof=1)
    if not math.isfinite(sd) or sd == 0:
        return np.array([], dtype=np.int64)
    indices = np.flatnonzero(ok)
    z = np.abs(data - mean) / sd
    criterion = n * np.array([math.erfc(value / math.sqrt(2.0)) for value in z])
    return indices[criterion < probability]


def k_sigma_rejections(values, include=None, *, k: float = K_SIGMA, max_iterations: int = K_SIGMA_MAX_ITERATIONS, min_n: int = 3) -> np.ndarray:
    """Indices of included values rejected by iterative k-σ clipping (ascending).

    Stops when a pass rejects nothing, after ``max_iterations`` passes, or when
    fewer than ``min_n`` values would remain to compute a mean and SD from.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    if max_iterations < 1:
        raise ValueError("max_iterations must be at least 1")
    values, ok = _prepare(values, include)
    keep = ok.copy()
    for _ in range(max_iterations):
        if int(keep.sum()) < max(min_n, 2):
            break
        data = values[keep]
        mean = data.mean()
        sd = data.std(ddof=1)
        if not math.isfinite(sd) or sd == 0:
            break
        outliers = keep & (np.abs(values - mean) > k * sd)
        if not outliers.any():
            break
        keep &= ~outliers
    return np.flatnonzero(ok & ~keep)


def legacy_two_sigma_rejections(values, include=None):
    """C# single strict 2 SD pass; SetOutliers live-count guard applies to the batch."""
    values, ok = _prepare(values, include)
    ok &= values > 0
    n = int(ok.sum())
    if n < 3:
        return np.array([], dtype=np.int64)
    data = values[ok]
    sd = data.std(ddof=1)
    rows = np.flatnonzero(ok & (np.abs(values - data.mean()) > 2 * sd))
    return rows if n > 2 + len(rows) else np.array([], dtype=np.int64)


def legacy_chauvenet_rejections(values, include=None, *, probability=0.5):
    """C# repeatedly removes one extreme positive point, recomputing after each removal."""
    if not 0 <= probability <= 1:
        raise ValueError("Chauvenet probability must be within [0, 1]")
    values, ok = _prepare(values, include)
    ok &= values > 0
    keep = ok.copy()
    while int(keep.sum()) > 3:  # SetOutliers: live count > 2 + requested removals (one)
        rows = np.flatnonzero(keep)
        data = values[rows]
        sd = data.std(ddof=1)
        if not math.isfinite(sd) or sd == 0:
            break
        deviations = np.abs(data - data.mean())
        worst = int(np.argmax(deviations))
        if len(data) * math.erfc(float(deviations[worst] / sd) / math.sqrt(2)) >= probability:
            break
        keep[rows[worst]] = False
    return np.flatnonzero(ok & ~keep)


@dataclass(frozen=True)
class RuleProposal:
    """What a rule would reject, before it is applied.

    ``rejected`` maps each examined function key to the row indices the rule
    flags in it. ``synced`` proposals reject the union (``cycles``) in every
    function of the analysis; per-function proposals reject each key's own
    rows in that key only.
    """

    rule: str
    params: dict[str, Any]
    scope: Scope
    keys: tuple[str, ...]
    synced: bool
    rejected: dict[str, tuple[int, ...]] = field(default_factory=dict)

    targets: dict[str, tuple[int, ...]] | None = None
    group_keys: tuple[str, ...] = ()
    evaluation: str = "per_function"
    free_synced: bool | None = None
    flagged: dict[str, tuple[int, ...]] = field(default_factory=dict)
    before_after: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def cycles(self) -> tuple[int, ...]:
        """The union of rejected rows across the examined functions, ascending."""
        union: set[int] = set()
        for rows in self.rejected.values():
            union.update(rows)
        return tuple(sorted(union))

    @property
    def is_empty(self) -> bool:
        return not self.cycles

    def describe(self) -> str:
        """Short provenance text, e.g. ``Chauvenet P=0.5 n>=20 (run, synced): 3 cycles``."""
        if self.rule == "chauvenet":
            head = f"Chauvenet P={self.params['probability']:g} n>={self.params['min_n']}"
        elif self.rule == "legacy_two_sigma":
            head = "Legacy 2σ (one strict pass)"
        elif self.rule == "legacy_chauvenet":
            head = f"Legacy Chauvenet P={self.params['probability']:g} (single worst, repeated)"
        else:
            head = f"k-sigma k={self.params['k']:g} max {self.params['max_iterations']} passes"
        mode = "synced" if self.synced else "per function"
        return f"{head} ({self.scope}, {mode}): {len(self.cycles)} cycles"

    def to_dict(self) -> dict[str, Any]:
        result = {
            "rule": self.rule,
            "params": dict(self.params),
            "scope": self.scope,
            "keys": list(self.keys),
            "synced": self.synced,
            "rejected": {key: list(rows) for key, rows in self.rejected.items()},
        }
        if self.targets is not None:
            result.update(targets={k: list(v) for k, v in self.targets.items()},
                          group_keys=list(self.group_keys), evaluation=self.evaluation, free_synced=self.free_synced,
                          flagged={k: list(v) for k, v in self.flagged.items()},
                          before_after=self.before_after)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleProposal:
        return cls(
            rule=data["rule"],
            params=dict(data["params"]),
            scope=data["scope"],
            keys=tuple(data["keys"]),
            synced=bool(data["synced"]),
            rejected={key: tuple(int(i) for i in rows) for key, rows in data["rejected"].items()},
            targets={k: tuple(v) for k, v in data["targets"].items()} if "targets" in data else None,
            group_keys=tuple(data.get("group_keys", ())),
            evaluation=data.get("evaluation", "per_function"),
            free_synced=data.get("free_synced"),
            flagged={k: tuple(v) for k, v in data.get("flagged", {}).items()},
            before_after=dict(data.get("before_after", {})),
        )


def _rule_values(values: np.ndarray, is_ratio: bool, log_ratios: bool) -> np.ndarray:
    return transform(values, "geometric") if (is_ratio and log_ratios) else values


def propose(
    rule: str,
    values: np.ndarray,
    include: np.ndarray,
    keys: Sequence[str],
    is_ratio: Sequence[bool],
    block: np.ndarray,
    *,
    scope: Scope = "run",
    synced: bool = True,
    **params: Any,
) -> RuleProposal:
    """Run a rule over several functions and return the proposal.

    ``values`` and ``include`` are ``n_cycles × len(keys)`` (the columns of the
    examined functions and their *effective* inclusion); ``block`` holds the
    block number of each row. ``params`` are the rule's own keyword arguments
    plus ``log_ratios`` (Chauvenet default False, as Tripoli; k-σ default True).
    """
    if rule not in RULES:
        raise ValueError(f"unknown rule {rule!r}; expected one of {RULES}")
    if scope not in ("run", "block"):
        raise ValueError(f"unknown scope {scope!r}")
    values = np.asarray(values, dtype=np.float64)
    include = np.asarray(include, dtype=bool)
    block = np.asarray(block)
    if values.shape != include.shape or values.ndim != 2 or values.shape[1] != len(keys) or len(is_ratio) != len(keys):
        raise ValueError("values, include, keys and is_ratio do not agree")
    if rule in ("legacy_two_sigma", "legacy_chauvenet"):
        settings = {"log_ratios": False}
        if rule == "legacy_chauvenet":
            settings["probability"] = float(params.pop("probability", 0.5))
        def apply(v, m):
            if rule == "legacy_two_sigma":
                return legacy_two_sigma_rejections(v, m)
            return legacy_chauvenet_rejections(v, m, probability=settings["probability"])
    elif rule == "chauvenet":
        settings = {
            "probability": float(params.pop("probability", CHAUVENET_PROBABILITY)),
            "min_n": int(params.pop("min_n", CHAUVENET_MIN_N)),
            "log_ratios": bool(params.pop("log_ratios", False)),
        }

        def apply(v: np.ndarray, m: np.ndarray) -> np.ndarray:
            return chauvenet_rejections(v, m, probability=settings["probability"], min_n=settings["min_n"])
    else:
        settings = {
            "k": float(params.pop("k", K_SIGMA)),
            "max_iterations": int(params.pop("max_iterations", K_SIGMA_MAX_ITERATIONS)),
            "log_ratios": bool(params.pop("log_ratios", True)),
        }

        def apply(v: np.ndarray, m: np.ndarray) -> np.ndarray:
            return k_sigma_rejections(v, m, k=settings["k"], max_iterations=settings["max_iterations"])
    if params:
        raise TypeError(f"unexpected parameters for {rule}: {sorted(params)}")
    groups = [np.arange(values.shape[0])] if scope == "run" else [np.flatnonzero(block == b) for b in np.unique(block)]
    rejected: dict[str, tuple[int, ...]] = {}
    for j, key in enumerate(keys):
        column = _rule_values(values[:, j], bool(is_ratio[j]), settings["log_ratios"])
        rows: list[int] = []
        for group in groups:
            rows.extend(int(group[i]) for i in apply(column[group], include[group, j]))
        rejected[key] = tuple(sorted(rows))
    return RuleProposal(rule=rule, params=settings, scope=scope, keys=tuple(keys), synced=bool(synced), rejected=rejected)


__all__ = [
    "CHAUVENET_MIN_N",
    "CHAUVENET_PROBABILITY",
    "K_SIGMA",
    "K_SIGMA_MAX_ITERATIONS",
    "RULES",
    "RuleProposal",
    "chauvenet_rejections",
    "k_sigma_rejections",
    "legacy_chauvenet_rejections",
    "legacy_two_sigma_rejections",
    "propose",
]
