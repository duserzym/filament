"""Report source semantics, preference isolation and P2 desktop acceptance."""
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets
from reader_fixtures import SYNTHETIC_U
from test_p2_exchange import synthetic

from rawtims.contract import csv_text
from rawtims.exports import clipboard_text, cycles_csv_text
from rawtims.reports import (
    DEFAULT_TEMPLATE,
    ReportColumn,
    ReportTemplate,
    TemplateOne,
    report_csv,
    report_table,
)
from rawtims.session import load_session, save_session
from rawtims_gui import main as gui
from rawtims_gui.exchange import InspectionDialog, export_tripoli, save_chosen
from rawtims_gui.recent_inputs import recent, remember
from rawtims_gui.report_builder import PREFERENCES_KEY, ReportDialog, preferences
from rawtims_gui.studio.theme import build_application
from rawtims_gui.workspace import Workspace


@pytest.fixture
def window(monkeypatch,tmp_path):
    build_application(['p2-test'],theme_mode='light')
    settings = QtCore.QSettings(str(tmp_path/'p2.ini'),QtCore.QSettings.Format.IniFormat)
    monkeypatch.setattr(gui,'app_settings',lambda: settings)
    w = gui.MainWindow(restore_geometry=False)
    w.workspace = Workspace()
    w.workspace.open([SYNTHETIC_U])
    w.show()
    w.select_run(w.workspace.fractions[0],'U')
    QtWidgets.QApplication.processEvents()
    yield w
    w.unsaved_prompt = lambda _: 'discard'
    w.close()
    w.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None,QtCore.QEvent.Type.DeferredDelete)


def test_report_columns_categories_order_and_geometric_units():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/reports/ReportCategory.java:29-63;
    Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/reports/ReportBuilderController.java:781-797.
    Filament's explicit category/field schema applies those presentation semantics.
    """
    template = ReportTemplate('SYNTHETIC custom',(ReportColumn('n_used','Counts'),ReportColumn('mean','Ratios'),ReportColumn('function','Identity')))
    a = synthetic()
    assert report_csv(a,template) == 'Counts,Ratios,Identity\nNumber included,Mean,Function\n3,3.0,206/204 D\n'
    a.set_setting('stat_mode','geometric')
    table = report_table(a)
    row = dict(zip([c.field for c in DEFAULT_TEMPLATE.columns],table[2]))
    assert row['se_abs'] == pytest.approx(a.stats(a.keys[0]).mean*a.stats(a.keys[0]).se_pct/100)
    assert row['statistic'] == 'geometric'


@pytest.mark.parametrize('data',[{}, {'version':2,'name':'SYNTHETIC','columns':[]},
                                {'version':1,'name':'','columns':[{'field':'mean','category':'A'}]},
                                {'version':1,'name':'SYNTHETIC','columns':[{'field':'r18','category':'A'}]},
                                {'version':1,'name':'SYNTHETIC','columns':[{'field':'mean','category':''}]},
                                {'version':1,'name':'SYNTHETIC','columns':[{'field':'mean','category':'A'}]*2}])
def test_report_schema_refuses_numeric_settings_and_invalid_templates(data):
    with pytest.raises(ValueError):
        ReportTemplate.from_dict(data)


def test_template_one_source_layout_bytes():
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:813-850;
    sessions/analysis/massSpectrometerModels/dataSourceProcessors/MassSpecExtractedData.java:182-188.
    Source explicitly uses intensity SD despite its header's SE label; preserve that quirk.
    """
    data = TemplateOne('SYNTHETIC','SYNTHETIC sample','SYNTHETIC method','SYNTHETIC time',
                       (('206Pb',10.,2.,4,5),),(('206Pb/204Pb',3.,.5),),1.,.01)
    assert data.text() == ('Software Version: SYNTHETIC\nSample: SYNTHETIC sample\nFraction: SYNTHETIC sample\n'
                           'Method Name: SYNTHETIC method\nStart Time: SYNTHETIC time\n\nMeasurement Outputs - Fraction\n'
                           'Name, Mean, Standard Error (1s abs), Number Included, Number Total\n'
                           'intensity 206Pb (cps),10.0,2.0,4,5\n206Pb/204Pb,3.0,0.5, , \nD/F Gain,1.0,0.01, , \n')


def test_explicit_settings_cascade_and_restore(window,tmp_path):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/sessions/analysis/Analysis.java:925-932
    copies session defaults; P2 applies this inheritance only to display/export preferences,
    with the user-requested method layer (D6 recommended default).
    """
    dialog = ReportDialog(window)
    stamp = datetime(2026,11,25,tzinfo=UTC)
    f,a = window.current[0], window.analysis
    def outputs():
        return csv_text([window.workspace.fraction_row(f,stamp)]),clipboard_text(f),cycles_csv_text(a),a.settings,a.history
    before = outputs()
    names = ['SYNTHETIC global','SYNTHETIC method','SYNTHETIC session','SYNTHETIC analysis']
    for scope,name in zip(['global','method','session','analysis'],names):
        dialog.scope.setCurrentIndex(dialog.scope.findData(scope))
        template = ReportTemplate(name,(ReportColumn('function','Identity'),ReportColumn('mean','Measurements')))
        dialog.change_default(template.to_dict())
        assert dialog.resolve()[0].name == name
        assert dialog.resolve()[1] == scope
    assert outputs() == before
    path = tmp_path/'synthetic.rawtims'
    save_session(window.workspace.session_state(),path)
    loaded, problems = load_session(path)
    assert not problems
    assert loaded.presentation == window.workspace.presentation
    for scope,name in zip(['analysis','session','method','global'],[names[2],names[1],names[0],DEFAULT_TEMPLATE.name]):
        dialog.scope.setCurrentIndex(dialog.scope.findData(scope))
        dialog.restore()
        assert dialog.resolve()[0].name == name
    assert 'report_preferences' not in window.workspace.presentation
    assert outputs() == before
    dialog.close()


def test_per_method_templates_global_fallback_delete_and_csv(window,tmp_path):
    """Tripoli/TripoliApp/src/main/java/org/cirdles/tripoli/gui/reports/ReportBuilderController.java:690-770
    exposes template save/delete/CSV; method placement is the user's P2 scope.
    """
    dialog = ReportDialog(window)
    dialog.scope.setCurrentIndex(dialog.scope.findData('global'))
    dialog.save_template('SYNTHETIC fallback')
    dialog.scope.setCurrentIndex(dialog.scope.findData('method'))
    assert dialog.templates.findText('SYNTHETIC fallback') >= 0
    dialog.columns.selectRow(0)
    dialog.move(1)
    dialog.save_template('SYNTHETIC method')
    dialog.templates.setCurrentIndex(dialog.templates.findText('SYNTHETIC method'))
    dialog.load_template()
    assert dialog.template().columns[0].field == 'unit'
    path = tmp_path/'synthetic-report.csv'
    assert dialog.save_csv(str(path)) == path
    assert path.read_text() == report_csv(window.analysis,dialog.template())
    dialog.delete_template()
    assert dialog.templates.findText('SYNTHETIC method') < 0
    assert dialog.templates.findText('SYNTHETIC fallback') >= 0
    window.analysis.run.metadata.method = 'SYNTHETIC different method'
    other = ReportDialog(window)
    assert other.templates.findText('SYNTHETIC method') < 0
    assert other.templates.findText('SYNTHETIC fallback') >= 0
    other.close()
    dialog.close()


def test_malformed_report_preferences_are_inert(window):
    window.settings.setValue(PREFERENCES_KEY,json.dumps({'methods':[],'global':[]}))
    assert preferences(window.settings) == {}
    window.workspace.presentation['report_preferences'] = []
    dialog = ReportDialog(window)
    assert 'invalid saved preference' in dialog.effective.text()
    dialog.scope.setCurrentIndex(dialog.scope.findData('session'))
    dialog.restore()
    assert 'Invalid session report preferences' in dialog.notice.text()
    assert window.analysis.settings.stat_mode == 'arithmetic'
    dialog.close()


@pytest.mark.parametrize('answer',[QtWidgets.QMessageBox.StandardButton.No,QtWidgets.QMessageBox.StandardButton.Yes])
def test_explicit_overwrite_confirmation(window,tmp_path,monkeypatch,answer):
    """P2 chosen-file confirmation requirement, separate from Java's unconditional REPLACE_EXISTING."""
    path = tmp_path/'synthetic.xml'
    path.write_text('SYNTHETIC original')
    called = []
    def confirm(*args):
        called.append(args)
        return answer
    monkeypatch.setattr(QtWidgets.QMessageBox,'question',confirm)
    result = save_chosen(window,path,'SYNTHETIC replacement')
    assert len(called) == 1 and called[0][-1] == QtWidgets.QMessageBox.StandardButton.No
    assert path.read_text() == ('SYNTHETIC replacement' if answer == QtWidgets.QMessageBox.StandardButton.Yes else 'SYNTHETIC original')
    assert (result is not None) == (answer == QtWidgets.QMessageBox.StandardButton.Yes)


def test_xml_gui_completed_only_and_separate_actions(window,tmp_path):
    a = window.analysis
    path = tmp_path/'synthetic.xml'
    a.run.metadata.complete = None
    a.run.metadata.extra.pop('end_status',None)
    assert export_tripoli(window,'xml',str(path)) is None and not path.exists()
    a.run.metadata.complete = True
    assert export_tripoli(window,'xml',str(path)) == path
    assert '<UPbReduxFraction>' in path.read_text()
    assert any(a.text() == 'Save Tripoli cycle TSV…' for a in window.exchange_menu.actions())


def test_og_inspection_retains_the_bytes_parsed(window,tmp_path,monkeypatch):
    """OGTripoli/source/TripoliWorkProduct.cs:2901-3051; inert import must preserve one consistent source snapshot."""
    from datetime import date

    from rawtims.readers import og_text as reader
    from rawtims.tripoli_exchange import og_text
    from rawtims_gui.exchange import inspect_legacy
    original = og_text(synthetic(),produced_on=date(2026,11,25)).encode()
    path = tmp_path/'synthetic.txt'
    path.write_bytes(original)
    def read_then_change(p):
        parsed = reader.parse_og_text(Path(p).read_bytes())
        Path(p).write_bytes(b'SYNTHETIC changed after read')
        return parsed
    monkeypatch.setattr(reader,'read_og_text',read_then_change)
    monkeypatch.setattr(QtWidgets.QDialog,'exec',lambda self: QtWidgets.QDialog.DialogCode.Rejected)
    before = cycles_csv_text(window.analysis),window.workspace.presentation.copy()
    document = inspect_legacy(window,og=True,path=str(path))
    assert bytes.fromhex(document['source_hex']) == original
    assert (cycles_csv_text(window.analysis),window.workspace.presentation) == before


def test_recent_inputs_deduplicate_limit_missing_and_restore(window,tmp_path):
    """Tripoli/TripoliCore/src/main/java/org/cirdles/tripoli/utilities/stateUtilities/TripoliPersistentState.java:253-277;
    OGTripoli/source/TripoliRegistry.cs:30-56. P2 extends recent native sessions with explicit file/folder lists.
    """
    for n in range(10):
        path = tmp_path/f'synthetic-{n}.txt'
        path.write_text('SYNTHETIC')
        remember(window.settings,'files',path)
    assert len(recent(window.settings,'files')) == 8
    remember(window.settings,'files',tmp_path/'synthetic-3.txt')
    assert Path(recent(window.settings,'files')[0]).name == 'synthetic-3.txt'
    (tmp_path/'synthetic-3.txt').unlink()
    assert len(recent(window.settings,'files')) == 7
    remember(window.settings,'folders',tmp_path)
    assert recent(window.settings,'folders') == [str(tmp_path)]
    same = QtCore.QSettings(window.settings.fileName(),QtCore.QSettings.Format.IniFormat)
    assert recent(same,'files') == recent(window.settings,'files')
    window._rebuild_recent_menu()
    assert {'Run files','Folders'} <= {a.text() for a in window.recent_menu.actions()}


@pytest.mark.parametrize('theme',['light','dark'])
@pytest.mark.parametrize('width,height',[(1280,800),(1440,900)])
def test_p2_layout_fits(window,theme,width,height,tmp_path):
    """No Tripoli screenshot oracle exists; explicit P2 lab layout acceptance in both themes."""
    window.set_theme(theme)
    window.resize(width,height)
    dialog = ReportDialog(window)
    dialog.show()
    for _ in range(3):
        QtWidgets.QApplication.processEvents()
    assert window.width() == width and window.height() == height
    assert window.plot_wall.horizontalScrollBar().maximum() == 0
    assert dialog.minimumSizeHint().width() < width
    assert dialog.width() < width and dialog.height() < height
    assert dialog.columns.horizontalScrollBar().maximum() == 0
    folder = Path(os.environ.get('RAWTIMS_P2_SHOTS',tmp_path))
    folder.mkdir(parents=True,exist_ok=True)
    assert dialog.grab().save(str(folder/f'synthetic-report-{theme}-{width}.png'))
    assert window.grab().save(str(folder/f'synthetic-p2-{theme}-{width}.png'))
    dialog.close()
    inspection = InspectionDialog(window,'SYNTHETIC inspection',{},[['Function','Included'],['SYNTHETIC',1]])
    inspection.show()
    QtWidgets.QApplication.processEvents()
    assert inspection.width() < width and inspection.height() < height
    assert inspection.grab().save(str(folder/f'synthetic-inspection-{theme}-{width}.png'))
    inspection.close()
