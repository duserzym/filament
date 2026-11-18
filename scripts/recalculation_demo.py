#!/usr/bin/env python3
"""Reproduce the private KD33 z1 reduction demo without opening any windows."""
from __future__ import annotations

import argparse
from pathlib import Path

from rawtims.recalculation import run_recalculation_demo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=Path)
    parser.add_argument("--sheet", type=Path)
    parser.add_argument("--age-repo", type=Path)
    parser.add_argument("--report", type=Path, default=Path(__file__).resolve().parents[1] / "docs" / "recalculation-demo.md")
    args = parser.parse_args()
    _evidence, scratch, markdown = run_recalculation_demo(folder=args.examples, sheet=args.sheet, age_repo=args.age_repo)
    args.report.write_text(markdown)
    print(markdown)
    print(f"Aggregate report: {args.report}\nScratch artifacts: {scratch}")


if __name__ == "__main__":
    main()
