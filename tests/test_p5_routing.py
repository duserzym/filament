"""Every pre-P5 committed fixture retains its exact content routing and reason.

Tripoli/constants/MassSpectrometerContextEnum.java:63-71: new exact signatures.
This baseline was captured before any P5 edits with rawtims.readers.sniff.
"""

import json
from pathlib import Path

from rawtims.readers import sniff

BASE = Path(__file__).parent / "fixtures"
BEFORE = json.loads(r"""{
  "MANIFEST.toml": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "synthetic/synthetic_BSU_U_oxide_R18.xls": [
    "ionvantage_xls",
    ""
  ],
  "synthetic/synthetic_ET2535_Pb_202.xls": [
    "ionvantage_xls",
    ""
  ],
  "synthetic/synthetic_MA1_zircon_CA-ID-TIMS.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/LICENSE-APACHE-2.0": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/NOTICE": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/ionvantage/BoiseState/B998_F11_13223M02_iz1_Pb1-14973.xls": [
    "ionvantage_xls",
    ""
  ],
  "tripoli/ionvantage/KU_IGL/GHR1 20200827-11 Pb-6590.xls": [
    "ionvantage_xls",
    ""
  ],
  "tripoli/ionvantage/KU_IGL/GHR1 20200827-11 U run2-6591.xls": [
    "ionvantage_xls",
    ""
  ],
  "tripoli/ionvantage/KU_IGL/NBS981-500_20191208-5563.xls": [
    "ionvantage_xls",
    ""
  ],
  "tripoli/oracle/cycleReports/KU_IGL/IonVantage/Oracle-NBS981-500 20191208-5563-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/cycleReports/KU_IGL/IsolinxVersion1/Oracle-NBS981 210325b-392-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/cycleReports/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921 F08b-216-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/cycleReports/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/cycleReports/KU_IGL/IsolinxVersion2/Oracle-NBS981 230024a-145-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/cycleReports/Purdue/Oracle-WH205 z4 Pb-654-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/cycleReports/Purdue/Oracle-WH205 z41 U-655-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/cycleReports/Purdue/Oracle-WH233B z1 U-671-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/cycleReports/Purdue/Oracle-WH233B z3 Pb-678-report.tsv": [
    null,
    "Tripoli report, not a raw run file"
  ],
  "tripoli/oracle/expressions/NBS981_210325b-392_ExpressionEval.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/fullReports/KU_IGL/IsolinxVersion1/Oracle-NBS981 210325b-392-report.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/fullReports/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921 F08b-216-report.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/fullReports/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239-report.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/fullReports/KU_IGL/IsolinxVersion2/Oracle-NBS981 230024a-145-report.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/fullReports/Purdue/Oracle-WH205 z4 Pb-654-report.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/fullReports/Purdue/Oracle-WH205 z41 U-655-report.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/fullReports/Purdue/Oracle-WH233B z1 U-671-report.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/fullReports/Purdue/Oracle-WH233B z3 Pb-678-report.csv": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/KU_IGL/IonVantage/Oracle-NBS981-500 20191208-5563.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/KU_IGL/IsolinxVersion1/Oracle-NBS981 210325b-392.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921 F08b-216.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/KU_IGL/IsolinxVersion2/Oracle-GHR1 230921F03 U-239.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/KU_IGL/IsolinxVersion2/Oracle-NBS981 230024a-145.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/Purdue/Oracle-WH205 z4 Pb-654.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/Purdue/Oracle-WH205 z41 U-655.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/Purdue/Oracle-WH233B z1 U-671.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/oracle/shortReports/Purdue/Oracle-WH233B z3 Pb-678.txt": [
    null,
    "not an IsoLinx .TIMSDP or IonVantage .xls run file (text that does not start with #HEADER)"
  ],
  "tripoli/timsdp/KU_IGL/IsolinxVersion1/NBS981 210325b-392.TIMSDP": [
    "isolinx_timsdp",
    ""
  ],
  "tripoli/timsdp/KU_IGL/IsolinxVersion2/GHR1 230921 F08b-216.TIMSDP": [
    "isolinx_timsdp",
    ""
  ],
  "tripoli/timsdp/KU_IGL/IsolinxVersion2/GHR1 230921F03 U-239.TIMSDP": [
    "isolinx_timsdp",
    ""
  ],
  "tripoli/timsdp/KU_IGL/IsolinxVersion2/NBS981 230024a-145.TIMSDP": [
    "isolinx_timsdp",
    ""
  ],
  "tripoli/timsdp/Purdue/WH205 z4 Pb-654.TIMSDP": [
    "isolinx_timsdp",
    ""
  ],
  "tripoli/timsdp/Purdue/WH205 z41 U-655.TIMSDP": [
    "isolinx_timsdp",
    ""
  ],
  "tripoli/timsdp/Purdue/WH233B z1 U-671.TIMSDP": [
    "isolinx_timsdp",
    ""
  ],
  "tripoli/timsdp/Purdue/WH233B z3 Pb-678.TIMSDP": [
    "isolinx_timsdp",
    ""
  ]
}""")


def test_all_pre_p5_fixture_routes_are_unchanged():
    for relative, expected in BEFORE.items():
        detected = sniff(BASE / relative)
        assert [detected.format, detected.reason] == expected, relative


def test_raw_folder_and_trip_project_dispatch_stays_unchanged(tmp_path):
    """.raw still opens its unique cached workbook; .trip remains an explicit project API."""
    import shutil

    import numpy as np
    from test_trip_reader import cls, stream

    from rawtims.readers import open_paths, open_run

    workbook = BASE / "synthetic/synthetic_ET2535_Pb_202.xls"
    folder = tmp_path / "synthetic.raw"
    folder.mkdir()
    cached = folder / "synthetic.xls"
    shutil.copyfile(workbook, cached)
    expected = open_run(workbook)
    actual = open_run(folder)
    assert actual.raw.format == expected.raw.format == "ionvantage_xls"
    np.testing.assert_array_equal(actual.values, expected.values)
    np.testing.assert_array_equal(actual.invalid, expected.invalid)
    project = tmp_path / "synthetic.trip"
    project.write_bytes(stream(cls(1, "Tripoli.TripoliWorkProduct", [], [])))
    runs, skipped = open_paths([project, folder])
    assert len(runs) == 1 and runs[0].raw.path == str(cached)
    assert skipped == [
        (project, "legacy Tripoli project, not a raw run file (use read_trip)")
    ]
