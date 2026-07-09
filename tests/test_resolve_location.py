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
    cfg = {"#api_key": "K", "location_type": "city", "location_query": "Prague"}
    c = _make_component(monkeypatch, cfg, {})
    c._state = {"location_key": "125594", "resolved_from": c._resolved_from()}
    monkeypatch.setattr(c, "get_state_file", lambda: c._state)
    assert c._resolve_location_key() == "125594"
    c._client.search_cities.assert_not_called()


def test_resolves_via_city_search_on_first_run(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "city", "location_query": "Prague"}
    c = _make_component(monkeypatch, cfg, {})
    c._client.search_cities.return_value = [{"Key": "125594"}]
    assert c._resolve_location_key() == "125594"
    c._client.search_cities.assert_called_once()
    c.write_state_file.assert_called_once()


def test_direct_location_key_skips_resolution(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "location_key", "location_key": "999"}
    c = _make_component(monkeypatch, cfg, {})
    assert c._resolve_location_key() == "999"
    c._client.search_cities.assert_not_called()


def test_empty_city_result_raises_userexception(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "city", "location_query": "Nowhere"}
    c = _make_component(monkeypatch, cfg, {})
    c._client.search_cities.return_value = []
    with pytest.raises(UserException):
        c._resolve_location_key()


def test_stale_cache_triggers_reresolution(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "city", "location_query": "Prague"}
    c = _make_component(monkeypatch, cfg, {})
    c._state = {"location_key": "OLD", "resolved_from": "different-hash"}
    monkeypatch.setattr(c, "get_state_file", lambda: c._state)
    c._client.search_cities.return_value = [{"Key": "NEW"}]
    assert c._resolve_location_key() == "NEW"
    c._client.search_cities.assert_called_once()


def test_geoposition_resolution(monkeypatch):
    cfg = {"#api_key": "K", "location_type": "geoposition", "latitude": 50.08, "longitude": 14.42}
    c = _make_component(monkeypatch, cfg, {})
    c._client.search_geoposition.return_value = {"Key": "125594"}
    assert c._resolve_location_key() == "125594"
    c._client.search_geoposition.assert_called_once()
