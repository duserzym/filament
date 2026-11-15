"""Fractions: the Pb and U analyses of one fraction and their contract row (SPEC F5, F15, section 3).

A :class:`Fraction` pairs an optional Pb :class:`~rawtims.analysis.Analysis`
with an optional U one under a user-set ``fraction_id`` and carries the
identity and setup fields of the contract. :func:`fraction_row` turns it into
one :class:`~rawtims.contract.FractionRow`.

Exported values:

* ``<ratio> Mean`` and ``<ratio> % Standard Error``: the statistics of the
  mapped function over its accepted cycles (:func:`rawtims.mapping.ratio_stats`,
  identical to ``Analysis.stats`` for a direct mapping): arithmetic by default,
  as legacy Tripoli (mean and 100·SD/√n/mean); geometric mode remains optional.
* ``rho A|B`` for every pair of mapped ratios of the same run, over the cycles
  included and usable for both (:func:`rawtims.mapping.ratio_correlation`).
* ``<El> Cycles Used``: the cycles accepted (included and usable) for **every**
  mapped ratio of the block; ``<El> Cycles Total``: the run's cycle rows.
* ``<El> Run Start``: ISO 8601 with offset, as the contract asks. The files
  carry no time zone, so the column is filled only when the instrument's time
  zone is known (``Fraction.timezone``, an IANA name such as
  ``America/Boise``, or a timezone-aware start from the reader). Otherwise it is
  left empty and ``Notes`` records the instrument's local start time.
* ``Filter Rule``: a short text from the edit history (:func:`filter_rule_text`).
* ``U Oxide 18O/16O``: the r18 of the oxide correction behind the mapped
  238/235 and 233/235 (the engine's derived columns, or the value in the names of
  pass-through columns); empty when no value is known.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np

from rawtims.analysis import Analysis
from rawtims.branding import APP_NAME, RAW_APP_LABEL
from rawtims.contract import (
    CONTRACT_ID,
    FractionRow,
    mean_column,
    rho_column,
    se_column,
)
from rawtims.mapping import ElementMapping, MappingError, element_ratios, propose_mapping, ratio_correlation, ratio_stats, ratio_usable
from rawtims.readers.functions import suggest_fraction_id

SPIKE_TYPES = ("535", "2535")
COLLECTORS = ("F", "D")


class FractionError(ValueError):
    """A fraction that cannot be exported as asked; the message says why."""


@dataclass(frozen=True)
class SessionInfo:
    """The saved session file a row points to (``Raw App Session`` and its SHA-256)."""

    name: str
    sha256: str | None = None


def _normalise_spike_type(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None and number.is_integer():
        text = str(int(number))
    if text not in SPIKE_TYPES:
        raise FractionError(f"Spike Type must be 535 or 2535, not {value!r}")
    return text


@dataclass
class Fraction:
    """One fraction: its Pb and U analyses, identity, setup and the function-to-ratio mapping per element."""

    fraction_id: str
    pb: Analysis | None = None
    u: Analysis | None = None
    sample: str | None = None
    beaker: str | None = None
    source_mount: str | None = None
    source_grain: str | None = None
    source_spot: str | None = None
    aliquot: str | None = None
    sample_weight_mg: float | None = None
    spike_weight_g: float | None = None
    spike_type: str | None = None
    spike: str | None = None
    collector: str | None = None
    pb_collector_detail: str | None = None
    instrument: str | None = None
    timezone: str | None = None
    notes: str | None = None
    pb_mapping: ElementMapping | None = None
    u_mapping: ElementMapping | None = None

    def __post_init__(self) -> None:
        if not self.fraction_id or not str(self.fraction_id).strip():
            raise FractionError("a fraction needs a Fraction ID")
        self.spike_type = _normalise_spike_type(self.spike_type)
        if self.collector not in (None, *COLLECTORS):
            raise FractionError(f"Collector must be 'F' or 'D', not {self.collector!r}")
        for slot, element in (("pb", "Pb"), ("u", "U")):
            analysis = getattr(self, slot)
            if analysis is not None and analysis.run.element not in (None, element):
                raise FractionError(f"the {element} slot holds a {analysis.run.element} run ({analysis.run.raw.name})")
        for element in ("Pb", "U"):
            analysis = self.analysis(element)
            if analysis is not None:
                stored = self.pb_mapping if element == "Pb" else self.u_mapping
                mapping = stored or propose_mapping(analysis, element, collector=self.collector if element == "Pb" else None)
                if not analysis.legacy_pending:
                    analysis.set_mapping(mapping)
        if self.timezone is not None:
            try:
                ZoneInfo(self.timezone)
            except (ZoneInfoNotFoundError, ValueError):
                raise FractionError(f"unknown time zone {self.timezone!r}; use an IANA name such as 'America/Boise'") from None

    def analysis(self, element: str) -> Analysis | None:
        return self.pb if element == "Pb" else self.u

    def mapping(self, element: str) -> ElementMapping | None:
        """The stored mapping of one element, or a fresh proposal from the analysis (None without an analysis)."""
        analysis = self.analysis(element)
        if analysis is None:
            return None
        stored = self.pb_mapping if element == "Pb" else self.u_mapping
        return stored if stored is not None else propose_mapping(analysis, element, collector=self.collector if element == "Pb" else None)


# ------------------------------------------------------------- pairing
@dataclass
class Pairing:
    """Result of :func:`pair_analyses`: fractions, and analyses it could not place (with the reason)."""

    fractions: list[Fraction] = field(default_factory=list)
    unplaced: list[tuple[Analysis, str]] = field(default_factory=list)


def suggested_fraction_id(analysis: Analysis) -> str:
    """The fraction ID suggested for a run: its sample ID without the element tag, else the file stem."""
    run = analysis.run
    stem = run.raw.name.rsplit(".", 1)[0]
    return suggest_fraction_id(run.metadata.sample_id) or stem


def pair_analyses(analyses: Iterable[Analysis]) -> Pairing:
    """Group analyses into fractions by :func:`suggested_fraction_id` (a suggestion for the user to confirm).

    A group gets at most one Pb and one U analysis; further runs of the same
    element, and runs with no element, are returned in ``unplaced``.
    """
    result = Pairing()
    groups: dict[str, Fraction] = {}
    for analysis in analyses:
        element = analysis.run.element
        if element not in ("Pb", "U"):
            result.unplaced.append((analysis, "element unknown; set Pb or U"))
            continue
        fid = suggested_fraction_id(analysis)
        fraction = groups.get(fid)
        if fraction is None:
            fraction = Fraction(fraction_id=fid, sample=analysis.run.metadata.sample_id)
            groups[fid] = fraction
            result.fractions.append(fraction)
        slot = "pb" if element == "Pb" else "u"
        if getattr(fraction, slot) is not None:
            result.unplaced.append((analysis, f"fraction {fid!r} already has a {element} run ({getattr(fraction, slot).run.raw.name})"))
            continue
        setattr(fraction, slot, analysis)
    return result


# --------------------------------------------------------- provenance text
def _changed_rows(op: Mapping[str, Any]) -> set[int]:
    return {int(row) for row, _ in op.get("changed", [])}


def filter_rule_text(analysis: Analysis) -> str:
    """Short text of the rejections in effect, from the history, e.g.
    ``Chauvenet P=0.5 n>=20 (synced, 3 cycles); 2 manual cycles; blocks 4, 7 excluded``.

    Rules are listed in the order applied, with the cycles each one actually
    excluded (``block`` scope and per-function mode are named when used). Hand
    edits are summarised as the cycles still excluded by hand. A reset clears
    what came before it. ``none`` when nothing is excluded.
    """
    parts: list[str] = []
    manual: set[int] = set()
    for op in analysis.history:
        kind = op["op"]
        if kind == "reset":
            parts, manual = [], set()
        elif kind == "apply_rule":
            params = op["params"]
            if op["rule"] == "chauvenet":
                head = f"Chauvenet P={params['probability']:g} n>={params['min_n']}"
                if params.get("log_ratios"):
                    head += " ln"
            else:
                head = f"k-sigma k={params['k']:g} max {params['max_iterations']} passes"
                if not params.get("log_ratios", True):
                    head += " linear"
            detail = [] if op["scope"] == "run" else [f"{op['scope']} scope"]
            detail.append("synced" if op["synced"] else "per function")
            count = len(_changed_rows(op))
            detail.append(f"{count} cycle{'s' if count != 1 else ''}")
            parts.append(f"{head} ({', '.join(detail)})")
        elif kind == "toggle_cycles":
            rows = _changed_rows(op)
            manual = (manual - rows) if op["include"] else (manual | rows)
    if manual:
        parts.append(f"{len(manual)} manual cycle{'s' if len(manual) != 1 else ''}")
    excluded_blocks = [int(b) for b in analysis.blocks[~analysis.block_included]]
    if excluded_blocks:
        parts.append(f"block{'s' if len(excluded_blocks) != 1 else ''} {', '.join(map(str, excluded_blocks))} excluded")
    return "; ".join(parts) if parts else "none"


def _iso_start(analysis: Analysis, timezone: str | None) -> tuple[str | None, str | None]:
    """``(Run Start text or None, note or None)``; see the module docstring."""
    start = analysis.run.metadata.analysis_start
    if start is None:
        raw = analysis.run.metadata.analysis_start_raw
        return None, (f"start time not read from the file ({raw!r})" if raw else None)
    if start.tzinfo is not None:
        return start.isoformat(), None
    if timezone is not None:
        return start.replace(tzinfo=ZoneInfo(timezone)).isoformat(), None
    return None, f"run start {start.isoformat()} instrument local time (no time zone known)"


# ----------------------------------------------------------- export row
def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FractionError(message)


def require_shared_selection(analysis: Analysis) -> None:
    consistent = analysis.group_consistent()  # Check at every ordinary export boundary.
    _require(consistent and not analysis.legacy_pending,
             f"{analysis.run.raw.name}: per-ratio selection (legacy); use the union of rejections before exporting")


def fraction_row(fraction: Fraction, exported_at: datetime, session_info: SessionInfo | None = None) -> FractionRow:
    """The contract row of one fraction. Raises :class:`FractionError` when a block cannot be exported.

    ``exported_at`` must be timezone-aware (the contract asks for ISO 8601 with
    an offset).
    """
    _require(fraction.pb is not None or fraction.u is not None, f"fraction {fraction.fraction_id!r} has neither a Pb nor a U run")
    _require(exported_at.tzinfo is not None and exported_at.utcoffset() is not None, "exported_at must be timezone-aware")
    values: dict[str, Any] = {
        "Contract": CONTRACT_ID,
        "Fraction ID": fraction.fraction_id,
        "Sample": fraction.sample,
        "Beaker": fraction.beaker,
        "Source Mount": fraction.source_mount,
        "Source Grain": fraction.source_grain,
        "Source Spot": fraction.source_spot,
        "Aliquot": fraction.aliquot,
        "Sample Weight (mg)": fraction.sample_weight_mg,
        "Spike Weight (g)": fraction.spike_weight_g,
        "Spike Type": fraction.spike_type,
        "Spike": fraction.spike,
        "Collector": fraction.collector,
        "Pb Collector Detail": fraction.pb_collector_detail,
    }
    notes: list[str] = []
    rules: list[tuple[str, str]] = []
    instruments: list[str] = []
    for element in ("Pb", "U"):
        analysis = fraction.analysis(element)
        if analysis is None:
            continue
        run = analysis.run
        mapping = fraction.mapping(element)
        assert mapping is not None
        require_shared_selection(analysis)
        _require(
            mapping.complete,
            f"fraction {fraction.fraction_id!r}: the {element} run {run.raw.name} lacks contract ratios: {mapping.describe_missing()}",
        )
        if element == "Pb" and fraction.spike_type == "2535":
            _require(
                "202Pb/205Pb" in mapping.ratios,
                f"fraction {fraction.fraction_id!r}: Spike Type 2535 needs measured 202Pb/205Pb (contract: required when "
                f"Spike Type = 2535), but no 202/205 function is mapped in {run.raw.name}",
            )
        mapped = [mapping.ratios[r] for r in element_ratios(element) if r in mapping.ratios]
        try:
            for entry in mapped:
                stats = ratio_stats(analysis, entry)
                _require(
                    np.isfinite(stats.mean) and stats.mean > 0 and np.isfinite(stats.se_pct),
                    f"fraction {fraction.fraction_id!r}: {entry.ratio} from {entry.key} has no valid mean and error "
                    f"({stats.n_used} usable cycles)",
                )
                values[mean_column(entry.ratio)] = stats.mean
                values[se_column(entry.ratio)] = stats.se_pct
                if entry.note:
                    notes.append(f"{element}: {entry.note}")
            for i, a in enumerate(mapped):
                for b in mapped[i + 1 :]:
                    r = ratio_correlation(analysis, a, b).r
                    if np.isfinite(r):
                        values[rho_column(a.ratio, b.ratio)] = r
            used = np.logical_and.reduce([ratio_usable(analysis, entry) for entry in mapped])
        except MappingError as error:
            raise FractionError(f"fraction {fraction.fraction_id!r}: {error}") from None
        values[f"{element} Raw File"] = run.raw.name
        values[f"{element} Raw SHA256"] = run.raw.sha256
        values[f"{element} Method"] = run.metadata.method
        values[f"{element} Cycles Used"] = int(used.sum())
        values[f"{element} Cycles Total"] = run.n_cycles
        values[f"{element} Mean Statistic"] = analysis.settings.stat_mode
        values[f"{element} Cycle Selection"] = "shared"  # contract clarification 8: enforced shared mask
        start, note = _iso_start(analysis, fraction.timezone)
        values[f"{element} Run Start"] = start
        if note:
            notes.append(f"{element}: {note}")
        rules.append((element, filter_rule_text(analysis)))
        if run.metadata.instrument:
            instruments.append(run.metadata.instrument)
        if element == "U":
            r18_values = {e.oxide_r18 for e in mapped if e.ratio in ("238U/235U", "233U/235U") and e.oxide_r18 is not None}
            _require(len(r18_values) <= 1, f"fraction {fraction.fraction_id!r}: the U ratios name different 18O/16O values {sorted(r18_values)}")
            sources = {e.source for e in mapped}
            _require(not {"derived", "pass_through"} <= sources, f"fraction {fraction.fraction_id!r}: the U ratios mix oxide-corrected values from the instrument file and from {APP_NAME}")
            if "derived" in sources:
                formula = analysis.oxide.formula
                notes.append(f"U: oxide correction by {APP_NAME} ({formula} formula)")
            else:
                formula = "instrument"
                notes.append("U: the file already carries oxide-corrected columns; passed through, not recomputed (formula not known)")
            if r18_values:
                values["U Oxide 18O/16O"] = r18_values.pop()
                values["U Oxide Formula"] = formula
            else:
                notes.append("U: 18O/16O of the oxide correction not known (not in the function names)")
    if fraction.collector is None and fraction.pb is not None:
        collectors = {e.collector for e in fraction.mapping("Pb").ratios.values()}  # type: ignore[union-attr]
        if len(collectors) == 1 and None not in collectors:
            values["Collector"] = collectors.pop()
            notes.append(f"Pb: Collector {values['Collector']} taken from the mapped functions")
    if len(rules) == 1:
        values["Filter Rule"] = rules[0][1]
    else:
        values["Filter Rule"] = " | ".join(f"{element}: {text}" for element, text in rules)
    instrument = fraction.instrument or " / ".join(dict.fromkeys(instruments)) or None
    values["Instrument"] = instrument
    values["Raw App"] = RAW_APP_LABEL
    values["Exported At"] = exported_at.isoformat(timespec="seconds")
    if session_info is not None:
        values["Raw App Session"] = session_info.name
        values["Raw App Session SHA256"] = session_info.sha256
    if fraction.notes:
        notes.insert(0, fraction.notes)
    values["Notes"] = "; ".join(notes) or None
    return FractionRow(values=values)


def fraction_rows(fractions: Sequence[Fraction], exported_at: datetime, session_info: SessionInfo | None = None) -> list[FractionRow]:
    return [fraction_row(fraction, exported_at, session_info) for fraction in fractions]


__all__ = [
    "COLLECTORS",
    "SPIKE_TYPES",
    "Fraction",
    "FractionError",
    "Pairing",
    "SessionInfo",
    "filter_rule_text",
    "fraction_row",
    "fraction_rows",
    "pair_analyses",
    "suggested_fraction_id",
]
