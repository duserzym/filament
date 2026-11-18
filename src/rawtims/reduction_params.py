"""Immutable numerical inputs for reproducible acquisition reduction (schema 1).

Canonical JSON is UTF-8, sorted keys, no whitespace, finite repr-roundtrip
floats. Unknown acquisition settings remain missing; they are never guessed.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from types import MappingProxyType

SCHEMA = "rawtims reduction parameters"
VERSION = 1
COLLECTORS = ("Low3", "Low2", "Axial", "High1", "High2", "High3", "High4", "High5", "High6")


def _number(name, value, *, minimum=0, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    if value < minimum or (positive and value == minimum):
        raise ValueError(f"{name} must be {'greater than' if positive else 'at least'} {minimum}")
    return float(value)


def _mapping(name, values, *, positive=False):
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a collector-to-number mapping")
    result = {}
    for key, value in values.items():
        allowed = (*COLLECTORS, "Multiplier") if name == "baseline.offsets" else COLLECTORS
        if key not in allowed:
            raise ValueError(f"{name}: unknown collector {key!r}")
        result[key] = _number(f"{name}.{key}", value, minimum=0 if positive else -math.inf, positive=positive)
    return MappingProxyType(result)


@dataclass(frozen=True)
class Baseline:
    """Offsets subtract an additional amount in output units (Pb cps, U V)."""
    mode: str = "as_acquired"
    offsets: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if self.mode not in ("as_acquired", "measured", "offset"):
            raise ValueError("baseline.mode must be as_acquired, measured or offset")
        object.__setattr__(self, "offsets", _mapping("baseline.offsets", self.offsets))
        if self.mode != "offset" and self.offsets:
            raise ValueError("baseline.offsets requires mode offset")


@dataclass(frozen=True)
class BeamInterpolation:
    enabled: bool = False
    history_cycles: int = 3

    def __post_init__(self):
        if not isinstance(self.enabled, bool):
            raise TypeError("beam_interpolation.enabled must be boolean")
        if type(self.history_cycles) is not int or not 2 <= self.history_cycles <= 3:
            raise ValueError("beam_interpolation.history_cycles must be 2 or 3 (acquired precycle limit)")


@dataclass(frozen=True)
class IntegrationRejection:
    sigma: float = 2.0
    max_percent: float = 5.0

    def __post_init__(self):
        object.__setattr__(self, "sigma", _number("integration_rejection.sigma", self.sigma, positive=True))
        object.__setattr__(self, "max_percent", _number("integration_rejection.max_percent", self.max_percent))
        if self.max_percent >= 100:
            raise ValueError("integration_rejection.max_percent must be below 100")


@dataclass(frozen=True)
class ReductionParameters:
    daly_dead_time_ns: float | None = None
    faraday_gains: Mapping[str, float] = field(default_factory=dict)
    baseline: Baseline = field(default_factory=Baseline)
    beam_interpolation: BeamInterpolation = field(default_factory=BeamInterpolation)
    integration_rejection: IntegrationRejection = field(default_factory=IntegrationRejection)
    oxide_r18: float | None = None
    route: str = "workbook"
    apply_baselines: bool = True
    apply_faraday_gains: bool = True
    correct_dead_time: bool = True
    multiplier_gain: float = 1.0
    faraday_resistors_ohm: Mapping[str, float] = field(default_factory=dict)
    # Recovered vendor conversion conventions, not modern SI constants.
    adc_zero: float = 8388608.0
    adc_volts_per_code: float = 1.192092896e-6
    electron_charge_c: float = 1.6021892e-19
    schema: str = SCHEMA
    version: int = VERSION

    def __post_init__(self):
        if self.schema != SCHEMA or type(self.version) is not int or self.version != VERSION:
            raise ValueError(f"unsupported reduction parameter schema/version: {self.schema!r}/{self.version!r}")
        if self.route not in ("raw", "workbook"):
            raise ValueError("route must be raw or workbook")
        for key, cls in (("baseline", Baseline), ("beam_interpolation", BeamInterpolation), ("integration_rejection", IntegrationRejection)):
            value = getattr(self, key)
            if isinstance(value, Mapping):
                try:
                    value = cls(**value)
                except TypeError as error:
                    raise ValueError(f"{key}: {error}") from None
                object.__setattr__(self, key, value)
            if not isinstance(value, cls):
                raise TypeError(f"{key} must be {cls.__name__} or an object")
        for name in ("apply_baselines", "apply_faraday_gains", "correct_dead_time"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")
        for name in ("daly_dead_time_ns", "oxide_r18"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, _number(name, getattr(self, name)))
        if self.oxide_r18 is not None and self.oxide_r18 >= 0.1:
            raise ValueError("oxide_r18 must be below 0.1")
        for name in ("multiplier_gain", "adc_volts_per_code", "electron_charge_c"):
            object.__setattr__(self, name, _number(name, getattr(self, name), positive=True))
        object.__setattr__(self, "adc_zero", _number("adc_zero", self.adc_zero))
        for name in ("faraday_gains", "faraday_resistors_ohm"):
            object.__setattr__(self, name, _mapping(name, getattr(self, name), positive=True))

    def to_dict(self):
        result = {f.name: getattr(self, f.name) for f in fields(self)}
        result["faraday_gains"] = dict(self.faraday_gains)
        result["faraday_resistors_ohm"] = dict(self.faraday_resistors_ohm)
        result["baseline"] = {"mode": self.baseline.mode, "offsets": dict(self.baseline.offsets)}
        result["beam_interpolation"] = {"enabled": self.beam_interpolation.enabled, "history_cycles": self.beam_interpolation.history_cycles}
        result["integration_rejection"] = {"sigma": self.integration_rejection.sigma, "max_percent": self.integration_rejection.max_percent}
        return result

    def canonical_json(self):
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))

    @property
    def sha256(self):
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, Mapping):
            raise TypeError("reduction parameters must be an object")
        if "schema" not in data or "version" not in data:
            raise ValueError("reduction parameters require schema and version")
        try:
            return cls(**data)
        except TypeError as error:
            raise ValueError(f"invalid reduction parameters: {error}") from None

    @classmethod
    def as_acquired(cls, run_source):
        return as_acquired(run_source)


def as_acquired(run_source) -> ReductionParameters:
    """Read defaults captured from TUNING/CTRL and the acquisition .ipf/.000.

    A Run retains the file's original record even after reprocessing. Paths may
    name a workbook or its .raw folder (which must contain a workbook).
    """
    from rawtims.model import Run
    if not isinstance(run_source, Run):
        from rawtims.readers import open_run
        from rawtims.readers.ionvantage_raw import workbook_path
        path = Path(run_source)
        run_source = open_run(workbook_path(path) if path.is_dir() else path)
    record = run_source.metadata.extra.get("acquired_reduction_parameters")
    if record is not None:
        return ReductionParameters.from_dict(record)
    r18 = {f.metadata["oxide_r18"] for f in run_source.functions if "oxide_r18" in f.metadata}
    return ReductionParameters(oxide_r18=next(iter(r18)) if len(r18) == 1 else None)


def capture_acquired(book, ctrl, functions, path):
    """Capture numeric defaults while the workbook is open; no acquisition data read."""
    from rawtims.readers.ionvantage_raw import acquisition_config, raw_folder
    gains, resistors, dt, multiplier_gain = {}, {}, None, 1.0
    if "TUNING" in book.sheet_names():
        sheet = book.sheet_by_name("TUNING")
        if sheet.nrows >= 10:
            for col in range(1, sheet.ncols):
                name = sheet.cell_value(3, col)
                name = "Axial" if name == "Ax Fara" else name
                gain, resistor = sheet.cell_value(6, col), sheet.cell_value(8, col)
                if name in COLLECTORS and isinstance(gain, float) and gain > 0:
                    gains[name], resistors[name] = gain, resistor
                if name == "Multiplier":
                    dt, multiplier_gain = sheet.cell_value(9, col), gain
    folder = raw_folder(Path(path))
    config, ipf = acquisition_config(folder) if folder is not None else ({}, {})
    for name in COLLECTORS:
        if name in config and float(config[name].get("FaradayGain", 0)) > 0:
            raw_gain = float(config[name]["FaradayGain"])
            if name in gains and raw_gain != gains[name]:
                raise ValueError(f"TUNING and _AcqParams.000 disagree on {name} gain")
            gains[name] = raw_gain
            resistors[name] = float(config[name]["FaradayResistor"])
    if "Multiplier" in config:
        raw_dt = float(config["Multiplier"]["ICDeadTime"])
        if dt is not None and raw_dt != dt:
            raise ValueError("TUNING and _AcqParams.000 disagree on Daly dead time")
        dt = raw_dt
        multiplier_gain = float(config["Multiplier"].get("ICGain", multiplier_gain))
    corrections = ipf.get("Corrections", {})
    def flag(key, fallback):
        return str(corrections.get(key, fallback)).lower() in ("true", "1", "1.0")
    r18 = {f.metadata["oxide_r18"] for f in functions if "oxide_r18" in f.metadata}
    return ReductionParameters(
        daly_dead_time_ns=dt, faraday_gains=gains, faraday_resistors_ohm=resistors,
        multiplier_gain=multiplier_gain,
        beam_interpolation=BeamInterpolation(bool(ctrl.get("Beam Interpolation (BI)", False)), int(ctrl.get("No. BI History Cycles", 3))),
        integration_rejection=IntegrationRejection(float(corrections.get("ECESDSigmaFilter", ctrl.get("Sigma Level", 2))),
                                                  float(corrections.get("ECEMaxDataReject", ctrl.get("Rejection %", 5)))),
        apply_baselines=flag("ApplyBaselines", ctrl.get("Apply Baselines", True)),
        correct_dead_time=flag("CorrectForDeadtime", True),
        apply_faraday_gains=flag("AmplifierGains", True),
        oxide_r18=next(iter(r18)) if len(r18) == 1 else None,
    )
