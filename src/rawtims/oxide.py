"""UO2 oxide correction (SPEC F12, section 1.2 and section 0, decision 2).

U is measured as UO2+, so mass 265 is 233U16O16O, 267 is 235U16O16O and 270 is
238U16O16O. The only interference corrected is 233U16O18O on mass 267, which
scales with mass 265 and with the oxygen ratio r18 = 18O/16O. Per cycle:

* ``et_redux`` (the default; ET_Redux ``R238_235oc``, legacy Tripoli and the
  Thermo Triton equation)::

      233/235oc = R265/267 / (1 − 2·r18·R265/267)
      238/235oc = R270/267 / (1 − 2·r18·R265/267)

* ``tripoli_00dc941`` (current CIRDLES Tripoli at commit 00dc941,
  ``MassSpecOutputBlockRecordLite.expandForUraniumOxideCorrection``), kept only
  so tests can compare with Tripoli's expected outputs; its 238/235 uses
  R270/267 in the denominator::

      238/235oc = R270/267 / (1 − 2·r18·R270/267)

* in both, ``238/233oc = 238/235oc / 233/235oc``.

Inputs are found by mass, not by exact name: a ratio column 265/267 and
270/267 is used directly; 267/265 is inverted; 270/265 is divided by 267/265
(or multiplied by 265/267). The result records which columns were used and how.

**Pass-through:** when the run already has oxide-corrected columns (names such
as ``238/235 oxide R18 0.00206``, which the readers mark with
``metadata["oxide_corrected"]`` and ``metadata["oxide_r18"]``), nothing is
recomputed: the result says ``pass_through`` and carries the r18 read from
the name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from rawtims.branding import APP_NAME
from rawtims.model import Function, Run

DEFAULT_R18 = 0.00205  # Tripoli's default 18O/16O (TripoliConstants.R18O_16O_DEFAULT_OXIDE_CORRECTION)
FORMULAS: tuple[str, ...] = ("et_redux", "tripoli_00dc941")
OxideFormula = Literal["et_redux", "tripoli_00dc941"]
DERIVED_NAMES = ("233/235oc", "238/235oc", "238/233oc")
FORMULA_TEXT = {
    "et_redux": {
        "233/235oc": "R265/267 / (1 - 2*r18*R265/267)",
        "238/235oc": "R270/267 / (1 - 2*r18*R265/267)",
        "238/233oc": "238/235oc / 233/235oc",
    },
    "tripoli_00dc941": {
        "233/235oc": "R265/267 / (1 - 2*r18*R265/267)",
        "238/235oc": "R270/267 / (1 - 2*r18*R270/267)",
        "238/233oc": "238/235oc / 233/235oc",
    },
}


def correct(r265_267, r270_267, r18: float = DEFAULT_R18, formula: OxideFormula = "et_redux") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(233/235oc, 238/235oc, 238/233oc)`` per cycle from R265/267 and R270/267."""
    if formula not in FORMULAS:
        raise ValueError(f"unknown oxide formula {formula!r}; expected one of {FORMULAS}")
    if not (0.0 <= r18 < 0.1):
        raise ValueError(f"18O/16O = {r18!r} is outside [0, 0.1)")
    r265 = np.asarray(r265_267, dtype=np.float64)
    r270 = np.asarray(r270_267, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        factor_233 = 1.0 - 2.0 * r18 * r265
        factor_238 = factor_233 if formula == "et_redux" else 1.0 - 2.0 * r18 * r270
        r233_235 = r265 / factor_233
        r238_235 = r270 / factor_238
        r238_233 = r238_235 / r233_235
    return r233_235, r238_235, r238_233


@dataclass(frozen=True)
class OxideResult:
    """What the oxide step did for one run.

    ``status`` is ``computed`` (this engine made ``values``), ``pass_through``
    (the file already has corrected columns, listed in ``pass_through_keys``,
    with ``r18`` read from their names; None if no name gives one) or
    ``not_applicable`` (no usable 265/267 and 270/267 inputs; ``reason``
    says why). ``inputs`` maps ``"R265/267"`` and ``"R270/267"`` to how each
    was obtained, e.g. ``"265/267"`` or ``"1 / 267/265"``.
    """

    status: Literal["computed", "pass_through", "not_applicable"]
    formula: str | None = None
    r18: float | None = None
    inputs: dict[str, str] = field(default_factory=dict)
    input_keys: tuple[str, ...] = ()
    values: dict[str, np.ndarray] = field(default_factory=dict, compare=False)
    pass_through_keys: tuple[str, ...] = ()
    reason: str = ""

    def provenance(self) -> dict[str, Any]:
        """Plain-data description for history, session and export."""
        data: dict[str, Any] = {"status": self.status, "formula": self.formula, "r18": self.r18, "inputs": dict(self.inputs)}
        if self.status == "computed":
            data["formula_text"] = dict(FORMULA_TEXT[self.formula])
            data["applied_by"] = APP_NAME
        if self.status == "pass_through":
            data["pass_through_keys"] = list(self.pass_through_keys)
            data["applied_by"] = "instrument file"
        if self.reason:
            data["reason"] = self.reason
        return data


def _ratio_by_masses(functions: tuple[Function, ...], numerator: int, denominator: int) -> Function | None:
    for function in functions:
        if (
            function.is_ratio
            and not function.metadata.get("oxide_corrected")
            and function.numerator_mass == numerator
            and function.denominator_mass == denominator
        ):
            return function
    return None


def find_inputs(run: Run) -> tuple[dict[str, str], tuple[str, ...], np.ndarray, np.ndarray] | None:
    """Locate R265/267 and R270/267 (directly or from 267/265 and 270/265). None when impossible.

    Returns ``(how, keys used, R265/267, R270/267)``.
    """
    functions = run.functions
    f265_267 = _ratio_by_masses(functions, 265, 267)
    f267_265 = _ratio_by_masses(functions, 267, 265)
    f270_267 = _ratio_by_masses(functions, 270, 267)
    f270_265 = _ratio_by_masses(functions, 270, 265)
    how: dict[str, str] = {}
    keys: list[str] = []
    with np.errstate(divide="ignore", invalid="ignore"):
        if f265_267 is not None:
            r265 = run.column(f265_267.key)
            how["R265/267"] = f265_267.key
            keys.append(f265_267.key)
        elif f267_265 is not None:
            r265 = 1.0 / run.column(f267_265.key)
            how["R265/267"] = f"1 / {f267_265.key}"
            keys.append(f267_265.key)
        else:
            return None
        if f270_267 is not None:
            r270 = run.column(f270_267.key)
            how["R270/267"] = f270_267.key
            keys.append(f270_267.key)
        elif f270_265 is not None:
            r270 = run.column(f270_265.key) * r265
            how["R270/267"] = f"{f270_265.key} * R265/267"
            keys.append(f270_265.key)
        else:
            return None
    return how, tuple(dict.fromkeys(keys)), r265, r270


def oxide_correction(run: Run, r18: float = DEFAULT_R18, formula: OxideFormula = "et_redux") -> OxideResult:
    """Decide and, when needed, compute the oxide correction for one run."""
    if formula not in FORMULAS:
        raise ValueError(f"unknown oxide formula {formula!r}; expected one of {FORMULAS}")
    corrected = [function for function in run.functions if function.metadata.get("oxide_corrected")]
    if corrected:
        r18_values = sorted({function.metadata["oxide_r18"] for function in corrected if "oxide_r18" in function.metadata})
        file_r18 = r18_values[0] if len(r18_values) == 1 else None
        reason = "" if len(r18_values) <= 1 else f"columns name different 18O/16O values {r18_values}"
        return OxideResult(status="pass_through", r18=file_r18, pass_through_keys=tuple(f.key for f in corrected), reason=reason)
    found = find_inputs(run)
    if found is None:
        return OxideResult(status="not_applicable", reason="no 265/267 (or 267/265) and 270/267 (or 270/265) ratio columns")
    how, keys, r265, r270 = found
    r233_235, r238_235, r238_233 = correct(r265, r270, r18, formula)
    values = dict(zip(DERIVED_NAMES, (r233_235, r238_235, r238_233)))
    return OxideResult(status="computed", formula=formula, r18=float(r18), inputs=how, input_keys=keys, values=values)


__all__ = ["DEFAULT_R18", "DERIVED_NAMES", "FORMULAS", "FORMULA_TEXT", "OxideFormula", "OxideResult", "correct", "find_inputs", "oxide_correction"]
