from unittest.mock import MagicMock

import pytest
from keboola.component.exceptions import UserException

import component as comp_mod
from client import AuthError
from configuration import Configuration


def _make(monkeypatch, cfg_kwargs):
    monkeypatch.setattr(comp_mod.Component, "__init__", lambda self: None)
    # sync_action wrapper checks self.configuration.action to decide sync vs. normal call
    monkeypatch.setattr(
        comp_mod.Component, "configuration", property(lambda self: MagicMock(action="run")), raising=False
    )
    c = comp_mod.Component()
    c._config = Configuration(**cfg_kwargs)
    c._client = MagicMock()
    return c


def test_test_connection_ok(monkeypatch):
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "search", "location_key": "1"})
    c._client.search_locations.return_value = [{"Key": "1"}]
    c.test_connection()  # must not raise
    # testConnection probes the generic search endpoint with a fixed query
    c._client.search_locations.assert_called_once_with("London")


def test_test_connection_bad_key(monkeypatch):
    c = _make(monkeypatch, {"#api_key": "BAD", "location_type": "search", "location_key": "1"})
    c._client.search_locations.side_effect = AuthError("401")
    with pytest.raises(UserException):
        c.test_connection()


def test_search_locations_returns_labels(monkeypatch):
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "search", "location_search": "Prague"})
    c._client.search_locations.return_value = [
        {
            "Key": "125594",
            "LocalizedName": "Prague",
            "AdministrativeArea": {"LocalizedName": "Prague"},
            "Country": {"LocalizedName": "Czechia"},
        }
    ]
    out = c.search_locations()
    assert out[0].value == "125594"
    assert "Prague" in out[0].label
    # search mode: the picker reads location_search and hits the generic endpoint
    c._client.search_locations.assert_called_once_with("Prague", None)


def test_search_locations_forwards_country_code(monkeypatch):
    c = _make(
        monkeypatch,
        {"#api_key": "K", "location_type": "search", "location_search": "Prague", "country_code": "CZ"},
    )
    c._client.search_locations.return_value = [{"Key": "125594", "LocalizedName": "Prague"}]
    out = c.search_locations()
    assert out[0].value == "125594"
    c._client.search_locations.assert_called_once_with("Prague", "CZ")


def test_search_locations_resolves_postal_code(monkeypatch):
    # A postal code typed into the single search box resolves via the same generic endpoint.
    c = _make(
        monkeypatch,
        {"#api_key": "K", "location_type": "search", "location_search": "110 00", "country_code": "CZ"},
    )
    c._client.search_locations.return_value = [
        {"Key": "373889_PC", "LocalizedName": "Josefov", "Country": {"LocalizedName": "Czechia"}}
    ]
    out = c.search_locations()
    assert out[0].value == "373889_PC"
    assert "Josefov" in out[0].label
    c._client.search_locations.assert_called_once_with("110 00", "CZ")


def test_search_locations_no_query_raises(monkeypatch):
    # search mode with no location_search term -> nothing to search on
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "search", "location_key": "1"})
    with pytest.raises(UserException):
        c.search_locations()
