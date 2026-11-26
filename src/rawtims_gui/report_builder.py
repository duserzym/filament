"""Report columns/categories/templates and explicit display-preference cascade."""
import json

from PySide6 import QtCore, QtWidgets

from rawtims.reports import (
    DEFAULT_TEMPLATE,
    FIELDS,
    ReportColumn,
    ReportError,
    ReportTemplate,
    effective_template,
    report_csv,
    report_table,
)

PREFERENCES_KEY = 'reports/preferences-v1'


def preferences(settings):
    try:
        value = json.loads(settings.value(PREFERENCES_KEY,'{}',type=str))
        if not isinstance(value,dict) or set(value)-{'global','methods'}:
            raise ValueError('Invalid report preferences')
        if not isinstance(value.get('global',{}),dict) or not isinstance(value.get('methods',{}),dict):
            raise ReportError('Invalid report scope')
        scopes = [value.get('global',{}),*value.get('methods',{}).values()]
        for scope in scopes:
            if not isinstance(scope,dict) or set(scope)-{'default','templates'} or not isinstance(scope.get('templates',{}),dict):
                raise ValueError('Invalid report scope')
        return value
    except (ValueError,TypeError):
        return {}


class ReportDialog(QtWidgets.QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.analysis = window.analysis
        self.method = self.analysis.run.metadata.method if self.analysis else None
        self.run_id = self.analysis.run.run_id if self.analysis else None
        self.setWindowTitle('Report columns and templates')
        self.resize(820,640)
        layout = QtWidgets.QVBoxLayout(self)
        self.effective = QtWidgets.QLabel()
        self.effective.setWordWrap(True)
        layout.addWidget(self.effective)
        scopes = QtWidgets.QHBoxLayout()
        layout.addLayout(scopes)
        scopes.addWidget(QtWidgets.QLabel('Save preference for'))
        self.scope = QtWidgets.QComboBox()
        for label, key in [('This analysis','analysis'),('This session','session'),('This method','method'),('All methods (fallback)','global')]:
            self.scope.addItem(label,key)
        self.scope.setCurrentIndex(2 if self.method else 3)
        if not self.method:
            self.scope.model().item(2).setEnabled(False)
        if not self.analysis:
            self.scope.model().item(0).setEnabled(False)
        scopes.addWidget(self.scope,1)
        restore = QtWidgets.QPushButton('Restore inherited')
        restore.clicked.connect(self.restore)
        scopes.addWidget(restore)
        self.columns = QtWidgets.QTableWidget(0,3)
        self.columns.setHorizontalHeaderLabels(['Use','Column','Category'])
        self.columns.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        self.columns.horizontalHeader().setSectionResizeMode(0,QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.columns.horizontalHeader().setSectionResizeMode(1,QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.columns.horizontalHeader().setSectionResizeMode(2,QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.columns,1)
        reorder = QtWidgets.QHBoxLayout()
        layout.addLayout(reorder)
        for label, step in [('Move up',-1),('Move down',1)]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(lambda _c=False,s=step: self.move(s))
            reorder.addWidget(button)
        reorder.addStretch()
        self.templates = QtWidgets.QComboBox()
        self.templates.setMinimumContentsLength(14)
        self.templates.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        template_row = QtWidgets.QHBoxLayout()
        layout.addLayout(template_row)
        template_row.addWidget(self.templates,1)
        for label, callback in [('Load',self.load_template),('Save template…',self.save_template),('Delete',self.delete_template)]:
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            template_row.addWidget(button)
        self.preview = QtWidgets.QTableWidget()
        self.preview.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setMaximumHeight(150)
        layout.addWidget(self.preview,1)
        self.notice = QtWidgets.QLabel('Preferences affect this report only. Statistics, masks and fraction exports retain their current values.')
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        for label, callback in [('Apply preference',self.apply),('Preview',self.refresh_preview),('Save report CSV…',self.save_csv)]:
            button = buttons.addButton(label,QtWidgets.QDialogButtonBox.ButtonRole.ActionRole)
            button.clicked.connect(callback)
        layout.addWidget(buttons)
        self.scope.currentIndexChanged.connect(self.refresh_templates)
        self.load_effective()
        self.refresh_templates()

    def store(self):
        return preferences(self.window.settings)

    def presentation(self):
        value = self.window.workspace.presentation.get('report_preferences',{})
        if not isinstance(value,dict) or not isinstance(value.get('analyses',{}),dict):
            raise ReportError('Invalid session report preferences')
        return value

    def resolve(self):
        saved, local = self.store(), self.presentation()
        return effective_template(global_default=saved.get('global',{}).get('default'),
                      method_default=saved.get('methods',{}).get(self.method,{}).get('default'),
                      session_default=local.get('default'),analysis_default=local.get('analyses',{}).get(self.run_id))

    def load_effective(self):
        try:
            template, source = self.resolve()
        except ValueError as error:
            template, source = DEFAULT_TEMPLATE, 'built in (invalid saved preference)'
            self.notice.setText(str(error))
        self.effective.setText(f'Effective report: {template.name} · {source} · Method: {self.method or "unspecified"}')
        self.populate(template)
        self.refresh_preview()

    def populate(self, template):
        selected = {c.field:c for c in template.columns}
        fields = [c.field for c in template.columns] + [f for f in FIELDS if f not in selected]
        self.columns.setRowCount(len(fields))
        for row, field in enumerate(fields):
            use = QtWidgets.QTableWidgetItem()
            use.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsUserCheckable | QtCore.Qt.ItemFlag.ItemIsSelectable)
            use.setCheckState(QtCore.Qt.CheckState.Checked if field in selected else QtCore.Qt.CheckState.Unchecked)
            self.columns.setItem(row,0,use)
            name = QtWidgets.QTableWidgetItem(FIELDS[field])
            name.setData(QtCore.Qt.ItemDataRole.UserRole,field)
            name.setFlags(name.flags() & ~QtCore.Qt.ItemFlag.ItemIsEditable)
            self.columns.setItem(row,1,name)
            self.columns.setItem(row,2,QtWidgets.QTableWidgetItem(selected.get(field,ReportColumn(field)).category))

    def template(self, name='Custom report'):
        return ReportTemplate(name,tuple(ReportColumn(self.columns.item(r,1).data(QtCore.Qt.ItemDataRole.UserRole),self.columns.item(r,2).text().strip())
                       for r in range(self.columns.rowCount()) if self.columns.item(r,0).checkState() == QtCore.Qt.CheckState.Checked))

    def move(self, step):
        row = self.columns.currentRow()
        other = row+step
        if row < 0 or not 0 <= other < self.columns.rowCount():
            return
        for col in range(3):
            a,b = self.columns.takeItem(row,col),self.columns.takeItem(other,col)
            self.columns.setItem(other,col,a)
            self.columns.setItem(row,col,b)
        self.columns.selectRow(other)

    def refresh_preview(self):
        if not self.analysis:
            return
        try:
            table = report_table(self.analysis,self.template())
            self.preview.setColumnCount(len(table[0]))
            self.preview.setRowCount(len(table)-2)
            self.preview.setHorizontalHeaderLabels([f'{c} · {f}' for c,f in zip(*table[:2])])
            for r,row in enumerate(table[2:]):
                for c,value in enumerate(row):
                    self.preview.setItem(r,c,QtWidgets.QTableWidgetItem(str(value)))
        except ValueError as error:
            self.notice.setText(str(error))

    def change_default(self, value):
        scope = self.scope.currentData()
        if scope in ('global','method'):
            saved = self.store()
            target = saved.setdefault('global',{}) if scope == 'global' else saved.setdefault('methods',{}).setdefault(self.method,{})
            if value is None:
                target.pop('default',None)
            else:
                target['default'] = value
            self.window.settings.setValue(PREFERENCES_KEY,json.dumps(saved))
        else:
            self.presentation()  # validate optional metadata before modifying it
            presentation = self.window.workspace.presentation
            saved = presentation.setdefault('report_preferences',{})
            target = saved if scope == 'session' else saved.setdefault('analyses',{})
            key = 'default' if scope == 'session' else self.run_id
            if value is None:
                target.pop(key,None)
                if saved.get('analyses') == {}:
                    saved.pop('analyses')
                if not saved:
                    presentation.pop('report_preferences')
            else:
                target[key] = value
            self.window._update_titles()

    def apply(self):
        try:
            self.change_default(self.template().to_dict())
            self.load_effective()
        except ValueError as error:
            self.notice.setText(str(error))

    def restore(self):
        try:
            self.change_default(None)
            self.load_effective()
        except ValueError as error:
            self.notice.setText(str(error))

    def library(self, saved):
        # Session/analysis choose from method templates with global fallback.
        if self.scope.currentData() == 'global' or not self.method:
            return saved.setdefault('global',{}).setdefault('templates',{})
        return saved.setdefault('methods',{}).setdefault(self.method,{}).setdefault('templates',{})

    def refresh_templates(self):
        saved = self.store()
        merged = dict(saved.get('global',{}).get('templates',{}))
        if self.scope.currentData() != 'global' and self.method:
            merged.update(saved.get('methods',{}).get(self.method,{}).get('templates',{}))
        self.templates.clear()
        self.templates.addItem(DEFAULT_TEMPLATE.name,DEFAULT_TEMPLATE.to_dict())
        for name,value in sorted(merged.items()):
            self.templates.addItem(name,value)

    def load_template(self):
        try:
            self.populate(ReportTemplate.from_dict(self.templates.currentData()))
            self.refresh_preview()
        except ValueError as error:
            self.notice.setText(str(error))

    def save_template(self, name=None):
        if not isinstance(name,str):
            name, ok = QtWidgets.QInputDialog.getText(self,'Save report template','Template name')
            if not ok:
                return
        try:
            template = self.template(name.strip())
            if template.name == DEFAULT_TEMPLATE.name:
                raise ValueError('Choose a name other than the built-in template')
            saved = self.store()
            self.library(saved)[template.name] = template.to_dict()
            self.window.settings.setValue(PREFERENCES_KEY,json.dumps(saved))
            self.refresh_templates()
        except ValueError as error:
            self.notice.setText(str(error))

    def delete_template(self):
        saved = self.store()
        name = self.templates.currentText()
        library = self.library(saved)
        if name not in library:
            self.notice.setText('Choose the owning scope to delete an inherited template.')
            return
        library.pop(name)
        self.window.settings.setValue(PREFERENCES_KEY,json.dumps(saved))
        self.refresh_templates()

    def save_csv(self, path=None):
        if not self.analysis:
            return None
        try:
            text = report_csv(self.analysis,self.template())
            if not isinstance(path,str):
                path, _ = QtWidgets.QFileDialog.getSaveFileName(self,'Save custom report','report.csv','CSV (*.csv)',
                                    options=QtWidgets.QFileDialog.Option.DontConfirmOverwrite)
            if not path:
                return None
            from rawtims_gui.exchange import save_chosen
            return save_chosen(self,path,text)
        except (ValueError,OSError) as error:
            self.notice.setText(str(error))
            return None
