"""Headless ``--verify``: open run files, pair them, write the contract CSV, no window (SPEC section 7).

``<app> --verify PATH ... --verification-output OUT.csv`` opens the files and
folders, pairs the runs into fractions by sample ID, uses the default mapping
(no remembered mappings, no user edits) and applies no rejection (SPEC section
0, decision 3). Every fraction that gives a valid contract row is written to
``OUT.csv`` (atomically, :func:`rawtims.contract.write_csv`). Fractions that
cannot be exported are listed on stderr with the reason.

Exit status: 0 when at least one row was written, 1 when nothing was
exportable (with a message), 2 for usage errors (argparse).

The packaged-app smoke test runs this in the frozen app and in the source
environment and compares the two files cell by cell (all but ``Exported At``).
Nothing here imports Qt.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
import sys
from typing import TextIO

from rawtims.contract import write_csv
from rawtims_gui.workspace import Workspace, describe_path


def run_verify(paths: Sequence[str], output: str | Path, *, stdout: TextIO | None = None, stderr: TextIO | None = None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    workspace = Workspace()
    result = workspace.open(list(paths))
    for path, reason in result.skipped:
        print(f"skipped {describe_path(path)}: {reason}", file=stderr)
    rows, left_out = workspace.export_rows(datetime.now().astimezone())
    for fraction_id, reason in left_out:
        print(f"not exported: {fraction_id}: {reason}", file=stderr)
    if not rows:
        opened = len(result.added)
        print(f"Nothing exportable: {opened} run{'s' if opened != 1 else ''} opened, no fraction gave a contract row.", file=stderr)
        return 1
    output = Path(output).expanduser()
    write_csv(rows, output)
    print(f"Wrote {len(rows)} fraction row{'s' if len(rows) != 1 else ''} to {output}", file=stdout)
    return 0


__all__ = ["run_verify"]
