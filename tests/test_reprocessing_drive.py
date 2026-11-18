"""Private acquisition validation, read-only at runtime and optional off Drive."""
from dataclasses import replace

import numpy as np
import pytest

from rawtims.parity import drive_path
from rawtims.readers import open_run
from rawtims.readers.ionvantage_raw import PB_WORKBOOK_RTOL, U_WORKBOOK_RTOL
from rawtims.reduction_params import ReductionParameters, as_acquired
from rawtims.reprocess import reprocess

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("fraction,element", [(1, "Pb"), (2, "Pb"), (1, "U"), (2, "U")])
def test_raw_reconstruction_and_canonical_repeat(fraction, element):
    folder = drive_path()
    if not folder.is_dir():
        pytest.skip("BSU raw acquisitions unavailable")
    path = next(folder.glob(f"*KD33 z{fraction} {element}-*.xls"))
    run = open_run(path)
    params = as_acquired(run)
    assert reprocess(run, params).values.tobytes() == run.values.tobytes()
    raw_params = replace(params, route="raw")
    raw = reprocess(run, raw_params)
    rows = slice(None, -1) if element == "U" else slice(None)
    np.testing.assert_allclose(raw.values[rows], run.values[rows], rtol=U_WORKBOOK_RTOL if element == "U" else PB_WORKBOOK_RTOL, atol=0)
    assert raw.keys == run.keys and np.array_equal(raw.cycle, run.cycle)
    if element == "U":
        assert any("270/267" in w for w in raw.warnings)
        assert any("terminal" in w for w in raw.warnings)
        assert not np.array_equal(raw.values[-1], run.values[-1])
    import json
    repeat = reprocess(run, ReductionParameters.from_dict(json.loads(raw_params.canonical_json())))
    assert repeat.values.tobytes() == raw.values.tobytes()


def test_end_to_end_demo_is_reproducible():
    from pathlib import Path

    from rawtims.parity import sheets_path
    from rawtims.recalculation import run_recalculation_demo
    age_repo = Path.home() / "Github" / "IDTIMS_UPbRPy"
    if not drive_path().is_dir() or not (sheets_path() / "KD33_ BSULab_UPbR24XML.xls").is_file() or not (age_repo / ".venv/bin/python").is_file():
        pytest.skip("private demo inputs or separate age-engine venv unavailable")
    result, scratch, markdown = run_recalculation_demo(age_repo=age_repo)
    assert result["reproducibility"]["contract_bit_identical"]
    assert result["reproducibility"]["dates_bit_identical"]
    assert result["reproducibility"]["u_unchanged"]
    assert len(result["clipboard"]) == 9
    assert all(v["provenance_roundtrip"] for v in result["ages"]["runs"].values())
    assert (scratch / "settings.json").is_file() and "per_ratio" in markdown
