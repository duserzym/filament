#!/usr/bin/env python3
"""Look up raw fractions and export only explicitly confirmed database links.

Example:
  python scripts/database_link_demo.py \
    --server http://localhost:8000 --username alice --output demo.fractions.csv \
    --confirm 'KD33 z1=<fraction uuid>' run1.xls run2.xls

Without --confirm, the CSV is an ordinary unlinked fractions export.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from rawtims.branding import DATABASE_PASSWORD_ENV
from rawtims.contract import write_csv
from rawtims.fractions import apply_link, database_link_warnings
from rawtims.upbdb import Client, DatabaseError
from rawtims_gui.workspace import Workspace


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=f"Set {DATABASE_PASSWORD_ENV} to the account password before running.")
    parser.add_argument("--server", required=True)
    parser.add_argument("--username", required=True)
    parser.add_argument("--output", type=Path, default=Path("database-demo.fractions.csv"))
    parser.add_argument("--confirm", action="append", default=[], metavar="SAMPLE FRACTION=UUID")
    parser.add_argument("raw_files", nargs="+")
    args = parser.parse_args(argv)
    password = os.environ.get(DATABASE_PASSWORD_ENV)
    if not password:
        parser.error(f"Set {DATABASE_PASSWORD_ENV} in the environment.")
    confirmations = {}
    for text in args.confirm:
        fid, separator, uid = text.rpartition("=")
        if not separator or not fid.strip() or not uid.strip() or fid in confirmations:
            parser.error("Each --confirm must uniquely name a raw Fraction ID and UUID: 'KD33 z1=<uuid>'.")
        confirmations[fid] = uid.strip()
    try:
        client = Client(args.server)
        client.login(args.username, password)
        workspace = Workspace()
        opened = workspace.open(args.raw_files)
        for path, reason in opened.skipped:
            print(f"Skipped {path}: {reason}")
        known = {f.fraction_id for f in workspace.fractions}
        if set(confirmations) - known:
            parser.error("Unknown confirmation Fraction ID(s): " + ", ".join(sorted(set(confirmations) - known)))
        for fraction in workspace.fractions:
            result = client.lookup(fraction.fraction_id)
            print(f"{fraction.fraction_id}: {result.message}")
            for candidate in result.candidates:
                f = candidate.fraction
                print(f"  {f['id']} · {candidate.sample_label} {f['name']} · "
                      f"{f.get('capsule_label') or ''} {f.get('capsule_set_name') or ''} · "
                      f"batch {candidate.batch.get('started_on', '')}")
                if candidate.chemistry_message:
                    print("  " + candidate.chemistry_message)
            if fraction.fraction_id in confirmations:
                selected = [c for c in result.candidates if c.fraction["id"] == confirmations[fraction.fraction_id]]
                if len(selected) != 1:
                    parser.error(f"Confirmation for {fraction.fraction_id!r} does not identify exactly one visible candidate.")
                apply_link(fraction, selected[0].confirm(client.server, client.account["username"]))
                print("  Linked by explicit --confirm")
                for warning in database_link_warnings(fraction):
                    print("  " + warning)
        rows, left = workspace.export_rows(datetime.now().astimezone())
        for fid, reason in left:
            print(f"Cannot export {fid}: {reason}")
        if not rows or any(fid in confirmations for fid, _reason in left):
            parser.error("No exportable rows, or a confirmed fraction cannot be exported.")
        write_csv(rows, args.output)
        print(f"Wrote {len(rows)} fraction(s) to {args.output}")
    except DatabaseError as error:
        parser.exit(1, str(error) + "\n")


if __name__ == "__main__":
    main()
