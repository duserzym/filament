"""Review diagnostics, plain notes and graph output. No reduction operations."""
from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets, QtPrintSupport

from rawtims.diagnostics import oxygen_monitor
from rawtims_gui.diagnostic_data import DisplayOptions, dot_sizes, histogram, reciprocal
from rawtims_gui.plot_palette import plot_palette


def display_options(settings):
    defaults = DisplayOptions()
    values = {}
    for key, default in asdict(defaults).items():
        if key in ('inverted', 'frozen'):
            continue  # These are deliberate transient review actions.
        values[key] = settings.value('plots/display/' + key, default, type=type(default))
    if values['bands'] not in ('2σ, σ, SE', 'σ, SE', 'SE'):
        values['bands'] = defaults.bands
    if values['rejected'] not in ('Pinned', 'INCLUDE', 'IGNORE', 'HIDE'):
        values['rejected'] = defaults.rejected
    return replace(defaults, **values)


def build_menu(window):
    menu = window.view_menu.addMenu('Review diagnostics')
    menu.addAction('Histogram / x–y / time / oxygen…', lambda: show_diagnostics(window))
    menu.addAction('Session and work-product notes…', lambda: edit_notes(window))
    menu.addSeparator()
    for key, text in (('block_means', 'Block-mean overlay'), ('stats', 'Show plot statistics'),
                      ('frozen', 'Freeze displayed statistics'), ('inverted', 'Invert all displays')):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(getattr(window.display_options, key))
        action.toggled.connect(lambda checked, k=key: set_display(window, k, checked))
    for key, text, choices in (('bands', 'Statistics bands', ('2σ, σ, SE', 'σ, SE', 'SE')),
                               ('rejected', 'Rejected-point display', ('Pinned', 'INCLUDE', 'IGNORE', 'HIDE'))):
        submenu = menu.addMenu(text)
        group = QtGui.QActionGroup(submenu)
        for value in choices:
            action = submenu.addAction(value)
            action.setCheckable(True)
            action.setChecked(getattr(window.display_options, key) == value)
            group.addAction(action)
            action.triggered.connect(lambda checked, k=key, v=value: set_display(window, k, v))
    menu.addSeparator()
    menu.addAction('Plot all functions in this view', lambda: window.set_plotted([
        f.key for f in window.analysis.functions
        if (f.kind == 'intensity') == (window.plot_kind == 'intensities')]) if window.analysis else None)
    menu.addAction('Show selected function rows', lambda: window.set_plotted([
        item.data(QtCore.Qt.ItemDataRole.UserRole) for item in window.function_list.selectedItems()]))
    menu.addAction('Select all function rows', lambda: window.function_list.selectAll())
    menu.addSeparator()
    menu.addAction('Save plot pages as PNG…', lambda: save_pages(window, plot_pages(window)))
    menu.addAction('Print plot pages…', lambda: print_pages(window, plot_pages(window)))
    menu.addAction('Save graph sheets as PNG…', lambda: save_pages(window, graph_sheets(plot_pages(window))))
    menu.addAction('Print graph sheets…', lambda: print_pages(window, graph_sheets(plot_pages(window))))
    return menu


def set_display(window, key, value):
    window.display_options = replace(window.display_options, **{key: value})
    if key not in ('inverted', 'frozen'):
        window.settings.setValue('plots/display/' + key, value)
    if key == 'inverted':
        for plot in window.plot_wall.plots:
            plot.invert_override = None
    state = window._state()
    if state:
        window.plot_wall.refresh(state, rebuild=key in ('inverted', 'rejected'))


def edit_notes(window):
    dialog = QtWidgets.QDialog(window)
    dialog.setWindowTitle('Plain notes')
    dialog.resize(620, 460)
    layout = QtWidgets.QVBoxLayout(dialog)
    scope = QtWidgets.QComboBox()
    scope.addItem('Session', 'session')
    if window.analysis:
        scope.addItem('Work product · ' + window.analysis.run.raw.name, 'run:' + window.analysis.run.run_id)
        scope.addItem('Fraction · ' + window.current[0].fraction_id, 'fraction:' + window.current[0].fraction_id)
        if window.current[0].sample:
            scope.addItem('Sample · ' + window.current[0].sample, 'sample:' + window.current[0].sample)
    layout.addWidget(scope)
    editor = QtWidgets.QPlainTextEdit()
    editor.setAccessibleName('Plain notes')
    layout.addWidget(editor)
    notes = dict(window.workspace.presentation.get('notes', {}))
    previous = ['session']

    def change_scope():
        notes[previous[0]] = editor.toPlainText()
        previous[0] = scope.currentData()
        editor.setPlainText(str(notes.get(previous[0], '')))

    editor.setPlainText(str(notes.get('session', '')))
    scope.currentIndexChanged.connect(change_scope)
    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel)
    layout.addWidget(buttons)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
        notes[previous[0]] = editor.toPlainText()
        window.workspace.presentation['notes'] = notes
        window._after_edit()


def plot_pages(window):
    """Every plot in function order, including plots below the wall viewport."""
    pages = []
    for plot in window.plot_wall.plots:
        graph = plot.grab().toImage()
        image = QtGui.QImage(graph.width(), graph.height() + 48, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor(plot_palette().background))
        painter = QtGui.QPainter(image)
        painter.setPen(QtGui.QColor(plot_palette().text))
        painter.drawText(QtCore.QRect(8, 0, graph.width()-16, 48),
                         QtCore.Qt.TextFlag.TextWordWrap | QtCore.Qt.AlignmentFlag.AlignVCenter, plot.title_text)
        painter.drawImage(0, 48, graph)
        painter.end()
        pages.append((plot.title_text, image))
    return pages


def save_pages(parent, pages):
    if not pages:
        return
    path, _ = QtWidgets.QFileDialog.getSaveFileName(parent, 'Save plot pages', '', 'PNG image (*.png)')
    if path:
        target = Path(path).with_suffix('.png')
        for index, (_, page) in enumerate(pages, 1):
            name = target if len(pages) == 1 else target.with_name(f'{target.stem}-{index:03d}.png')
            if not page.save(str(name), 'PNG'):
                raise OSError(f'Could not save {name}')


def graph_sheets(pages):
    """Two columns, four graphs per sheet; stable function/page order."""
    sheets = []
    for start in range(0, len(pages), 4):
        group = pages[start:start+4]
        width = max(image.width() for _, image in group)
        height = max(image.height() for _, image in group)
        sheet = QtGui.QImage(width * min(2, len(group)), height * ((len(group)+1)//2), QtGui.QImage.Format.Format_ARGB32)
        sheet.fill(QtGui.QColor(plot_palette().background))
        painter = QtGui.QPainter(sheet)
        for index, (_, image) in enumerate(group):
            painter.drawImage((index % 2)*width, (index // 2)*height, image)
        painter.end()
        sheets.append((f'Graphs {start+1}–{start+len(group)}', sheet))
    return sheets


def print_pages(parent, pages):
    if not pages:
        return
    printer = QtPrintSupport.QPrinter(QtPrintSupport.QPrinter.PrinterMode.HighResolution)
    dialog = QtPrintSupport.QPrintDialog(printer, parent)
    if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
        return
    painter = QtGui.QPainter(printer)
    if not painter.isActive():
        return
    try:
        for index, (title, page) in enumerate(pages):
            if index:
                printer.newPage()
            area = printer.pageRect(QtPrintSupport.QPrinter.Unit.DevicePixel).toRect()
            painter.drawText(area, QtCore.Qt.AlignmentFlag.AlignTop, title)
            area.adjust(0, printer.resolution() // 3, 0, 0)
            scaled = page.scaled(area.size(), QtCore.Qt.AspectRatioMode.KeepAspectRatio, QtCore.Qt.TransformationMode.SmoothTransformation)
            painter.drawImage(area.topLeft(), scaled)
    finally:
        painter.end()


def show_diagnostics(window):
    if window.analysis is None:
        return
    dialog = DiagnosticDialog(window)
    dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.show()


class DiagnosticDialog(QtWidgets.QDialog):
    """A live, read-only diagnostic view of one work product."""

    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.analysis = window.analysis
        self.setWindowTitle('Review diagnostics · ' + self.analysis.run.raw.name)
        self.resize(860, 620)
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QGridLayout()
        layout.addLayout(form)
        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(['Histogram', 'x–y', 'Time', 'Oxygen monitor'])
        self.x, self.y, self.intensity = (QtWidgets.QComboBox() for _ in range(3))
        self.intensity.addItem('Uniform dots', None)
        for function in self.analysis.functions:
            for combo in (self.x, self.y, self.intensity):
                combo.addItem(function.key, function.key)
        for col, (label, widget) in enumerate((('View', self.mode), ('Function / X', self.x), ('Y', self.y), ('Dot intensity', self.intensity))):
            widget.setMinimumContentsLength(8)
            widget.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            form.addWidget(QtWidgets.QLabel(label), 0, col)
            form.addWidget(widget, 1, col)
            form.setColumnStretch(col, 1)
        self.verify = QtWidgets.QCheckBox('Verified from method: 272 = 238U16O18O, 270 = 238U16O2; ratio is dimensionless')
        layout.addWidget(self.verify)
        self.inverse = QtWidgets.QCheckBox('Invert displayed values (exports stay measured)')
        layout.addWidget(self.inverse)
        controls = QtWidgets.QHBoxLayout()
        layout.addLayout(controls)
        self.bins = QtWidgets.QSpinBox()
        self.bins.setRange(1, 200)
        self.bins.setValue(20)
        self.minimum, self.maximum = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
        for widget, value in ((self.minimum, 2), (self.maximum, 6)):
            widget.setRange(.5, 20)
            widget.setValue(value)
        for label, widget in (('Bins', self.bins), ('Min dot radius (px)', self.minimum), ('Max', self.maximum)):
            controls.addWidget(QtWidgets.QLabel(label))
            controls.addWidget(widget)
        self.color = QtWidgets.QPushButton('Point color…')
        self.color.clicked.connect(self.choose_color)
        controls.addWidget(self.color)
        self.point_color = None
        self.plot = pg.PlotWidget()
        layout.addWidget(self.plot, 1)
        self.status = QtWidgets.QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        recipes = QtWidgets.QHBoxLayout()
        layout.addLayout(recipes)
        self.recipe = QtWidgets.QComboBox()
        self.recipe.setMinimumContentsLength(15)
        recipes.addWidget(self.recipe, 1)
        for label, callback in (('Load recipe', self.load_recipe), ('Save recipe…', self.save_recipe), ('Delete', self.delete_recipe),
                                ('PNG…', lambda: save_pages(self, [(self.windowTitle(), self.plot.grab().toImage())])),
                                ('Print…', lambda: print_pages(self, [(self.windowTitle(), self.plot.grab().toImage())]))):
            button = QtWidgets.QPushButton(label)
            button.clicked.connect(callback)
            recipes.addWidget(button)
        for combo in (self.mode, self.x, self.y, self.intensity):
            combo.currentIndexChanged.connect(self.redraw)
        for widget in (self.bins, self.minimum, self.maximum):
            widget.valueChanged.connect(self.redraw)
        self.verify.toggled.connect(self.redraw)
        self.x.currentIndexChanged.connect(lambda: self.verify.setChecked(False))
        self.inverse.toggled.connect(self.redraw)
        self.refresh_recipes()
        # Parent edits refresh this open view; values and masks are never cached.
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.refresh_if_changed)
        self.timer.start(200)
        self._signature = None
        self.redraw()

    def refresh_if_changed(self):
        if not any(self.analysis is a for f in self.owner.workspace.fractions for a in (f.pb, f.u)):
            self.close()
            return
        signature = (id(self.analysis.values), self.analysis.effective.tobytes(), plot_palette().background)
        if signature != self._signature:
            self._signature = signature
            self.redraw()

    def choose_color(self):
        color = QtWidgets.QColorDialog.getColor(QtGui.QColor(self.point_color or plot_palette().included), self)
        if color.isValid():
            self.point_color = color.name()
            self.redraw()

    def recipe_data(self):
        return dict(mode=self.mode.currentText(), x=self.x.currentData(), y=self.y.currentData(),
                    intensity=self.intensity.currentData(), minimum=self.minimum.value(), maximum=self.maximum.value(),
                    bins=self.bins.value(), inverse=self.inverse.isChecked(), color=self.point_color)

    def refresh_recipes(self):
        self.recipe.clear()
        recipes = self.owner.workspace.presentation.get('recipes', {})
        self.recipe.addItems(sorted(recipes))

    def save_recipe(self):
        name, ok = QtWidgets.QInputDialog.getText(self, 'Save display recipe', 'Recipe name')
        if ok and name.strip():
            self.owner.workspace.presentation.setdefault('recipes', {})[name.strip()] = self.recipe_data()
            self.refresh_recipes()
            self.owner._after_edit()

    def delete_recipe(self):
        self.owner.workspace.presentation.get('recipes', {}).pop(self.recipe.currentText(), None)
        self.refresh_recipes()
        self.owner._after_edit()

    def load_recipe(self):
        recipe = self.owner.workspace.presentation.get('recipes', {}).get(self.recipe.currentText())
        if not isinstance(recipe, dict):
            return
        for key in ('minimum', 'maximum', 'bins'):
            value = recipe.get(key, getattr(self, key).value())
            expected = int if key == 'bins' else (int, float)
            if not isinstance(value, expected) or not np.isfinite(value):
                self.status.setText('Recipe contains an invalid size or bin count.')
                return
        if recipe.get('mode', 'Histogram') not in ('Histogram', 'x–y', 'Time', 'Oxygen monitor'):
            self.status.setText('Recipe view unavailable.')
            return
        for key in ('x', 'y', 'intensity'):
            combo = getattr(self, key)
            if combo.findData(recipe.get(key)) < 0:
                self.status.setText('Recipe function unavailable in this work product.')
                return
        self.verify.setChecked(False)  # Verification never transfers between work products.
        for key in ('x', 'y', 'intensity'):
            combo = getattr(self, key)
            combo.setCurrentIndex(combo.findData(recipe.get(key)))
        self.mode.setCurrentText(recipe.get('mode', 'Histogram'))
        for key in ('minimum', 'maximum', 'bins'):
            getattr(self, key).setValue(recipe.get(key, getattr(self, key).value()))
        self.inverse.setChecked(bool(recipe.get('inverse', False)))
        color = recipe.get('color')
        self.point_color = color if isinstance(color, str) and QtGui.QColor(color).isValid() else None
        self.redraw()

    def redraw(self):
        self.plot.clear()
        palette = plot_palette()
        self.plot.setBackground(palette.background)
        for side in ('left', 'bottom'):
            self.plot.getAxis(side).setTextPen(palette.axisText)
            self.plot.getAxis(side).setPen(palette.axisLine)
        mode = self.mode.currentText()
        self.verify.setVisible(mode == 'Oxygen monitor')
        self.y.setEnabled(mode == 'x–y')
        self.intensity.setEnabled(mode == 'x–y')
        self.bins.setEnabled(mode == 'Histogram')
        self.minimum.setEnabled(mode == 'x–y')
        self.maximum.setEnabled(mode == 'x–y')
        xkey, ykey = self.x.currentData(), self.y.currentData()
        values = self.analysis.column(xkey)
        include = self.analysis.included_for(xkey).copy()
        label = xkey
        if mode == 'Oxygen monitor':
            function = self.analysis.function(xkey)
            if not (self.verify.isChecked() and function.numerator_mass == 272 and function.denominator_mass == 270):
                self.status.setText('Select 272/270 and verify the molecular assignment and units before enabling the diagnostic.')
                return
            values = oxygen_monitor(values, verified_uo2=True)
            label = '18O/16O monitor = (272/270)/2 · diagnostic only'
        if self.inverse.isChecked():
            values = reciprocal(values)
            label = f'1/({label}) [display inverse]'
        color = self.point_color or palette.included
        self.plot.addLegend(offset=(10, 10)) if self.plot.plotItem.legend is None else None
        if mode == 'Histogram':
            edges, accepted, rejected = histogram(values, include, self.bins.value())
            self.histogram_data = edges, accepted, rejected
            widths = np.diff(edges)
            centers = (edges[1:] + edges[:-1]) / 2
            self.plot.addItem(pg.BarGraphItem(x=centers, height=accepted, width=widths, brush=color, name='Accepted'))
            self.plot.addItem(pg.BarGraphItem(x=centers, height=rejected, y0=accepted, width=widths, brush=palette.excluded, name='Rejected'))
            self.plot.setLabel('bottom', label, color=palette.axisText)
            self.plot.setLabel('left', 'Cycle count', color=palette.axisText)
            self.status.setText(f'{accepted.sum()} accepted · {rejected.sum()} rejected · finite samples only; shared bin edges')
        else:
            if mode == 'x–y':
                x, y = values, self.analysis.column(ykey)
                if self.inverse.isChecked():
                    y = reciprocal(y)
                include &= self.analysis.included_for(ykey)
                ylabel = f'1/({ykey}) [display inverse]' if self.inverse.isChecked() else ykey
                xlabel = label
            else:
                x, y = self.analysis.run.time, values
                xlabel, ylabel = 'Elapsed time (s)', label
                if not np.isfinite(x).any():
                    self.status.setText('This work product has no recorded cycle times.')
                    return
            finite = np.isfinite(x) & np.isfinite(y)
            self.rows = np.flatnonzero(finite)
            sizes = np.full(len(x), 4.5)
            intensity = self.intensity.currentData()
            if mode == 'x–y' and intensity:
                if self.minimum.value() > self.maximum.value():
                    self.status.setText('Minimum dot radius must not exceed maximum.')
                    return
                sizes = dot_sizes(self.analysis.column(intensity), self.minimum.value(), self.maximum.value())
            self.coordinates = x[finite], y[finite]
            points = pg.ScatterPlotItem(x=x[finite], y=y[finite], size=sizes[finite], symbol='s',
                                       brush=[color if used else palette.background for used in include[finite]],
                                       pen=[palette.pointHalo if used else palette.excluded for used in include[finite]],
                                       data=[f'Cycle {self.analysis.run.cycle[row]} · block {self.analysis.run.block[row]}: '
                                             f'{x[row]:.12g}, {y[row]:.12g}' for row in self.rows], hoverable=True,
                                       tip=lambda x, y, data: data)
            self.plot.addItem(points)
            self.plot.setLabel('bottom', xlabel, color=palette.axisText)
            self.plot.setLabel('left', ylabel, color=palette.axisText)
            self.status.setText(f'{len(self.rows)} paired finite cycles · accepted only when both functions accept the cycle. '
                                'Square dots: filled accepted, hollow rejected. Read-only; exports stay measured.')
        self.plot.autoRange()
