"""Synthetic scalar/source oracles, not calibrated-lab validation.

Tripoli citations use OGTripoli d906f70 / Java 00dc941. XML is generated
in-memory from the C# schema, so no external lab files are used by tests.
"""

import copy
from dataclasses import replace

import numpy as np
import pytest

from rawtims.fractionation_preview import (
    PreviewBook,
    UComponents,
    preview_oxide_233_236,
    preview_pb,
    preview_u,
    u_moles,
)
from rawtims.tracers import Estimate as E
from rawtims.tracers import Tracer, add_tracer, parse_tracer_xml


def synthetic_xml(root="Tracer", version=1):
    def model(name, value, sigma, kind="ABS"):
        return f"<ValueModel><name>{name}</name><value>{value}</value><uncertaintyType>{kind}</uncertaintyType><oneSigma>{sigma}</oneSigma></ValueModel>"

    return (
        f'<{root} xmlns="https://raw.githubusercontent.com/EARTHTIME/Schema">'
        f"<tracerName>SYNTHETIC 2535</tracerName><versionNumber>{version}</versionNumber>"
        "<tracerType>mixed 202-205-233-235</tracerType><labName>SYNTHETIC</labName>"
        "<dateCertified>2026-11-26</dateCertified><ratios>"
        + model("r202_205t", ".3", ".1", "PCT")
        + model("r233_235t", "1.2", ".001")
        + model("r238_235t", ".01", ".0001")
        + "</ratios><isotopeConcentrations>"
        + model("concU235t", "1e-9", "1e-12")
        + f"</isotopeConcentrations></{root}>"
    ).encode()


def tracer():
    return parse_tracer_xml(synthetic_xml())


def components(blank=0.1):
    return UComponents(E(blank), E(137.88), E(137.88), E(0.01), E(235), E(238))


def pb():
    return {
        "202Pb/205Pb": E(0.303, 0.0006),
        "206Pb/205Pb": E(10, 0.01),
        "206Pb/204Pb": E(20, 0.02),
        "206Pb/207Pb": E(2, 0.002),
        "207Pb/205Pb": E(5, 0.005),
        "208Pb/205Pb": E(4, 0.004),
        "204Pb/205Pb": E(0.5, 0.0005),
    }


def uranium():
    return {
        "233U/235U": E(0.6, 0.0006),
        "238U/235U": E(70, 0.07),
        "238U/233U": E(70 / 0.6, 0.12),
    }


@pytest.mark.parametrize("root", ["Tracer", "TracerUPbModel"])
def test_csharp_xml_identity_units_and_roundtrip(root):
    """OGTripoli/source/earth_time_org/{Tracer.cs:40-150,TracerUPbModel.cs:40-146,ValueModel.cs:28-81}."""
    t = parse_tracer_xml(synthetic_xml(root))
    assert t.identity == "SYNTHETIC 2535 v1"
    assert t.get("r202_205t") == E(0.3, 0.0003)
    assert t.get("r233_235t") == E(1.2, 0.001)
    assert Tracer.from_dict(t.to_dict()) == t


def test_library_versions_conflicts_and_immutable_originals():
    """OGTripoli/source/earth_time_org/Tracer.cs:89-102 (identity/version); local immutable extension."""
    t = tracer()
    library = add_tracer([], t)
    assert add_tracer(library, t) == library
    second = add_tracer(library, parse_tracer_xml(synthetic_xml(version=2)))
    assert len(second) == 2 and len(library) == 1
    conflict = parse_tracer_xml(
        synthetic_xml().replace(b"<value>.3</value>", b"<value>.4</value>")
    )
    with pytest.raises(ValueError, match="different XML"):
        add_tracer(library, conflict)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda x: b'<!DOCTYPE Tracer [<!ENTITY x "1">]>' + x,
        lambda x: x.replace(b"<ratios>", b"<covariance/> <ratios>"),
        lambda x: x.replace(b"PCT", b"UNKNOWN"),
        lambda x: x.replace(b"<value>.3</value>", b"<value>nan</value>"),
        lambda x: x.replace(b"<oneSigma>.1</oneSigma>", b"<oneSigma>-1</oneSigma>"),
        lambda x: x.replace(b"<versionNumber>1", b"<versionNumber>-1"),
        lambda x: x.replace(b"<oneSigma>.1</oneSigma>", b""),
        lambda x: x.replace(b"<ratios>", b"<ratios><Unknown/>"),
        lambda x: x.replace(b"<ratios>", b"<versionNumber>2</versionNumber><ratios>"),
        lambda x: x.replace(b"r238_235t", b"r233_235t"),
    ],
)
def test_xml_rejects_unknown_unsafe_ambiguous_uncertainties(mutation):
    with pytest.raises(ValueError):
        parse_tracer_xml(mutation(synthetic_xml()))


def test_java_tracer_dialect_is_not_invented():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/parameterModels/AbstractRatiosDataModel.java:35-39
    comments XMLSerializationI out; resources/.../tracerModels contains no XML.
    ValueModel.java:41-43 has separate analytical/systematic absolute sigma.
    These are not the C# oneSigma/PCT schema. Refuse speculative conversion.
    """
    with pytest.raises(ValueError, match="roots"):
        parse_tracer_xml(b"<AbstractRatiosDataModel/>")


def test_csharp_pb_scalar_and_propagated_control_derivatives():
    """OGTripoli/source/TripoliWorkProduct.cs:1683-1710,2025-2035.
    Independently transcribed scalar reference: .303 measured/.3 tracer,
    alpha=1/303; +1,+2,+3,-1 amu multipliers, control remains measured.
    """
    result = preview_pb(pb(), tracer())
    values = dict(zip(result["names"], result["values"]))
    assert values["alpha"] == pytest.approx(1 / 303, abs=1e-16)
    assert values["206Pb/205Pb"] == pytest.approx(10.033003300330033)
    assert values["207Pb/205Pb"] == pytest.approx(5.033003300330033)
    assert values["208Pb/205Pb"] == pytest.approx(4.03960396039604)
    assert values["206Pb/207Pb"] == pytest.approx(1.9933993399339933)
    assert values["202Pb/205Pb"] == 0.303
    alpha_sigma = np.hypot(0.3 / (3 * 0.303**2) * 0.0006, 0.0003 / (3 * 0.303))
    assert result["sigma"][0] == pytest.approx(alpha_sigma)
    i = result["names"].index("206Pb/205Pb")
    assert result["sigma"][i] == pytest.approx(
        np.hypot((1 + 1 / 303) * 0.01, 10 * alpha_sigma)
    )
    assert "Independent" in result["uncertainty"]


def test_csharp_u_components_and_scalar_reference():
    """OGTripoli/source/TripoliWorkProduct.cs:1145-1167,1292-1372;
    USampleComponents.cs:40-85 specifies pg/g/gmol units. Expected constants
    below were evaluated separately with 40-digit Decimal, term1..term5
    transcribed from C#, not generated by the preview implementation.
    """
    t, c = tracer(), components()
    m = u_moles(t, c)
    assert m["235b"] == pytest.approx(3.0640258848906755564e-18, rel=1e-14, abs=0)
    assert m["238b"] == pytest.approx(4.1714266351701971111e-16, rel=1e-14, abs=0)
    assert m["233t"] == pytest.approx(1.2e-11, abs=0)
    result = preview_u(uranium(), t, c)
    assert result["values"] == pytest.approx(
        [
            -0.0146263728552633847683,
            0.61755164742631606172,
            108.13461583442969222,
            66.928461700394689199,
        ],
        rel=1e-13,
    )
    assert not np.isclose(
        result["values"][2], result["values"][3] / result["values"][1], rtol=1e-5
    )


def test_zero_fractionation_and_no_tracer_limits():
    """OGTripoli/source/TripoliWorkProduct.cs:1093,1292-1372,2025-2035.
    No tracer here is an explicit identity diagnostic, never an applied correction.
    """
    for measured, fn in ((pb(), preview_pb), (uranium(), preview_u)):
        result = fn(measured)
        assert result["values"] == [0, *[v.value for k, v in sorted(measured.items())]]
        assert result["sigma"] == [0, *[v.sigma for k, v in sorted(measured.items())]]
    measured = pb()
    measured["202Pb/205Pb"] = E(0.3)
    assert preview_pb(measured, tracer())["values"][0] == 0
    c = replace(components(0), sample_238_235=E(140))
    measured = {"233U/235U": E(0.6), "238U/235U": E(70.005)}
    result = preview_u(measured, tracer(), c)
    assert result["values"][0] == pytest.approx(0, abs=2e-16)


def test_u_covariance_propagation_independent_finite_difference_check():
    """C# alpha formula above; propagation is a new diagnostic, not claimed as C# sigma output.
    Independent central differences exercise every primitive including tracer mass/blank.
    """
    t, c, m = tracer(), components(), uranium()
    c = replace(
        c,
        blank_pg=E(0.1, 0.02),
        sample_238_235=E(137.88, 0.1),
        tracer_g=E(0.01, 0.0001),
    )
    r = preview_u(m, t, c)
    all_inputs = list(r["inputs"].values())
    x = np.array([e["value"] for e in all_inputs])
    cov = np.array(r["input_covariance"])
    cov[0, 2] = cov[2, 0] = 0.4 * np.sqrt(cov[0, 0] * cov[2, 2])
    correlated = preview_u(m, t, c, covariance=cov)

    def compute(x):
        mm = {k: E(v) for k, v in zip(sorted(m), x[:3])}
        names = ["r233_235t", "r238_235t", "concU235t"]
        vals = dict(t.values)
        vals.update({k: E(v) for k, v in zip(names, x[3:6])})
        tt = replace(t, values=tuple(vals.items()))
        cc = UComponents(*[E(v) for v in x[6:]])
        return np.array(preview_u(mm, tt, cc)["values"])

    jac = []
    for i, v in enumerate(x):
        step = abs(v) * 1e-4
        lo, hi = x.copy(), x.copy()
        lo[i] -= step
        hi[i] += step
        jac.append((compute(hi) - compute(lo)) / (2 * step))
    jac = np.array(jac).T
    np.testing.assert_allclose(
        correlated["covariance"], jac @ cov @ jac.T, rtol=2e-7, atol=1e-16
    )
    assert correlated["sigma"][0] != r["sigma"][0]
    assert "Supplied covariance" in correlated["uncertainty"]


@pytest.mark.parametrize(
    "bad",
    [
        np.array([[1, 2], [2, 1]]),
        np.array([[1, np.nan], [0, 1]]),
        np.array([[-1, 0], [0, 1]]),
    ],
)
def test_invalid_covariance_is_refused(bad):
    with pytest.raises(ValueError, match="covariance|Covariance"):
        preview_pb({"202Pb/205Pb": E(0.303, 1)}, tracer(), covariance=bad)


def test_mixed_scale_impossible_covariance_cannot_hide_in_tolerance():
    # A concentration-like uncertainty and ratio uncertainty differ by 12 orders.
    # This rho=2 covariance has a small negative eigenvalue in absolute units.
    with pytest.raises(ValueError, match="covariance"):
        preview_pb(
            {"202Pb/205Pb": E(0.303, 1)},
            tracer(),
            covariance=np.array([[1, 6e-4], [6e-4, 9e-8]]),
        )
    with pytest.raises(ValueError, match="covariance"):
        preview_pb(
            {"202Pb/205Pb": E(0.303, 1e-12), "206Pb/205Pb": E(10, 1)},
            covariance=np.array([[1e-24, 2e-12], [2e-12, 1]]),
        )


def test_csharp_233_236_oxide_scalar_uncertainty_and_unsupported_fractionation():
    """OGTripoli/source/TripoliWorkProduct.cs:1170-1190,2815-2837.
    233/236 fractionation is explicitly unsupported, oxide has a separate law.
    """
    r = preview_oxide_233_236(E(2, 0.01), E(0.5, 0.002), E(0.002, 0.0001))
    assert r["values"] == pytest.approx([0.5, 1.996, 3.992])
    assert r["sigma"][1] == pytest.approx(np.hypot(0.01, 0.0002))
    t = replace(tracer(), tracer_type="mixed 202-205-233-236")
    with pytest.raises(ValueError, match="233/236"):
        preview_u(uranium(), t, components())
    with pytest.raises(ValueError, match="nonpositive"):
        preview_oxide_233_236(E(0.001), E(0.5), E(0.002))


@pytest.mark.parametrize(
    "run",
    [
        lambda: preview_pb({"202Pb/205Pb": E(0)}, tracer()),
        lambda: preview_pb({"206Pb/205Pb": E(1)}, tracer()),
        lambda: preview_u(uranium(), tracer()),
        lambda: preview_u({"233U/236U": E(1)}, tracer(), components()),
        lambda: UComponents(E(-1), E(1), E(1), E(1), E(1), E(1)),
        lambda: preview_pb(pb(), replace(tracer(), tracer_type="mixed 205-233-235")),
    ],
)
def test_invalid_missing_and_unsupported_inputs_fail(run):
    with pytest.raises(ValueError):
        run()


def test_append_only_revisions_undo_redo_and_hash_verification():
    """OGTripoli/source/forms/fmrMainTripoli.cs:7216 batch re-correction.
    Append-only isolated records are the D1 extension, not legacy overwrites.
    """
    book = PreviewBook()
    data = {"synthetic": preview_pb(pb(), tracer())}
    book.add(data)
    frozen = copy.deepcopy(book.data["records"][0])
    data["synthetic"]["values"][0] = 999
    book.add({"synthetic": preview_pb(pb())})
    assert book.data["records"][0] == frozen
    assert book.undo() and len(book.visible()) == 1
    assert book.redo() and len(book.visible()) == 2
    assert PreviewBook(book.to_dict()).to_dict() == book.to_dict()
    book.undo()
    book.add({"synthetic": "new branch"})
    assert len(book.data["records"]) == 3 and not book.redo()
    assert book.data["records"][0] == frozen
    corrupt = book.to_dict()
    corrupt["records"][0]["data"]["synthetic"]["values"][0] = 999
    with pytest.raises(ValueError, match="hash"):
        PreviewBook(corrupt)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"version": 2, "applied": 0, "events": [], "records": [], "library": []},
        {"version": 1, "applied": 1, "events": [0], "records": [], "library": []},
        {"version": 1, "applied": True, "events": [], "records": [], "library": []},
    ],
)
def test_malformed_revision_history_is_refused(data):
    with pytest.raises(ValueError):
        PreviewBook(data)


def test_committed_age_app_scalar_crosscheck_and_blank_difference():
    """IDTIMS_UPbRPy/src/IDTIMS_UPbRPy/utils.py:734-774 (read-only P7 snapshot,
    SHA256 f915df247d7ff6c3c99040c1115232f030a89ff3a5d05e1953b949792ff79181).
    Constants were obtained by executing the age app on these synthetic inputs;
    scripts/check_fractionation_age_app.py reproduces the external cross-check.
    """
    p = preview_pb(pb(), tracer())
    assert p["values"][0] == pytest.approx(0.0033003300330033034, rel=1e-14)
    assert p["sigma"][0] == pytest.approx(0.0007321367075848143, rel=1e-14)
    zero = preview_u(uranium(), tracer(), components(0))
    assert zero["values"][0] == pytest.approx(-0.014626369055871408, rel=1e-13)
    nonzero = preview_u(uranium(), tracer(), components(0.1))
    assert abs(nonzero["values"][0] - zero["values"][0]) > 3e-9
