"""Shared selection in the review UI, migration and comparison."""
import numpy as np
import pytest
from PySide6 import QtCore, QtWidgets
from reader_fixtures import B998
from test_review_window import app as review_app
from test_review_window import window as review_window

app = review_app


@pytest.fixture(params=["classic", "wall"])
def window(app, qt_settings_folder, request):
    yield from review_window.__wrapped__(app, qt_settings_folder, request)
from rawtims_gui.rules_panel import SHARED_SELECTION_TOOLTIP


def test_synch_locked_and_free_controls_still_work(window):
    window.open_paths([B998], synchronous=True)
    a = window.analysis
    assert window.synch_action.isChecked() and not window.synch_action.isEnabled()
    assert window.synch_action.toolTip() == SHARED_SELECTION_TOOLTIP
    assert window.rules_panel.synch_box.isChecked() and not window.rules_panel.synch_box.isEnabled()
    window.set_synch(False)
    assert a.settings.synced and not a.history
    window.set_plotted(['206/208 D'])
    window._set_focus_key('206/208 D')
    assert window.synch_action.isEnabled()
    window.set_synch(False)
    before = a.included.copy()
    window.request_toggle('206/208 D', [4])
    for key in a.group_keys:
        np.testing.assert_array_equal(a.included[:, a.index(key)], before[:, a.index(key)])
    assert not a.included[4, a.index('206/208 D')]
    window.set_synch(True)
    window.request_toggle('206/208 D', [6])
    assert all(not a.included[6, a.index(k)] for k in a.keys if k not in a.group_keys)
    assert a.group_consistent()


def test_hand_box_block_refresh_every_group_plot(window):
    window.open_paths([B998], synchronous=True)
    a = window.analysis
    window.set_synch(False)
    plot = window.plot_wall.plot('206/205 D')
    plot._on_click(plot.point_of(3), QtCore.Qt.KeyboardModifier.NoModifier)
    assert a.group_consistent()
    assert all(not p._effective[3] for p in window.plot_wall.plots)
    rect = QtCore.QRectF(QtCore.QPointF(10.6, -1e9), QtCore.QPointF(13.4, 1e9))
    rows = plot.rows_in(rect)
    plot._on_box(rect, QtCore.Qt.KeyboardModifier.NoModifier)
    assert rows
    for p in window.plot_wall.plots:
        assert not p._effective[rows].any()
    window.request_block_toggle(plot.key, 40)
    for p in window.plot_wall.plots:
        assert not p._effective[a.run.block == a.run.block[40]].any()
    assert len(a.history) == 3 and a.group_consistent()
    window.undo()
    window.undo()
    window.undo()
    assert a.included.all() and a.block_included.all()
    window.redo()
    assert all(not p._effective[3] for p in window.plot_wall.plots)


def test_rules_table_and_one_ratio_preview_match_engine_without_applying(window):
    window.open_paths([B998], synchronous=True)
    a, panel = window.analysis, window.rules_panel
    before = a.included.copy()
    p = window.preview_rule()
    assert panel.preview_table.rowCount() == len(a.group_keys)
    for row, key in enumerate(a.group_keys):
        assert panel.preview_table.item(row, 0).text() == key
        assert panel.preview_table.item(row, 1).text() == str(len(p.flagged[key]))
        assert panel.preview_table.item(row, 2).text() == '96→93'
    assert 'Union: 3' in panel.result_label.text()
    panel.function_combo.setCurrentIndex(panel.function_combo.findData('one'))
    assert window.current_proposal() is None and not panel.apply_button.isEnabled()
    panel.ratio_combo.setCurrentIndex(panel.ratio_combo.findData('208/205 D'))
    p = window.preview_rule()
    assert p.evaluation == 'one' and p.keys == ('208/205 D',)
    assert len(p.cycles) == 2 and len(p.flagged) == 6
    assert all(plot.preview_rows == frozenset(p.cycles) for plot in window.plot_wall.plots)
    assert not a.history
    np.testing.assert_array_equal(a.included, before)
    window.apply_preview()
    assert a.group_consistent() and a.stats('206/204 D').n_used == 94


def test_why_link_opens_plain_language_document_nonmodally(window):
    window.open_paths([B998], synchronous=True)
    window.why_link.linkActivated.emit('shared')
    dialogs = window.findChildren(QtWidgets.QDialog)
    assert len(dialogs) == 1 and not dialogs[0].isModal()
    text = dialogs[0].findChild(QtWidgets.QTextBrowser).toPlainText()
    assert 'All ratios mapped for export from one run use the same accepted cycles.' in text
    assert 'BSU B998' in text and '0.4468' in text
    dialogs[0].close()


def test_legacy_session_notice_union_button_and_export_block(window, tmp_path):
    from test_shared_mask import old_session
    path, original, _proposal = old_session(tmp_path)
    assert window.open_session(path, synchronous=True)
    a = window.analysis
    assert window.legacy_bar.isVisibleTo(window)
    text = window.legacy_notice.text()
    assert 'per-ratio selection (legacy)' in text
    for key, cycles in a.group_differences().items():
        assert f'{key}:' in text
        assert all(str(c) in text for c in cycles)
    assert not QtWidgets.QApplication.activeModalWidget()
    assert not window.export_panel.save_button.isEnabled()
    assert 'per-ratio selection (legacy)' in window.export_panel.problems.text()
    assert window.save_contract_csv(str(tmp_path / 'blocked.csv')) is None
    np.testing.assert_array_equal(a.included, original)
    n = len(a.history)
    window.legacy_union_button.click()
    assert len(a.history) == n + 1 and a.group_consistent()
    assert not window.legacy_bar.isVisibleTo(window) and window.export_panel.save_button.isEnabled()
    assert window.save_contract_csv(str(tmp_path / 'shared.csv'))
    window.undo()
    assert window.legacy_bar.isVisibleTo(window) and not window.export_panel.save_button.isEnabled()
    np.testing.assert_array_equal(a.included, original)
    window.redo()
    assert not window.legacy_bar.isVisibleTo(window) and a.group_consistent()


def test_comparison_view_is_read_only_and_never_changes_export_or_history(window):
    from datetime import UTC, datetime
    window.open_paths([B998], synchronous=True)
    a = window.analysis
    a.toggle_cycles([5], ['206/204 D'], False)
    window._after_edit()
    before, history = a.included.copy(), a.history
    row = window.workspace.fraction_row(window.current[0], datetime.now(UTC))
    window.export_panel.compare_legacy_button.click()
    from rawtims_gui.legacy_comparison import LegacyComparisonDialog
    dialog = window.findChild(LegacyComparisonDialog)
    assert dialog is not None and not dialog.isModal()
    assert dialog.clipboard_preview.isReadOnly()
    assert dialog.table.editTriggers() == QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers
    assert 'comparison only' in dialog.copy_button.text()
    for rule in (None, 'chauvenet', 'k_sigma'):
        dialog.rule_combo.setCurrentIndex(dialog.rule_combo.findData(rule))
        for index, result in enumerate(dialog.comparison.rows):
            assert float(dialog.table.item(index, 1).text()) == pytest.approx(result.stats.mean)
            assert result.stats.mode == 'arithmetic'
        dialog.copy_button.click()
        assert QtWidgets.QApplication.clipboard().text() == dialog.comparison.clipboard_text
        np.testing.assert_array_equal(a.included, before)
        assert a.history == history
        after = window.workspace.fraction_row(window.current[0], datetime.fromisoformat(row.values['Exported At']))
        assert after.values == row.values
    dialog.close()


def test_mapping_undo_redo_updates_plots_and_adopted_mask(window):
    window.open_paths([B998], synchronous=True)
    window.request_toggle('206/204 D', [5])
    original = window.analysis.included.copy()
    window.corrections_panel.choose('206Pb/207Pb', '206/207 F')
    assert '206/207 F' in window.plotted_keys()
    assert not window.analysis.included_for('206/207 F')[5]
    window.undo()
    assert '206/207 D' in window.plotted_keys() and '206/207 F' not in window.plotted_keys()
    np.testing.assert_array_equal(window.analysis.included, original)
    window.redo()
    assert '206/207 F' in window.plotted_keys() and window.analysis.group_consistent()
