"""Opt-in linear-law diagnostics. No Analysis, mapping or export dependencies.

Mean-level calibration/propagation is deliberately separate from Tripoli's
per-cycle correction. Algorithm version pins the convention, not lab validity.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass

import numpy as np

from rawtims.covariance import validate_covariance
from rawtims.tracers import Estimate

ALGORITHM = "ogtripoli-linear-preview/1"


@dataclass(frozen=True)
class UComponents:
    """Explicit C# units: blank pg, tracer g, isotope molar masses g/mol."""

    blank_pg: Estimate
    blank_238_235: Estimate
    sample_238_235: Estimate
    tracer_g: Estimate
    gmol235: Estimate
    gmol238: Estimate

    def __post_init__(self):
        for name, item in self.__dict__.items():
            if item.value < 0 or (name != "blank_pg" and item.value == 0):
                raise ValueError(
                    f"U component {name} must be positive (blank may be zero)"
                )


def u_moles(tracer, components):
    """C# TripoliWorkProduct.cs:1145-1167; isotope-specific blank mass split."""
    c = components
    b = c.blank_pg.value * 1e-12
    r = c.blank_238_235.value
    t235 = tracer.get("concU235t").value * c.tracer_g.value
    if t235 <= 0:
        raise ValueError("U235 tracer amount must be positive")
    result = {
        "235b": b / (r + 1) / c.gmol235.value,
        "238b": b * r / (r + 1) / c.gmol238.value,
        "235t": t235,
        "233t": t235 * tracer.get("r233_235t").value,
        "238t": t235 * tracer.get("r238_235t").value,
    }
    if not all(math.isfinite(v) for v in result.values()):
        raise ValueError("U component moles must be finite")
    return result


def _propagate(inputs, names, function, covariance=None):
    """First-order J S Jᵀ. Complex-step derivatives of analytic rational laws."""
    keys = tuple(inputs)
    x = np.array([e.value for e in inputs.values()])
    errors = np.array([e.sigma for e in inputs.values()])
    cov = (
        np.diag(errors**2)
        if covariance is None
        else np.asarray(covariance, dtype=float)
    )
    validity = validate_covariance(keys, cov)
    if not validity.valid:
        raise ValueError("Invalid preview covariance: " + "; ".join(validity.issues))
    if not np.allclose(np.diag(cov), errors**2, rtol=1e-10, atol=0):
        raise ValueError("Covariance diagonal must match input absolute 1σ²")
    # Check dimensionless correlations as well: the primitive units span many
    # orders of magnitude, so a global covariance tolerance alone can conceal
    # an impossible tiny submatrix beside a large component variance.
    nonzero = errors > 0
    if np.any(cov[~nonzero] != 0) or np.any(cov[:, ~nonzero] != 0):
        raise ValueError("Zero-uncertainty inputs cannot have covariance")
    if np.any(nonzero):
        rho = (
            cov[np.ix_(nonzero, nonzero)]
            / errors[nonzero, None]
            / errors[None, nonzero]
        )
        validity = validate_covariance(
            tuple(k for k, ok in zip(keys, nonzero) if ok), rho
        )
        if not validity.valid or np.any(np.abs(rho) > 1 + 1e-12):
            raise ValueError("Invalid preview covariance after scaling to correlations")
    with np.errstate(all="ignore"):
        y = np.asarray(function(x), dtype=float)
        jac = np.empty((len(y), len(x)))
        for i in range(len(x)):
            z = x.astype(complex)
            step = max(np.finfo(float).tiny, 1e-24 * abs(x[i])) if x[i] else 1e-24
            z[i] += step * 1j
            jac[:, i] = np.imag(function(z)) / step
        propagated = jac @ cov @ jac.T
    if not np.all(np.isfinite(y)) or not np.all(np.isfinite(propagated)):
        raise ValueError("Singular/nonfinite preview calibration")
    if any(v <= 0 for n, v in zip(names, y) if n != "alpha"):
        raise ValueError("Preview correction produced a nonpositive ratio")
    sigma = np.sqrt(np.maximum(0, np.diag(propagated)))
    return {
        "algorithm": ALGORITHM,
        "names": list(names),
        "values": y.tolist(),
        "sigma": sigma.tolist(),
        "covariance": propagated.tolist(),
        "input_names": list(keys),
        "inputs": {k: asdict(v) for k, v in inputs.items()},
        "input_covariance": cov.tolist(),
        "uncertainty": "Independent inputs assumed; absolute 1σ, first-order J S Jᵀ"
        if covariance is None
        else "Supplied covariance; absolute 1σ, first-order J S Jᵀ",
    }


def _measured(measured):
    if not measured or any(e.value <= 0 for e in measured.values()):
        raise ValueError("Preview requires positive finite measured ratios")
    return dict(sorted(measured.items()))


def _unchanged(measured, covariance):
    return _propagate(measured, ["alpha", *measured], lambda x: np.r_[0, x], covariance)


def preview_pb(measured, tracer=None, *, covariance=None):
    """Pb alpha and mass-difference multipliers; C# WorkProduct.cs:1683-1710,2025-2035.

    Covariance order is sorted measured names, then tracer:r202_205t.
    No tracer means exactly unchanged ratios, alpha=0 (no calibration applied).
    """
    measured = _measured(measured)
    allowed = {
        "202Pb/205Pb",
        "206Pb/204Pb",
        "207Pb/204Pb",
        "208Pb/204Pb",
        "206Pb/207Pb",
        "206Pb/208Pb",
        "204Pb/205Pb",
        "206Pb/205Pb",
        "207Pb/205Pb",
        "208Pb/205Pb",
    }
    if not set(measured) <= allowed:
        raise ValueError("Unsupported Pb preview ratio")
    if tracer is None:
        return _unchanged(measured, covariance)
    if tracer.tracer_type not in ("mixed 202-205-233-235", "mixed 202-205-233-236"):
        raise ValueError("Pb preview requires a 202-205 tracer")
    if "202Pb/205Pb" not in measured or tracer.get("r202_205t").value <= 0:
        raise ValueError("Pb preview requires measured and tracer 202/205")
    keys = list(measured)
    control = keys.index("202Pb/205Pb")
    inputs = {**measured, "tracer:r202_205t": tracer.get("r202_205t")}
    deltas = np.array([int(k[:3]) - int(k.split("/")[1][:3]) for k in keys])
    # C# retains the control ratio; only the other lead ratios are corrected.
    deltas[control] = 0

    def calculate(x):
        alpha = (1 - x[-1] / x[control]) / 3
        return np.r_[alpha, x[:-1] * (1 + deltas * alpha)]

    result = _propagate(inputs, ["alpha", *keys], calculate, covariance)
    result["control"] = "202Pb/205Pb remains the measured alpha control"
    return result


def preview_u(measured, tracer=None, components=None, *, covariance=None):
    """C# WorkProduct.cs:1292-1372, 233/235–238/235 calibration and linear correction.

    Input order: sorted measured, tracer r233_235t/r238_235t/concU235t,
    then UComponents declaration order. 238/233 uses its own linear +5α law,
    not a quotient of corrected 238/235 and 233/235.
    """
    measured = _measured(measured)
    if not set(measured) <= {"233U/235U", "238U/235U", "238U/233U"}:
        raise ValueError(
            "Unsupported U preview ratio (233/236 fractionation is unsupported in C#)"
        )
    if tracer is None:
        return _unchanged(measured, covariance)
    if tracer.tracer_type not in ("mixed 202-205-233-235", "mixed 205-233-235"):
        raise ValueError("C# does not implement 233/236 tracer fractionation")
    if components is None or not {"233U/235U", "238U/235U"} <= set(measured):
        raise ValueError("U preview requires components and both 233/235 and 238/235")
    moles = u_moles(tracer, components)
    if moles["233t"] <= 0:
        raise ValueError("U233 tracer amount must be positive")
    inputs = dict(measured)
    for name in ("r233_235t", "r238_235t", "concU235t"):
        inputs["tracer:" + name] = tracer.get(name)
    inputs.update({"component:" + k: v for k, v in components.__dict__.items()})
    keys = list(measured)
    n = len(keys)

    def calculate(x):
        a, b = x[keys.index("233U/235U")], x[keys.index("238U/235U")]
        t33, t38, conc = x[n : n + 3]
        blank, rb, rs, mass, g235, g238 = x[n + 3 :]
        t235 = conc * mass
        b235 = blank * 1e-12 / (rb + 1) / g235 / t235
        b238 = blank * 1e-12 * rb / (rb + 1) / g238 / t235
        balance = b238 + t38 - rs * (b235 + 1)
        alpha = (rs * t33 - b * t33 + a * balance) / (3 * b * t33 + 2 * a * balance)
        delta = np.array(
            [{"233U/235U": -2, "238U/235U": 3, "238U/233U": 5}[k] for k in keys]
        )
        return np.r_[alpha, x[:n] * (1 + delta * alpha)]

    result = _propagate(inputs, ["alpha", *keys], calculate, covariance)
    result["u_moles"] = moles
    return result


def preview_oxide_233_236(r270_268, r265_268, r18, *, covariance=None):
    """C# WorkProduct.cs:2815-2837: identity 233/236, 238/236=270/268−2r18.

    Explicit diagnostic only; no automatic molecular assignment or /1 mapping.
    """
    inputs = {"270/268": r270_268, "265/268": r265_268, "r18": r18}
    if min(r270_268.value, r265_268.value) <= 0 or r18.value < 0:
        raise ValueError("Oxide preview requires positive ratios and nonnegative r18")
    return _propagate(
        inputs,
        ["233U/236U", "238U/236U", "238U/233U"],
        lambda x: np.array([x[1], x[0] - 2 * x[2], (x[0] - 2 * x[2]) / x[1]]),
        covariance,
    )


class PreviewBook:
    """Append-only derived revisions; undo changes visibility, preserves originals."""

    def __init__(self, data=None):
        try:
            self.data = json.loads(
                json.dumps(
                    data
                    if data is not None
                    else {
                        "version": 1,
                        "library": [],
                        "records": [],
                        "events": [],
                        "applied": 0,
                        "active_tracer": None,
                    },
                    allow_nan=False,
                )
            )
            d = self.data
            if (
                d["version"] != 1
                or type(d["applied"]) is not int
                or not all(
                    isinstance(d[k], list) for k in ("library", "records", "events")
                )
                or not 0 <= d["applied"] <= len(d["events"])
                or any(
                    type(i) is not int or not 0 <= i < len(d["records"])
                    for i in d["events"]
                )
                or len(set(d["events"])) != len(d["events"])
            ):
                raise ValueError("Unsupported or invalid preview history")
            for record in d["records"]:
                if self.key(record["data"]) != record["key"]:
                    raise ValueError("Preview revision hash mismatch")
            from rawtims.tracers import Tracer, add_tracer

            library = []
            for item in d["library"]:
                library = add_tracer(library, Tracer.from_dict(item))
            if len(library) != len(d["library"]):
                raise ValueError("Duplicate preview tracer library entry")
            if d.get("active_tracer") is not None and d["active_tracer"] not in {
                t["sha256"] for t in library
            }:
                raise ValueError("Active preview tracer is missing from library")
        except (KeyError, TypeError, IndexError) as error:
            raise ValueError("Invalid preview history schema") from error

    @staticmethod
    def key(data):
        return hashlib.sha256(
            json.dumps(
                data, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode()
        ).hexdigest()

    def add(self, data):
        snapshot = json.loads(json.dumps(data, allow_nan=False))
        key = self.key(snapshot)
        # Identical reruns still get distinct revision numbers, but share content identity.
        index = len(self.data["records"])
        self.data["records"].append({"key": key, "data": snapshot})
        self.data["events"] = self.data["events"][: self.data["applied"]] + [index]
        self.data["applied"] += 1
        return index

    def undo(self):
        if self.data["applied"]:
            self.data["applied"] -= 1
            return True
        return False

    def redo(self):
        if self.data["applied"] < len(self.data["events"]):
            self.data["applied"] += 1
            return True
        return False

    def to_dict(self):
        return json.loads(json.dumps(self.data, allow_nan=False))

    def visible(self):
        return [
            (i, self.data["records"][i])
            for i in self.data["events"][: self.data["applied"]]
        ]
