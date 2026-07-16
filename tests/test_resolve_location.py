from unittest.mock import MagicMock

import pytest
from keboola.component.exceptions import UserException

import component as comp_mod
from configuration import Configuration


def _make_component(monkeypatch, cfg_kwargs, state):
    monkeypatch.setattr(comp_mod.Component, "__init__", lambda self: None)
    c = comp_mod.Component()
    c._config = Configuration(**cfg_kwargs)
    c._client = MagicMock()
    c._state = state
    monkeypatch.setattr(c, "get_state_file", lambda: state, raising=False)
    c.write_state_file = MagicMock()
    return c


def test_uses_cached_key_when_resolved_from_matches(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "search", "location_search": "Prague"}
    c = _make_component(monkeypatch, cfg, {})
    c._state = {"location_key": "125594", "resolved_from": c._resolved_from()}
    monkeypatch.setattr(c, "get_state_file", lambda: c._state)
    assert c._resolve_location_key() == "125594"
    c._client.search_locations.assert_not_called()


def test_resolves_via_generic_search_on_first_run(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "search", "location_search": "Prague", "country_code": "CZ"}
    c = _make_component(monkeypatch, cfg, {})
    c._client.search_locations.return_value = [{"Key": "125594"}]
    assert c._resolve_location_key() == "125594"
    # location_search drives the generic search (matches cities AND postal codes)
    c._client.search_locations.assert_called_once_with("Prague", "CZ")
    c.write_state_file.assert_called_once()
    # cached-state shape: location_key + a resolved_from fingerprint
    written = c.write_state_file.call_args.args[0]
    assert written["location_key"] == "125594"
    assert written["resolved_from"] == c._resolved_from()


def test_resolves_postal_code_via_generic_search(monkeypatch):
    # A postal code typed into the single search box resolves via the same generic endpoint.
    cfg = {"#api_key": "K", "location_type": "search", "location_search": "110 00", "country_code": "CZ"}
    c = _make_component(monkeypatch, cfg, {})
    c._client.search_locations.return_value = [{"Key": "373889_PC"}]
    assert c._resolve_location_key() == "373889_PC"
    c._client.search_locations.assert_called_once_with("110 00", "CZ")


def test_confirmed_key_skips_resolution(monkeypatch):
    # A confirmed/pasted key in search mode is authoritative: no search, no state lookup.
    cfg = {"#api_key": "K", "location_type": "search", "location_search": "Prague", "location_key": "999"}
    c = _make_component(monkeypatch, cfg, {})
    assert c._resolve_location_key() == "999"
    c._client.search_locations.assert_not_called()
    c.write_state_file.assert_not_called()


def test_empty_search_result_raises_userexception(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "search", "location_search": "Nowhere"}
    c = _make_component(monkeypatch, cfg, {})
    c._client.search_locations.return_value = []
    with pytest.raises(UserException):
        c._resolve_location_key()


def test_stale_cache_triggers_reresolution(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "search", "location_search": "Prague"}
    c = _make_component(monkeypatch, cfg, {})
    c._state = {"location_key": "OLD", "resolved_from": "different-hash"}
    monkeypatch.setattr(c, "get_state_file", lambda: c._state)
    c._client.search_locations.return_value = [{"Key": "NEW"}]
    assert c._resolve_location_key() == "NEW"
    c._client.search_locations.assert_called_once()


def test_geoposition_resolution(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "geoposition", "latitude": 50.08, "longitude": 14.42}
    c = _make_component(monkeypatch, cfg, {})
    c._client.search_geoposition.return_value = {"Key": "125594"}
    assert c._resolve_location_key() == "125594"
    c._client.search_geoposition.assert_called_once()
