"""Read-only periodic-table resource, Java Tripoli 00dc941 schema 1.

Copyright 2022 James Bowring, Noah McLean, Scott Burdick, and CIRDLES.org.
Apache-2.0; resources/LICENSE-APACHE-2.0. ElementsFactory.java:42-68 adapted
without changing the P6 nuclide parser or any reduction/reference defaults.
"""

import csv
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from io import StringIO

from rawtims.methods import CATALOG_VERSION, nuclides

RESOURCE_VERSION = CATALOG_VERSION


@dataclass(frozen=True)
class Element:
    number: int
    name: str
    symbol: str
    atomic_mass: float
    row: int
    column: int


@lru_cache(maxsize=1)
def elements() -> tuple[Element, ...]:
    resource = files("rawtims").joinpath("resources/PeriodicTableOfElements.csv")
    return tuple(
        Element(
            int(r[0]), r[1].strip(), r[2].strip(), float(r[3]), int(r[4]), int(r[5])
        )
        for r in list(csv.reader(StringIO(resource.read_text(encoding="utf-8"))))[1:]
    )


def element_nuclides(symbol):
    """Keep upstream order and P6 missing-value/stable sentinels unchanged."""
    return tuple(n for n in nuclides() if n.symbol == symbol)
