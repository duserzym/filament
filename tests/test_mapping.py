"""Mapping run functions to contract ratios (SPEC F14): collectors, shorthand, oxide-only U, inversion, ambiguity, remembering."""

from __future__ import annotations

from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pytest

from rawtims.analysis import Analysis, AnalysisSettings
from rawtims.mapping import MappingError, MethodMapping, mapped_values, mapping_for, propose_mapping, ratio_stats
from rawtims.model import Function
from rawtims.oxide import OxideResult
from rawtims.readers.functions import build_functions
from rawtims.stats import describe
from reader_fixtures import B998, GHR1_PB_XLS, GHR1_U_XLS, SYNTHETIC_PB, SYNTHETIC_U, TIMSDP_FILES, read

PB_D = {
    "206Pb/204Pb": "206/204 D", "206Pb/207Pb": "206/207 D", "206Pb/205Pb": "206/205 D",
    "207Pb/205Pb": "207/205 D", "204Pb/205Pb": "204/205 D", "208Pb/205Pb": "208/205 D",
}
PB_F = {
    "206Pb/204Pb": "206/204 F-D", "206Pb/207Pb": "206/207 F", "206Pb/205Pb": "206/205 F",
    "207Pb/205Pb": "207/205 F", "204Pb/205Pb": "204/205 F-D", "208Pb/205Pb": "208/205 F",
}


def _keys(mapping) -> dict[str, str]:
    return {ratio: mapped.key for ratio, mapped in mapping.ratios.items()}


def _stub(names: list[str], columns: list[np.ndarray], element: str, stat_mode: str = "geometric", extra=None):
    """A minimal object with the attributes propose_mapping reads (functions, column, run, settings, oxide)."""
    functions = build_functions(names, extra)
    values = np.column_stack(columns)
    return SimpleNamespace(
        functions=functions,
        column=lambda key: values[:, next(f.index for f in functions if f.key == key)],
        run=SimpleNamespace(element=element, metadata=SimpleNamespace(method="stub method")),
        settings=SimpleNamespace(stat_mode=stat_mode),
        oxide=OxideResult(status="not_applicable", reason="stub"),
    )


# ------------------------------------------------------------------ Pb, BSU
def test_b998_maps_the_daly_user_functions_by_default():
    mapping = propose_mapping(Analysis(read(B998)))
    assert mapping.complete and _keys(mapping) == PB_D
    # "206/204 Daly" has identical values but belongs to a family that covers only three contract ratios.
    assert mapping.ratios["206Pb/204Pb"].alternatives == ("206/204 Daly",)
    assert not [i for i in mapping.issues if i.kind != "warning"]
    assert all(m.collector == "D" and not m.inverted and not m.raw for m in mapping.ratios.values())


def test_b998_maps_faraday_functions_when_collector_is_f():
    mapping = propose_mapping(Analysis(read(B998)), collector="F")
    assert mapping.complete and _keys(mapping) == PB_F
    # IonVantage repeats user functions; identical repeats resolve to the first.
    assert mapping.ratios["206Pb/207Pb"].alternatives == ("206/207 F #2",)
    assert mapping.issues == ()


def test_raw_instrument_ratios_rank_last():
    analysis = Analysis(read(B998))
    raw_only = MethodMapping("Pb 205 Daly 150 ratios", "Pb", {"206Pb/205Pb": {"function": "Pb206+At206/Tl205 raw"}}).apply(analysis)
    assert raw_only.ratios["206Pb/205Pb"].raw
    proposed = propose_mapping(analysis)
    assert not any(m.raw for m in proposed.ratios.values())
    # With the processed functions gone, the raw ones are what is left.
    stub = _stub(["Pb206+At206/Tl205 raw", "206/205 D"], [np.full(5, 2.0), np.full(5, 2.0)], "Pb")
    assert propose_mapping(stub).ratios["206Pb/205Pb"].key == "206/205 D"
    stub = _stub(["Pb206+At206/Tl205 raw"], [np.full(5, 2.0)], "Pb")
    assert propose_mapping(stub).ratios["206Pb/205Pb"].key == "Pb206+At206/Tl205 raw"


def test_explicit_collector_with_only_the_other_detector_maps_with_a_warning():
    stub = _stub(["206/204 D"], [np.full(5, 900.0)], "Pb")
    mapping = propose_mapping(stub, collector="F")
    assert mapping.ratios["206Pb/204Pb"].key == "206/204 D"
    assert [(i.ratio, i.kind) for i in mapping.issues if i.ratio == "206Pb/204Pb"] == [("206Pb/204Pb", "warning")]


def test_competing_families_are_reported_not_guessed():
    stub = _stub(["206/204 D", "206/204 Daly"], [np.full(5, 900.0), np.full(5, 901.0)], "Pb")
    mapping = propose_mapping(stub)
    assert "206Pb/204Pb" not in mapping.ratios
    issue = next(i for i in mapping.issues if i.ratio == "206Pb/204Pb")
    assert issue.kind == "ambiguous" and set(issue.candidates) == {"206/204 D", "206/204 Daly"}
    # Same family, different values: still ambiguous.
    stub = _stub(["206/204 D", "206/204 D"], [np.full(5, 900.0), np.full(5, 901.0)], "Pb")
    assert next(i for i in propose_mapping(stub).issues if i.ratio == "206Pb/204Pb").kind == "ambiguous"


# --------------------------------------------------------- Pb, other labs
def test_unlabelled_ku_functions_map_directly():
    mapping = propose_mapping(Analysis(read(TIMSDP_FILES["GHR1 230921 F08b-216"])))
    assert mapping.complete and _keys(mapping) == {r: m.name for r, m in mapping.ratios.items()}
    assert _keys(mapping)["206Pb/204Pb"] == "206/204" and all(m.collector is None for m in mapping.ratios.values())
    assert propose_mapping(Analysis(read(GHR1_PB_XLS))).complete


def test_isolinx_shorthand_maps_by_name_and_formula():
    analysis = Analysis(read(TIMSDP_FILES["WH205 z4 Pb-654"]))
    mapping = propose_mapping(analysis)
    assert mapping.complete
    assert _keys(mapping) == {
        "206Pb/204Pb": "R64", "206Pb/207Pb": "R67", "206Pb/205Pb": "R65",
        "207Pb/205Pb": "R75", "204Pb/205Pb": "R45", "208Pb/205Pb": "R85",
    }
    # R64 is classified "other" by the reader, but as a contract ratio it gets ratio (geometric) statistics.
    assert analysis.function("R64").kind == "other" and analysis.stats("R64").mode == "arithmetic"
    assert ratio_stats(analysis, mapping.ratios["206Pb/204Pb"]).mode == "geometric"


def test_shorthand_with_a_contradicting_formula_is_not_a_candidate():
    # i205Pb reads Intensity(2,_RPM); an "R65" whose numerator is Intensity(2,_RPM) measures 205, so it cannot be 206/205.
    names = ["i205Pb", "R65", "R64x"]
    extra = [{"formula": "Intensity(2,_RPM)"}, {"formula": "Intensity(2,_RPM)/Intensity(3,_RPM)"}, {"formula": "Intensity(3,_RPM)/Intensity(1,_RPM)"}]
    mapping = propose_mapping(_stub(names, [np.ones(5)] * 3, "Pb", extra=extra))
    assert "206Pb/205Pb" not in mapping.ratios and "206Pb/204Pb" not in mapping.ratios  # "R64x" is not shorthand
    extra[1] = {"formula": "Intensity(1,_RPM)*2"}  # not a plain ratio of two intensities
    assert "206Pb/205Pb" not in propose_mapping(_stub(names, [np.ones(5)] * 3, "Pb", extra=extra)).ratios
    extra[1] = {"formula": "Intensity(3,_RPM)/Intensity(2,_RPM)"}
    assert propose_mapping(_stub(names, [np.ones(5)] * 3, "Pb", extra=extra)).ratios["206Pb/205Pb"].key == "R65"


# --------------------------------------------------------------------- U
def test_u_maps_only_oxide_corrected_values():
    analysis = Analysis(read(GHR1_U_XLS))
    mapping = propose_mapping(analysis)
    assert _keys(mapping) == {"238U/235U": "238/235oc", "233U/235U": "233/235oc", "238U/233U": "238/233oc"}
    assert all(m.source == "derived" and m.oxide_r18 == 0.00205 for m in mapping.ratios.values())
    assert "270/267" not in mapping.function_keys


def test_u_pass_through_records_the_r18_from_the_names():
    mapping = propose_mapping(Analysis(read(SYNTHETIC_U)))
    assert _keys(mapping) == {"238U/235U": "238/235 oxide R18 0.00206", "233U/235U": "233/235 oxide R18 0.00206", "238U/233U": "238/233 oxide"}
    assert mapping.ratios["238U/235U"].oxide_r18 == 0.00206 and mapping.ratios["238U/233U"].oxide_r18 is None
    assert all(m.source == "pass_through" for m in mapping.ratios.values())


def test_u_function_that_is_not_oxide_corrected_is_refused():
    stub = _stub(["238/235", "233/235", "238/233"], [np.full(5, 2.4), np.full(5, 0.98), np.full(5, 2.5)], "U")
    mapping = propose_mapping(stub)
    assert mapping.ratios == {} and not mapping.complete
    kinds = {(i.ratio, i.kind) for i in mapping.issues}
    assert ("238U/235U", "refused") in kinds and ("238U/235U", "missing") in kinds
    assert "not oxide-corrected" in mapping.describe_missing()


# ----------------------------------------------------------------- inversion
def test_inverted_orientation_maps_in_geometric_mode_only():
    run = read(TIMSDP_FILES["NBS981 230024a-145"])
    geometric = propose_mapping(Analysis(run))
    entry = geometric.ratios["206Pb/204Pb"]
    assert entry.key == "204/206 Daly" and entry.inverted and "1/(204/206 Daly)" in entry.note
    arithmetic = propose_mapping(Analysis(run, AnalysisSettings(stat_mode="arithmetic")))
    assert "206Pb/204Pb" not in arithmetic.ratios
    issue = next(i for i in arithmetic.issues if i.ratio == "206Pb/204Pb")
    assert issue.kind == "refused" and "arithmetic" in issue.message and "geometric" in issue.message


def test_inversion_is_exact_for_geometric_means_and_percent_se():
    """1/gm(x) = gm(1/x) and SD(ln 1/x) = SD(ln x): the inverted mean and % SE are exact, on real and random data."""
    rng = np.random.default_rng(7)
    for values in (rng.lognormal(np.log(0.001), 0.02, 400), np.exp(rng.normal(3.0, 0.5, 31))):
        direct, inverse = describe(values, mode="geometric"), describe(1.0 / values, mode="geometric")
        assert inverse.mean * direct.mean == pytest.approx(1.0, abs=1e-14)
        assert inverse.se_pct == pytest.approx(direct.se_pct, rel=1e-12)
        assert inverse.n_used == direct.n_used
        arithmetic = describe(1.0 / values, mode="arithmetic").mean
        assert abs(arithmetic * describe(values, mode="arithmetic").mean - 1.0) > 1e-8  # not exact arithmetically
    # Real file with both orientations as separate instrument columns: 1/(204/206) reproduces 206/204 to the
    # precision the file stores each column with (per cycle |1/x - y|/y <= 3.6e-10).
    analysis = Analysis(read(TIMSDP_FILES["NBS981 210325b-392"]))
    forced = MethodMapping("m", "Pb", {"206Pb/204Pb": {"function": "204/206", "inverted": True}}).apply(analysis)
    inverted = ratio_stats(analysis, forced.ratios["206Pb/204Pb"])
    direct = analysis.stats("206/204")
    assert inverted.mean == pytest.approx(direct.mean, rel=1e-9)
    assert inverted.se_pct == pytest.approx(direct.se_pct, rel=1e-7)
    assert inverted.mean * analysis.stats("204/206").mean == pytest.approx(1.0, abs=1e-14)  # exact against its own column
    assert inverted.se_pct == pytest.approx(analysis.stats("204/206").se_pct, rel=1e-12)


def test_inverted_values_refuse_arithmetic_mode():
    analysis = Analysis(read(TIMSDP_FILES["NBS981 230024a-145"]))
    entry = propose_mapping(analysis).ratios["206Pb/204Pb"]
    analysis.set_setting("stat_mode", "arithmetic")
    with pytest.raises(MappingError, match="arithmetic"):
        mapped_values(analysis, entry)
    remembered = MethodMapping("m", "Pb", {"206Pb/204Pb": entry.to_dict()}).apply(analysis)
    assert remembered.ratios == {} and next(i for i in remembered.issues if i.ratio == "206Pb/204Pb").kind == "refused"


# ------------------------------------------------------------- remembering
def test_method_mapping_round_trips_as_json_and_applies_to_the_same_method():
    analysis = Analysis(read(B998))
    proposed = propose_mapping(analysis, collector="F")
    remembered = proposed.to_method_mapping()
    data = json.loads(json.dumps(remembered.to_dict()))
    assert data["method"] == "Pb 205 Daly 150 ratios" and data["ratios"]["206Pb/204Pb"] == {"function": "206/204 F-D", "inverted": False}
    again = MethodMapping.from_dict(data).apply(analysis)
    assert _keys(again) == _keys(proposed) and again.complete and again.collector == "F"
    chosen = mapping_for(analysis, {remembered.method: MethodMapping.from_dict(data)})
    assert _keys(chosen) == PB_F  # remembered beats the default D proposal
    assert _keys(mapping_for(analysis, {})) == PB_D


def test_remembered_mapping_reports_functions_that_are_gone():
    analysis = Analysis(read(SYNTHETIC_PB))
    remembered = MethodMapping(analysis.run.metadata.method, "Pb", {"206Pb/204Pb": {"function": "206/204 F-D"}})
    mapping = remembered.apply(analysis)
    assert "206Pb/204Pb" not in mapping.ratios and not mapping.complete
    assert any(i.kind == "missing" and "206/204 F-D" in i.message for i in mapping.issues)
    assert mapping_for(analysis, {remembered.method: remembered}).complete  # falls back to a proposal
    with pytest.raises(MappingError):
        MethodMapping.from_dict({"method": "m", "element": "Pb", "ratios": {"238U/235U": {"function": "x"}}})


def test_synthetic_2535_maps_202_205():
    mapping = propose_mapping(Analysis(read(SYNTHETIC_PB)))
    assert mapping.ratios["202Pb/205Pb"].key == "202/205 D"
    assert mapping.function_keys[-1] == "202/205 D"


# --------------------------------------------- rule proposals use the mapping
def test_rule_proposals_default_to_mapped_functions_when_a_mapping_is_given():
    analysis = Analysis(read(B998))
    mapping = propose_mapping(analysis)
    proposal = analysis.propose_chauvenet(mapping=mapping)
    assert list(proposal.keys) == list(PB_D.values())
    assert list(analysis.propose_k_sigma(mapping=mapping).keys) == list(PB_D.values())
    assert list(analysis.propose_chauvenet().keys) == analysis.ratio_keys  # no mapping: every ratio, as before
    assert len(analysis.ratio_keys) > len(PB_D)
    assert list(analysis.propose_chauvenet(["206/204 D"], mapping=mapping).keys) == ["206/204 D"]  # explicit keys win


def test_shorthand_functions_are_ratios_for_mapped_k_sigma():
    analysis = Analysis(read(TIMSDP_FILES["WH205 z4 Pb-654"]))
    mapping = propose_mapping(analysis)
    with_mapping = analysis.propose_k_sigma(mapping=mapping)
    as_ratio = analysis.propose_k_sigma(list(mapping.function_keys), log_ratios=True)
    assert set(with_mapping.keys) == set(mapping.function_keys)
    # Without the mapping, "other" functions are clipped on their linear values; with it, on ln r.
    assert with_mapping.params["log_ratios"] and as_ratio.keys == with_mapping.keys


def test_function_objects_are_not_mutated_by_mapping():
    run = read(B998)
    before = [replace(f) for f in run.functions]
    propose_mapping(Analysis(run))
    assert list(run.functions) == before and all(isinstance(f, Function) for f in run.functions)


def test_ratio_candidates_list_every_usable_function_per_ratio():
    from rawtims.mapping import ratio_candidates

    analysis = Analysis(read(B998))
    candidates = ratio_candidates(analysis)
    keys = [c.key for c in candidates["206Pb/207Pb"]]
    assert "206/207 D" in keys and "206/207 F" in keys
    assert all(not c.inverted for c in candidates["206Pb/207Pb"] if c.key in ("206/207 D", "206/207 F"))
    assert {c.collector for c in candidates["206Pb/205Pb"]} >= {"D", "F"}
    # U: only oxide-corrected functions (the derived columns here), never raw 270/267.
    u = ratio_candidates(Analysis(read(GHR1_U_XLS)))
    assert [c.key for c in u["238U/235U"]] == ["238/235oc"] and u["238U/235U"][0].source == "derived"
    with pytest.raises(MappingError):
        ratio_candidates(Analysis(read(B998)), "Th")
