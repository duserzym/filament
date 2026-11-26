"""Explicit, inert OGTripoli text migration, independent of vendor dispatch."""
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rawtims.readers import UnsupportedFile
from rawtims.tripoli_exchange import OG_HEADER


@dataclass(frozen=True)
class OgText:
    names: tuple[str, ...]
    values: np.ndarray
    included: np.ndarray
    block: np.ndarray
    header: tuple[str, ...]
    statistics: tuple[tuple[str, ...], ...]
    source: bytes


def parse_og_text(data: bytes) -> OgText:
    """OGTripoli TripoliWorkProduct.cs:2901-3051; Java OgTripoliImporter.java:42-184.

    Preserve all six header rows, signed masks and missing values. Never apply
    saved means, correction flags or settings to a new numerical analysis.
    Multi-line/corrected labels are retained verbatim for inspection.
    """
    if len(data) > 64*1024*1024:
        raise UnsupportedFile('OG text byte limit exceeded')
    try:
        lines = data.decode('utf-8-sig').splitlines()
        if len(lines) < 17 or lines[0] != OG_HEADER:
            raise UnsupportedFile('Not an OGTripoli processed-data text export')
        def cells(line):
            parts = line.split('\t')
            if parts[-1] == '':
                parts.pop()
            return tuple(p.strip() for p in parts)
        names = cells(lines[9])
        if not names or any(not n for n in names) or len(names) > 1000:
            raise UnsupportedFile('Invalid OG function headers')
        saved = tuple(cells(line) for line in lines[10:15])
        if any(len(row) != len(names) for row in saved) or lines[15].strip():
            raise UnsupportedFile('Unrecognized OG statistics/header layout')
        if any(flag not in ('not frac corr', 'frac corr') for flag in saved[-1]):
            raise UnsupportedFile('Unrecognized OG correction flag')
        rows, blocks = [], []
        block, separator = 1, False
        for line in lines[16:]:
            if not line.strip() and '\t' not in line:
                separator = bool(rows)
                continue
            if separator:
                block += 1
                separator = False
            row = cells(line)
            if len(row) != len(names):
                raise UnsupportedFile('Ragged OG cycle row')
            values = [float(v) if v else np.nan for v in row]
            if any(np.isinf(v) for v in values):
                raise UnsupportedFile('Non-finite OG cycle value')
            rows.append(values)
            blocks.append(block)
            if len(rows)*len(names) > 2_000_000:
                raise UnsupportedFile('OG cycle slot limit exceeded')
        if not rows:
            raise UnsupportedFile('OG export contains no cycles')
        signed = np.array(rows)
        return OgText(names, np.abs(signed), np.isfinite(signed) & (signed > 0), np.array(blocks), tuple(lines[:9]), saved, data)
    except (UnicodeError, ValueError, IndexError) as error:
        if isinstance(error, UnsupportedFile):
            raise
        raise UnsupportedFile(f'Malformed OG text: {error}') from error


def read_og_text(path) -> OgText:
    with Path(path).open('rb') as handle:
        return parse_og_text(handle.read(64*1024*1024+1))
