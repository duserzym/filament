"""Read-only P6 APIs; source citations use Java Tripoli 00dc941, not runtime claims."""

import hashlib
import runpy
import xml.etree.ElementTree as ET
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import numpy as np
import pytest

from rawtims.intensity_matrices import (
    java_spline_basis,
    linear_cycle_matrix,
    spline_basis,
)
from rawtims.methods import (
    CATALOG_VERSION,
    INSTRUMENTS,
    SYNTHETIC_DETECTORS,
    AmplifierType,
    DetectorType,
    isotope,
    nuclides,
)
from rawtims.model import Function, RawFile, Run, RunMetadata
from rawtims.phoenix_method import parse_method_xml, read_method_xml
from rawtims.physical_units import (
    JAVA_CHARGE_C,
    DisplayCalibration,
    IntensityUnit,
    convert_intensity,
    display_availability,
    display_intensity,
)
from rawtims.reduction_params import ReductionParameters
from rawtims.synthetic_acquisition import parse_java_synthetic, read_java_synthetic

FIXTURES = Path(__file__).parent / "fixtures"
XML = FIXTURES / "synthetic/synthetic_phoenix_method.xml"
K = FIXTURES / "tripoli/p6"
CORE = "TripoliCore/src/main/java/org/cirdles/tripoli/"


def test_source_schema_specimen_and_mapping():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:200-303.
    SYNTHETIC XML written to TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:261-270,418-440,721-733,
    910-918,1165-1197,1628-1690; no real vendor XML specimen is available.
    """
    generated = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts/make_synthetic_fixtures.py")
    )["phoenix_method_xml"]()
    assert generated == XML.read_bytes()
    method = read_method_xml(XML)
    assert (
        method.schema == "rawtims-method/1"
        and method.catalog_version == CATALOG_VERSION
    )
    assert method.source_sha256 == hashlib.sha256(generated).hexdigest()
    assert method.name == "SYNTHETIC Phoenix Pb"
    assert [(c.detector, c.baseline, c.mass) for c in method.baseline_cells] == [
        ("Ax", "BL1", 205.75),
        ("Ax", "BL2", 207.5),
        ("H2", "BL1", 208.75),
        ("H2", "BL2", 210.5),
    ]
    assert [
        (c.detector, c.sequence, c.species.mass_number, c.baseline_refs)
        for c in method.sequence_cells
    ] == [
        ("Ax", 1, 206, ("BL1", "BL2")),
        ("H2", 1, 208, ("BL1", "BL2")),
        ("Ax", 2, 207, ("BL1",)),
    ]
    # Java includes all rows; Enabled is retained, not silently used as a filter.
    assert method.on_peak[1].get("Enabled") == "False"
    with pytest.raises(FrozenInstanceError):
        method.name = "edit refused"


def test_java_name_only_consistency():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:306-322.
    Baseline/sequence count checks upstream are commented out.
    """
    method = read_method_xml(XML)
    assert method.compare_data_method(method.name.lower()) == ""
    assert (
        method.compare_data_method("other")
        == f"Method name: {method.name} differs from data file's method name. \n"
    )


def modified(section, field, value, occurrence=0):
    root = ET.fromstring(XML.read_bytes())
    root.findall(section)[occurrence].find(field).text = value
    return ET.tostring(root)


@pytest.mark.parametrize(
    "section,field,value,message",
    [
        ("HEADER", "Filename", "", "Filename"),
        ("SETTINGS", "AxialColl", "invented", "axial"),
        ("BASELINE", "Sequence", "2", "contiguous"),
        ("BASELINE", "AxMass", "nan", "finite"),
        ("BASELINE", "AxMassOffset", "inf", "finite"),
        ("BASELINE", "BLReferences", "BL9", "mass reference"),
        ("ONPEAK", "CollectorArray", "206Pb:BadS1", "collector"),
        ("ONPEAK", "CollectorArray", "999Pb:AxS1", "Unknown isotope"),
        ("ONPEAK", "CollectorArray", "206Pb:AxS9", "suffix"),
        ("ONPEAK", "CollectorArray", "206Pb:AxS1,207Pb:AxS1", "collector"),
        ("ONPEAK", "CollectorArray", "208Pb:H2S1", "axial baseline"),
        ("ONPEAK", "BLReferences", "BL99", "baseline reference"),
        ("ONPEAK", "BLReferences", "BL1, BL1", "baseline reference"),
    ],
)
def test_synthetic_method_semantic_refusals(section, field, value, message):
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:223-297 consumed fields; strict validation is this adapter's extension."""
    with pytest.raises(ValueError, match=message):
        parse_method_xml(modified(section, field, value))


@pytest.mark.parametrize(
    "mutation",
    [
        "root",
        "unknown_section",
        "unknown_field",
        "missing",
        "duplicate",
        "order",
        "nested",
        "attribute",
        "text",
        "dtd",
        "malformed",
        "oversize",
    ],
)
def test_strict_xml_refusals(mutation):
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:261-270 known schema; refusing unknown XML is a P6 requirement."""
    root = ET.fromstring(XML.read_bytes())
    if mutation == "root":
        root.tag = "other"
    elif mutation == "unknown_section":
        ET.SubElement(root, "UNKNOWN")
    elif mutation == "unknown_field":
        ET.SubElement(root.find("HEADER"), "Unknown")
    elif mutation == "missing":
        root.remove(root.find("SETTINGS"))
    elif mutation == "duplicate":
        root.find("HEADER").append(ET.Element("Filename"))
    elif mutation == "order":
        last = root[-1]
        root.remove(last)
        root.insert(0, last)
    elif mutation == "nested":
        ET.SubElement(root.find("HEADER/Filename"), "Nested")
    elif mutation == "attribute":
        root.find("HEADER/Filename").set("unknown", "yes")
    elif mutation == "text":
        root.find("HEADER").text = "unexpected text"
    data = ET.tostring(root)
    if mutation == "dtd":
        data = b'<!DOCTYPE x [<!ENTITY e "value">]>' + data
    elif mutation == "malformed":
        data = b"<ANALYSIS_METHOD>"
    elif mutation == "oversize":
        data = b" " * 2_000_001
    with pytest.raises(ValueError):
        parse_method_xml(data)


def test_pm_and_optional_onpeak():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethod.java:211-218,285-297: PM uses Ax ordinal 4 for nonaxial deltas."""
    root = ET.fromstring(modified("SETTINGS", "AxialColl", "PM"))
    for child in root.findall("ONPEAK/CollectorArray"):
        child.text = child.text.replace(":AxS", ":PMS")
    method = parse_method_xml(ET.tostring(root))
    assert [(c.detector, c.mass) for c in method.baseline_cells] == [
        ("PM", 205.75),
        ("PM", 207.5),
        ("H2", 208.75),
        ("H2", 210.5),
    ]
    for child in root.findall("ONPEAK"):
        root.remove(child)
    assert not parse_method_xml(ET.tostring(root)).sequence_cells
    with pytest.raises(ValueError, match="unique"):
        parse_method_xml(
            XML.read_bytes(), SYNTHETIC_DETECTORS + SYNTHETIC_DETECTORS[:1]
        )


def test_catalog_and_abundances():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/MassSpectrometerBuiltinModelFactory.java:35-46; TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/detectorSetups/DetectorSetupBuiltinModelFactory.java:39-61;
    TripoliCore/src/main/java/org/cirdles/tripoli/expressions/species/nuclides/NuclidesFactory.java:60-98 and resource TripoliCore/src/main/resources/org/cirdles/tripoli/species/nuclides/NuclidesChartData.csv:1-7,2663-2665.
    """
    assert [
        (i.name, i.collector_width_mm, i.magnet_radius_mm, i.beam_width_mm)
        for i in INSTRUMENTS
    ] == [("Phoenix", 0.95135, 540.0, 0.35), ("UNKNOWN", 0.0, 0.0, 0.0)]
    assert [d.name for d in SYNTHETIC_DETECTORS] == [
        "L5",
        "L4",
        "L3",
        "L2",
        "Ax",
        "PM",
        "H1",
        "H2",
        "H3",
        "H4",
    ]
    assert [d.ordinal for d in SYNTHETIC_DETECTORS] == list(range(10))
    assert all(
        (d.resistance_ohm, d.gain, d.efficiency, d.dead_time) == (1e11, 0.0, 1.0, 0.0)
        for d in SYNTHETIC_DETECTORS
    )
    assert SYNTHETIC_DETECTORS[5].kind == DetectorType.DALY
    assert SYNTHETIC_DETECTORS[5].amplifier == AmplifierType.VIRTUAL
    assert len(nuclides()) == 3365
    assert isotope("Pb", 208).abundance_percent == 52.4
    assert isotope("H", 1).atomic_mass == 1.007825031898
    assert isotope("H", 1).half_life_annum == -1.0
    assert isotope("n", 4).atomic_mass == 0.0
    assert isotope("n", 4).abundance_percent == 0.0
    with pytest.raises(ValueError):
        isotope("Invented", 999)
    with pytest.raises(FrozenInstanceError):
        INSTRUMENTS[0].beam_width_mm = 9
    resource = Path(__file__).parents[1] / "src/rawtims/resources/NuclidesChartData.csv"
    assert (
        hashlib.sha256(resource.read_bytes()).hexdigest()
        in resource.with_name("NOTICE").read_text()
    )


def matrices(name):
    answer = []
    for line in (K / name).read_text().splitlines():
        dims, *values = line.rstrip(",").split(",")
        answer.append(
            np.array(values, float).reshape(
                tuple(int(float(n)) for n in dims.split("x"))
            )
        )
    return answer


@pytest.mark.parametrize("index", range(100))
def test_oracle_k_all_stored_spline_matrices(index):
    """TripoliCore/src/test/resources/org/cirdles/tripoli/core/matLab/bspline/bspline_{matrix_A,matrix_B,answers}.txt:1-100;
    TripoliCore/src/test/java/org/cirdles/tripoli/utilities/mathUtilities/SplineBasisModelTest.java:111-168 (disabled comparison), TripoliCore/src/main/java/org/cirdles/tripoli/utilities/mathUtilities/SplineBasisModel.java:38-160.
    K serializes inputs AND answers at six decimals. Absolute 4e-6 accounts for
    rounded abscissae/bounds and answers (observed maximum 3.469e-6); no existing
    tolerance changed. This is stored-matrix parity, not Java-runtime parity.
    """
    x = matrices("bspline_matrix_A.txt")[index].ravel()
    lower, upper, _, segments, degree = matrices("bspline_matrix_B.txt")[index][0]
    expected = matrices("bspline_answers.txt")[index]
    actual = spline_basis(x, int(segments), int(degree), lower=lower, upper=upper)
    assert actual.shape == expected.shape
    np.testing.assert_allclose(actual, expected, rtol=0, atol=4e-6)


def test_synthetic_spline_degree_sign_and_bounds():
    """TripoliCore/src/main/java/org/cirdles/tripoli/utilities/mathUtilities/SplineBasisModel.java:65-68,124-127 misses (-1)^(degree+1) for even degrees.
    Explicitly retain the literal Java convention separately from positive oracle K.
    """
    x = np.linspace(0, 2, 5)
    expected = np.array(
        [
            [0.5, 0.5, 0, 0],
            [0.125, 0.75, 0.125, 0],
            [0, 0.5, 0.5, 0],
            [0, 0.125, 0.75, 0.125],
            [0, 0, 0.5, 0.5],
        ]
    )
    np.testing.assert_allclose(spline_basis(x, 2, 2), expected, atol=1e-14)
    np.testing.assert_allclose(java_spline_basis(x, 2, 2), -expected, atol=1e-14)
    np.testing.assert_allclose(
        spline_basis(x, 2, 3), java_spline_basis(x, 2, 3), atol=0
    )
    assert spline_basis(x, 2, 3, lower=-1, upper=3).shape == (5, 5)
    np.testing.assert_allclose(
        spline_basis(x, 2, 3, lower=0.1, upper=1.9), spline_basis(x, 2, 3)
    )


@pytest.mark.parametrize(
    "times,segments,degree",
    [
        ([0], 2, 3),
        ([0, 0], 2, 3),
        ([0, float("nan")], 2, 3),
        ([1, 0], 2, 3),
        ([[0, 1]], 2, 3),
        ([0, 1], 0, 3),
        ([0, 1], 2, -1),
        ([0, 1], 2, 1.5),
    ],
)
def test_synthetic_spline_domains(times, segments, degree):
    with pytest.raises(ValueError):
        spline_basis(times, segments, degree)


@pytest.mark.parametrize("index", [1, 2])
def test_java_synthetic_file_structure(index):
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PhoenixMassSpec.java:163-231,420-449,488-590 (TripoliCore/.../dataSourceProcessors/phoenix);
    Oracle K SyntheticDataset_01.txt / _02.txt:19-1819, upstream synthetic only.
    """
    source = K / f"JavaDataset_0{index}.txt"
    data = read_java_synthetic(source)
    assert data.schema == "rawtims-java-synthetic/1" and len(data.blocks) == 1
    block = data.blocks[0]
    assert (
        block.number == 1 and len(block.baseline) == 300 and len(block.on_peak) == 1500
    )
    assert block.cycle_starts == tuple(range(0, 1500, 100))
    assert len(data.columns) == 16 and block.baseline[0].mass == 205.5
    assert block.on_peak[-1].cycle == 15 and block.on_peak[-1].time == 239.9
    assert block.baseline[0].intensities[4] == (
        29274.0921 if index == 1 else 29826.2229
    )
    assert not data.omitted_baseline_only_tail
    # Independently reconstruct every stored field, preserving all original rows.
    raw = [line.split(",") for line in source.read_text().splitlines()[19:]]
    for row, original in zip(block.baseline + block.on_peak, raw, strict=True):
        assert (row.sequence, row.block, row.cycle, row.integration) == (
            original[0],
            int(original[1]),
            int(original[2]),
            int(original[3]),
        )
        assert (row.time, row.mass, *row.intensities) == tuple(map(float, original[4:]))
    matrix = linear_cycle_matrix([r.time for r in block.on_peak], block.cycle_starts)
    assert matrix.shape == (1500, 16)
    np.testing.assert_allclose(matrix.sum(axis=1), 1.0)
    assert matrix[0, 0] == 1 and matrix[-1, -1] == 1


SYNTHETIC_TEXT = """Version,1.00
Filename,SYNTHETIC source-schema scalar
#START
ID,Block,Cycle,Integ,Time,Mass,Ax
BL1,1,0,1,0,205.5,-2
S1,1,1,1,1,206,10
S1,1,1,2,2,206,20
S1,1,2,1,3,206,30
S1,1,2,2,5,206,50
"""


def test_synthetic_structure_linear_scalar_and_baseline_tail():
    """TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/SingleBlockModelDriver.java:189-233; scalar matrix hand-calculated from cycle-start times."""
    data = parse_java_synthetic(SYNTHETIC_TEXT)
    b = data.blocks[0]
    assert b.baseline[0].intensities == (-2.0,) and b.cycle_starts == (0, 2)
    np.testing.assert_allclose(
        linear_cycle_matrix([r.time for r in b.on_peak], b.cycle_starts),
        [[1, 0, 0], [0.5, 0.5, 0], [0, 1, 0], [0, 0, 1]],
    )
    tail = parse_java_synthetic(SYNTHETIC_TEXT + "BL1,2,0,1,0,205.5,0\n")
    assert len(tail.blocks) == 1 and tail.omitted_baseline_only_tail


@pytest.mark.parametrize(
    "old,new",
    [
        ("1.00", "1.20"),
        ("#START", "#BASELINES"),
        ("Ax\n", "Ax,Ax\n"),
        ("BL1,1,0", "S1,1,0"),
        ("S1,1,2", "S1,1,3"),
        ("1,0,205.5,-2", "1,0,205.5,nan"),
        ("S1,1,1,2,2", "S1,1,1,2,1"),
        ("206,50", "206"),
        ("BL1,1", "BL1,2"),
    ],
)
def test_synthetic_structure_refusals(old, new):
    with pytest.raises(ValueError):
        parse_java_synthetic(SYNTHETIC_TEXT.replace(old, new))


@pytest.mark.parametrize("starts", [[], [1], [0, 0], [0, 3], [0, 1.5]])
def test_synthetic_linear_refusals(starts):
    with pytest.raises(ValueError):
        linear_cycle_matrix([0, 1, 2, 3], starts)


def display_run(element="U"):
    """Synthetic run already carrying the same provenance schema as a decoded raw Run."""
    keys = (
        ("265", "267", "ratio")
        if element == "U"
        else ("Pb206+At206 S2 int", "206 D", "ratio")
    )
    params = ReductionParameters(
        route="raw",
        faraday_gains={"Low3": 1.2, "High1": 1.1},
        faraday_resistors_ohm={"Low3": 1e11, "High1": 1e12},
    )
    return Run(
        "synthetic-display",
        RawFile("synthetic", "synthetic", 0, "0" * 64, "synthetic"),
        element,
        RunMetadata(method="SYNTHETIC verified raw metadata"),
        (
            Function(0, keys[0], keys[0], "intensity"),
            Function(1, keys[1], keys[1], "intensity"),
            Function(2, "ratio", "ratio", "ratio"),
        ),
        np.arange(1, 4),
        np.ones(3, int),
        np.arange(3.0),
        np.array([[1.0, 2.0, 3.0], [-1.0, 4.0, 5.0], [np.nan, 6.0, 7.0]]),
        np.zeros((3, 3), bool),
        params,
        provenance={
            "reduction_route": "raw",
            "raw_inputs": {"synthetic.DAT": "0" * 64},
            "reduction_parameters_sha256": params.sha256,
        },
    )


@pytest.mark.parametrize("source", list(IntensityUnit))
@pytest.mark.parametrize("target", list(IntensityUnit))
def test_typed_units_source_formula_and_roundtrip(source, target):
    """TripoliCore/src/main/java/org/cirdles/tripoli/constants/TripoliConstants.java:63-67,155-173; TripoliApp/src/main/java/org/cirdles/tripoli/gui/dataViews/plots/plotsControllers/ogTripoliPlots/analysisPlots/SpeciesIntensityAnalysisPlot.java:219-245.
    Independent scalar SI current convention, plus synthetic signed/missing data.
    """
    c = DisplayCalibration(
        "SYNTHETIC Ax", 1e11, 1.2, True, JAVA_CHARGE_C, "synthetic-parameters"
    )
    values = np.array([0.0, 1.0, -2.0, np.nan])
    factors = {
        IntensityUnit.COUNTS: JAVA_CHARGE_C,
        IntensityUnit.VOLTS: 1e-11,
        IntensityUnit.AMPS: 1.0,
    }
    result = convert_intensity(values, source, target, c)
    np.testing.assert_allclose(
        result, values * factors[source] / factors[target], equal_nan=True
    )
    np.testing.assert_allclose(
        convert_intensity(result, target, source, c), values, equal_nan=True
    )
    assert not np.shares_memory(result, values)
    # Gain is already in the source values, not a second correction.
    np.testing.assert_array_equal(
        result, convert_intensity(values, source, target, replace(c, recorded_gain=2.0))
    )


def test_display_only_eligibility_and_vendor_charge():
    """Existing ionvantage_raw.py:194-201: gain-scaled U volts/Pb cps, vendor charge recorded by route.
    No existing raw route is executed/modified here; synthetic metadata exercise only.
    """
    for element, key, target in [
        ("U", "265", IntensityUnit.AMPS),
        ("Pb", "Pb206+At206 S2 int", IntensityUnit.VOLTS),
    ]:
        run = display_run(element)
        before = run.values.copy()
        status = display_availability(run, key)
        assert status.available
        factor = (
            1e-11
            if element == "U"
            else run.reduction_parameters.electron_charge_c * 1e12
        )
        np.testing.assert_allclose(
            display_intensity(run, key, target),
            run.column(key) * factor,
            equal_nan=True,
        )
        np.testing.assert_array_equal(run.values, before)
        assert run.function(key).unit is None
        assert run.reduction_parameters.electron_charge_c != JAVA_CHARGE_C
    assert "Multiplier" in display_availability(display_run("Pb"), "206 D").reason


@pytest.mark.parametrize(
    "variant,reason",
    [
        ("params", "provenance"),
        ("route", "provenance"),
        ("hash", "provenance"),
        ("inputs", "provenance"),
        ("resistor", "missing"),
        ("gain", "missing"),
        ("ratio", "intensity"),
        ("unmapped", "mapping"),
    ],
)
def test_synthetic_unavailable_conversions(variant, reason):
    run = display_run()
    key = "265"
    if variant == "params":
        run.reduction_parameters = None
    elif variant == "route":
        run.provenance["reduction_route"] = "workbook"
    elif variant == "hash":
        run.provenance["reduction_parameters_sha256"] = "wrong"
    elif variant == "inputs":
        run.provenance["raw_inputs"] = {}
    elif variant in ("resistor", "gain"):
        field = "faraday_resistors_ohm" if variant == "resistor" else "faraday_gains"
        run.reduction_parameters = replace(run.reduction_parameters, **{field: {}})
        run.provenance["reduction_parameters_sha256"] = run.reduction_parameters.sha256
    elif variant == "ratio":
        key = "ratio"
    if variant == "unmapped":
        run.functions = (replace(run.functions[0], key="unknown"), *run.functions[1:])
        key = "unknown"
    result = display_availability(run, key)
    assert not result.available and reason in result.reason
    with pytest.raises(ValueError, match=reason):
        display_intensity(run, key, IntensityUnit.VOLTS)


@pytest.mark.parametrize(
    "field,value",
    [
        ("resistance_ohm", 0),
        ("recorded_gain", float("nan")),
        ("charge_c", -1),
        ("collector", ""),
        ("parameters_sha256", ""),
    ],
)
def test_synthetic_invalid_display_calibration(field, value):
    c = DisplayCalibration("synthetic", 1e11, 1.0, True, JAVA_CHARGE_C, "hash")
    with pytest.raises(ValueError):
        replace(c, **{field: value})


def test_new_inspection_formats_never_route_to_run_readers():
    """P6 isolation requirement: TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PhoenixMassSpec.java:163-231 synthetic records stay separate.
    No acquisition decoder or /1 input route is added for method XML or synthetic matrices.
    """
    from rawtims.readers import UnsupportedFile, open_run

    for path in (XML, K / "JavaDataset_01.txt", K / "bspline_matrix_A.txt"):
        with pytest.raises(UnsupportedFile):
            open_run(path)


def test_disabled_gain_remains_a_display_fact():
    """ionvantage_raw.py:196-201: already-selected gain state is never applied again by display."""
    run = display_run()
    before = display_intensity(run, "265", IntensityUnit.AMPS)
    run.reduction_parameters = replace(
        run.reduction_parameters, apply_faraday_gains=False
    )
    run.provenance["reduction_parameters_sha256"] = run.reduction_parameters.sha256
    status = display_availability(run, "265")
    assert status.available and not status.calibration.gain_applied
    assert "disabled" in status.reason
    np.testing.assert_array_equal(
        display_intensity(run, "265", IntensityUnit.AMPS), before
    )
