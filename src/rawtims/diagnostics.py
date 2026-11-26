"""Opt-in diagnostics. These arrays never join Analysis or the export mapping."""
from __future__ import annotations

import numpy as np


def oxygen_monitor(ratio_272_270, *, verified_uo2: bool = False) -> np.ndarray:
    """Return (238U16O18O / 238U16O2) / 2 after explicit assignment verification.

    Mass numbers alone cannot establish molecular identities. Invalid inputs
    remain absent; this monitor never substitutes for acquisition r18.
    """
    if not verified_uo2:
        raise ValueError("Verified UO2 molecular assignment is required")
    values = np.asarray(ratio_272_270, dtype=float)
    return np.where(np.isfinite(values) & (values > 0), values / 2, np.nan)
