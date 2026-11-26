"""Display/export report preferences, independent of numerical settings."""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

FIELDS = {'function':'Function', 'kind':'Kind', 'unit':'Unit', 'mean':'Mean', 'se_abs':'SE (1s abs)',
          'se_pct':'SE (1s %)', 'n_used':'Number included', 'n_total':'Number total',
          'statistic':'Statistic', 'method':'Method', 'source':'Source'}


class ReportError(ValueError):
    """Invalid report schema or saved display preference."""


@dataclass(frozen=True)
class ReportColumn:
    field: str
    category: str = 'Measurement outputs'


@dataclass(frozen=True)
class ReportTemplate:
    name: str
    columns: tuple[ReportColumn, ...]

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 120:
            raise ValueError('Report template needs a name (up to 120 characters)')
        if not self.columns or len(self.columns) > len(FIELDS):
            raise ValueError('Select at least one report column')
        if len({c.field for c in self.columns}) != len(self.columns):
            raise ValueError('Report columns must be unique')
        for column in self.columns:
            if column.field not in FIELDS or not isinstance(column.category, str) or not column.category.strip() or len(column.category) > 120:
                raise ValueError('Unknown report field or empty category')

    def to_dict(self):
        return {'version':1, 'name':self.name, 'columns':[{'field':c.field,'category':c.category} for c in self.columns]}

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != {'version','name','columns'} or data['version'] != 1:
            raise ValueError('Unknown report template schema')
        if not isinstance(data['columns'], list):
            raise ReportError('Invalid report columns')
        try:
            return cls(data['name'], tuple(ReportColumn(**c) for c in data['columns']))
        except (TypeError, KeyError) as error:
            raise ValueError('Invalid report columns') from error


DEFAULT_TEMPLATE = ReportTemplate('Cycle summary', tuple(ReportColumn(k) for k in
                                  ('function','unit','mean','se_abs','se_pct','n_used','n_total','statistic')))


def effective_template(*, global_default=None, method_default=None, session_default=None, analysis_default=None):
    """Most specific explicit preference wins; restore removes only that override."""
    for source, value in [('analysis',analysis_default), ('session',session_default), ('method',method_default), ('global',global_default)]:
        if value is not None:
            return ReportTemplate.from_dict(value), source
    return DEFAULT_TEMPLATE, 'built in'


def report_table(analysis, template=DEFAULT_TEMPLATE):
    rows = [[c.category for c in template.columns], [FIELDS[c.field] for c in template.columns]]
    for function in analysis.functions:
        stats = analysis.stats(function.key)
        # Geometric se is a log-scale error; report the smaller absolute side
        # corresponding to the established percent-SE convention.
        se_abs = abs(stats.mean)*stats.se_pct/100 if stats.mode == 'geometric' else stats.se
        values = {'function':function.name, 'kind':function.kind, 'unit':function.unit or '',
                  'mean':stats.mean, 'se_abs':se_abs, 'se_pct':stats.se_pct, 'n_used':stats.n_used,
                  'n_total':stats.n_total, 'statistic':stats.mode, 'method':analysis.run.metadata.method or '',
                  'source':analysis.run.raw.name}
        rows.append([values[c.field] for c in template.columns])
    return rows


def report_csv(analysis, template=DEFAULT_TEMPLATE):
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    for row in report_table(analysis, template):
        writer.writerow(['' if isinstance(v,float) and not math.isfinite(v) else v for v in row])
    return output.getvalue()


@dataclass(frozen=True)
class TemplateOne:
    """Explicit Phoenix Full results, never inferred from processed cycle columns.

    Intensities contain (species short label, mean, SD, included, total).
    Ratios contain (pretty label, weighted mean, higher absolute one sigma).
    """
    software: str
    sample: str
    method: str
    start: str
    intensities: tuple[tuple[str, float, float, int, int], ...]
    ratios: tuple[tuple[str, float, float], ...]
    gain: float
    gain_one_sigma: float

    def text(self):
        """Analysis.java:813-850; MassSpecExtractedData.java:182-188.

        Preserve upstream's Fraction=Sample header and SD-under-SE label.
        This adapter has no automatic processed-run conversion.
        """
        from rawtims.tripoli_exchange import _label, java_double
        text = (f'Software Version: {_label(self.software)}\nSample: {_label(self.sample)}\n'
                f'Fraction: {_label(self.sample)}\nMethod Name: {_label(self.method)}\nStart Time: {_label(self.start)}\n\n'
                'Measurement Outputs - Fraction\nName, Mean, Standard Error (1s abs), Number Included, Number Total\n')
        for name, mean, sd, included, total in self.intensities:
            text += f'intensity {_label(name)} (cps),{java_double(mean)},{java_double(sd)},{included},{total}\n'
        for name, mean, sigma in self.ratios:
            text += f'{_label(name)},{java_double(mean)},{java_double(sigma)}, , \n'
        return text + f'D/F Gain,{java_double(self.gain)},{java_double(self.gain_one_sigma)}, , \n'
