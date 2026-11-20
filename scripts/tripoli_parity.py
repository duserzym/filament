#!/usr/bin/env python3
"""Audit read-only legacy Tripoli projects and write a summary-only Markdown report."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rawtims.parity import drive_path, render_report, run_parity, sheets_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--drive', type=Path, default=drive_path())
    parser.add_argument('--sheets', type=Path, default=sheets_path())
    parser.add_argument('--output', type=Path, default=Path('docs/tripoli-parity.md'))
    args = parser.parse_args(argv)
    # Guard both requested inputs and the known Drive roots, even when an env
    # override is used. Reporting must never create a file under either Drive.
    protected = [args.drive.resolve(), args.sheets.resolve()]
    protected += [p for p in Path.home().glob('*Drive*') if p.is_dir()]
    output = args.output.resolve()
    if any(output == p or p in output.parents for p in protected):
        parser.error('report output must be outside the read-only data folders')
    if not args.drive.is_dir() or not list(args.drive.glob('*.trip')):
        parser.error('no legacy projects found in the data folder')
    audit = run_parity(args.drive, args.sheets)
    args.output.write_text(render_report(audit), encoding='utf-8')
    for p in audit.projects:
        print(f'{p.label}: {p.status}; {len(p.failures)} unexpected mismatches')
    print(f'{len(audit.projects)} distinct projects; {sum(not p.issues and not p.failures for p in audit.projects)} workbook-backed; '
          f'{sum(p.sheet_matches for p in audit.projects)} pasted ratio pairs matched; {audit.seconds:.3f} s')
    print(f'Report: {args.output}')
    if not audit.sheet_count:
        print('BSU spreadsheets unavailable: independent clipboard validation not performed', file=sys.stderr)
    return 0 if audit.passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
