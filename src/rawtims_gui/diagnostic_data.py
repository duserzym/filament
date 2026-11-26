"""Pure presentation transforms, preserving original acquisition row identities."""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class DisplayOptions:
    stats: bool = True
    bands: str = "2σ, σ, SE"
    block_means: bool = False
    rejected: str = "Pinned"
    inverted: bool = False
    frozen: bool = False


def reciprocal(values):
    values = np.asarray(values, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(np.isfinite(values) & (values != 0), 1 / values, np.nan)


def histogram(values, included, bins=20):
    """Common finite-sample edges; accepted and rejected counts share every bin."""
    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    edges = np.histogram_bin_edges(values[finite], bins=bins)
    # Tripoli's epsilon places a datum exactly on an internal positive edge
    # in the lower bin. Clamp the right endpoint as Java does. Unlike its
    # ensemble primitive, retain zero-valued cycle measurements in the counts.
    width = edges[1] - edges[0]
    indices = np.minimum(np.floor(np.abs((values[finite] - edges[0] * 1.000000001) / width)).astype(int), len(edges)-2)
    accepted = np.bincount(indices[included[finite]], minlength=len(edges)-1)
    rejected = np.bincount(indices[~included[finite]], minlength=len(edges)-1)
    return edges, accepted, rejected


def dot_sizes(intensity, minimum=4., maximum=12.):
    """Java's linear radius scaling, expressed as pyqtgraph diameters."""
    if not 0 < minimum <= maximum:
        raise ValueError("Dot radii must be positive and ordered")
    values = np.asarray(intensity, dtype=float)
    usable = np.isfinite(values) & (values != 0)
    sizes = np.full(values.shape, 2 * minimum)
    if usable.any():
        lo, hi = values[usable].min(), values[usable].max()
        # Java uses [0, 1] for a constant intensity column.
        if lo == hi:
            lo, hi = 0., 1.
        sizes[usable] = 2 * (minimum + np.clip((values[usable] - lo) / (hi - lo), 0, 1) * (maximum - minimum))
    return sizes
