"""Read-only database lookup, snapshots, cache and chemistry without sockets."""
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest

from rawtims.upbdb import (
    Candidate,
    Client,
    ConnectionFailed,
    DatabaseError,
    DatabaseLink,
    Response,
    Source,
    TokenStore,
    cache_age,
    chemistry_summary,
    match_fractions,
    normalize_server,
    parse_fraction_id,
)

SAMPLE = {"id": "s1", "name": "AH1-gc1", "aliases": ["OLD"], "project": {"code": "P1"}}
FRACTION = {"id": "f1", "name": "z1", "sample": {"id": "s1", "name": "AH1-gc1"},
            "capsule_label": "K9", "capsule_set_name": "Krogh", "batch_id": "b1", "status": "spiked",
            "sources": [{"grain_id": "g1", "spot_id": "p1", "mount_name": "S", "grain_label": "G1",
                         "spot_label": "S 1", "is_fragment": True, "fragment_note": "half"}]}
BATCH = {"id": "b1", "started_on": "2026-11-14", "steps": [
    {"id": "a", "ordinal": 1, "method_code": "SP-TIMS-ANNEAL", "parameters": {"temperature_c": 900, "duration_h": 60}},
    {"id": "c", "ordinal": 2, "method_code": "SP-TIMS-CA", "parameters": {"temperature_c": 190, "duration_h": 12, "acid": "29 M HF"}},
    {"id": "w", "ordinal": 3, "method_code": "SP-TIMS-WASH", "parameters": {"acid": "HCl"}},
    {"id": "p", "ordinal": 4, "method_code": "SP-TIMS-SPIKE", "parameters": {"spike_version": "v0"}},
], "fraction_step_records": [
    {"fraction_id": "f1", "step_id": "a", "parameters": {"duration_h": 48}},
    {"fraction_id": "f1", "step_id": "c", "parameters": {"duration_h": 10}, "outcome": "dissolved_in_ca"},
    {"fraction_id": "f1", "step_id": "w", "skipped": True},
], "spikes": [{"fraction_id": "f1", "step_id": "p", "spike_version_id": "v1", "spike_weight_g": "0.0000123456789"}],
    "spike_versions": {"v1": {"registry_id": "ET535", "subfraction": "master", "version": "v3"}}}


class MemoryTokens:
    def __init__(self):
        self.values = {}

    def get(self, server):
        return self.values.get(server)

    def set(self, server, token):
        self.values[server] = token

    def delete(self, server):
        self.values.pop(server, None)


class Fake:
    def __init__(self):
        self.calls = []
        self.offline = False
        self.not_modified = False
        self.batch_status = 200
        self.paginate = False

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if self.offline:
            raise ConnectionFailed("offline")
        path = urlsplit(url).path
        if path.endswith("auth/login"):
            assert json.loads(body) == {"username": "alice", "password": "secret"}
            return Response(200, {}, {"token": "private-token", "account": {"username": "alice"}})
        if path.endswith("auth/logout"):
            return Response(200, {}, {})
        if path.endswith("accounts/me"):
            return Response(200, {}, {"username": "alice"})
        if path.endswith("batches/b1") and self.batch_status != 200:
            return Response(self.batch_status, {}, {})
        if self.not_modified and headers.get("If-None-Match"):
            return Response(304, {})
        payload = BATCH if path.endswith("batches/b1") else [SAMPLE] if path.endswith("samples") else [FRACTION]
        response_headers = {"ETag": '"etag-1"'}
        if self.paginate and path.endswith("fractions") and "after" not in parse_qs(urlsplit(url).query):
            payload = []
            response_headers["X-Next-Cursor"] = "cursor+next"
        return Response(200, response_headers, deepcopy(payload))


def client(tmp_path):
    fake = Fake()
    c = Client("HTTP://LOCALHOST:8000/v1/", cache_dir=tmp_path, transport=fake, token_store=MemoryTokens())
    c.login("alice", "secret")
    return c, fake


def candidate():
    return Candidate(deepcopy(FRACTION), deepcopy(SAMPLE), deepcopy(BATCH), "2026-11-20T12:00:00+00:00")


@pytest.mark.parametrize(("value", "expected"), [
    ("WH205 z4", ("WH205", "z4")), ("AH1-gc1 z1", ("AH1-gc1", "z1")),
    (" Multi word sample ABC123a ", ("Multi word sample", "ABC123a")),
    ("WH205", None), ("z1", None), ("WH205 123", None), ("WH205 z1234", None),
    ("WH205 abcd1", None), ("WH205 z1ab", None), ("", None),
])
def test_parse_fraction_id(value, expected):
    assert parse_fraction_id(value) == expected


@pytest.mark.parametrize(("query", "name", "count", "reason"), [
    ("AH1-gc1", "z1", 1, ""), ("old", "Z1", 1, ""), ("ah1-GC1", "z1", 1, ""),
    ("AH1", "z1", 0, "no_sample"), ("AH1-gc1", "z2", 0, "no_fraction"),
])
def test_matching(query, name, count, reason):
    result = match_fractions([SAMPLE], [FRACTION], query, name)
    assert len(result.candidates) == count and result.reason == reason


def test_many_candidates_and_retired():
    s2 = {**SAMPLE, "id": "s2"}
    f2 = {**FRACTION, "id": "f2", "sample": {"id": "s2"}}
    retired = {**FRACTION, "id": "f3", "retired_at": "yesterday"}
    result = match_fractions([SAMPLE, s2], [FRACTION, f2, retired], "OLD", "Z1")
    assert [c.fraction["id"] for c in result.candidates] == ["f1", "f2"]


def test_chemistry_overrides_skip_outcome_and_spike():
    c = chemistry_summary(BATCH, "f1")
    assert c.annealing == "900 °C, 48 h" and c.annealing_duration_h == 48.0
    assert c.chemical_abrasion == "190 °C, 10 h, 29 M HF (dissolved_in_ca)"
    assert c.ca_temperature_c == 190.0 and c.ca_duration_h == 10.0
    assert "WASH" not in c.chemistry_steps
    assert c.spike_solution == "ET535/master/v3" and c.spike_version_uid == "v1"
    assert c.spike_weight_g == 0.0000123456789


def test_two_ca_and_anneal_steps_leave_numbers_empty():
    batch = deepcopy(BATCH)
    batch["steps"] += [{"id": "c2", "ordinal": 5, "method_code": "SP-TIMS-CA", "parameters": {"temperature_c": 180, "duration_h": 6}},
                       {"id": "a2", "ordinal": 6, "method_code": "SP-TIMS-ANNEAL", "parameters": {"duration_h": 60}}]
    c = chemistry_summary(batch, "f1")
    assert c.ca_temperature_c is None and c.ca_duration_h is None
    assert c.annealing_temperature_c is None and c.annealing_duration_h is None
    assert c.chemical_abrasion.endswith("; 180 °C, 6 h")
    assert c.chemistry_steps.index("SP-TIMS-ANNEAL") < c.chemistry_steps.index("SP-TIMS-CA")


def test_spike_fallback_other_steps_and_no_chemistry():
    batch = deepcopy(BATCH)
    batch["spikes"] = []
    batch["steps"][3]["parameters"] = {"spike_version": "v1", "spike_weight_g": 0.01}
    batch["fraction_step_records"] = []
    c = chemistry_summary(batch, "f1")
    assert c.spike_solution == "ET535/master/v3" and c.spike_weight_g == 0.01
    assert "SP-TIMS-WASH HCl" in c.chemistry_steps
    assert chemistry_summary({}, "f1").chemistry_steps == ""


def test_chemistry_steps_show_spike_key_weight_and_parameter_units():
    batch = deepcopy(BATCH)
    batch["spikes"][0]["spike_weight_g"] = "0.008120000000"
    batch["fraction_step_records"] = []
    batch["steps"][2].update(
        parameters={"ultrasonic_min": 30.0, "volume_ul": "12.5000", "repeats": 2.0,
                    "acid": "HCl", "saved_cuts": [], "notes": "", "duration_h": "", "missing": None, "zero": 0.0},
        parameter_definitions=[{"name": "ultrasonic_min", "unit": "min", "type": "number"},
                               {"name": "volume_ul", "unit": "µL", "type": "number"}])
    summary = chemistry_summary(batch, "f1")
    assert summary.chemistry_steps.split("; ")[-1] == "SP-TIMS-SPIKE ET535/master/v3, 0.00812 g"
    assert summary.chemistry_steps.split("; ")[2] == "SP-TIMS-WASH HCl, ultrasonic 30 min, volume ul 12.5 µL, repeats 2, zero 0"
    assert "spike_version=" not in summary.chemistry_steps
    assert "saved_cuts" not in summary.chemistry_steps and "missing" not in summary.chemistry_steps
    assert summary.annealing == "900 °C, 60 h"
    assert summary.chemical_abrasion == "190 °C, 12 h, 29 M HF"


@pytest.mark.parametrize(("code", "params", "definitions", "expected"), [
    ("SP-TIMS-ANNEAL", {"duration_h": 60, "temperature_c": 900},
     [("duration_h", "h"), ("temperature_c", "°C")], "SP-TIMS-ANNEAL 900 °C, 60 h"),
    ("SP-TIMS-CA", {"vessel": "Parr", "acid": "29 M HF", "duration_h": 12, "temperature_c": 190},
     [("vessel", None), ("duration_h", "h"), ("acid", None), ("temperature_c", "°C")],
     "SP-TIMS-CA 190 °C, 12 h, 29 M HF, Parr"),
    ("SP-TIMS-LEACH", {"rinses": 3, "rinse_liquid": "MQ water", "hotplate_temperature_c": 120,
                       "hotplate_min": 30, "acid": "3.5 M HNO3", "ultrasonic_min": 30},
     [("acid", None), ("ultrasonic_min", "min"), ("hotplate_min", "min"),
      ("hotplate_temperature_c", "°C"), ("rinses", None), ("rinse_liquid", None)],
     "SP-TIMS-LEACH 3.5 M HNO3, ultrasonic 30 min, hotplate 30 min, hotplate temperature 120 °C, rinses 3, rinse liquid MQ water"),
    ("SP-TIMS-LOAD", {"emitter": "silica gel-H3PO4", "filament": "single Re"},
     [("filament", None), ("emitter", None)], "SP-TIMS-LOAD filament single Re, emitter silica gel-H3PO4"),
])
def test_chemistry_step_display_order_and_labels(code, params, definitions, expected):
    batch = {"steps": [{"id": "step", "method_code": code, "parameters": params,
                         "parameter_definitions": [{"name": name, "unit": unit} for name, unit in definitions]}]}
    summary = chemistry_summary(batch, "f1")
    assert summary.chemistry_steps == expected
    if code == "SP-TIMS-ANNEAL":
        assert summary.chemistry_steps == f"{code} {summary.annealing}"
    elif code == "SP-TIMS-CA":
        assert summary.chemistry_steps == f"{code} {summary.chemical_abrasion}"


def test_chemistry_step_strips_only_trailing_unit_suffixes_and_keeps_unknown_parameters():
    batch = {"steps": [{"id": "step", "method_code": "SP-TIMS-WASH",
                         "parameters": {"extra_note": "kept", "wait_min": "30.000", "heat_c": 120.0,
                                        "hold_h": 2.0, "mass_g": 0.00812, "rinses": "3.000"},
                         "parameter_definitions": [
                             {"name": "mass_g", "unit": "g"}, {"name": "hold_h", "unit": "h"},
                             {"name": "heat_c", "unit": "°C"}, {"name": "wait_min", "unit": "min", "type": "number"},
                             {"name": "rinses", "type": "integer"}]}]}
    assert chemistry_summary(batch, "f1").chemistry_steps == (
        "SP-TIMS-WASH mass 0.00812 g, hold 2 h, heat 120 °C, wait 30 min, rinses 3, extra note kept")


def test_spike_step_does_not_expose_uuid_when_version_details_are_missing():
    batch = deepcopy(BATCH)
    batch["spike_versions"] = {}
    text = chemistry_summary(batch, "f1").chemistry_steps.split("; ")[-1]
    assert text == "SP-TIMS-SPIKE 1.23457e-05 g"
    assert "v1" not in text


def test_cache_etag_pagination_offline_age_and_no_guess(tmp_path):
    c, fake = client(tmp_path)
    fake.paginate = True
    first = c.lookup("AH1-gc1 z1")
    assert len(first.candidates) == 1 and not first.offline
    pages = [call for call in fake.calls if "/fractions?" in call[1]]
    assert len(pages) == 2
    assert parse_qs(urlsplit(pages[1][1]).query) == {"sample": ["s1"], "limit": ["500"], "after": ["cursor+next"]}
    fake.not_modified = True
    again = c.lookup("AH1-gc1 z1")
    assert again.candidates[0].chemistry == first.candidates[0].chemistry
    assert any(call[2].get("If-None-Match") == '"etag-1"' for call in fake.calls)
    stamp = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    c.cache["lookups"]["ah1-gc1"]["fetched_at"] = stamp
    c._save()
    fake.offline = True
    reloaded = Client(c.server, cache_dir=tmp_path, transport=fake, token_store=c.tokens)
    offline = reloaded.lookup("AH1-gc1 z1")
    assert offline.offline and offline.fetched_at == stamp
    assert "2 days ago" in offline.message and cache_age(stamp) == "2 days ago"
    assert reloaded.lookup("NeverFetched z1").reason == "not_cached"
    assert reloaded.lookup("unparseable").reason == "not_parsed"
    assert offline.candidates[0].confirm(c.server, "alice").database_read_at == stamp
    content = c.cache_path.read_text()
    assert "private-token" not in content and "secret" not in content
    assert all(method == "GET" or "auth/" in url for method, url, _headers, _body in fake.calls)
    assert not any("/mounts/" in call[1] for call in fake.calls)


@pytest.mark.parametrize("status", [403, 404])
def test_chemistry_permission_is_not_a_link_refusal(tmp_path, status):
    c, fake = client(tmp_path)
    c.lookup("AH1-gc1 z1")
    fake.batch_status = status
    result = c.lookup("AH1-gc1 z1")
    assert len(result.candidates) == 1
    assert str(status) in result.candidates[0].chemistry_message
    link = result.candidates[0].confirm(c.server, "alice")
    assert not link.chemistry.chemistry_steps and not c.cache["batches"]


def test_confirm_snapshot_labels_optional_and_roundtrip():
    choice = candidate()
    choice.fraction["sources"] = [{"grain_id": "g1"}, {"grain_id": "g2", "retired_at": "yesterday"}]
    link = choice.confirm("HTTPS://EXAMPLE.COM/v1", "alice")
    assert link.server == "https://example.com" and link.confirmed_by == "alice"
    assert link.sources == [Source(grain_uid="g1")]
    assert DatabaseLink.from_dict(link.to_dict()) == link
    with pytest.raises(DatabaseError, match="Sign in"):
        choice.confirm(link.server, "")


def test_normalize_reject_credentials_and_invalid_scheme():
    assert normalize_server("Example.COM/base/v1/") == "https://example.com/base"
    assert normalize_server("localhost:8000") == "http://localhost:8000"
    for url in ("https://user:pass@example.com", "ftp://example.com", "", "https://x:bad"):
        with pytest.raises(DatabaseError):
            normalize_server(url)


def test_token_keyring_failure_uses_memory(monkeypatch):
    def failed_import(_name):
        raise ImportError("no keyring")
    monkeypatch.setattr("rawtims.upbdb.importlib.import_module", failed_import)
    store = TokenStore()
    store.set("example.com/v1/", "token")
    assert store.get("https://example.com") == "token"
    store.delete("example.com")
    assert store.get("example.com") is None


def test_token_login_me_logout_and_cache_cleared(tmp_path):
    c, fake = client(tmp_path)
    c.lookup("AH1-gc1 z1")
    c.use_token("pasted")
    assert c.account["username"] == "alice"
    c.logout()
    assert c.tokens.get(c.server) is None and not c.cache["lookups"] and not c.account
    assert any(call[0] == "POST" and call[1].endswith("auth/logout") for call in fake.calls)


def test_401_never_falls_back_to_visible_cache(tmp_path):
    c, _fake = client(tmp_path)
    c.lookup("AH1-gc1 z1")
    c.transport = lambda *_args: Response(401, {}, {})
    with pytest.raises(DatabaseError, match="Sign in"):
        c.lookup("AH1-gc1 z1")
    assert c.tokens.get(c.server) is None


def test_offline_alias_uses_already_fetched_sample(tmp_path):
    c, fake = client(tmp_path)
    c.lookup("AH1-gc1 z1")
    fake.offline = True
    result = c.lookup("OLD Z1")
    assert result.offline and [c.fraction["id"] for c in result.candidates] == ["f1"]


def test_cache_bound_and_batches_only_when_referenced(tmp_path, monkeypatch):
    c, _fake = client(tmp_path)
    c.lookup("AH1-gc1 z1")
    c.cache["batches"]["unrelated"] = {"payload": {}, "fetched_at": "2000-01-01T00:00:00+00:00"}
    monkeypatch.setattr("rawtims.upbdb.MAX_LOOKUPS", 2)
    c.lookup("other z1")
    c.lookup("third z1")
    assert len(c.cache["lookups"]) == 2
    assert c.cache["batches"] == {}
    assert all(not entry["samples"] for entry in c.cache["lookups"].values())
    assert all(not page["payload"] for entry in c.cache["lookups"].values() for page in entry["pages"].values())


def test_304_without_cache_and_cancellation_are_clear_errors(tmp_path):
    c, _fake = client(tmp_path)
    c.transport = lambda *_args: Response(304, {})
    with pytest.raises(DatabaseError, match="304 without a cached copy"):
        c.lookup("AH1-gc1 z1")
    c.cancelled = lambda: True
    with pytest.raises(DatabaseError, match="cancelled"):
        c.lookup("AH1-gc1 z1")


def test_signout_revokes_even_after_lookup_cancel(tmp_path):
    c, fake = client(tmp_path)
    c.cancelled = lambda: True
    c.logout()
    assert fake.calls[-1][0] == "POST" and fake.calls[-1][1].endswith("auth/logout")
    assert c.tokens.get(c.server) is None
