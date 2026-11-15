"""The window's fractions without Qt: pairing across imports, duplicates, renames and merges."""

from __future__ import annotations

import os
import subprocess
import sys

from reader_fixtures import B998, GHR1_PB_XLS, GHR1_U_XLS, TIMSDP_FILES
from rawtims.analysis import Analysis
from rawtims.readers import open_run
from rawtims_gui.workspace import Workspace


def test_workspace_needs_no_qt():
    code = "import sys, rawtims_gui.workspace; print(any(m.split('.')[0] == 'PySide6' for m in sys.modules))"
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False"


def test_later_imports_join_open_fractions_and_skip_duplicates():
    workspace = Workspace()
    first = workspace.open([GHR1_PB_XLS])
    assert [f.fraction_id for f in first.fractions] == ["GHR1 20200827-11"]
    second = workspace.open([GHR1_U_XLS, GHR1_PB_XLS])
    assert len(workspace.fractions) == 1
    fraction = workspace.fractions[0]
    assert fraction.pb.run.raw.name == GHR1_PB_XLS.name and fraction.u.run.raw.name == GHR1_U_XLS.name
    assert [a.run.raw.name for a in second.added] == [GHR1_U_XLS.name]
    assert len(second.skipped) == 1 and "already open" in second.skipped[0][1]
    assert workspace.mapping(fraction.u).function_keys == ["238/235oc", "233/235oc", "238/233oc"]


def test_a_second_run_of_the_same_element_gets_its_own_fraction():
    workspace = Workspace()
    workspace.open([B998])
    # Same content under a different identity is a duplicate; a second Pb run with the same ID is not.
    run = open_run(B998)
    clone = Analysis(type(run)(**{**run.__dict__, "raw": type(run.raw)(**{**run.raw.__dict__, "sha256": "0" * 64})}))
    result = workspace.add([clone])
    assert [f.fraction_id for f in workspace.fractions] == ["13223M02 iz1", "13223M02 iz1 #2"]
    assert result.fractions[0].pb is clone


def test_rename_merges_fitting_fractions_and_refuses_clashes():
    workspace = Workspace()
    workspace.open([TIMSDP_FILES["GHR1 230921 F08b-216"], TIMSDP_FILES["GHR1 230921F03 U-239"], B998])
    ids = [f.fraction_id for f in workspace.fractions]
    assert ids == ["GHR1 230921 F08", "GHR1 230921F01", "13223M02 iz1"]
    u_only = workspace.find("GHR1 230921F01")
    ok, message, holder = workspace.rename(u_only, "  ")
    assert not ok and holder is u_only
    ok, message, holder = workspace.rename(u_only, "GHR1 230921 F08")
    assert ok and "Merged" in message and holder.pb is not None and holder.u is not None
    assert [f.fraction_id for f in workspace.fractions] == ["GHR1 230921 F08", "13223M02 iz1"]
    ok, message, holder = workspace.rename(workspace.find("13223M02 iz1"), "GHR1 230921 F08")
    assert not ok and "already has a Pb run" in message
    ok, _, holder = workspace.rename(workspace.find("13223M02 iz1"), "z1")
    assert ok and holder.fraction_id == "z1"
