"""Read-only method/catalog schema 1, pinned to Java Tripoli 00dc941.

Source root: TripoliCore/src/main/java/org/cirdles/tripoli/.
Detector fields: sessions/analysis/massSpectrometerModels/detectorSetups/Detector.java:35-55.
Catalog: MassSpectrometerBuiltinModelFactory.java:35-46 in that package;
synthetic setup: detectorSetups/DetectorSetupBuiltinModelFactory.java:39-61.
These reference defaults are never acquisition calibration or reduction settings.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from importlib.resources import files
from io import StringIO

SCHEMA = "rawtims-method/1"
CATALOG_VERSION = "java-tripoli-00dc941/1"


class DetectorType(StrEnum):
    FARADAY = "Faraday"
    DALY = "DalyDetector"
    SEM = "SEM"
    CDD = "CDD"


class AmplifierType(StrEnum):
    RESISTANCE = "Resistance"
    CAPACITANCE = "Capacitance"
    VIRTUAL = "VIRTUAL"


@dataclass(frozen=True)
class Detector:
    name: str
    ordinal: int
    kind: DetectorType
    amplifier: AmplifierType
    resistance_ohm: float
    gain: float
    efficiency: float
    dead_time: float


@dataclass(frozen=True)
class Instrument:
    name: str
    collector_width_mm: float
    magnet_radius_mm: float
    beam_width_mm: float
    version: str = CATALOG_VERSION


INSTRUMENTS = (
    Instrument("Phoenix", 0.95135, 540.0, 0.35),
    Instrument("UNKNOWN", 0.0, 0.0, 0.0),
)
# The Java factory has only one built-in detector setup, for its synthetic context.
SYNTHETIC_DETECTORS = tuple(
    Detector(
        name,
        i,
        DetectorType.DALY if name == "PM" else DetectorType.FARADAY,
        AmplifierType.VIRTUAL if name == "PM" else AmplifierType.RESISTANCE,
        1e11,
        0.0,
        1.0,
        0.0,
    )
    for i, name in enumerate(
        ("L5", "L4", "L3", "L2", "Ax", "PM", "H1", "H2", "H3", "H4")
    )
)


@dataclass(frozen=True)
class Nuclide:
    symbol: str
    protons: int
    neutrons: int
    atomic_mass: float
    half_life_annum: float  # Java sentinel: stable=-1, unavailable=0
    abundance_percent: float  # Java sentinel: unavailable=0

    @property
    def mass_number(self):
        return self.protons + self.neutrons


@lru_cache(maxsize=1)
def nuclides() -> tuple[Nuclide, ...]:
    """NuclidesFactory.java:60-98 parsing conventions, including missing sentinels.

    Resource: species/nuclides/NuclidesChartData.csv at 00dc941. It is a pinned
    reference, not a newly certified source of isotope abundances.
    """

    def number(text):
        try:
            return float(text)
        except ValueError:
            return 0.0

    resource = files("rawtims").joinpath("resources/NuclidesChartData.csv")
    rows = csv.reader(StringIO(resource.read_text(encoding="utf-8")))
    next(rows)
    return tuple(
        Nuclide(
            r[2].strip(),
            int(r[0]),
            int(r[1]),
            number(r[5]),
            -1.0 if "STABLE" in r[4].upper() else number(r[4]),
            number(r[3]),
        )
        for r in rows
    )


def isotope(symbol: str, mass_number: int) -> Nuclide:
    for entry in nuclides():
        if (entry.symbol, entry.mass_number) == (symbol, mass_number):
            return entry
    raise ValueError(f"Unknown isotope: {mass_number}{symbol}")


@dataclass(frozen=True)
class MethodRow:
    """Original string fields; JAXB's schema declares every leaf as string."""

    fields: tuple[tuple[str, str], ...]

    def get(self, name):
        return dict(self.fields)[name]


@dataclass(frozen=True)
class BaselineCell:
    detector: str
    baseline: str
    sequence: int
    mass: float


@dataclass(frozen=True)
class SequenceCell:
    detector: str
    sequence: int
    species: Nuclide
    baseline_refs: tuple[str, ...]


@dataclass(frozen=True)
class Method:
    name: str
    header: MethodRow
    settings: MethodRow
    baselines: tuple[MethodRow, ...]
    on_peak: tuple[MethodRow, ...]
    equilibration: MethodRow
    detectors: tuple[Detector, ...]
    baseline_cells: tuple[BaselineCell, ...]
    sequence_cells: tuple[SequenceCell, ...]
    source_sha256: str
    schema: str = SCHEMA
    catalog_version: str = CATALOG_VERSION

    def compare_data_method(self, name: str) -> str:
        """AnalysisMethod.java:306-322: only the name check is active upstream."""
        return (
            ""
            if self.name.casefold() == name.casefold()
            else f"Method name: {self.name} differs from data file's method name. \n"
        )
