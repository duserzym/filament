# Vendored from UPbRPy e91ae97, UPbRPy/naming.py; unchanged below.
"""Ordering helpers for sample and spot labels."""

import re


def natural_sort_key(text: str) -> tuple:
    """Compare digit runs as integers and other runs with ``casefold``.

    Punctuation stays in the text runs: ``30.7`` compares as 30, ".", 7,
    rather than as a decimal. Tagged chunks make mixed text/number positions
    comparable. The original string breaks case and leading-zero ties.
    """
    chunks = tuple(
        (0, int(part)) if part.isdecimal() else (1, part.casefold())
        for part in re.split(r"(\d+)", text) if part
    )
    return chunks, text
