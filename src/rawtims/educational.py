"""Bundled, independent educational sessions; no Analysis/session/export route.

Upstream resources: CIRDLES/Tripoli 00dc941, Apache-2.0; see resources/NOTICE
and resources/educational-manifest.json. No sampler or peak inversion is run.
"""

import csv
import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from io import StringIO

import numpy as np

from rawtims.mcmc1.forward import Observations, array
from rawtims.mcmc1.initialize import (
    Initialization,
    initialize,
    prepare_two_isotope_synthetic,
)
from rawtims.synthetic_acquisition import parse_java_synthetic

DEMO_VERSION = "rawtims-educational/1"


@dataclass(frozen=True)
class PeakScan:
    metadata: tuple[tuple[str, str], ...]
    mass: np.ndarray
    intensity: np.ndarray

    def __post_init__(self):
        object.__setattr__(self, "mass", array(self.mass))
        object.__setattr__(self, "intensity", array(self.intensity))
        if (
            len(self.mass) < 2
            or len(self.mass) != len(self.intensity)
            or np.any(np.diff(self.mass) <= 0)
        ):
            raise ValueError("Expected an increasing peak scan with at least two rows")


def parse_peak_scan(text):
    """Phoenix PeakShapeProcessor_PhoenixTextFile.java:53-92, raw columns only.

    Strict pinned header, no physical widths, fitting or inferred intensity units.
    """
    rows = [[s.strip() for s in r] for r in csv.reader(StringIO(text)) if r]
    headers = (
        "Timestamp",
        "Collector",
        "Mass ID",
        "Initial Mass",
        "Peak Centre Mass",
        "Method",
        "PDT",
        "Baseline",
        "DetThreshold",
        "DeltaMass",
        "IntegPeriod",
    )
    if (
        len(rows) < 14
        or any(len(r) != 2 for r in rows)
        or tuple(r[0] for r in rows[:11]) != headers
        or rows[11] != ["Mass", "Intensity"]
        or rows[5][1] != "PeakScanning"
    ):
        raise ValueError("Expected the pinned Phoenix educational peak-scan layout")
    values = np.array(rows[12:], dtype=float)
    return PeakScan(tuple(tuple(r) for r in rows[:11]), values[:, 0], values[:, 1])


@dataclass(frozen=True)
class DemoSession:
    key: str
    title: str
    source_path: str
    source_sha256: str
    observations: Observations | None = None
    initialization: Initialization | None = None
    scan: PeakScan | None = None
    schema: str = DEMO_VERSION


def demo_catalog():
    """Return fresh metadata; callers cannot mutate a shared manifest."""
    resource = files("rawtims").joinpath("resources/educational-manifest.json")
    return json.loads(resource.read_text(encoding="utf-8"))["demos"]


def open_demo(key, *, kind="linear") -> DemoSession:
    """Only bundled, digest-pinned inputs. Every open owns independent arrays."""
    catalog = demo_catalog()
    if key not in catalog:
        raise ValueError("Unknown bundled educational demo")
    if kind not in ("linear", "cubic"):
        raise ValueError("Unknown educational intensity basis")
    entry = catalog[key]
    data = files("rawtims").joinpath("resources/" + entry["file"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise ValueError("Bundled educational resource digest mismatch")
    args = (key, entry["title"], entry["source_path"], entry["sha256"])
    if entry["type"] == "two-isotope":
        acquisition = parse_java_synthetic(data.decode("utf-8"))
        observations = prepare_two_isotope_synthetic(acquisition, kind=kind)
        return DemoSession(*args, observations, initialize(observations))
    return DemoSession(*args, scan=parse_peak_scan(data.decode("utf-8")))
