"""Opt-in Tripoli 00dc941 / OGTripoli d906f70 exchange adapters.

These writers never call or modify the native fraction/cycle writers. Dates
and paths are arguments so byte oracles can suppress volatile provenance.
"""
from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np

from rawtims.fractions import require_shared_selection
from rawtims.mapping import ratio_stats


def java_double(value: float) -> str:
    """Shortest round-trip decimal with Java's fixed/scientific thresholds."""
    value = float(value)
    if not math.isfinite(value):
        return 'NaN' if math.isnan(value) else ('-Infinity' if value < 0 else 'Infinity')
    if value == 0:
        return '-0.0' if math.copysign(1, value) < 0 else '0.0'
    decimal = Decimal(repr(value))
    if 1e-3 <= abs(value) < 1e7:
        text = format(decimal, 'f')
        return text if '.' in text else text + '.0'
    digits = decimal.as_tuple()
    coefficient = ''.join(map(str, digits.digits)).rstrip('0')
    if len(coefficient) == 1:
        # Java requires at least two significant decimal digits in scientific
        # form and chooses the closest such decimal (MIN_VALUE -> 4.9E-324).
        decimal = Decimal(format(value,'.1e'))
        coefficient = ''.join(map(str,decimal.as_tuple().digits))
    exponent = decimal.adjusted()
    return ('-' if value < 0 else '') + coefficient[0] + '.' + (coefficient[1:] or '0') + 'E' + str(exponent)


def _label(value) -> str:
    value = str(value)
    if any(ord(c) < 32 for c in value):
        raise ValueError('Tripoli text labels cannot contain tabs, newlines or control characters')
    return value


def java_cycles_tsv(analysis, *, session_path='*Unsaved Session*', data_path='', produced_on=None) -> str:
    """Analysis.java:703-782; includes Cycle/Time before source and derived functions.

    The pinned implementation prints NaN rather than the blank promised by
    its prose; keep that source behavior (including discarded &NaN&).
    """
    require_shared_selection(analysis)
    values = np.column_stack((analysis.run.cycle, analysis.run.time, analysis.values))
    masks = np.column_stack((np.ones((analysis.n_cycles, 2), dtype=bool), analysis.effective))
    def join(cells):
        return ''.join(f'{cell:<17}\t' for cell in cells).strip(' \t')
    stamp = '' if produced_on is None else produced_on.strftime('%m/%d/%y %H:%M:%S')
    text = ('New Tripoli tab-delimited output of processed data for:\n'
            f'Session: {_label(session_path)}\nAnalysis: {_label(data_path)}\nproduced on: {stamp}\n\n'
            'Data is presented by cycles.\nAny discarded values are wrapped in &s.\n'
            'Any missing values are represented as a blank entry.\n\n')
    text += join(['Cycle', 'Time', *[_label(f.name) for f in analysis.functions]]) + '\n'
    for row, included in zip(values, masks):
        cells = [str(int(v)) if i == 0 and ok else java_double(v) if ok else '&' + java_double(v) + '&'
                 for i, (v, ok) in enumerate(zip(row, included))]
        text += join(cells) + '\n'
    return text


OG_HEADER = 'Tripoli tab-delimited output of processed data for:'


def _e9(value):
    if not math.isfinite(value):
        return java_double(value)
    mantissa, exponent = format(value, '.9E').split('E')
    return f'{mantissa}E{int(exponent):+04d}'


def _og_name_rows(name):
    """Literal C# Split/Substring/PadRight behavior, including its third-row width."""
    parts = re.split(r'[\r\n]',name,maxsplit=1)
    first = _label(parts[0]).ljust(16)
    second = ''
    if len(parts) == 2:
        prefix = re.split(r'[w\\]',parts[1],maxsplit=1)[0]
        if len(prefix) < 2:
            raise ValueError('OG correction label is too short for its two-character prefix')
        second = _label(prefix[2:])
    third = re.split(r'[w\\]',name,maxsplit=1)
    third = 'w'+_label(third[1]).ljust(16) if len(third) == 2 else ' '*16
    return first, second.ljust(16), third


def og_text(analysis, *, source_name='', produced_on: date, keys=None) -> str:
    """TripoliWorkProduct.cs:2901-3051, Windows/en-US measured ratios.

    OG's arithmetic sum/sum-of-squares statistics are computed locally solely
    for this compatibility file. They never enter Analysis or /1 exports.
    """
    require_shared_selection(analysis)
    keys = list(keys if keys is not None else [f.key for f in analysis.functions if f.is_ratio
                                              or re.match(r'^\d{2,3}/\d{2,3}(?:\s|$)', f.name)])
    if not keys or len(set(keys)) != len(keys):
        raise ValueError('Select unique ratio columns for OG export')
    names = [_og_name_rows(analysis.function(k).name) for k in keys]
    values = analysis.values[:, [analysis.index(k) for k in keys]]
    if np.any(np.isfinite(values) & (values < 0)):
        raise ValueError('OG signed-mask dialect cannot represent negative measured values')
    effective = analysis.effective[:, [analysis.index(k) for k in keys]]
    cpb = analysis.run.metadata.cycles_per_block
    if not cpb or not np.array_equal(analysis.run.block, np.arange(analysis.n_cycles) // cpb + 1):
        raise ValueError('OG export requires regular, one-based blocks')
    lines = [OG_HEADER, _label(source_name), f'produced on: {produced_on.month}/{produced_on.day}/{produced_on.year}', '',
             'Each column header shows ratio name, Tripolized mean, Tripolized stdErr, Fractionation Corrected flag.',
             'Data is presented by blocks that are separated by blank lines. ',
             'Any discarded value is shown as a negative number. ',
             'Any missing value is represented by a blank entry. ', '',
             *[''.join(n[row]+'\t' for n in names) for row in range(3)]]
    means, errors = [], []
    for column, mask in zip(values.T, effective.T):
        accepted = column[mask & np.isfinite(column) & (column > 0)]
        n = len(accepted)
        total = squares = 0.
        # C# accumulates left to right; Python 3.12+'s sum(float) uses a
        # compensated algorithm and would alter OG's cancellation behavior.
        for x in accepted:
            total += float(x)
            squares += float(x)*float(x)
        mean = total / n if n else 0.
        variance = (squares-total*total/n)/(n-1) if n > 1 else 0.
        se = math.sqrt(variance) / math.sqrt(n) if variance >= 0 and n else (math.nan if n else 0.)
        means.append(mean)
        errors.append(100*se/mean if mean else 0.)
    lines += [''.join(_e9(x)+'\t' for x in means), ''.join(_e9(x)+'\t' for x in errors),
              ''.join(f'{"not frac corr":<16}\t' for _ in names), '']
    for i, row in enumerate(values):
        lines.append(''.join((' '*16 if not math.isfinite(v) or v == 0 else f'{_e9(v if effective[i,j] else -v):>16}')+'\t'
                             for j, v in enumerate(row)))
        if (i+1) % cpb == 0:
            lines.append('')
    return '\r\n'.join(lines) + '\r\n'


ET_NAMES = {'Pb': ('206_204','207_204','208_204','206_207','206_208','204_205','206_205','207_205','208_205','202_205'),
            'U': ('238_236','233_236','238_235','233_235','238_233')}


def et_redux_xml(fraction, element: str) -> str:
    """Pinned ETReduxFraction + MeasuredUserFunction schema; current measured stats.

    Java's builder leaves unmapped ratios at zero. No ratios are synthesized
    by dividing unrelated means. The selected Analysis statistic is retained.
    """
    analysis = fraction.analysis(element)
    if analysis is None or element not in ET_NAMES:
        raise ValueError('Select a Pb or U analysis')
    require_shared_selection(analysis)
    meta = analysis.run.metadata
    completed = meta.extra.get('end_status') == 'AnalysisCompleted' or meta.complete is True
    if meta.aborted or not completed:
        raise ValueError('ET_Redux XML requires explicit completed-analysis evidence')
    mapping = fraction.mapping(element)
    if mapping is None or not mapping.complete:
        raise ValueError('Resolve the measured-ratio mapping before ET_Redux export')
    if not fraction.sample or not fraction.fraction_id:
        raise ValueError('Sample and Fraction ID are required for ET_Redux export')
    entries = {}
    for name, mapped in mapping.ratios.items():
        masses = re.findall(r'\d+', name)
        et_name = '_'.join(masses)
        if et_name not in ET_NAMES[element]:
            continue
        stats = ratio_stats(analysis, mapped)
        if not math.isfinite(stats.mean) or not math.isfinite(stats.se_pct) or stats.n_used < 2:
            raise ValueError(f'{name}: ET_Redux requires at least two accepted cycles and finite statistics')
        function = analysis.function(mapped.key)
        entries[et_name] = (stats.mean, stats.se_pct,
                            bool(function.metadata.get('oxide_corrected') or function.metadata.get('derived') == 'oxide'))
    # Java includes named measured functions beyond the /1 subset (e.g.
    # 207/204 and 238/236). Only unique direct species ratios are eligible;
    # ambiguity requires an explicit mapping rather than a guessed choice.
    for et_name in ET_NAMES[element]:
        if et_name in entries:
            continue
        numerator, denominator = map(int, et_name.split('_'))
        candidates = [f for f in analysis.functions if f.is_ratio and f.numerator_mass == numerator
                      and f.denominator_mass == denominator and not f.metadata.get('raw')
                      and re.fullmatch(rf'{numerator}/{denominator}(?: [DF])?', f.name)
                      and (not fraction.collector or not f.collector or f.collector == fraction.collector)]
        if len(candidates) > 1:
            raise ValueError(f'{et_name}: ambiguous ET_Redux function; resolve duplicate columns before exporting')
        if candidates:
            function = candidates[0]
            stats = analysis.stats(function.key)
            if not math.isfinite(stats.mean) or not math.isfinite(stats.se_pct) or stats.n_used < 2:
                raise ValueError(f'{et_name}: ET_Redux requires at least two accepted cycles and finite statistics')
            entries[et_name] = (stats.mean, stats.se_pct,
                               bool(function.metadata.get('oxide_corrected') or function.metadata.get('derived') == 'oxide'))
    def node(name, value, indent=2):
        # Escaping text locally avoids importing saxutils' HTTP input helpers
        # into the Qt/network-free reduction package.
        value = _label(value).translate(str.maketrans({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&apos;'}))
        return ' '*indent + f'<{name}>{value}</{name}>'
    lines = ['<UPbReduxFraction>', node('sampleName',fraction.sample), node('fractionID',fraction.fraction_id),
             node('ratioType',element), node('pedigree','None'), '  <measuredRatios>']
    for name in ET_NAMES[element]:
        mean, se, oxide = entries.get(name, (0.,0.,False))
        lines += ['    <MeasuredUserFunctionModel>', node('name',name,6), node('value',java_double(mean),6),
                  node('uncertaintyType','PCT',6), node('oneSigma',java_double(se),6), node('fracCorr','false',6),
                  node('oxideCorr',str(oxide).lower(),6), '    </MeasuredUserFunctionModel>']
    lines += ['  </measuredRatios>']
    if element == 'U' and analysis.oxide.status == 'pass_through' and analysis.oxide.r18 is None:
        raise ValueError('ET_Redux requires known r18 for instrument oxide-corrected U functions')
    r18 = analysis.oxide.r18 if analysis.oxide.r18 is not None else analysis.settings.r18
    for name, value in [('meanAlphaU',0.),('meanAlphaPb',0.),('r18O16O',r18),('labUBlankMass',0.),
                        ('r238235b',0.),('r238235s',0.),('tracerMass',0.)]:
        lines.append(node(name,java_double(value)))
    return '\n'.join([*lines, '</UPbReduxFraction>', ''])


def write_exchange(path, text: str, *, overwrite=False) -> Path:
    """Exclusive creation by default; replacement requires an explicit caller choice."""
    path = Path(path)
    data = text.encode('utf-8')
    if not overwrite:
        with path.open('xb') as handle:
            handle.write(data)
    else:
        # Replace atomically after complete serialization, in the chosen folder.
        from tempfile import NamedTemporaryFile
        with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            try:
                handle.write(data)
                handle.flush()
            except BaseException:
                temp.unlink(missing_ok=True)
                raise
        try:
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)
    return path
