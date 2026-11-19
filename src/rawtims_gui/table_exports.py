"""Review tables; openpyxl is a desktop extra, imported only for XLSX export."""
from __future__ import annotations

import csv
import math
from pathlib import Path
from tempfile import NamedTemporaryFile

from rawtims.contract import header_for
from rawtims.fractions import require_shared_selection


def tables(rows, fractions):
    header = header_for(rows)
    fraction_table = [header, *[[r.get(k) for k in header] for r in rows]]
    keys = list(dict.fromkeys(k for f in fractions for a in (f.pb, f.u) if a for k in a.keys))
    cycles = [["Fraction ID", "Element", "Source", "Block", "Cycle", "Time (s)",
               *[name for key in keys for name in (key, key + " included")]]]
    provenance = [["Fraction ID", "Element", "Warnings", "Reduction parameters", "Route", "Source SHA-256"]]
    for f in fractions:
        for element, a in (("Pb", f.pb), ("U", f.u)):
            if a is None:
                continue
            require_shared_selection(a)
            effective = a.effective
            cols = {k: a.index(k) for k in a.keys}
            provenance.append([f.fraction_id, element, '\n'.join(a.run.warnings),
                               a.run.reduction_parameters.canonical_json(), a.run.reduction_parameters.route, a.run.raw.sha256])
            for i in range(a.n_cycles):
                row = [f.fraction_id, element, a.run.raw.name, int(a.run.block[i]), int(a.run.cycle[i]), float(a.run.time[i])]
                for key in keys:
                    col = cols.get(key)
                    row.extend((float(a.values[i, col]), int(effective[i, col])) if col is not None else (None, None))
                cycles.append([None if isinstance(v, float) and not math.isfinite(v) else v for v in row])
    return {"Fractions": fraction_table, "Cycles": cycles, "Provenance": provenance}


def write_xlsx(path, rows, fractions):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    data = tables(rows, fractions)
    book = Workbook()
    book.remove(book.active)
    for name, table in data.items():
        sheet = book.create_sheet(name)
        for row in table:
            sheet.append(row)
            for cell in sheet[sheet.max_row]:
                if isinstance(cell.value, str):
                    cell.data_type = 's'  # instrument labels and notes are data, never formulas
        sheet.freeze_panes = 'A2'
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='344A60')
        for col in range(1, sheet.max_column + 1):
            sheet.column_dimensions[get_column_letter(col)].width = min(38, max(14, len(str(sheet.cell(1, col).value)) + 2))
    path = Path(path)
    with NamedTemporaryFile(dir=path.parent, suffix='.xlsx', delete=False) as temp:
        tmp = Path(temp.name)
    try:
        book.save(tmp)
        tmp.replace(path)
    finally:
        book.close()
        tmp.unlink(missing_ok=True)
    return path


def write_tables_csv(folder, rows, fractions):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    outputs = []
    for name, table in tables(rows, fractions).items():
        path = folder / (name.lower() + '.csv')
        with path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.writer(handle)
            writer.writerows(table)
        outputs.append(path)
    return outputs
