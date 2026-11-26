"""In-memory synthetic UI stress data. Never part of the real-data manifest."""
from copy import copy
from dataclasses import replace

import numpy as np

from rawtims.analysis import Analysis
from rawtims.model import Function


def install_synthetic_review(window):
    """Twelve functions, twenty blocks, four hundred cycles, forty 60-char IDs."""
    source = window.analysis.run
    functions = [replace(source.function(key), index=i) for i, key in enumerate(window.plotted_keys()[:12])]
    functions += [Function(i, f'Synthetic ratio {i}', f'Synthetic ratio {i}', 'ratio') for i in range(len(functions), 12)]
    cycle = np.arange(1, 401)
    values = np.column_stack([(i + 1) * (1 + .03 * np.sin(cycle * .37 + i)) for i in range(12)])
    run = replace(source, run_id='synthetic-review-run',
                  raw=replace(source.raw, path='synthetic-review-memory', name='synthetic-review-memory'),
                  functions=tuple(functions), cycle=cycle, block=(cycle - 1) // 20 + 1,
                  time=cycle.astype(float), values=values, invalid=np.zeros_like(values, dtype=bool))
    analysis = Analysis(run)
    fraction = copy(window.current[0])
    fraction.pb = analysis
    fraction.u = None
    fractions = []
    for i in range(40):
        item = copy(fraction)
        item.fraction_id = f'Synthetic laboratory fraction {i:02d} '.ljust(60, 'x')
        fractions.append(item)
    window.workspace.fractions = fractions
    window.fraction_list.set_fractions(fractions, None)
    window.select_run(fractions[0], 'Pb')
    window.set_plotted(run.keys)
    return run
