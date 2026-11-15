"""filament's default oxide formula equals legacy C# Tripoli's, the program behind Yiming's BSU numbers.

Legacy Tripoli (CIRDLES/OGTripoli 4.10.0.3, ``source/TripoliWorkProduct.cs``,
``PerformOxideCorrectionFor233_235Tracer``, lines 2655-2672) computes per cycle, in ``decimal``::

    denominator = 1 / R265_267 - 2 * r18
    r233_235    = 1 / denominator
    r238_235    = (R270_267 / R265_267) / denominator
    r238_233    = r238_235 / r233_235

with ``r18`` = ``_r18O_16O`` (line 131), taken from the user's saved ``USampleComponents.DefaultR18O_16O``
(set in the Oxide Correction dialog, ``forms/frmOxideCorrection.cs``; 0.0020 if unset). Algebraically
``r233_235 = R265/267 / (1 - 2·r18·R265/267)`` and ``r238_235 = R270/267 / (1 - 2·r18·R265/267)``, which is
``isobar_233_18O``. The test re-implements the legacy steps literally (in Decimal, as the C# code does) and
compares them with filament on real cycles.
"""

from __future__ import annotations

from decimal import Decimal, getcontext

import numpy as np
import pytest

from rawtims import oxide
from reader_fixtures import TIMSDP_FILES, read

getcontext().prec = 28  # C# decimal carries 28-29 significant digits


def legacy_tripoli(r265_267: float, r270_267: float, r18: float) -> tuple[float, float, float]:
    denominator = (Decimal(1) / Decimal(r265_267)) - (Decimal(2) * Decimal(str(r18)))
    r233_235 = Decimal(1) / denominator
    r238_235 = (Decimal(r270_267) / Decimal(r265_267)) / denominator
    return float(r233_235), float(r238_235), float(r238_235) / float(r233_235)


@pytest.mark.parametrize("r18", [0.0020, 0.00205, 0.00206])
def test_isobar_233_18O_equals_legacy_tripoli_on_real_cycles(r18):
    run = read(TIMSDP_FILES["GHR1 230921F03 U-239"])
    _, _, r265, r270 = oxide.find_inputs(run)
    ok = np.isfinite(r265) & np.isfinite(r270) & (r265 > 0) & (r270 > 0)
    r265, r270 = r265[ok], r270[ok]
    ours = oxide.correct(r265, r270, r18, "isobar_233_18O")
    legacy = np.array([legacy_tripoli(a, b, r18) for a, b in zip(r265, r270)]).T
    for mine, theirs in zip(ours, legacy):
        assert np.max(np.abs(mine / theirs - 1.0)) < 1e-14


def test_isobar_233_18O_equals_legacy_tripoli_at_bsu_magnitudes():
    # 233/235 and 238/235 of the size in Yiming's BSU sheets, R18 = 0.00206.
    for r265, r270 in [(1.0012, 0.4644), (1.0049, 0.3377)]:
        ours = oxide.correct(np.array([r265]), np.array([r270]), 0.00206, "isobar_233_18O")
        legacy = legacy_tripoli(r265, r270, 0.00206)
        for mine, theirs in zip(ours, legacy):
            assert mine[0] == pytest.approx(theirs, rel=1e-15)


def test_java_tripoli_form_differs_from_legacy():
    a = legacy_tripoli(0.97291, 2.42704, 0.00205)[1]
    b = oxide.correct(np.array([0.97291]), np.array([2.42704]), 0.00205, "tripoli_java_00dc941")[1][0]
    assert b / a - 1.0 == pytest.approx(0.00602, abs=2e-5)
