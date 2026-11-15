"""GUI step B: rules with preview, corrections, mapping editor, export (SPEC section 5, F9-F17; SPEC section 0, decision 3)."""

from __future__ import annotations

import csv
from datetime import datetime

import numpy as np
import pytest

QtCore = pytest.importorskip("PySide6.QtCore")
from PySide6 import QtWidgets  # noqa: E402

from reader_fixtures import B998, GHR1_PB_XLS, GHR1_U_XLS, SYNTHETIC_U, TIMSDP_FILES  # noqa: E402
from rawtims.contract import read_csv  # noqa: E402
from rawtims.exports import clipboard_text  # noqa: E402
from rawtims_gui import main as gui_main  # noqa: E402
from rawtims_gui.corrections_panel import PASS_THROUGH_TEXT  # noqa: E402
from rawtims_gui.studio.theme import build_application  # noqa: E402
from rawtims_gui.workspace import Workspace  # noqa: E402

B998_MAPPED = ["206/204 D", "206/207 D", "206/205 D", "207/205 D", "204/205 D", "208/205 D"]
GHR1_U239 = TIMSDP_FILES["GHR1 230921F03 U-239"]
GHR1_PB216 = TIMSDP_FILES["GHR1 230921 F08b-216"]


@pytest.fixture
def app():
    return build_application(["test"], theme_mode="light")


def _make_window():
    window = gui_main.MainWindow(restore_geometry=False)
    window.resize(gui_main.DEFAULT_SIZE)
    window.show()
    return window


def _close(window) -> None:
    import shiboken6

    if not shiboken6.isValid(window):
        return  # closed by the test already
    window.close()
    window.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


@pytest.fixture
def window(app, qt_settings_folder):
    gui_main.app_settings().clear()
    window = _make_window()
    yield window
    _close(window)
    gui_main.app_settings().clear()


def _open(window, *paths):
    window.open_paths([str(p) for p in paths], synchronous=True)
    QtWidgets.QApplication.processEvents()
    return window


def _row(window, fraction=None):
    fraction = fraction or window.current[0]
    return window.workspace.fraction_row(fraction, datetime.now().astimezone())


# ------------------------------------------------------------------ rules
def test_preview_does_not_change_the_mask_and_apply_is_the_proposal(window):
    _open(window, B998)
    analysis = window.analysis
    before = analysis.effective.copy()
    proposal = window.preview_rule()
    assert proposal is not None and proposal.rule == "chauvenet" and proposal.synced
    assert list(proposal.keys) == B998_MAPPED  # default: the contract-mapped functions
    assert proposal.cycles  # B998 has outliers Chauvenet flags
    assert np.array_equal(analysis.effective, before) and analysis.history == []
    # Shown on the plots, in the table and in the panel, without touching the mask.
    plot = window.plot_wall.plot("206/204 D")
    assert plot.preview_rows == frozenset(proposal.cycles)
    assert window.cycle_table.cycle_model.preview["206/204 D"] == frozenset(proposal.cycles)
    assert window.rules_panel.apply_button.isEnabled()
    assert window.rules_panel.result_list.count() == len(B998_MAPPED)
    assert f"Would reject {len(proposal.cycles)} cycle" in window.rules_panel.result_label.text()

    op = window.apply_preview()
    assert op["op"] == "apply_rule" and op["rejected"] == proposal.to_dict()["rejected"]
    assert analysis.history[-1]["rule"] == "chauvenet"
    excluded = {int(row) for row, _key in op["changed"]}
    assert excluded == set(proposal.cycles)
    assert all(not analysis.included[row, :].any() for row in proposal.cycles)  # synced: every function
    assert window.preview is None and plot.preview_rows == frozenset()
    assert "Rule: Chauvenet" in window.rules_panel.history_texts()[-1]
    assert "◀ now" in window.rules_panel.history_texts()[-1]
    # The rule is in the exported provenance.
    assert _row(window).values["Filter Rule"].startswith("Chauvenet P=0.5 n>=20 (synced")

    window.undo_action.trigger()
    assert np.array_equal(analysis.effective, before) and analysis.history == []
    assert window.rules_panel.history_texts() == ["0  Opened: every valid cycle included   ◀ now"]


def test_rule_parameters_are_undoable_settings_and_edits_discard_the_preview(window):
    _open(window, B998)
    analysis = window.analysis
    panel = window.rules_panel
    panel.set_rule("k_sigma")
    panel.k.setValue(3.0)
    panel.scope_combo.setCurrentIndex(panel.scope_combo.findData("block"))
    panel.function_combo.setCurrentIndex(panel.function_combo.findData("plotted"))
    proposal = window.preview_rule()
    assert proposal.rule == "k_sigma" and proposal.params["k"] == 3.0 and proposal.scope == "block"
    assert analysis.history[-1] == {"op": "set_setting", "name": "k_sigma", "old": 2.0, "new": 3.0}
    assert window.preview is not None
    panel.k.setValue(2.5)  # a parameter edit drops the preview: what is applied is always what is shown
    assert window.preview is None and not panel.apply_button.isEnabled()
    window.preview_rule()
    plot = window.plot_wall.plot("206/204 D")
    plot._on_click(plot.point_of(50), QtCore.Qt.KeyboardModifier.NoModifier)  # any edit drops it too
    assert window.preview is None
    window.preview_rule()
    window.discard_preview()
    assert window.preview is None and window.apply_preview() is None


# ------------------------------------------------------------ corrections
def test_oxide_formula_switch_changes_u_values_and_the_exported_formula(window):
    _open(window, GHR1_U239)
    window.set_workflow_step("Correct")
    assert window.inspector_tabs.currentIndex() == gui_main.INSPECTOR_TABS.index("Corrections")
    panel = window.corrections_panel
    analysis = window.analysis
    assert "Computed here: isobar_233_18O" in panel.oxide_status.text()
    assert not panel.formula_warning.isVisibleTo(panel)
    default = _row(window)
    assert default.values["U Oxide Formula"] == "isobar_233_18O" and default.values["U Oxide 18O/16O"] == 0.00205
    panel.formula.setCurrentIndex(panel.formula.findData("tripoli_java_00dc941"))
    assert analysis.settings.oxide_formula == "tripoli_java_00dc941"
    assert analysis.history[-1]["name"] == "oxide_formula"
    assert panel.formula_warning.isVisibleTo(panel)
    assert panel.formula_description.text() == "Comparison only: current Tripoli Java form"
    comparison = _row(window)
    assert comparison.values["U Oxide Formula"] == "tripoli_java_00dc941"
    # Tripoli's form uses R270/267 in the 238/235 denominator: higher here, where 238/235 > 233/235 (oxide-correction.md).
    assert comparison.mean("238U/235U") > default.mean("238U/235U")
    assert comparison.mean("233U/235U") == default.mean("233U/235U")
    window.undo_action.trigger()
    assert analysis.settings.oxide_formula == "isobar_233_18O" and _row(window).mean("238U/235U") == default.mean("238U/235U")
    assert panel.formula.currentData() == "isobar_233_18O"


def test_r18_bsu_button_sets_0_00206_through_the_history(window):
    _open(window, GHR1_U239)
    panel = window.corrections_panel
    before = _row(window).mean("238U/235U")
    panel.bsu_button.click()
    assert window.analysis.settings.r18 == 0.00206 and panel.r18.value() == pytest.approx(0.00206)
    assert window.analysis.history[-1] == {"op": "set_setting", "name": "r18", "old": 0.00205, "new": 0.00206}
    row = _row(window)
    assert row.values["U Oxide 18O/16O"] == 0.00206 and row.mean("238U/235U") != before
    panel.r18.setValue(0.0021)
    panel.r18.editingFinished.emit()
    assert window.analysis.settings.r18 == 0.0021
    panel.default_r18_button.click()
    assert window.analysis.settings.r18 == 0.00205


def test_pass_through_is_shown_for_the_synthetic_bsu_u_file_behaviour_only(window):
    # Behaviour test on a SYNTHETIC file: it says nothing about BSU's real numbers (SPEC section 0, decision 4).
    _open(window, SYNTHETIC_U)
    panel = window.corrections_panel
    text = panel.oxide_status.text()
    assert text.startswith("Pass-through") and PASS_THROUGH_TEXT in text and "18O/16O = 0.00206" in text
    assert not panel.oxide_controls.isEnabled()
    row = _row(window)
    assert row.values["U Oxide Formula"] == "instrument" and row.values["U Oxide 18O/16O"] == 0.00206


def test_mapping_editor_selection_changes_the_exported_function(window):
    _open(window, B998)
    window.set_workflow_step("Correct")
    panel = window.corrections_panel
    analysis = window.analysis
    assert panel.chosen()["206Pb/207Pb"] == ("206/207 D", False)
    assert _row(window).mean("206Pb/207Pb") == analysis.stats("206/207 D").mean
    panel.choose("206Pb/207Pb", "206/207 F")
    assert window.workspace.mapping_source(analysis) == "edited"
    assert window.mapping.ratios["206Pb/207Pb"].key == "206/207 F"
    assert _row(window).mean("206Pb/207Pb") == analysis.stats("206/207 F").mean
    assert "206/207 F" in [plot.key for plot in window.plot_wall.plots]
    assert panel.revert_button.isEnabled()
    # "(none)" leaves a required ratio unmapped: shown inline and the fraction needs attention.
    panel.choose("206Pb/204Pb", None)
    assert "no function chosen" in panel.issue_labels["206Pb/204Pb"].text()
    assert window.fraction_list.states() == [("13223M02 iz1", "attention")]
    panel.revert_button.click()
    assert window.mapping.ratios["206Pb/207Pb"].key == "206/207 D" and window.workspace.mapping_source(analysis) == "proposed"


def test_collector_steers_the_pb_proposal(window):
    _open(window, B998)
    panel = window.corrections_panel
    assert panel.collector_row.isVisibleTo(panel)
    panel.collector.setCurrentIndex(panel.collector.findData("F"))
    assert window.current[0].collector == "F"
    assert window.mapping.ratios["206Pb/207Pb"].key == "206/207 F"
    assert _row(window).values["Collector"] == "F"


def test_remembered_method_mapping_is_applied_next_time_and_can_be_forgotten(window):
    _open(window, B998)
    window.corrections_panel.choose("206Pb/207Pb", "206/207 F")
    remembered = window.remember_mapping()
    method = window.analysis.run.metadata.method
    assert remembered.method == method and remembered.ratios["206Pb/207Pb"]["function"] == "206/207 F"
    assert method in gui_main.load_remembered(gui_main.app_settings())
    _close(window)

    second = _make_window()
    try:
        _open(second, B998)
        assert second.workspace.mapping_source(second.analysis) == "remembered"
        assert second.mapping.ratios["206Pb/207Pb"].key == "206/207 F"
        assert "Remembered for method" in second.corrections_panel.mapping_source.text()
        assert second.corrections_panel.forget_button.isEnabled()
        assert second.forget_mapping()
        assert second.workspace.mapping_source(second.analysis) == "proposed"
        assert second.mapping.ratios["206Pb/207Pb"].key == "206/207 D"
        assert gui_main.app_settings().value(gui_main.REMEMBERED_KEY) is None
    finally:
        _close(second)


# ----------------------------------------------------------------- export
def test_export_form_values_land_in_the_contract_row(window):
    _open(window, GHR1_PB_XLS, GHR1_U_XLS)
    window.set_workflow_step("Export")
    assert window.inspector_tabs.currentIndex() == gui_main.INSPECTOR_TABS.index("Export")
    panel = window.export_panel
    assert panel.fraction_id.isReadOnly() and panel.fraction_id.text() == "GHR1 20200827-11"
    for attribute, text in (("sample", "GHR1"), ("beaker", "K1"), ("source_grain", "g12"), ("source_spot", "s3"),
                            ("source_mount", "M7"), ("aliquot", "A"), ("sample_weight_mg", "0.0021"),
                            ("spike_weight_g", "0.0125"), ("spike_type", "535"), ("spike", "ET535"),
                            ("collector", "D"), ("timezone", "America/Chicago")):
        panel.set_field(attribute, text)
    values = _row(window).values
    assert (values["Sample"], values["Beaker"], values["Source Grain"], values["Source Spot"]) == ("GHR1", "K1", "g12", "s3")
    assert (values["Source Mount"], values["Aliquot"], values["Spike Type"], values["Spike"], values["Collector"]) == ("M7", "A", "535", "ET535", "D")
    assert values["Sample Weight (mg)"] == 0.0021 and values["Spike Weight (g)"] == 0.0125
    assert values["Pb Run Start"].endswith(("-05:00", "-06:00")) and "Raw App Session" not in values
    assert panel.row_cells()["Beaker"] == "K1"
    assert window.fraction_list.states() == [("GHR1 20200827-11", "ready")]
    # Bad input is refused with a message and changes nothing.
    panel.set_field("sample_weight_mg", "abc")
    assert window.current[0].sample_weight_mg == 0.0021 and "not a number" in panel.form_message.text()
    panel.set_field("timezone", "Mars/Olympus")
    assert window.current[0].timezone == "America/Chicago" and "IANA" in panel.form_message.text()


def test_problems_are_listed_for_a_2535_fraction_without_202_205(window):
    _open(window, B998)
    window.export_panel.set_field("spike_type", "2535")
    assert window.fraction_list.states() == [("13223M02 iz1", "attention")]
    problems = window.export_panel.problems.text()
    assert "13223M02 iz1" in problems and "202Pb/205Pb" in problems and "2535" in problems
    assert window.export_panel.row_cells()["cannot export"].startswith("fraction '13223M02 iz1': Spike Type 2535")
    assert not window.export_panel.save_button.isEnabled()
    assert window.save_contract_csv("unused.csv") is None


def test_save_contract_csv_reads_back_equal(window, tmp_path):
    _open(window, GHR1_PB_XLS, GHR1_U_XLS, B998)
    window.select_run(window.workspace.find("13223M02 iz1"), "Pb")
    window.preview_rule()
    window.apply_preview()
    path = window.save_contract_csv(str(tmp_path / "2026-11-14.fractions.csv"))
    assert path is not None and path.name == "2026-11-14.fractions.csv"
    back = read_csv(path)
    exported_at = datetime.fromisoformat(back[0].values["Exported At"])
    expected = [window.workspace.fraction_row(f, exported_at) for f in window.workspace.fractions]
    assert [row.values for row in back] == [row.values for row in expected]
    assert [row.fraction_id for row in back] == ["GHR1 20200827-11", "13223M02 iz1"]
    assert back[1].values["Filter Rule"].startswith("Chauvenet")
    assert not list(tmp_path.glob(".*.tmp"))  # atomic write leaves no temporary file


def test_clipboard_text_matches_the_engine(window):
    _open(window, GHR1_PB_XLS, GHR1_U_XLS)
    text = window.copy_clipboard()
    fraction = window.current[0]
    assert text == clipboard_text(fraction) and "  (Mean, %StdErr)" in text
    assert QtWidgets.QApplication.clipboard().text() == text
    assert text.count("(Mean, %StdErr)") == 9
    window.export_panel.separator.setCurrentIndex(1)
    assert window.copy_clipboard() == clipboard_text(fraction, separator=" ")


def test_save_cycles_csv_writes_the_current_run(window, tmp_path):
    _open(window, B998)
    path = window.save_cycles_csv(str(tmp_path / "b998.cycles.csv"))
    with path.open(newline="") as stream:
        rows = list(csv.reader(stream))
    assert rows[0][:3] == ["Block", "Cycle", "Time (s)"] and len(rows) == 97


def test_rail_steps_switch_the_inspector_and_follow_it(window):
    _open(window, B998)
    window.set_workflow_step("Export")
    assert window.inspector_tabs.currentIndex() == gui_main.INSPECTOR_TABS.index("Export")
    window.inspector_tabs.setCurrentIndex(gui_main.INSPECTOR_TABS.index("Rules"))
    assert gui_main.WORKFLOW_STEPS[window.workflow_step_list.currentRow()] == "Review"
    window.inspector_tabs.setCurrentIndex(gui_main.INSPECTOR_TABS.index("Corrections"))
    assert gui_main.WORKFLOW_STEPS[window.workflow_step_list.currentRow()] == "Correct"
    assert window.fraction_list.states() == [("13223M02 iz1", "incomplete")]


@pytest.mark.parametrize("size", [(1280, 800), (1440, 900), (1024, 640)])
def test_inspector_pages_never_scroll_sideways(window, size):
    _open(window, GHR1_PB_XLS, GHR1_U_XLS)
    window.resize(*size)
    for index in range(window.inspector_tabs.count()):
        window.inspector_tabs.setCurrentIndex(index)
        for _ in range(3):
            QtWidgets.QApplication.processEvents()
        page = window.inspector_tabs.widget(index)
        for scroll in [page, *page.findChildren(QtWidgets.QScrollArea)]:
            if isinstance(scroll, QtWidgets.QScrollArea) and scroll.widget() is not None and scroll.isVisible():
                assert scroll.widget().width() <= scroll.viewport().width(), (index, size)


# ------------------------------------------------------------------ verify
def test_verify_writes_the_expected_csv(tmp_path):
    from test_main_window import _run_cli

    output = tmp_path / "verify.fractions.csv"
    result = _run_cli("--verify", str(GHR1_PB216), str(GHR1_U239), "--verification-output", str(output), tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "Wrote 2 fraction rows" in result.stdout
    rows = read_csv(output)
    workspace = Workspace()
    workspace.open([GHR1_PB216, GHR1_U239])
    expected, left_out = workspace.export_rows(datetime.fromisoformat(rows[0].values["Exported At"]))
    assert not left_out
    assert [row.values for row in rows] == [row.values for row in expected]
    assert rows[1].values["U Oxide Formula"] == "isobar_233_18O" and rows[0].values["Filter Rule"] == "none"
