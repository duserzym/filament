"""Name classification, element detection, fraction-ID suggestions, dates, keys and run ids."""

from __future__ import annotations

from datetime import datetime
import time
import uuid

import pytest

from rawtims import model
from rawtims.model import unique_keys, uuid7
from rawtims.readers.common import parse_instrument_datetime
from rawtims.readers.functions import build_functions, classify, detect_element, suggest_fraction_id
from reader_fixtures import B998, GHR1_U_XLS, SYNTHETIC_U, TIMSDP_FILES, read

# name: (kind, numerator, denominator, mass, collector)
CLASSIFICATION = {
    "206/204 D": ("ratio", "206", "204", None, "D"),
    "206/204 F-D": ("ratio", "206", "204", None, None),
    "206/207 F": ("ratio", "206", "207", None, "F"),
    "202/205 D": ("ratio", "202", "205", None, "D"),
    "270/267": ("ratio", "270", "267", None, None),
    "265/267": ("ratio", "265", "267", None, None),
    "Pb206+At206/Tl205 raw": ("ratio", "Pb206+At206", "Tl205", None, None),
    "238/235 oxide R18 0.00206": ("ratio", "238", "235", None, None),
    "233/235 oxide R18 0.00206": ("ratio", "233", "235", None, None),
    "238/233 oxide": ("ratio", "238", "233", None, None),
    "208/206 F/F S1": ("ratio", "208", "206", None, None),
    "206/204 Daly": ("ratio", "206", "204", None, "D"),
    "alpha 204/206": ("other", None, None, None, None),
    "Daly/Faraday Gain": ("other", None, None, None, None),
    "D/F Gain": ("other", None, None, None, None),
    "R45": ("other", None, None, None, None),
    "204 D": ("intensity", None, None, 204, "D"),
    "i265": ("intensity", None, None, 265, None),
    "i204 Daly": ("intensity", None, None, 204, "D"),
    "265UO2_V": ("intensity", None, None, 265, None),
    "265UO2": ("intensity", None, None, 265, None),
    "i205Pb": ("intensity", None, None, 205, None),
    "Tl205 S2 int": ("intensity", None, None, 205, None),
    "Pb204+Hg204 S1 int": ("intensity", None, None, 204, None),
}


@pytest.mark.parametrize("name", sorted(CLASSIFICATION))
def test_classification_table(name):
    kind, numerator, denominator, mass, collector = CLASSIFICATION[name]
    fields = classify(name)
    assert fields["kind"] == kind
    assert fields.get("numerator") == numerator and fields.get("denominator") == denominator
    assert fields.get("mass") == mass and fields.get("collector") == collector


def test_ratio_details_and_oxide_metadata():
    oxide = classify("238/235 oxide R18 0.00206")
    assert oxide["metadata"] == {"oxide_corrected": True, "oxide_r18": 0.00206}
    assert (oxide["numerator_mass"], oxide["denominator_mass"]) == (238, 235)
    assert classify("238/233 oxide")["metadata"] == {"oxide_corrected": True}
    assert classify("270/267")["metadata"] == {}
    assert classify("206/204 F-D")["metadata"] == {"collector_suffix": "F-D"}
    raw = classify("Pb206+At206/Tl205 raw")
    assert (raw["numerator_mass"], raw["denominator_mass"]) == (206, 205)
    assert classify("265UO2_V")["unit"] == "V"


def test_element_detection():
    assert detect_element(build_functions(["i204", "206/204"])) == "Pb"
    assert detect_element(build_functions(["270/267", "265/267"])) == "U"
    assert detect_element(build_functions(["238/235 oxide R18 0.00206"])) == "U"
    assert detect_element(build_functions(["R45", "Daly/Faraday Gain"])) is None
    assert read(B998).element == "Pb" and read(GHR1_U_XLS).element == "U"
    assert read(TIMSDP_FILES["WH205 z41 U-655"]).element == "U" and read(SYNTHETIC_U).element == "U"


@pytest.mark.parametrize(
    ("sample_id", "suggested"),
    [
        ("GHR1 20200827-11 U run2", "GHR1 20200827-11"),
        ("GHR1 20200827-11 U", "GHR1 20200827-11"),
        ("GHR1 230921F01 U", "GHR1 230921F01"),
        ("WH205 z4 Pb", "WH205 z4"),
        ("B998 z1 Pb1", "B998 z1"),
        ("13223M02 iz1", "13223M02 iz1"),
        ("NBS981 230024a", "NBS981 230024a"),
        ("Pb", "Pb"),
        (None, None),
    ],
)
def test_fraction_id_suggestion(sample_id, suggested):
    assert suggest_fraction_id(sample_id) == suggested


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2022-11-28 6:30:05 AM", datetime(2022, 11, 28, 6, 30, 5)),
        ("2022-11-28 6:30:05 PM", datetime(2022, 11, 28, 18, 30, 5)),
        ("2022-11-28 12:05:00 AM", datetime(2022, 11, 28, 0, 5, 0)),
        ("2022-11-28 06:30:05", datetime(2022, 11, 28, 6, 30, 5)),
        ("26/09/2023 12:53:31", datetime(2023, 9, 26, 12, 53, 31)),
        ("05/10/2023 12:44:38", datetime(2023, 10, 5, 12, 44, 38)),
        ("7/3/2018 7:46:33 AM", datetime(2018, 7, 3, 7, 46, 33)),
        ("Tuesday 3 July 2018 7:46:32", datetime(2018, 7, 3, 7, 46, 32)),
        ("Sunday 30 August 2020 18:38:8", datetime(2020, 8, 30, 18, 38, 8)),
        ("31/02/2023 10:00:00", None),
        ("2022-11-28 13:00:00 PM", None),
        ("not a date", None),
        ("", None),
        (None, None),
    ],
)
def test_instrument_dates(text, expected):
    assert parse_instrument_datetime(text) == expected


def test_unique_keys_keep_repeated_names_apart():
    assert unique_keys(["a", "b", "a", "a"]) == ["a", "b", "a #2", "a #3"]
    assert unique_keys(["a", "a #2", "a"]) == ["a", "a #2", "a #3"]


@pytest.mark.parametrize("use_stdlib", [True, False])
def test_uuid7(monkeypatch, use_stdlib):
    if not use_stdlib:
        monkeypatch.delattr(uuid, "uuid7", raising=False)
    before = time.time_ns() // 1_000_000
    first, second = uuid7(), model.uuid7()
    after = time.time_ns() // 1_000_000
    for value in (first, second):
        assert value.version == 7 and value.variant == uuid.RFC_4122
        assert before <= value.int >> 80 <= after
    assert first != second
    assert read(B998).run_id != read(GHR1_U_XLS).run_id and uuid.UUID(read(B998).run_id).version == 7
