"""The demo never links on a name match without --confirm."""
from datetime import datetime

import pytest
from reader_fixtures import SYNTHETIC_PB
from test_upbdb import candidate

from rawtims.contract import read_csv
from rawtims.upbdb import MatchResult
from scripts import database_link_demo as demo


class DemoClient:
    server = "https://example.com"

    def __init__(self, server):
        self.account = {"username": "alice"}
        assert server == "https://example.com"

    def login(self, username, password):
        assert username == "alice" and password == "secret"

    def lookup(self, fid):
        return MatchResult([candidate()])


@pytest.mark.parametrize("confirmed", [False, True])
def test_demo_explicit_confirmation_only(tmp_path, monkeypatch, confirmed):
    monkeypatch.setenv("FILAMENT_UPBDB_PASSWORD", "secret")
    monkeypatch.setattr(demo, "Client", DemoClient)
    output = tmp_path / "demo.csv"
    from rawtims_gui.workspace import Workspace
    workspace = Workspace()
    workspace.open([SYNTHETIC_PB])
    fid = workspace.fractions[0].fraction_id
    args = ["--server", "https://example.com", "--username", "alice", "--output", str(output)]
    if confirmed:
        args += ["--confirm", fid + "=f1"]
    args.append(str(SYNTHETIC_PB))
    demo.main(args)
    rows = read_csv(output)
    assert len(rows) == 1
    assert rows[0].get("Fraction UID") == ("f1" if confirmed else None)
    assert rows[0].get("Sample") == ("AH1-gc1" if confirmed else workspace.fractions[0].sample)
    assert datetime.fromisoformat(rows[0].get("Exported At")).utcoffset() is not None


def test_demo_wrong_confirmation_never_exports(tmp_path, monkeypatch):
    monkeypatch.setenv("FILAMENT_UPBDB_PASSWORD", "secret")
    monkeypatch.setattr(demo, "Client", DemoClient)
    output = tmp_path / "demo.csv"
    from rawtims_gui.workspace import Workspace
    workspace = Workspace()
    workspace.open([SYNTHETIC_PB])
    fid = workspace.fractions[0].fraction_id
    with pytest.raises(SystemExit):
        demo.main(["--server", "https://example.com", "--username", "alice", "--output", str(output),
                   "--confirm", fid + "=wrong", str(SYNTHETIC_PB)])
    assert not output.exists()


def test_demo_same_named_candidates_show_project_and_sample_uuid_tail(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("FILAMENT_UPBDB_PASSWORD", "secret")
    monkeypatch.setattr(demo, "Client", DemoClient)
    choices = [candidate(), candidate()]
    for choice, project, tail in zip(choices, ("P1", "P2"), ("12345678", "87654321")):
        choice.sample.update(name="KG5", id="00000000-0000-0000-0000-0000" + tail, project={"code": project})
    monkeypatch.setattr(DemoClient, "lookup", lambda _self, _fid: MatchResult(choices))
    demo.main(["--server", "https://example.com", "--username", "alice", "--output", str(tmp_path / "demo.csv"),
               str(SYNTHETIC_PB)])
    output = capsys.readouterr().out
    assert "KG5 / P1 [12345678] z1" in output
    assert "KG5 / P2 [87654321] z1" in output
