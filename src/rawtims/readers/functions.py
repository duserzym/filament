"""Function-name classification, element detection and fraction-ID suggestions.

Classification works on the column name alone, so both formats behave alike:

* **ratio**: the name *starts* with ``<species>/<species>`` where each species
  carries a 2-3 digit mass number, optionally followed by a descriptor:
  ``206/204 D``, ``206/204 F-D``, ``270/267``, ``Pb206+At206/Tl205 raw``,
  ``208/206 F/F S1``, ``238/235 oxide R18 0.00206``. Names that start with a
  word, such as ``alpha 204/206`` (an IsoLinx user function), are not ratios.
  This is close to Tripoli's rule (a header regex that excludes names starting
  with ``alph``), restated as an anchored pattern.
* **intensity**: a single species with an optional ``i`` prefix and collector,
  sequence, unit or ``int`` tokens: ``204 D``, ``i265``, ``i204 Daly``,
  ``265UO2_V``, ``204Pb``, ``i205Pb``, ``Tl205 S2 int``.
* **other**: everything else (``Daly/Faraday Gain``, ``D/F Gain``, ``alpha
  204/206``, IsoLinx shorthand such as ``R45``).

A trailing ``oxide R18 <value>`` is parsed into ``metadata["oxide_r18"]`` and
``oxide`` anywhere in the descriptor sets ``metadata["oxide_corrected"]``, so
the engine can pass such columns through instead of correcting them again.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from rawtims.model import Element, Function, FunctionKind, unique_keys

_ELEMENTS = (  # noqa: SIM905 - three readable lines beat a 100-item list literal
    "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr "
    "Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb "
    "Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm"
).split()
# Longest symbols first so that "Pb" is not read as "P" + "b".
_SYMBOL = "(?:" + "|".join(sorted(_ELEMENTS, key=len, reverse=True)) + ")"
# A species: optional element symbol, 2-3 digit mass, optional molecule tail
# (``UO2``, ``Pb``), optionally joined to isobars with ``+`` (``Pb206+At206``).
# Only real element symbols may prefix the mass, so IsoLinx shorthand such as
# ``R45`` is not mistaken for a species.
_ATOM = rf"{_SYMBOL}?\d{{2,3}}(?:{_SYMBOL}\d*)*"
_SPECIES = rf"{_ATOM}(?:\+{_ATOM})*"
_RATIO = re.compile(rf"^(?P<num>{_SPECIES})\s*/\s*(?P<den>{_SPECIES})(?=$|[\s_])(?P<rest>.*)$")
_INTENSITY = re.compile(
    rf"^i?(?P<sp>{_SPECIES})(?P<rest>(?:[\s_]+(?:D|F|Daly|Faraday|V|mV|cps|CPS|S\d+|int|raw))*)\s*$"
)
_MASS = re.compile(r"(?<!\d)(\d{2,3})(?!\d)")
_OXIDE_R18 = re.compile(r"\boxide\s+R18\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*$", re.IGNORECASE)
_OXIDE = re.compile(r"\boxide\b", re.IGNORECASE)

PB_MASSES = frozenset(range(202, 209))
U_MASSES = frozenset({233, 234, 235, 236, 238, *range(265, 273)})


def _first_mass(species: str) -> int | None:
    match = _MASS.search(species)
    return int(match.group(1)) if match else None


def _collector(rest: str) -> tuple[str | None, str | None]:
    """Return (``"D"``/``"F"``/None, the raw collector token) from a descriptor."""
    tokens = [token for token in re.split(r"[\s_]+", rest.strip()) if token]
    for token in tokens:
        if token in {"D", "Daly"}:
            return "D", token
        if token in {"F", "Faraday"}:
            return "F", token
        if re.fullmatch(r"[DF](?:[-/][DF])+", token):
            return None, token
    return None, None


def classify(name: str) -> dict[str, Any]:
    """Return the classification fields of :class:`~rawtims.model.Function` for one name."""
    text = name.strip()
    match = _RATIO.match(text)
    if match:
        rest = match.group("rest")
        collector, token = _collector(rest)
        metadata: dict[str, Any] = {}
        if token and collector is None:
            metadata["collector_suffix"] = token
        if _OXIDE.search(rest):
            metadata["oxide_corrected"] = True
            r18 = _OXIDE_R18.search(rest)
            if r18:
                metadata["oxide_r18"] = float(r18.group(1))
        num, den = match.group("num"), match.group("den")
        return {
            "kind": "ratio",
            "numerator": num,
            "denominator": den,
            "numerator_mass": _first_mass(num),
            "denominator_mass": _first_mass(den),
            "collector": collector,
            "metadata": metadata,
        }
    match = _INTENSITY.match(text)
    if match:
        rest = match.group("rest")
        collector, token = _collector(rest)
        unit = None
        for word in re.split(r"[\s_]+", rest.strip()):
            unit = unit or normalize_unit(word)
        metadata = {"collector_suffix": token} if token and collector is None else {}
        return {"kind": "intensity", "mass": _first_mass(match.group("sp")), "collector": collector, "unit": unit, "metadata": metadata}
    return {"kind": "other", "metadata": {}}


_UNITS = {"cps": "cps", "v": "V", "volt": "V", "volts": "V", "mv": "mV"}


def normalize_unit(text: str | None) -> str | None:
    """``cps``, ``V`` or ``mV`` from the spellings the files use (``CPS``, ``Volts``, ``V``); else None."""
    if not text:
        return None
    return _UNITS.get(text.strip().lower())


def kind_of(name: str) -> FunctionKind:
    return classify(name)["kind"]


def build_functions(names: list[str], extra: list[dict[str, Any]] | None = None, default_unit: str | None = None) -> tuple[Function, ...]:
    """Make :class:`Function` objects for column names, keyed uniquely and indexed by position.

    ``extra[i]`` is merged into the metadata of function ``i``. ``default_unit``
    (the file's processing unit) applies to intensities whose name gives none.
    """
    keys = unique_keys(names)
    functions = []
    for index, (name, key) in enumerate(zip(names, keys)):
        fields = classify(name)
        metadata = dict(fields.pop("metadata"))
        if extra is not None:
            metadata.update(extra[index])
        if fields["kind"] == "intensity" and fields.get("unit") is None:
            fields["unit"] = normalize_unit(default_unit)
        functions.append(Function(index=index, name=name, key=key, metadata=metadata, **fields))
    return tuple(functions)


def detect_element(functions: Iterable[Function]) -> Element | None:
    """``Pb`` when the functions mention Pb masses (202-208), ``U`` for UO2 (265-272) or 233/235/238.

    A run mentioning both (it should not happen) goes to whichever has more
    mentions; a tie gives None.
    """
    pb = u = 0
    for function in functions:
        for mass in (function.mass, function.numerator_mass, function.denominator_mass):
            if mass is None:
                continue
            pb += mass in PB_MASSES
            u += mass in U_MASSES
    if pb == u:
        return None
    return "Pb" if pb > u else "U"


_ELEMENT_SUFFIX = re.compile(r"[\s_-]+(?:Pb|U)(?:\d+|[\s_-]*run[\s_-]*\d+)?\s*$", re.IGNORECASE)


def suggest_fraction_id(sample_id: str | None) -> str | None:
    """Suggest a fraction ID from a sample ID by dropping a trailing element tag.

    ``"GHR1 20200827-11 U run2"`` → ``"GHR1 20200827-11"``, ``"WH205 z4 Pb"`` →
    ``"WH205 z4"``. A suggestion for the user to confirm, never stored as truth.
    """
    if sample_id is None:
        return None
    text = sample_id.strip()
    stripped = _ELEMENT_SUFFIX.sub("", text).strip()
    return stripped or text
