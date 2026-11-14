"""Content sniffing, unsupported files and folder imports."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil

import numpy as np
import pytest

from rawtims.model import FORMAT_IONVANTAGE_XLS, FORMAT_ISOLINX_TIMSDP
from rawtims.readers import UnsupportedFile, open_paths, open_run, sniff
from reader_fixtures import FIXTURES, NBS981_XLS, SYNTHETIC, TIMSDP_FILES, TRIPOLI

ROOT = Path(__file__).resolve().parents[1]


def _writer():
    spec = importlib.util.spec_from_file_location("make_synthetic_fixtures", ROOT / "scripts" / "make_synthetic_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_files() -> list[Path]:
    return sorted([*TRIPOLI.rglob("*.xls"), *TRIPOLI.rglob("*.TIMSDP"), *SYNTHETIC.glob("*.xls")])


def test_open_paths_on_the_fixtures_folder():
    runs, skipped = open_paths([FIXTURES])
    assert sorted(Path(run.raw.path).resolve() for run in runs) == [p.resolve() for p in _run_files()]
    assert len(runs) == 14
    for run in runs:
        ratio = np.array([function.is_ratio for function in run.functions])
        with np.errstate(invalid="ignore"):
            expected = ~np.isfinite(run.values) | (ratio[None, :] & ~(run.values > 0))
        assert np.array_equal(run.invalid, expected), run.raw.name
    reasons = {path.name: reason for path, reason in skipped}
    oracles = sorted(p.name for p in (TRIPOLI / "oracle").rglob("*") if p.is_file())
    assert set(oracles) <= set(reasons)
    for name in oracles:
        if name.endswith(".tsv"):
            assert reasons[name] == "Tripoli report, not a raw run file"
        else:
            assert "not an IsoLinx .TIMSDP or IonVantage .xls run file" in reasons[name]
    # A fractions CSV (the vendored legacy MA1 file) is not a run file either.
    assert "not an IsoLinx .TIMSDP or IonVantage .xls run file" in reasons["MA1_zircon_CA-ID-TIMS.csv"]
    assert set(reasons) == set(oracles) | {"MANIFEST.toml", "LICENSE-APACHE-2.0", "NOTICE", "MA1_zircon_CA-ID-TIMS.csv"}


def test_open_paths_ignores_hidden_and_temporary_files(tmp_path):
    source = TIMSDP_FILES["WH233B z3 Pb-678"]
    shutil.copy(source, tmp_path / "run.TIMSDP")
    shutil.copy(source, tmp_path / ".hidden.TIMSDP")
    shutil.copy(source, tmp_path / "run.TIMSDP~")
    shutil.copy(source, tmp_path / "copy.tmp")
    shutil.copy(NBS981_XLS, tmp_path / "~$lock.xls")
    (tmp_path / ".cache").mkdir()
    shutil.copy(source, tmp_path / ".cache" / "inside.TIMSDP")
    (tmp_path / "sub").mkdir()
    shutil.copy(NBS981_XLS, tmp_path / "sub" / "nested.xls")
    runs, skipped = open_paths([tmp_path, tmp_path / "run.TIMSDP", tmp_path / "missing.xls"])
    assert sorted(run.raw.name for run in runs) == ["nested.xls", "run.TIMSDP"]
    assert skipped == [(tmp_path / "missing.xls", "does not exist")]


def test_sniff_is_by_content_not_extension(tmp_path):
    timsdp_as_xls = tmp_path / "really_text.xls"
    shutil.copy(TIMSDP_FILES["WH233B z3 Pb-678"], timsdp_as_xls)
    xls_as_txt = tmp_path / "really_xls.txt"
    shutil.copy(NBS981_XLS, xls_as_txt)
    assert sniff(timsdp_as_xls).format == FORMAT_ISOLINX_TIMSDP
    assert sniff(xls_as_txt).format == FORMAT_IONVANTAGE_XLS
    assert open_run(xls_as_txt).n_cycles == 150


def _unsupported(tmp_path: Path) -> dict[str, tuple[Path, str]]:
    writer = _writer()
    cases: dict[str, tuple[Path, str]] = {}

    def add(name: str, data: bytes, reason_part: str) -> None:
        path = tmp_path / name
        path.write_bytes(data)
        cases[name] = (path, reason_part)

    add("empty.TIMSDP", b"", "empty file")
    add("notes.TIMSDP", b"Cycle,Time,206/204\n1,2,3\n", "does not start with #HEADER")
    add("header_only.TIMSDP", b"#HEADER\nAnalysis\nFilename,x\n", "#HEADER without Version, MethodName")
    add("book.xlsx", b"PK\x03\x04" + b"\0" * 64, "zip container")
    add("db.TIMSAD", b"SQLite format 3\x00" + b"\0" * 64, "SQLite database")
    add("blob.xls", b"\x00\x01\x02binary", "binary file")
    add("broken.xls", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600, "cannot be read as an Excel")
    add("other.xls", writer.compound_file(writer._workbook_stream([("Sheet1", {(0, 0): "hello"})])), "without a CYCLE sheet")
    add("cycle_wrong.xls", writer.compound_file(writer._workbook_stream([("CYCLE", {(0, 0): "Something else"})])), "does not start with 'CYCLE Data'")
    return cases


def test_unsupported_files_give_a_clear_reason(tmp_path):
    for name, (path, reason_part) in _unsupported(tmp_path).items():
        result = sniff(path)
        assert result.format is None and not result.supported, name
        assert reason_part in result.reason, (name, result.reason)
        with pytest.raises(UnsupportedFile, match=reason_part.replace("(", r"\(").replace(")", r"\)")):
            open_run(path)
    assert sniff(tmp_path / "nowhere").reason == "not a file"


def test_folder_import_reports_unsupported_files_without_stopping(tmp_path):
    cases = _unsupported(tmp_path)
    shutil.copy(TIMSDP_FILES["WH233B z3 Pb-678"], tmp_path / "good.TIMSDP")
    runs, skipped = open_paths([tmp_path])
    assert [run.raw.name for run in runs] == ["good.TIMSDP"]
    assert sorted(path.name for path, _ in skipped) == sorted(cases)
    for path, reason in skipped:
        assert cases[path.name][1] in reason
