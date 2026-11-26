"""Offline C# tracer XML models for diagnostic use; never reduction settings.

The Java 00dc941 tree has no concrete tracer XML reader (its abstract model
comments XMLSerializationI out). Do not invent a Java tracer dialect here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Estimate:
    """Value and absolute one-sigma uncertainty, in the value's units."""

    value: float
    sigma: float = 0.0

    def __post_init__(self):
        if (
            not math.isfinite(self.value)
            or not math.isfinite(self.sigma)
            or self.sigma < 0
        ):
            raise ValueError("Values must be finite and absolute 1σ nonnegative")


@dataclass(frozen=True)
class Tracer:
    name: str
    version: int
    tracer_type: str
    lab: str
    certified: str
    values: tuple[tuple[str, Estimate], ...]
    xml: str
    source_sha256: str

    @property
    def identity(self):
        return f"{self.name} v{self.version}"

    def get(self, name):
        try:
            return dict(self.values)[name]
        except KeyError:
            raise ValueError(f"Tracer lacks {name}") from None

    def to_dict(self):
        return {"xml": self.xml, "sha256": self.source_sha256}

    @classmethod
    def from_dict(cls, data):
        result = parse_tracer_xml(data["xml"].encode("utf-8"))
        if result.source_sha256 != data["sha256"]:
            raise ValueError("Tracer XML hash mismatch")
        return result


def parse_tracer_xml(data: bytes) -> Tracer:
    """Read Tracer/TracerUPbModel, namespace-independent; no schema/network access.

    OGTripoli/source/earth_time_org/Tracer.cs:40-150 and
    TracerUPbModel.cs:40-146; ValueModel.cs:28-81 (PCT or ABS oneSigma).
    Unknown fields fail rather than discarding uncertainty/covariance metadata.
    """
    if (
        len(data) > 2_000_000
        or b"<!DOCTYPE" in data.upper()
        or b"<!ENTITY" in data.upper()
    ):
        raise ValueError("Tracer XML is too large or contains a DTD/entity")
    try:
        xml = data.decode("utf-8")
        root = ET.fromstring(xml)
    except (UnicodeError, ET.ParseError) as error:
        raise ValueError(f"Invalid UTF-8 tracer XML: {error}") from error
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    if root.tag not in ("Tracer", "TracerUPbModel"):
        raise ValueError("Supported tracer roots: Tracer, TracerUPbModel (C#)")

    def fields(node, allowed):
        result = {}
        for child in node:
            if child.tag not in allowed or child.tag in result:
                raise ValueError(f"Unknown or duplicate tracer field: {child.tag}")
            result[child.tag] = child
        return result

    top = fields(
        root,
        {
            "tracerName",
            "versionNumber",
            "tracerType",
            "labName",
            "dateCertified",
            "ratios",
            "isotopeConcentrations",
        },
    )

    def text(name):
        if name not in top or not (top[name].text or "").strip():
            raise ValueError(f"Tracer lacks {name}")
        return top[name].text.strip()

    name, kind = text("tracerName"), text("tracerType")
    try:
        version = int(text("versionNumber"))
    except ValueError:
        raise ValueError("Tracer version must be a nonnegative integer") from None
    if version < 0:
        raise ValueError("Tracer version must be a nonnegative integer")
    values = {}
    for group in ("ratios", "isotopeConcentrations"):
        if group not in top:
            raise ValueError(f"Tracer lacks {group}")
        for node in top[group]:
            if node.tag != "ValueModel":
                raise ValueError(f"Unsupported tracer value model: {node.tag}")
            f = fields(node, {"name", "value", "uncertaintyType", "oneSigma"})
            if set(f) != {"name", "value", "uncertaintyType", "oneSigma"}:
                raise ValueError("Incomplete tracer ValueModel")
            v = {k: (n.text or "").strip() for k, n in f.items()}
            key = v["name"]
            if not key or key in values:
                raise ValueError("Empty or duplicate tracer value name")
            if v["uncertaintyType"] not in ("PCT", "ABS"):
                raise ValueError("Tracer uncertaintyType must be PCT or ABS")
            value, sigma = float(v["value"]), float(v["oneSigma"])
            Estimate(value, sigma)  # Check before converting signed percent.
            if value < 0:
                raise ValueError("Tracer ratios/concentrations must be nonnegative")
            values[key] = Estimate(
                value,
                sigma * abs(value) / 100 if v["uncertaintyType"] == "PCT" else sigma,
            )
    return Tracer(
        name,
        version,
        kind,
        text("labName"),
        text("dateCertified"),
        tuple(sorted(values.items())),
        xml,
        sha256(data).hexdigest(),
    )


def read_tracer(path) -> Tracer:
    with Path(path).open("rb") as stream:
        return parse_tracer_xml(stream.read(2_000_001))


def add_tracer(library, tracer):
    """Return a new versioned local library; same identity/different bytes fails."""
    result = list(library)
    for record in result:
        previous = Tracer.from_dict(record)
        if (previous.name, previous.version) == (tracer.name, tracer.version):
            if previous.source_sha256 != tracer.source_sha256:
                raise ValueError(
                    "This tracer name/version already has different XML; use a new version"
                )
            return result
    return result + [tracer.to_dict()]
