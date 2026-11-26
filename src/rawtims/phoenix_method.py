"""Strict read-only Phoenix XML import, no reader/reduction registration.

Field vocabulary/order transcribed from PhoenixAnalysisMethod.java:261-270,
418-440,721-733,910-918,1165-1197,1628-1690 (Java Tripoli 00dc941).
JAXB declares strings. Structural/reference/finite-number refusal is explicit
validation in this adapter; no vendor XML specimen is claimed as validated.
"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from rawtims.methods import (
    SYNTHETIC_DETECTORS,
    BaselineCell,
    Method,
    MethodRow,
    SequenceCell,
    isotope,
)

FIELDS = {
    "HEADER": ("Filename", "DateModified", "DateCreated", "CreatedBy", "ModifiedBy"),
    "SETTINGS": (
        "IntersperseBaselines",
        "BaselineFrequency",
        "PKCCycleInterval",
        "TotalBlocks",
        "TotalCycles",
        "CalculateRatios",
        "InitialBLMagnetDelay",
        "DeflectBeamProtection",
        "PerformBeamInterpCycles",
        "PerformInterBlocks",
        "AxialColl",
        "ActiveSEMCollectors",
        "MagnetFlybackSettleTime",
        "CorrectForBaselines",
        "CorrectForDeadtimes",
        "IsoWorks_Method",
        "Rejection_Sigma",
        "Rejection_Percentage",
        "ActiveSubChannel",
        "ProcessingUnits",
        "TFE_Enabled",
        "TFE_MonitorPeak",
        "TFE_IntensityThreshold",
        "TFE_IntervalPeakCentring",
        "TFE_PeakCentringInterval",
        "TFE_PeakCentringMonitorThreshold",
        "Export_IsotopePoints",
        "Export_ASCFile",
        "Export_ASCOptions",
        "Export_ASCActiveColl",
        "Export_TXTEveryCYCLE",
        "Export_TripoliLiveData",
    ),
    "BASELINE": (
        "Sequence",
        "Enabled",
        "MassID",
        "AxMass",
        "IntegPeriod",
        "IntegTime",
        "PKCParentID",
        "BLReferences",
        "MagnetSettleTime",
        "AxMassOffset",
        "CurveFit",
        "TraceColour",
    ),
    "ONPEAK": (
        "Sequence",
        "Enabled",
        "MassID",
        "MassIDCollector",
        "AxMass",
        "IntegPeriod",
        "IntegTime",
        "PeakCentre",
        "PKCCollector",
        "PKCMethod",
        "PKCParentID",
        "BLReferences",
        "CollectorArray",
        "MagnetSettleTime",
        "AxMassOffset",
        "CurveFit",
        "TraceColour",
    ),
    "EQUILIBRATION": (
        "Enabled",
        "Collector",
        "AxMass",
        "MassID",
        "Duration",
        "IntegPeriod",
        "StoreToDB",
    ),
}


def _number(value, field):
    try:
        result = float(value)
    except ValueError:
        raise ValueError(f"{field}: expected a finite number") from None
    if not math.isfinite(result):
        raise ValueError(f"{field}: expected a finite number")
    return result


def _sequence(row):
    text = row.get("Sequence")
    if not re.fullmatch(r"[1-9][0-9]*", text):
        raise ValueError("Sequence must be a positive integer")
    return int(text)


def parse_method_xml(data: bytes, detectors=SYNTHETIC_DETECTORS) -> Method:
    """AnalysisMethod.java:200-303 mapping, including Ax/PM ordinal convention.

    Detector setup is explicit; the default is the *synthetic reference* setup.
    This does not verify any run's collector hardware or calibration. Original
    string fields and source hash remain available for read-only inspection.
    """
    if len(data) > 2_000_000:
        raise ValueError("Method XML exceeds 2 MB")
    # UTF-8 only, so DTD/entity screening cannot be bypassed with UTF-16 NULs.
    text = data.decode("utf-8-sig")
    if re.search(r"<!DOCTYPE|<!ENTITY", text, re.IGNORECASE):
        raise ValueError("DTD/entities are not supported in method XML")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        raise ValueError(f"Malformed method XML: {error}") from None
    if root.tag != "ANALYSIS_METHOD" or root.attrib:
        raise ValueError("Expected unnamespaced ANALYSIS_METHOD without attributes")
    if (root.text or "").strip() or any((c.tail or "").strip() for c in root):
        raise ValueError("Unexpected method root text")
    tags = [child.tag for child in root]
    # The JAXB list API accepts multiple BASELINE entries although the generated
    # schema comment omits maxOccurs. Retain that explicitly supported list.
    if not re.fullmatch(
        r"HEADER SETTINGS(?: BASELINE)+(?: ONPEAK)* EQUILIBRATION", " ".join(tags)
    ):
        raise ValueError("Unknown, missing, repeated or out-of-order method section")
    rows = {}
    for section in root:
        if (
            section.attrib
            or tuple(child.tag for child in section) != FIELDS[section.tag]
        ):
            raise ValueError(
                f"{section.tag}: unknown, missing, repeated or out-of-order fields"
            )
        if (section.text or "").strip():
            raise ValueError("Unexpected method section text")
        for child in section:
            if child.attrib or len(child) or (child.tail or "").strip():
                raise ValueError(f"{child.tag}: expected an unadorned string")
        rows.setdefault(section.tag, []).append(
            MethodRow(tuple((c.tag, c.text or "") for c in section))
        )
    header, settings = rows["HEADER"][0], rows["SETTINGS"][0]
    if not header.get("Filename").strip():
        raise ValueError("Filename is required")
    setup = tuple(detectors)
    detector_map = {d.name: d for d in setup}
    if len(detector_map) != len(setup) or len({d.ordinal for d in setup}) != len(setup):
        raise ValueError("Detector names and ordinals must be unique")
    axial_name = "Ax" if settings.get("AxialColl").startswith("A") else "PM"
    if settings.get("AxialColl") not in ("Ax", "Axial", "PM"):
        raise ValueError("Unknown axial collector")
    if not {axial_name, "Ax"} <= detector_map.keys():
        raise ValueError("Detector setup lacks axial collector")
    baselines = tuple(rows["BASELINE"])
    if [_sequence(r) for r in baselines] != list(range(1, len(baselines) + 1)):
        raise ValueError("Baseline sequences must be contiguous and ordered from 1")
    baseline_masses = {}
    for row in baselines:
        ref = row.get("BLReferences").strip()
        mass = row.get("AxMass")
        if ref and ref.upper() != "MASS":
            match = re.fullmatch(r"([0-9]+)([A-Za-z]+)", ref)
            if not match:
                raise ValueError(
                    "Baseline mass reference must be MASS or an isotope such as 206Pb"
                )
            isotope(match[2], int(match[1]))
            mass = match[1]
        baseline_masses[f"BL{_sequence(row)}"] = _number(mass, "AxMass") + _number(
            row.get("AxMassOffset"), "AxMassOffset"
        )
    on_peak = tuple(rows.get("ONPEAK", ()))
    sequence_numbers = [_sequence(row) for row in on_peak]
    if len(set(sequence_numbers)) != len(sequence_numbers):
        raise ValueError("Duplicate on-peak sequence")
    cells, referenced = [], set()
    for row in on_peak:
        sequence = _sequence(row)
        refs = tuple(r.strip() for r in row.get("BLReferences").split(",") if r.strip())
        if len(set(refs)) != len(refs) or any(r not in baseline_masses for r in refs):
            raise ValueError("Unknown or repeated baseline reference")
        used = set()
        for entry in row.get("CollectorArray").strip().split(","):
            match = re.fullmatch(
                r"(?:([0-9]+)([A-Za-z]+)|([A-Za-z]+)([0-9]+)):([A-Za-z0-9]+)S([1-9][0-9]*)",
                entry.strip(),
            )
            if not match:
                raise ValueError(f"Invalid CollectorArray entry: {entry!r}")
            mass, symbol = (match[1], match[2]) if match[1] else (match[4], match[3])
            detector = match[5]
            if (
                detector not in detector_map
                or detector in used
                or int(match[6]) != sequence
            ):
                raise ValueError(
                    "Unknown/duplicate collector or inconsistent sequence suffix"
                )
            used.add(detector)
            cells.append(
                SequenceCell(detector, sequence, isotope(symbol, int(mass)), refs)
            )
            referenced.update((detector, r) for r in refs)
    # Java needs the matching axial baseline cell to establish all other masses.
    for _, ref in referenced:
        if (axial_name, ref) not in referenced:
            raise ValueError(f"Missing axial baseline cell for {ref}")
    baseline_cells = tuple(
        BaselineCell(
            name,
            ref,
            int(ref[2:]),
            baseline_masses[ref]
            + (
                0
                if name == axial_name
                else detector_map[name].ordinal - detector_map["Ax"].ordinal
            ),
        )
        for name, ref in sorted(
            referenced, key=lambda p: (detector_map[p[0]].ordinal, int(p[1][2:]))
        )
    )
    return Method(
        header.get("Filename"),
        header,
        settings,
        baselines,
        on_peak,
        rows["EQUILIBRATION"][0],
        setup,
        baseline_cells,
        tuple(cells),
        hashlib.sha256(data).hexdigest(),
    )


def read_method_xml(path, detectors=SYNTHETIC_DETECTORS) -> Method:
    return parse_method_xml(Path(path).read_bytes(), detectors)
