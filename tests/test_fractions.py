"""Fraction rows from real fixtures against Tripoli's oracle, provenance, 2535 rule, inversion and refusals (SPEC F5, F15)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from oracle_reports import read_short_report
from rawtims.analysis import Analysis, AnalysisSettings
from rawtims.branding import RAW_APP_LABEL
from rawtims.contract import CONTRACT_ID, PB_REQUIRED_RATIOS, U_RATIOS, csv_text, ratio_pairs, rho_column
from rawtims.fractions import Fraction, FractionError, SessionInfo, filter_rule_text, fraction_row, pair_analyses
from rawtims.mapping import MethodMapping, propose_mapping
from reader_fixtures import B998, GHR1_PB_XLS, GHR1_U_XLS, SYNTHETIC_PB, SYNTHETIC_U, TIMSDP_FILES, TRIPOLI, read

SHORT = TRIPOLI / "oracle" / "shortReports" / "KU_IGL" / "IsolinxVersion2"
PB_FILE = TIMSDP_FILES["GHR1 230921 F08b-216"]
U_FILE = TIMSDP_FILES["GHR1 230921F03 U-239"]
EXPORTED_AT = datetime(2026, 11, 14, 9, 30, tzinfo=timezone(timedelta(hours=-6)))
TOLERANCE = 1e-9
# Oracle function name for each contract ratio of the KU GHR1 Pb run (same names in the file).
PB_ORACLE = {"206Pb/204Pb": "206/204", "206Pb/207Pb": "206/207", "206Pb/205Pb": "206/205", "207Pb/205Pb": "207/205", "204Pb/205Pb": "204/205", "208Pb/205Pb": "208/205"}
U_ORACLE = {"238U/235U": "238/235oc", "233U/235U": "233/235oc", "238U/233U": "238/233oc"}


def _rel(a: float, b: float) -> float:
    return abs(a - b) / abs(b)


def _oracle(name: str) -> dict[str, tuple[float, float]]:
    return {fn: (mean, pct) for fn, mean, pct in read_short_report(SHORT / name)}


def ghr1_fraction(settings_u: AnalysisSettings | None = None, *, settings_pb: AnalysisSettings | None = None, **fields) -> Fraction:
    """KU GHR1: the Pb run F08b-216 and the U run U-239 are the same sample, exported as one fraction."""
    return Fraction("GHR1", pb=Analysis(read(PB_FILE), settings_pb), u=Analysis(read(U_FILE), settings_u), **fields)


def test_ku_ghr1_pb_matches_the_tripoli_short_report():
    row = fraction_row(ghr1_fraction(AnalysisSettings(stat_mode="geometric"), settings_pb=AnalysisSettings(stat_mode="geometric")), EXPORTED_AT)
    oracle = _oracle("Oracle-GHR1 230921 F08b-216.txt")
    for ratio, name in PB_ORACLE.items():
        mean, pct = oracle[name]
        assert _rel(row.mean(ratio), mean) <= TOLERANCE, ratio
        assert _rel(row.se_pct(ratio), pct) <= TOLERANCE, ratio
    assert row.values["Pb Cycles Used"] == row.values["Pb Cycles Total"] == 99


def test_ku_ghr1_u_oxide_plumbing_matches_tripoli_with_its_formula():
    row = fraction_row(ghr1_fraction(AnalysisSettings(stat_mode="geometric", oxide_formula="tripoli_java_00dc941", r18=0.00205)), EXPORTED_AT)
    oracle = _oracle("Oracle-GHR1 230921F03 U-239.txt")
    for ratio, name in U_ORACLE.items():
        mean, pct = oracle[name]
        assert _rel(row.mean(ratio), mean) <= TOLERANCE, ratio
        assert _rel(row.se_pct(ratio), pct) <= TOLERANCE, ratio
    assert row.values["U Oxide 18O/16O"] == 0.00205 and row.values["U Cycles Used"] == 770


def test_ku_ghr1_u_default_isobar_233_18O_values():
    row = fraction_row(ghr1_fraction(AnalysisSettings(stat_mode="geometric"), settings_pb=AnalysisSettings(stat_mode="geometric")), EXPORTED_AT)
    oracle = _oracle("Oracle-GHR1 230921F03 U-239.txt")
    assert _rel(row.mean("233U/235U"), oracle["233/235oc"][0]) <= TOLERANCE  # the same formula in both forms
    assert row.mean("238U/235U") == pytest.approx(2.43849557, rel=1e-8)
    assert _rel(row.mean("238U/235U"), oracle["238/235oc"][0]) > 5e-3  # the documented 0.6 % difference
    # With the ET_Redux form the 18O factors cancel in 238/233: it equals the measured 270/265 = (270/267)/(265/267).
    analysis = Analysis(read(U_FILE))
    ratio = analysis.column("270/267") / analysis.column("265/267")
    assert row.mean("238U/233U") == pytest.approx(float(np.exp(np.log(ratio).mean())), rel=1e-13)
    assert row.values["U Oxide 18O/16O"] == 0.00205
    assert "isobar_233_18O formula" in row.values["Notes"]


@pytest.mark.parametrize("mode", ["arithmetic", "geometric"])
def test_writer_records_each_blocks_mean_statistic(mode):
    fraction = ghr1_fraction(AnalysisSettings(stat_mode=mode), settings_pb=AnalysisSettings(stat_mode=mode))
    row = fraction_row(fraction, EXPORTED_AT)
    assert row.values["Pb Mean Statistic"] == row.values["U Mean Statistic"] == mode
    assert f"{mode} statistics" not in row.get("Notes", "")
    fraction.u = None
    pb_only = fraction_row(fraction, EXPORTED_AT)
    assert pb_only.get("Pb Mean Statistic") == mode and "U Mean Statistic" not in pb_only.values


@pytest.mark.parametrize("mode", ["arithmetic", "geometric"])
def test_correlations_are_bounded_and_equal_a_direct_numpy_computation(mode):
    fraction = ghr1_fraction(AnalysisSettings(stat_mode=mode), settings_pb=AnalysisSettings(stat_mode=mode))
    fraction.pb.toggle_cycles([3, 4], ["206/204"], include=False)  # the edit expands to the correlated group
    row = fraction_row(fraction, EXPORTED_AT)
    for element, analysis, oracle in (("Pb", fraction.pb, PB_ORACLE), ("U", fraction.u, U_ORACLE)):
        pairs = ratio_pairs(element)
        expected_pairs = [(a, b) for a, b in pairs if a in oracle and b in oracle]
        for a, b in expected_pairs:
            r = row.rho(a, b)
            assert -1.0 <= r <= 1.0
            ka, kb = oracle[a], oracle[b]
            both = analysis.included_for(ka) & analysis.included_for(kb)
            transform = np.log if mode == "geometric" else np.asarray
            direct = np.corrcoef(transform(analysis.column(ka)[both]), transform(analysis.column(kb)[both]))[0, 1]
            assert r == pytest.approx(direct, abs=1e-12), (a, b)
    assert rho_column("206Pb/204Pb", "202Pb/205Pb") not in row.values  # 202 not measured
    assert len([k for k in row.values if k.startswith("rho ")]) == 15 + 3
    assert row.values["Pb Cycles Used"] == 97


def test_provenance_columns():
    fraction = ghr1_fraction(sample="GHR1", spike_type=535, spike="ET535", collector="D", notes="user note")
    row = fraction_row(fraction, EXPORTED_AT, SessionInfo("ghr1.rawtims", "0" * 64))
    v = row.values
    assert v["Contract"] == CONTRACT_ID and v["Fraction ID"] == "GHR1" and v["Spike Type"] == "535"
    assert v["Pb Raw File"] == "GHR1 230921 F08b-216.TIMSDP" and v["Pb Raw SHA256"] == read(PB_FILE).raw.sha256
    assert v["U Method"] == "UO2 Static 265-7-8-0 Faraday 272 Daly 18s BL 22s OP FewPlot.TIMSAM"
    assert v["Filter Rule"] == "Pb: none | U: none"
    assert v["Raw App"] == RAW_APP_LABEL and v["Exported At"] == "2026-11-14T09:30:00-06:00"
    assert v["Raw App Session"] == "ghr1.rawtims" and v["Raw App Session SHA256"] == "0" * 64
    # No time zone in the files: the run starts stay empty and the local times go to Notes.
    assert "Pb Run Start" not in v and "U Run Start" not in v
    assert v["Notes"].startswith("user note; ") and "Pb: run start 2023-09-26T12:53:31 instrument local time" in v["Notes"]
    assert not row.problems()


def test_run_start_with_a_known_time_zone():
    row = fraction_row(ghr1_fraction(timezone="America/Chicago"), EXPORTED_AT)
    assert row.values["Pb Run Start"] == "2023-09-26T12:53:31-05:00"
    assert row.values["U Run Start"] == "2023-10-05T12:44:38-05:00"
    assert "instrument local time" not in (row.values.get("Notes") or "")
    with pytest.raises(FractionError, match="time zone"):
        ghr1_fraction(timezone="Boise")


def test_filter_rule_text_from_history():
    analysis = Analysis(read(U_FILE))
    assert filter_rule_text(analysis) == "none"
    proposal = analysis.propose_chauvenet(mapping=propose_mapping(analysis))
    analysis.apply_rule(proposal)
    n = len(proposal.cycles)
    assert n > 0 and filter_rule_text(analysis) == f"Chauvenet P=0.5 n>=20 (synced, {n} cycles)"
    free = [row for row in range(analysis.n_cycles) if row not in proposal.cycles][:3]
    analysis.toggle_cycles(free, include=False)
    analysis.toggle_cycles(free[:1], include=True)
    analysis.toggle_block(2, include=False)
    assert filter_rule_text(analysis) == f"Chauvenet P=0.5 n>=20 (synced, {n} cycles); 2 manual cycles; block 2 excluded"
    analysis.undo()
    assert filter_rule_text(analysis) == f"Chauvenet P=0.5 n>=20 (synced, {n} cycles); 2 manual cycles"
    analysis.reset()
    assert filter_rule_text(analysis) == "none"
    analysis.apply_rule(analysis.propose_k_sigma(["270/267"], synced=False, scope="block"))
    assert filter_rule_text(analysis).startswith("k-sigma k=2 max 10 passes (block scope, synced, ")


def test_rejection_changes_the_exported_numbers_and_counts():
    fraction = Fraction("GHR1 U", u=Analysis(read(U_FILE)))
    before = fraction_row(fraction, EXPORTED_AT)
    proposal = fraction.u.propose_chauvenet(mapping=fraction.mapping("U"))
    fraction.u.apply_rule(proposal)
    after = fraction_row(fraction, EXPORTED_AT)
    assert after.values["U Cycles Used"] == 770 - len(proposal.cycles)
    assert after.mean("238U/235U") != before.mean("238U/235U")
    assert after.values["Filter Rule"].startswith("Chauvenet P=0.5 n>=20 (synced, ")
    assert not any(k.startswith(("206Pb", "Pb ")) for k in after.values)


def test_b998_daly_by_default_fills_collector_from_the_functions():
    row = fraction_row(Fraction("13223M02 iz1", pb=Analysis(read(B998))), EXPORTED_AT)
    assert row.values["Collector"] == "D" and "Collector D taken from the mapped functions" in row.values["Notes"]
    assert row.values["Pb Cycles Total"] == 96 and row.values["Pb Method"] == "Pb 205 Daly 150 ratios"
    analysis = Analysis(read(B998))
    for ratio, key in zip(PB_REQUIRED_RATIOS, ("206/204 D", "206/207 D", "206/205 D", "207/205 D", "204/205 D", "208/205 D")):
        assert row.mean(ratio) == analysis.stats(key).mean and row.se_pct(ratio) == analysis.stats(key).se_pct
    f_row = fraction_row(Fraction("13223M02 iz1", pb=Analysis(read(B998)), collector="F"), EXPORTED_AT)
    assert f_row.mean("206Pb/204Pb") == analysis.stats("206/204 F-D").mean and f_row.values["Collector"] == "F"


def test_synthetic_et2535_row_carries_202_205():
    """Behaviour on a synthetic ET2535 file (not a BSU-agreement test): 202Pb/205Pb is exported and required."""
    fraction = Fraction("SYN z1", pb=Analysis(read(SYNTHETIC_PB)), spike_type="2535", spike="ET2535")
    row = fraction_row(fraction, EXPORTED_AT)
    assert row.mean("202Pb/205Pb") == fraction.pb.stats("202/205 D").mean
    assert row.rho("206Pb/205Pb", "202Pb/205Pb") is not None
    assert len([k for k in row.values if k.startswith("rho ")]) == 21
    csv_text([row])  # a valid contract row


def test_2535_without_202_is_refused():
    with pytest.raises(FractionError, match=r"Spike Type 2535 needs measured 202Pb/205Pb"):
        fraction_row(Fraction("iz1", pb=Analysis(read(B998)), spike_type="2535"), EXPORTED_AT)
    analysis = Analysis(read(SYNTHETIC_PB))
    without = propose_mapping(analysis)
    without.ratios.pop("202Pb/205Pb")
    with pytest.raises(FractionError, match="202Pb/205Pb"):
        fraction_row(Fraction("SYN z1", pb=analysis, spike_type="2535", pb_mapping=without), EXPORTED_AT)
    # Spike Type 535 does not need it.
    assert fraction_row(Fraction("SYN z1", pb=analysis, spike_type="535", pb_mapping=without), EXPORTED_AT).mean("202Pb/205Pb") is None


def test_remembered_mapping_checks_masses_and_incomplete_runs_are_refused():
    analysis = Analysis(read(TIMSDP_FILES["NBS981 210325b-392"]), AnalysisSettings(stat_mode="geometric"))
    keys = {"206Pb/204Pb": ("204/206", True), "206Pb/207Pb": ("207/206", True), "206Pb/205Pb": ("205/206", True),
            "207Pb/205Pb": ("207/204", False), "204Pb/205Pb": ("204/208", False), "208Pb/205Pb": ("208/204", False)}
    # Not a physical mapping (NBS981 has no 205 spike): it only exercises inversion through a full row.
    remembered = MethodMapping("m", "Pb", {r: {"function": k, "inverted": inv} for r, (k, inv) in keys.items()})
    applied = remembered.apply(analysis)
    assert set(applied.ratios) == {"206Pb/204Pb", "206Pb/207Pb", "206Pb/205Pb"}  # the others have wrong masses
    assert {i.ratio for i in applied.issues if i.kind == "refused"} == {"207Pb/205Pb", "204Pb/205Pb", "208Pb/205Pb"}
    mapping = propose_mapping(Analysis(read(TIMSDP_FILES["NBS981 230024a-145"])))
    assert not mapping.complete
    with pytest.raises(FractionError, match="207Pb/205Pb: no function with these masses"):
        fraction_row(Fraction("NBS", pb=Analysis(read(TIMSDP_FILES["NBS981 230024a-145"]))), EXPORTED_AT)


def test_inverted_mapping_through_fraction_row(tmp_path):
    # Build a complete Pb mapping for B998 where 206/204 comes from the inverted raw 204/206 column.
    analysis = Analysis(read(B998), AnalysisSettings(stat_mode="geometric"))
    base = propose_mapping(analysis).to_method_mapping().to_dict()
    base["ratios"]["206Pb/204Pb"] = {"function": "Pb204+Hg204/Pb206+At206 raw", "inverted": True}
    mapping = MethodMapping.from_dict(base).apply(analysis)
    row = fraction_row(Fraction("iz1", pb=analysis, pb_mapping=mapping), EXPORTED_AT)
    direct = analysis.stats("Pb204+Hg204/Pb206+At206 raw")
    assert row.mean("206Pb/204Pb") * direct.mean == pytest.approx(1.0, abs=1e-14)
    assert row.se_pct("206Pb/204Pb") == pytest.approx(direct.se_pct, rel=1e-12)
    assert "206Pb/204Pb = 1/(Pb204+Hg204/Pb206+At206 raw), geometric mean (exact)" in row.values["Notes"]
    analysis.set_setting("stat_mode", "arithmetic")
    with pytest.raises(FractionError, match="arithmetic"):
        fraction_row(Fraction("iz1", pb=analysis, pb_mapping=mapping), EXPORTED_AT)


def test_u_pass_through_and_missing_r18():
    row = fraction_row(Fraction("SYN U", u=Analysis(read(SYNTHETIC_U))), EXPORTED_AT)
    assert row.values["U Oxide 18O/16O"] == 0.00206 and row.values["U Oxide Formula"] == "instrument"
    assert "already carries oxide-corrected columns; passed through, not recomputed" in row.values["Notes"]
    assert set(U_RATIOS) <= {k.removesuffix(" Mean") for k in row.values}


def test_refusals():
    with pytest.raises(FractionError, match="neither a Pb nor a U run"):
        fraction_row(Fraction("empty"), EXPORTED_AT)
    with pytest.raises(FractionError, match="timezone-aware"):
        fraction_row(ghr1_fraction(), datetime(2026, 11, 14, 9, 30))
    with pytest.raises(FractionError, match="U slot holds a Pb run"):
        Fraction("x", u=Analysis(read(B998)))
    with pytest.raises(FractionError, match="Spike Type"):
        Fraction("x", spike_type="205")
    with pytest.raises(FractionError, match="Collector"):
        Fraction("x", collector="Daly")


def test_pairing_by_suggested_fraction_id():
    analyses = [Analysis(read(path)) for path in (GHR1_PB_XLS, GHR1_U_XLS, B998, PB_FILE)]
    pairing = pair_analyses(analyses)
    ids = {f.fraction_id: f for f in pairing.fractions}
    assert ids["GHR1 20200827-11"].pb is analyses[0] and ids["GHR1 20200827-11"].u is analyses[1]
    assert ids["13223M02 iz1"].pb is analyses[2] and ids["13223M02 iz1"].u is None
    assert pairing.unplaced == []
    again = pair_analyses([analyses[0], Analysis(read(GHR1_PB_XLS))])
    assert len(again.fractions) == 1 and "already has a Pb run" in again.unplaced[0][1]


def test_derived_oxide_correction_records_its_formula_and_r18():
    row = fraction_row(ghr1_fraction(), EXPORTED_AT)
    assert row.values["U Oxide Formula"] == "isobar_233_18O"
    assert row.values["U Oxide 18O/16O"] == 0.00205
    assert not row.problems()
