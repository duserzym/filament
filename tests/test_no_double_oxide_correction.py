"""A file that already carries oxide-corrected U columns is never corrected again.

Where BSU's `238/235 oxide R18 0.00206` columns are computed is still open (docs/oxide-correction.md). These
are behaviour tests on the synthetic BSU-style U workbook (no BSU agreement is claimed):
the file carries both the corrected functions and the raw 270/267 and 265/267 columns, which is exactly
the situation where a double correction could happen.
"""

from __future__ import annotations

import numpy as np
import pytest

from rawtims.analysis import Analysis
from rawtims.fractions import Fraction, fraction_row
from rawtims.oxide import FORMULAS
from reader_fixtures import SYNTHETIC_U, read
from datetime import datetime, timezone

EXPORTED_AT = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
CORRECTED = {
    "238U/235U": "238/235 oxide R18 0.00206",
    "233U/235U": "233/235 oxide R18 0.00206",
    "238U/233U": "238/233 oxide",
}


def _geometric_mean(analysis: Analysis, key: str) -> float:
    values = analysis.run.column(key)
    ok = np.isfinite(values) & (values > 0)
    return float(np.exp(np.log(values[ok]).mean()))


def test_behaviour_file_has_both_raw_and_corrected_columns():
    keys = set(read(SYNTHETIC_U).keys)
    assert {"270/267", "265/267"} <= keys and set(CORRECTED.values()) <= keys


@pytest.mark.parametrize("stat_mode", ["arithmetic", "geometric"])
@pytest.mark.parametrize("formula", FORMULAS)
@pytest.mark.parametrize("r18", [0.00205, 0.00206, 0.0021])
def test_behaviour_instrument_corrected_u_is_passed_through_whatever_the_settings(formula, r18, stat_mode):
    analysis = Analysis(read(SYNTHETIC_U))
    analysis.set_setting("stat_mode", stat_mode)
    analysis.set_setting("r18", r18)
    analysis.set_setting("oxide_formula", formula)
    assert analysis.oxide.status == "pass_through"
    assert not any(key.endswith("oc") for key in analysis.keys), "no derived oxide-corrected functions"
    row = fraction_row(Fraction("SYN U", u=analysis), EXPORTED_AT)
    assert row.values["U Oxide Formula"] == "instrument"
    assert row.values["U Oxide 18O/16O"] == 0.00206  # from the function names, not the setting
    for ratio, key in CORRECTED.items():
        values = analysis.run.column(key)
        expected = _geometric_mean(analysis, key) if stat_mode == "geometric" else float(values[np.isfinite(values) & (values > 0)].mean())
        assert row.mean(ratio) == pytest.approx(expected, rel=1e-14)
