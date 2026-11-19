"""Launcher discovery and XLSX data never execute commands during tests."""
import plistlib

from rawtims_gui import age_app


def test_configured_command_is_argv_and_appends_open(tmp_path,monkeypatch):
    executable=tmp_path/'python with spaces'
    executable.touch()
    csv=tmp_path/'contract with spaces.csv'
    csv.touch()
    launched=[]
    result=age_app.send(csv,f'"{executable}" -m idtims_app',launcher=lambda argv:launched.append(argv))
    assert launched==[[str(executable),'-m','idtims_app','--open',str(csv)]]
    assert 'opened' in result


def test_app_discovery_by_bundle_id(tmp_path):
    app=tmp_path/'Different name.app'
    (app/'Contents').mkdir(parents=True)
    (app/'Contents'/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':age_app.BUNDLE_ID}))
    assert age_app.discover(platform='darwin',roots=[tmp_path])==['open','-n','-a',str(app),'--args']


def test_absent_or_bad_app_reveals_file(tmp_path,monkeypatch):
    monkeypatch.setattr(age_app,'discover',lambda command:None)
    revealed=[]
    def never(*args):raise AssertionError('must not launch')
    text=age_app.send(tmp_path/'fractions.csv',launcher=never,reveal=revealed.append)
    assert revealed==[tmp_path/'fractions.csv']
    assert 'not found' in text


def test_reveal_selects_exact_file_without_real_launch(tmp_path):
    launched = []
    path = tmp_path / 'saved contract.csv'
    age_app.reveal_file(path, platform='darwin', launcher=launched.append)
    assert launched == [['/usr/bin/open', '-R', str(path)]]
