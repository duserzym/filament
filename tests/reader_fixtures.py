"""Shared paths and a cached reader for the reader tests (test helper)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from rawtims.model import Run
from rawtims.readers import open_run

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TRIPOLI = FIXTURES / "tripoli"
IONVANTAGE = TRIPOLI / "ionvantage"
TIMSDP = TRIPOLI / "timsdp"
ORACLE_CYCLES = TRIPOLI / "oracle" / "cycleReports"
SYNTHETIC = FIXTURES / "synthetic"

B998 = IONVANTAGE / "BoiseState" / "B998_F11_13223M02_iz1_Pb1-14973.xls"
GHR1_PB_XLS = IONVANTAGE / "KU_IGL" / "GHR1 20200827-11 Pb-6590.xls"
GHR1_U_XLS = IONVANTAGE / "KU_IGL" / "GHR1 20200827-11 U run2-6591.xls"
NBS981_XLS = IONVANTAGE / "KU_IGL" / "NBS981-500_20191208-5563.xls"

TIMSDP_FILES = {
    "NBS981 210325b-392": TIMSDP / "KU_IGL" / "IsolinxVersion1" / "NBS981 210325b-392.TIMSDP",
    "GHR1 230921 F08b-216": TIMSDP / "KU_IGL" / "IsolinxVersion2" / "GHR1 230921 F08b-216.TIMSDP",
    "GHR1 230921F03 U-239": TIMSDP / "KU_IGL" / "IsolinxVersion2" / "GHR1 230921F03 U-239.TIMSDP",
    "NBS981 230024a-145": TIMSDP / "KU_IGL" / "IsolinxVersion2" / "NBS981 230024a-145.TIMSDP",
    "WH205 z4 Pb-654": TIMSDP / "Purdue" / "WH205 z4 Pb-654.TIMSDP",
    "WH205 z41 U-655": TIMSDP / "Purdue" / "WH205 z41 U-655.TIMSDP",
    "WH233B z1 U-671": TIMSDP / "Purdue" / "WH233B z1 U-671.TIMSDP",
    "WH233B z3 Pb-678": TIMSDP / "Purdue" / "WH233B z3 Pb-678.TIMSDP",
}

SYNTHETIC_U = SYNTHETIC / "synthetic_BSU_U_oxide_R18.xls"
SYNTHETIC_PB = SYNTHETIC / "synthetic_ET2535_Pb_202.xls"
SYNTHETIC_FRACTIONS = SYNTHETIC / "synthetic_MA1_zircon_CA-ID-TIMS.csv"


@cache
def read(path: Path) -> Run:
    """Read a fixture once per test process. Tests must not mutate the returned run."""
    return open_run(path)
