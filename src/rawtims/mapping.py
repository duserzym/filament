"""Map run functions to contract ratios (SPEC F14).

A mapping says which function of an analysis supplies each contract ratio
(``206Pb/204Pb`` … ``202Pb/205Pb``, ``238U/235U``, ``233U/235U``,
``238U/233U``). :func:`propose_mapping` proposes one from the functions;
:class:`MethodMapping` is the same choice as plain data, keyed by the method
name, so a session can remember it and apply it to the next run of that method.

**Candidates.** A function is a candidate for ``aXX/bYY`` when its parsed
numerator and denominator masses are (a, b), or (b, a) for the inverted
orientation:

* ordinary ratio names: ``206/204``, ``206/204 D``, ``206/204 F-D``,
  ``206/204 Daly``, ``Pb206+At206/Tl205 raw``;
* IsoLinx shorthand ``R<d><d>`` for Pb (``R64`` = 206/204: masses 20d), checked
  against the ``#FUNCTIONS`` formula when the run has one: the
  ``Intensity(i,cup)`` terms of the formula must agree with the masses of the
  intensity functions that read the same ``Intensity(i,cup)``;
* U: only **oxide-corrected** functions, i.e. the engine's derived ``238/235oc``,
  ``233/235oc``, ``238/233oc`` or pass-through columns such as
  ``238/235 oxide R18 0.00206``. Raw ``270/267`` has masses 270/267 and is
  never a candidate; a function with masses 238/235 that is not marked
  oxide-corrected is refused with a message.

**Ranking.** For each ratio:

1. *Collector.* ``D``/``Daly`` is Daly; ``F``, ``Faraday`` and mixed suffixes
   starting with F (``F-D``, ``F/F``) are Faraday. When candidates of the
   wanted collector exist (the fraction's ``Collector`` setting, ``D`` when
   unset, as at Boise State), only those stay. Otherwise the remaining
   candidates stay; if the setting was explicit and only the other collector
   is available, the ratio is mapped and a ``warning`` issue says so.
2. *Tier.* Processed functions before ``raw`` ones (a ``raw`` descriptor or an
   isobar label such as ``Pb206+At206`` marks the instrument's unprocessed
   ratio, not the user's function), and the direct orientation before the
   inverted one.
3. *Family.* If several candidates remain, the one whose name family (the
   descriptor after the ratio, e.g. ``D`` vs ``Daly``) supplies the most
   contract ratios of the block wins. If one family still has several columns
   with identical values (IonVantage repeats user functions), the first is
   taken and the others are listed as alternatives. Anything else is an
   ``ambiguous`` issue and the ratio stays unmapped: the user must choose.

**Inversion.** Using 1/(204/206) for 206/204 is allowed only in geometric
statistics mode: the geometric mean of 1/x is exactly 1/(geometric mean of x),
and SD(ln 1/x) = SD(ln x), so the 1σ % SE (Tripoli's smaller-side
convention) is the same. In arithmetic mode mean(1/x) ≠ 1/mean(x), so the
mapping refuses it. Inverted ratios are recorded in ``MappedRatio.inverted``
and in the exported ``Notes``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import re
from typing import Any, Literal

import numpy as np

from rawtims import stats as _stats
from rawtims.contract import PB_RATIOS, PB_REQUIRED_RATIOS, U_RATIOS, U_REQUIRED_RATIOS, ratio_masses
from rawtims.model import Function
from rawtims.readers.functions import ratio_descriptor

MAPPING_FORMAT_VERSION = 1
Source = Literal["file", "derived", "pass_through"]
IssueKind = Literal["missing", "ambiguous", "refused", "warning"]

_SHORTHAND = re.compile(r"^R(\d)(\d)$")
_INTENSITY_TERM = re.compile(r"Intensity\(\s*([^)]*?)\s*\)")
_RATIO_FORMULA = re.compile(r"^\s*(Intensity\([^)]*\))\s*/\s*(Intensity\([^)]*\))\s*$")


class MappingError(ValueError):
    """A mapping that cannot be used as asked (e.g. an inverted ratio in arithmetic mode)."""


def element_ratios(element: str) -> tuple[str, ...]:
    if element == "Pb":
        return PB_RATIOS
    if element == "U":
        return U_RATIOS
    raise ValueError(f"unknown element {element!r}")


def required_ratios(element: str) -> tuple[str, ...]:
    return PB_REQUIRED_RATIOS if element == "Pb" else U_REQUIRED_RATIOS


@dataclass(frozen=True)
class MappedRatio:
    """One contract ratio and the function that supplies it.

    ``key`` is the analysis function key (unique; ``"206/207 F #2"`` for a
    repeated name) and ``name`` the function's name as in the file, which the
    Tripoli clipboard uses. ``inverted`` means the contract value is 1/function.
    ``oxide_r18`` is the 18O/16O of an oxide-corrected U function (derived or
    from its name), None otherwise or when unknown.
    """

    ratio: str
    key: str
    name: str
    inverted: bool = False
    source: Source = "file"
    collector: str | None = None
    family: str = ""
    raw: bool = False
    oxide_r18: float | None = None
    alternatives: tuple[str, ...] = ()
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"function": self.key, "inverted": self.inverted}


@dataclass(frozen=True)
class MappingIssue:
    ratio: str
    kind: IssueKind
    message: str
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    key: str
    name: str
    masses: tuple[int, int]
    collector: str | None
    family: str
    raw: bool
    source: Source
    oxide_r18: float | None
    index: int


@dataclass
class ElementMapping:
    """The mapping of one analysis (one element): mapped ratios plus the issues found."""

    element: str
    method: str | None
    stat_mode: str
    ratios: dict[str, MappedRatio] = field(default_factory=dict)
    issues: tuple[MappingIssue, ...] = ()
    collector: str | None = None

    @property
    def function_keys(self) -> list[str]:
        """Keys of the mapped functions in contract order, without repeats."""
        keys = [self.ratios[r].key for r in element_ratios(self.element) if r in self.ratios]
        return list(dict.fromkeys(keys))

    @property
    def missing_required(self) -> list[str]:
        return [r for r in required_ratios(self.element) if r not in self.ratios]

    @property
    def complete(self) -> bool:
        return not self.missing_required

    def issues_for(self, ratio: str) -> list[MappingIssue]:
        return [issue for issue in self.issues if issue.ratio == ratio]

    def describe_missing(self) -> str:
        """One sentence per missing required ratio, with the reason found."""
        parts = []
        for ratio in self.missing_required:
            reasons = [issue.message for issue in self.issues_for(ratio) if issue.kind != "warning"]
            parts.append(f"{ratio}: {reasons[0] if reasons else 'no candidate function'}")
        return "; ".join(parts)

    def to_method_mapping(self) -> MethodMapping:
        if not self.method:
            raise MappingError("this run has no method name to remember the mapping by")
        return MethodMapping(
            method=self.method,
            element=self.element,
            ratios={ratio: mapped.to_dict() for ratio, mapped in self.ratios.items()},
            collector=self.collector,
        )


# ----------------------------------------------------------- candidates
def _collector_of(function: Function) -> str | None:
    if function.collector in ("D", "F"):
        return function.collector
    suffix = function.metadata.get("collector_suffix")
    if isinstance(suffix, str) and suffix[:1] in ("D", "F"):
        return suffix[0]
    return None


def _intensity_masses(functions: Sequence[Function]) -> dict[str, int]:
    """``"1,_RPM"`` → mass, from intensity functions whose IsoLinx formula is a single ``Intensity(...)`` term."""
    known: dict[str, int] = {}
    for function in functions:
        formula = function.metadata.get("formula")
        if function.kind != "intensity" or function.mass is None or not isinstance(formula, str):
            continue
        terms = _INTENSITY_TERM.findall(formula)
        if len(terms) == 1 and formula.strip().startswith("Intensity(") and formula.strip().endswith(")"):
            known[terms[0].replace(" ", "")] = function.mass
    return known


def _shorthand_masses(function: Function, element: str, intensity_masses: dict[str, int]) -> tuple[int, int] | None:
    """Masses of an IsoLinx ``R<d><d>`` function, or None when it is not one (or its formula disagrees)."""
    match = _SHORTHAND.match(function.name.strip())
    if not match or element != "Pb":
        return None
    masses = (200 + int(match.group(1)), 200 + int(match.group(2)))
    if not all(202 <= mass <= 208 for mass in masses) or masses[0] == masses[1]:
        return None
    formula = function.metadata.get("formula")
    if isinstance(formula, str) and formula.strip():
        parts = _RATIO_FORMULA.match(formula)
        if not parts:
            return None  # a formula that is not a plain ratio of two intensities: not a measured ratio
        for term, mass in zip(parts.groups(), masses):
            inside = _INTENSITY_TERM.findall(term)[0].replace(" ", "")
            if inside in intensity_masses and intensity_masses[inside] != mass:
                return None
    return masses


def _candidates(functions: Sequence[Function], element: str) -> tuple[list[_Candidate], list[_Candidate]]:
    """Return ``(usable, refused)``: refused are U functions with contract masses that are not oxide-corrected."""
    intensity_masses = _intensity_masses(functions)
    usable: list[_Candidate] = []
    refused: list[_Candidate] = []
    for function in functions:
        metadata = function.metadata
        source: Source = "file"
        oxide_r18 = None
        if function.is_ratio and function.numerator_mass and function.denominator_mass:
            masses = (function.numerator_mass, function.denominator_mass)
            descriptor = ratio_descriptor(function.name)
            family = descriptor if descriptor is not None else ""
        else:
            shorthand = _shorthand_masses(function, element, intensity_masses)
            if shorthand is None:
                continue
            masses, family = shorthand, "R shorthand"
        if metadata.get("derived") == "oxide":
            source, oxide_r18 = "derived", metadata.get("r18")
            family = "derived oxide correction"
        elif metadata.get("oxide_corrected"):
            source, oxide_r18 = "pass_through", metadata.get("oxide_r18")
        tokens = re.split(r"[\s_]+", family.lower())
        raw = "raw" in tokens or "+" in (function.numerator or "") or "+" in (function.denominator or "")
        candidate = _Candidate(function.key, function.name, masses, _collector_of(function), family, raw, source, oxide_r18, function.index)
        if element == "U" and source == "file":
            refused.append(candidate)
        else:
            usable.append(candidate)
    return usable, refused


def _identical(analysis: Any, keys: Sequence[str]) -> bool:
    first = np.asarray(analysis.column(keys[0]))
    return all(np.array_equal(first, np.asarray(analysis.column(key)), equal_nan=True) for key in keys[1:])


def _names(candidates: Sequence[_Candidate]) -> tuple[str, ...]:
    return tuple(candidate.key for candidate in candidates)


def propose_mapping(analysis: Any, element: str | None = None, *, collector: str | None = None) -> ElementMapping:
    """Propose the function for each contract ratio of one analysis (see the module docstring for the rules).

    ``analysis`` is an :class:`~rawtims.analysis.Analysis` (its functions
    include the derived oxide columns). ``collector`` is the fraction's
    ``Collector`` setting (``"D"``, ``"F"`` or None for the default D).
    """
    element = element or analysis.run.element
    if element not in ("Pb", "U"):
        raise MappingError(f"cannot map a run whose element is {element!r}; set the element to Pb or U first")
    if collector not in (None, "D", "F"):
        raise MappingError(f"Collector must be 'D' or 'F', not {collector!r}")
    stat_mode = analysis.settings.stat_mode
    usable, refused = _candidates(analysis.functions, element)
    want = collector or "D"
    issues: list[MappingIssue] = []
    pools: dict[str, list[tuple[_Candidate, bool]]] = {}
    for ratio in element_ratios(element):
        masses = ratio_masses(ratio)
        direct = [c for c in usable if c.masses == masses]
        inverse = [c for c in usable if c.masses == masses[::-1]]
        rejected = [c for c in refused if c.masses in (masses, masses[::-1])]
        if rejected:
            issues.append(MappingIssue(ratio, "refused", f"{', '.join(_names(rejected))} not oxide-corrected; U ratios must be oxide-corrected", _names(rejected)))
        if stat_mode != "geometric" and inverse:
            if not direct:
                issues.append(MappingIssue(
                    ratio, "refused",
                    f"only the inverted orientation is measured ({', '.join(_names(inverse))}); inverting is exact only "
                    "for geometric means, and the statistics mode is arithmetic",
                    _names(inverse),
                ))
            inverse = []
        candidates = [(c, False) for c in direct] + [(c, True) for c in inverse]
        if not candidates:
            if ratio in required_ratios(element):
                if element == "U" and analysis.oxide.status == "not_applicable":
                    reason = f"no oxide-corrected function, and the oxide correction cannot run ({analysis.oxide.reason})"
                elif element == "U":
                    reason = "no oxide-corrected function with these masses in this run"
                else:
                    reason = "no function with these masses in this run"
                issues.append(MappingIssue(ratio, "missing", reason))
            continue
        kinds = {c.collector for c, _ in candidates}
        if want in kinds:
            pool = [(c, inv) for c, inv in candidates if c.collector == want]
        else:
            other = "F" if want == "D" else "D"
            unlabelled = [(c, inv) for c, inv in candidates if c.collector is None]
            pool = unlabelled or candidates
            if collector is not None and not unlabelled and other in kinds:
                issues.append(MappingIssue(ratio, "warning", f"Collector is {collector} but only {'Daly' if other == 'D' else 'Faraday'} functions measure {ratio}", _names([c for c, _ in pool])))
        best = min((c.raw, inv) for c, inv in pool)
        pools[ratio] = [(c, inv) for c, inv in pool if (c.raw, inv) == best]
    coverage: dict[str, int] = {}
    for pool in pools.values():
        for family in {c.family for c, _ in pool}:
            coverage[family] = coverage.get(family, 0) + 1
    ratios: dict[str, MappedRatio] = {}
    for ratio, pool in pools.items():
        chosen: _Candidate | None = None
        inverted = False
        note = ""
        alternatives: tuple[str, ...] = ()
        if len(pool) == 1:
            chosen, inverted = pool[0]
        else:
            top = max(coverage[c.family] for c, _ in pool)
            leaders = [(c, inv) for c, inv in pool if coverage[c.family] == top]
            families = {c.family for c, _ in leaders}
            if len(families) == 1 and (len(leaders) == 1 or _identical(analysis, [c.key for c, _ in leaders])):
                chosen, inverted = leaders[0]
                alternatives = tuple(c.key for c, _ in pool if c.key != chosen.key)
            else:
                issues.append(MappingIssue(
                    ratio, "ambiguous",
                    f"several functions could supply {ratio} ({', '.join(c.key for c, _ in pool)}); choose one",
                    tuple(c.key for c, _ in pool),
                ))
                continue
        assert chosen is not None
        if inverted:
            note = f"{ratio} = 1/({chosen.name}), geometric mean (exact)"
        ratios[ratio] = MappedRatio(
            ratio=ratio, key=chosen.key, name=chosen.name, inverted=inverted, source=chosen.source,
            collector=chosen.collector, family=chosen.family, raw=chosen.raw, oxide_r18=chosen.oxide_r18,
            alternatives=alternatives, note=note,
        )
    return ElementMapping(element=element, method=analysis.run.metadata.method, stat_mode=stat_mode, ratios=ratios, issues=tuple(issues), collector=collector)


# ------------------------------------------------------------ remembered
@dataclass(frozen=True)
class MethodMapping:
    """A mapping as plain data, remembered per instrument method name.

    ``ratios`` maps contract ratio → ``{"function": <key>, "inverted": bool}``.
    JSON round trip: :meth:`to_dict` / :meth:`from_dict`.
    """

    method: str
    element: str
    ratios: Mapping[str, Mapping[str, Any]]
    collector: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": MAPPING_FORMAT_VERSION,
            "method": self.method,
            "element": self.element,
            "collector": self.collector,
            "ratios": {ratio: {"function": str(entry["function"]), "inverted": bool(entry.get("inverted", False))} for ratio, entry in self.ratios.items()},
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MethodMapping:
        version = data.get("format_version", MAPPING_FORMAT_VERSION)
        if version != MAPPING_FORMAT_VERSION:
            raise MappingError(f"mapping format version {version!r} is not supported")
        element = data["element"]
        known = set(element_ratios(element))
        ratios = {}
        for ratio, entry in dict(data["ratios"]).items():
            if ratio not in known:
                raise MappingError(f"{ratio!r} is not a contract ratio of the {element} block")
            ratios[ratio] = {"function": str(entry["function"]), "inverted": bool(entry.get("inverted", False))}
        return cls(method=str(data["method"]), element=element, ratios=ratios, collector=data.get("collector"))

    def apply(self, analysis: Any) -> ElementMapping:
        """Resolve the remembered keys in ``analysis``; anything that no longer fits becomes an issue."""
        if analysis.run.element not in (None, self.element):
            raise MappingError(f"mapping for {self.element} applied to a {analysis.run.element} run")
        stat_mode = analysis.settings.stat_mode
        usable, refused = _candidates(analysis.functions, self.element)
        by_key = {c.key: c for c in usable}
        refused_keys = {c.key for c in refused}
        issues: list[MappingIssue] = []
        ratios: dict[str, MappedRatio] = {}
        for ratio, entry in self.ratios.items():
            key, inverted = entry["function"], bool(entry.get("inverted", False))
            masses = ratio_masses(ratio)
            if key in refused_keys:
                issues.append(MappingIssue(ratio, "refused", f"{key} is not oxide-corrected; U ratios must be oxide-corrected", (key,)))
                continue
            candidate = by_key.get(key)
            if candidate is None:
                issues.append(MappingIssue(ratio, "missing", f"remembered function {key!r} is not in this run", (key,)))
                continue
            if candidate.masses != (masses[::-1] if inverted else masses):
                issues.append(MappingIssue(ratio, "refused", f"remembered function {key!r} has masses {candidate.masses}, which do not give {ratio}", (key,)))
                continue
            if inverted and stat_mode != "geometric":
                issues.append(MappingIssue(ratio, "refused", f"{ratio} = 1/({candidate.name}) needs geometric statistics; the mode is arithmetic", (key,)))
                continue
            ratios[ratio] = MappedRatio(
                ratio=ratio, key=key, name=candidate.name, inverted=inverted, source=candidate.source,
                collector=candidate.collector, family=candidate.family, raw=candidate.raw, oxide_r18=candidate.oxide_r18,
                note=f"{ratio} = 1/({candidate.name}), geometric mean (exact)" if inverted else "",
            )
        for ratio in required_ratios(self.element):
            if ratio not in self.ratios:
                issues.append(MappingIssue(ratio, "missing", "not in the remembered mapping"))
        return ElementMapping(element=self.element, method=analysis.run.metadata.method, stat_mode=stat_mode, ratios=ratios, issues=tuple(issues), collector=self.collector)


def mapping_for(analysis: Any, remembered: Mapping[str, MethodMapping] | None = None, *, collector: str | None = None) -> ElementMapping:
    """The remembered mapping of this run's method when there is one and it resolves completely, else a proposal."""
    method = analysis.run.metadata.method
    if remembered and method in remembered:
        mapping = remembered[method].apply(analysis)
        if mapping.complete and not any(issue.kind in ("refused", "missing") for issue in mapping.issues):
            return mapping
    return propose_mapping(analysis, collector=collector)


# ------------------------------------------------------------ statistics
def mapped_values(analysis: Any, mapped: MappedRatio) -> tuple[np.ndarray, np.ndarray]:
    """``(values, include)`` of the contract ratio per cycle: the function's column, or 1/column when inverted."""
    values = np.asarray(analysis.column(mapped.key), dtype=np.float64)
    include = analysis.included_for(mapped.key)
    if mapped.inverted:
        if analysis.settings.stat_mode != "geometric":
            raise MappingError(f"{mapped.ratio} = 1/({mapped.name}) is exact only for geometric means; the statistics mode is arithmetic")
        with np.errstate(divide="ignore", invalid="ignore"):
            values = 1.0 / values
    return values, include


def ratio_stats(analysis: Any, mapped: MappedRatio) -> _stats.Stats:
    """Statistics of a contract ratio: ratio statistics (the analysis's mode) over the function's included cycles.

    For a direct mapping of a ratio function this is exactly
    ``analysis.stats(key)``; IsoLinx shorthand functions (classified
    ``other``) get ratio statistics too, because they are ratios.
    """
    values, include = mapped_values(analysis, mapped)
    return _stats.describe(values, include, mode=analysis.settings.stat_mode)


def ratio_usable(analysis: Any, mapped: MappedRatio) -> np.ndarray:
    values, include = mapped_values(analysis, mapped)
    return _stats.usable(values, include, mode=analysis.settings.stat_mode)


def ratio_correlation(analysis: Any, a: MappedRatio, b: MappedRatio) -> _stats.Correlation:
    """Pearson r of two contract ratios over the cycles included and usable for both (see :func:`rawtims.stats.correlation`)."""
    mode = analysis.settings.stat_mode
    va, ia = mapped_values(analysis, a)
    vb, ib = mapped_values(analysis, b)
    return _stats.correlation(va, vb, ia, ib, mode_a=mode, mode_b=mode)


__all__ = [
    "MAPPING_FORMAT_VERSION",
    "ElementMapping",
    "MappedRatio",
    "MappingError",
    "MappingIssue",
    "MethodMapping",
    "element_ratios",
    "mapped_values",
    "mapping_for",
    "propose_mapping",
    "ratio_correlation",
    "ratio_stats",
    "ratio_usable",
    "required_ratios",
]
