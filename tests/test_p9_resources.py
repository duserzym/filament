"""P9 committed resource/source oracles; Java Tripoli 00dc941, never executed."""

import hashlib
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from rawtims.educational import demo_catalog, open_demo, parse_peak_scan
from rawtims.mcmc1.initialize import initialize, prepare_two_isotope_synthetic
from rawtims.reference_data import element_nuclides, elements
from rawtims.synthetic_acquisition import read_java_synthetic

ROOT = Path(__file__).parents[1]
RESOURCES = ROOT / "src/rawtims/resources"
SYNTHETIC_SCAN = """Timestamp, SYNTHETIC
Collector, PhotoMultiplier
Mass ID, 208Pb
Initial Mass, 208
Peak Centre Mass, 208
Method, PeakScanning
PDT, 30
Baseline, 0
DetThreshold, 2
DeltaMass, 1
IntegPeriod, ms200

Mass, Intensity
207, 0
208, 10
209, 0
"""


def test_periodic_resource_oracle():
    """TripoliCore/src/main/resources/org/cirdles/tripoli/elements/PeriodicTableOfElements.csv:1-119;
    TripoliCore/src/main/java/org/cirdles/tripoli/elements/ElementsFactory.java:42-68.
    Source bytes pinned independently; Java rows/columns retained, including gap.
    """
    digest = hashlib.sha256(
        (RESOURCES / "PeriodicTableOfElements.csv").read_bytes()
    ).hexdigest()
    assert digest == "b532be1e6126b91de348540ea68c6114c5922fa1f163860a39cb2a9d37c411af"
    assert digest in (RESOURCES / "NOTICE").read_text()
    es = elements()
    assert len(es) == 118
    assert [e.number for e in es] == list(range(1, 119))
    assert len({(e.row, e.column) for e in es}) == 118
    assert (
        es[81].name,
        es[81].symbol,
        es[81].atomic_mass,
        es[81].row,
        es[81].column,
    ) == ("Lead", "Pb", 207.2, 6, 15)
    assert (es[91].symbol, es[91].row, es[91].column) == ("U", 10, 7)
    with pytest.raises(FrozenInstanceError):
        es[0].name = "changed"


def test_nuclide_oracle_and_complete_browser_coverage():
    """TripoliApp/src/main/java/org/cirdles/tripoli/gui/PeriodicTableController.java:120-131;
    TripoliCore/src/main/resources/org/cirdles/tripoli/species/nuclides/NuclidesChartData.csv:2663-2665.
    P6 parser/sentinels retained, with the free neutron accessible separately.
    """
    assert (
        sum(len(element_nuclides(s)) for s in [e.symbol for e in elements()] + ["n"])
        == 3365
    )
    pb = {n.mass_number: n for n in element_nuclides("Pb")}
    assert pb[206].abundance_percent == 24.1
    assert pb[206].half_life_annum == -1
    assert element_nuclides("SYNTHETIC-unknown") == ()


@pytest.mark.parametrize("index", [1, 2])
@pytest.mark.parametrize("kind", ["linear", "cubic"])
def test_packaged_synthetic_demo_matches_p6_p8_oracle(index, kind):
    """TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/synthetic/twoIsotopeSyntheticData/SyntheticDataset_01.txt:19-1819 (also _02);
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/methods/AnalysisMethodBuiltinFactory.java:54-91;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataModels/mcmc/initializers/SingleBlockModelInitForMCMC.java:70-181,366-396,814-870.
    Synthetic input oracle and existing independently scalar-checked P8 APIs.
    """
    session = open_demo(f"two-isotope-{index}", kind=kind)
    data = prepare_two_isotope_synthetic(
        read_java_synthetic(
            ROOT / f"tests/fixtures/tripoli/p6/JavaDataset_0{index}.txt"
        ),
        kind=kind,
    )
    result = initialize(data)
    np.testing.assert_array_equal(session.observations.observed, data.observed)
    np.testing.assert_array_equal(
        session.initialization.parameters.vector, result.parameters.vector
    )
    for name in ("model", "residual", "variance"):
        np.testing.assert_array_equal(
            getattr(session.initialization.evaluation, name),
            getattr(result.evaluation, name),
        )
    assert session.scan is None
    assert session.observations.included.sum() == 3000
    assert not session.observations.included[:600].any()
    assert "SYNTHETIC" in session.title
    again = open_demo(session.key, kind=kind)
    assert not np.shares_memory(
        session.observations.observed, again.observations.observed
    )
    with pytest.raises(ValueError):
        session.initialization.evaluation.model[0] = 100


@pytest.mark.parametrize(
    "key,first,last,maximum,total",
    [
        ("peak-208", 207.53107, 208.4224, 42433, 1572393),
        ("peak-205", 204.53168, 205.41013, 20227, 744163),
    ],
)
def test_peak_input_oracle(key, first, last, maximum, total):
    """TripoliCore/src/main/resources/org/cirdles/tripoli/dataSourceProcessors/dataSources/peakShapes/6NHCl dpblank-210204A-169-PKC-208Pb-PM-S5B2C1.TXT:1-105;
    same directory/DVCC18-9 z9 Pb-570-PKC-205Pb-PM-S2B7C1.TXT:1-105;
    TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/massSpectrometerModels/dataSourceProcessors/phoenix/PeakShapeProcessor_PhoenixTextFile.java:53-92.
    Only recorded columns, no numerical fitted-shape oracle is claimed.
    """
    s = open_demo(key)
    assert len(s.scan.mass) == 92
    np.testing.assert_array_equal(s.scan.mass[[0, -1]], [first, last])
    assert s.scan.intensity.max() == maximum
    assert s.scan.intensity.sum() == total
    assert s.observations is None and s.initialization is None
    assert not s.scan.mass.flags.writeable


def test_synthetic_peak_columns_and_ownership():
    """PeakShapeProcessor_PhoenixTextFile.java:65-67 (full path above); scalar synthetic fixture."""
    scan = parse_peak_scan(SYNTHETIC_SCAN)
    np.testing.assert_array_equal(scan.mass, [207, 208, 209])
    np.testing.assert_array_equal(scan.intensity, [0, 10, 0])
    assert dict(scan.metadata)["Timestamp"] == "SYNTHETIC"
    assert not scan.intensity.flags.writeable


@pytest.mark.parametrize(
    "old,new",
    [
        ("208, 10", "207, 10"),
        ("208, 10", "208, nan"),
        ("Mass, Intensity", "Mass, Unknown"),
        ("209, 0", "209, 0, 1"),
        ("PeakScanning", "Unknown"),
    ],
)
def test_synthetic_peak_refusals(old, new):
    with pytest.raises(ValueError):
        parse_peak_scan(SYNTHETIC_SCAN.replace(old, new))


def test_bundled_provenance_packaging_refusal_and_headless():
    """TripoliApp/src/main/resources/org/cirdles/tripoli/gui/TripoliGUI.fxml:103-106
    ships a hidden demo menu; ours explicitly limits it to bundled teaching data.
    """
    manifest = json.loads((RESOURCES / "educational-manifest.json").read_text())
    assert manifest["source_commit"] == "00dc94109f572c22bb3f357c0f7b1bb5347f62f5"
    assert manifest["license"] == "Apache-2.0"
    assert len(demo_catalog()) == 4
    for e in manifest["demos"].values():
        assert (
            hashlib.sha256((RESOURCES / e["file"]).read_bytes()).hexdigest()
            == e["sha256"]
        )
    changed = demo_catalog()
    changed.clear()
    assert len(demo_catalog()) == 4
    with pytest.raises(ValueError, match="Unknown bundled"):
        open_demo("../../user-session.rawtims")
    with pytest.raises(ValueError, match="basis"):
        open_demo("two-isotope-1", kind="unknown")
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from rawtims.educational import open_demo; from rawtims.reference_data import elements; import sys; open_demo('two-isotope-1'); assert not any(x.startswith(('PySide6','rawtims_gui','requests','keyring')) for x in sys.modules)",
        ],
        check=True,
    )


def test_bundled_digest_guard(monkeypatch):
    import rawtims.educational as module

    catalog = demo_catalog()
    catalog["peak-208"]["sha256"] = "0" * 64
    monkeypatch.setattr(module, "demo_catalog", lambda: catalog)
    with pytest.raises(ValueError, match="digest"):
        open_demo("peak-208")
