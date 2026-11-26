"""Separate Tripoli exchange actions and inert saved-work inspection."""
import json
from datetime import date, datetime
from pathlib import Path

from PySide6 import QtWidgets

from rawtims.tripoli_exchange import (
    et_redux_xml,
    java_cycles_tsv,
    og_text,
    write_exchange,
)


def save_chosen(parent, path, text):
    """A chosen filename alone never authorizes replacement."""
    try:
        return write_exchange(path,text)
    except FileExistsError:
        answer = QtWidgets.QMessageBox.question(parent,'Replace export?',f'Replace {Path(path).name}?',
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No)
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return None
        return write_exchange(path,text,overwrite=True)


def export_tripoli(window, dialect, path=None):
    analysis = window.analysis
    if analysis is None:
        return None
    try:
        if dialect == 'xml':
            fraction, element = window.current
            window.workspace.sync_mappings(fraction)
            text, suffix, label = et_redux_xml(fraction,element), '.et-redux.xml', 'ET_Redux measured ratios'
        elif dialect == 'java':
            text = java_cycles_tsv(analysis, session_path=str(window.session_path) if window.session_path else '*Unsaved Session*',
                                   data_path=analysis.run.raw.path, produced_on=datetime.now())
            suffix, label = '.tripoli-cycles.tsv', 'Tripoli cycle TSV'
        elif dialect == 'og':
            text = og_text(analysis,source_name=analysis.run.raw.name,produced_on=date.today())
            suffix, label = '.og-tripoli.txt', 'OGTripoli ratio text'
        else:
            raise ValueError('Unknown exchange dialect')
        if path is None:
            default = str(Path(window._export_folder())/(Path(analysis.run.raw.name).stem+suffix))
            path, _ = QtWidgets.QFileDialog.getSaveFileName(window,'Save '+label,default, 'Exchange file (*'+suffix+')',
                                    options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return None
        written = save_chosen(window,path,text)
        if written:
            from rawtims_gui.main import EXPORT_DIR_KEY
            window.settings.setValue(EXPORT_DIR_KEY,str(written.parent))
            window.statusBar().showMessage(f'Saved {label} to {written.name}',8000)
        return written
    except (ValueError,OSError) as error:
        window.statusBar().showMessage(f'Could not export: {error}',10000)
        return None


class InspectionDialog(QtWidgets.QDialog):
    def __init__(self, parent, title, document, table=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(780,570)
        self.document = document
        layout = QtWidgets.QVBoxLayout(self)
        notice = QtWidgets.QLabel('Read-only legacy data. No saved settings, corrections, paths or objects are applied to the current session.')
        notice.setWordWrap(True)
        layout.addWidget(notice)
        if table is not None:
            if len(table) > 1001:
                notice.setText(notice.text()+' Showing the first 1000 cycles; the inspection JSON retains all cycles.')
            table = table[:1001]
            view = QtWidgets.QTableWidget(len(table)-1,len(table[0]))
            view.setHorizontalHeaderLabels(table[0])
            view.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
            for row, cells in enumerate(table[1:]):
                for col, value in enumerate(cells):
                    view.setItem(row,col,QtWidgets.QTableWidgetItem(str(value)))
            layout.addWidget(view,1)
        else:
            view = QtWidgets.QPlainTextEdit()
            view.setReadOnly(True)
            # Keep large embedded source/graphs out of the text widget; the full
            # inspection is available in its explicit JSON export.
            summary = {k:v for k,v in document.items() if k not in ('source_hex','graph')}
            graph = document['graph']
            summary['graph_nodes'] = len(graph['nodes'])
            summary['root'] = graph['nodes'][graph['root']['ref']]
            view.setPlainText(json.dumps(summary,indent=2)[:100_000])
            layout.addWidget(view,1)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        save = buttons.addButton('Save inspection JSON…',QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
        save.clicked.connect(self.save)
        layout.addWidget(buttons)

    def save(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self,'Save inert inspection','legacy-inspection.json','JSON (*.json)',
                                      options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
        if path:
            try:
                save_chosen(self,path,json.dumps(self.document,ensure_ascii=True,allow_nan=False,indent=2)+'\n')
            except (ValueError,OSError) as error:
                QtWidgets.QMessageBox.warning(self,'Could not save inspection',str(error))


def inspect_legacy(window, *, og=False, path=None):
    if path is None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(window,'Inspect legacy saved work','',
                         'OGTripoli text (*.txt)' if og else 'Tripoli saved work (*.trip *.triphis *.tripoli)')
    if not path:
        return None
    try:
        if og:
            from rawtims.readers.legacy_saved import LegacyInspection
            from rawtims.readers.og_text import read_og_text
            data = read_og_text(path)
            raw = {'names':list(data.names),'values':data.values,'included':data.included,'block':data.block,
                   'header':list(data.header),'statistics':[list(row) for row in data.statistics]}
            document = LegacyInspection(Path(path),'og-text',data.source,raw).document()
            table = [['Block','Cycle',*[label for n in data.names for label in (n,n+' included')]]]
            for i, row in enumerate(data.values):
                table.append([int(data.block[i]),i+1,*[v for j,value in enumerate(row) for v in (value,int(data.included[i,j]))]])
        else:
            from rawtims.readers.legacy_saved import inspect_saved
            document, table = inspect_saved(path).document(), None
        dialog = InspectionDialog(window,'OGTripoli text' if og else 'Legacy saved work',document,table)
        dialog.exec()
        return document
    except (ValueError,OSError) as error:
        window.statusBar().showMessage(f'Could not inspect saved work: {error}',10000)
        return None


def build_menu(window):
    menu = window.menuBar().addMenu('Exchange')
    for title, dialect in [('Save Tripoli cycle TSV…','java'),('Save OGTripoli ratio text…','og'),('Save ET_Redux measured XML…','xml')]:
        menu.addAction(window._action(title,lambda _c=False,d=dialect: export_tripoli(window,d)))
    menu.addSeparator()
    menu.addAction(window._action('Inspect OGTripoli text…',lambda: inspect_legacy(window,og=True)))
    menu.addAction(window._action('Inspect legacy saved work…',lambda: inspect_legacy(window)))
    menu.addSeparator()
    from rawtims_gui.report_builder import ReportDialog
    menu.addAction(window._action('Report columns and templates…',lambda: ReportDialog(window).exec()))
    menu.addAction('Template 1: Phoenix Full results required').setEnabled(False)
    return menu
