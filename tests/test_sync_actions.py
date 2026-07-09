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
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "location_key", "location_key": "1"})
    c._client.search_cities.return_value = [{"Key": "1"}]
    c.test_connection()  # must not raise


def test_test_connection_bad_key(monkeypatch):
    c = _make(monkeypatch, {"#api_key": "BAD", "location_type": "location_key", "location_key": "1"})
    c._client.search_cities.side_effect = AuthError("401")
    with pytest.raises(UserException):
        c.test_connection()


def test_search_locations_returns_labels(monkeypatch):
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "city", "city_query": "Prague"})
    c._client.search_cities.return_value = [
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
    # city mode: the search helper reads city_query
    c._client.search_cities.assert_called_once_with("Prague", None)


def test_search_locations_reads_location_search_in_location_key_mode(monkeypatch):
    # In location_key mode the async picker's helper reads the location_search field.
    c = _make(
        monkeypatch,
        {"#api_key": "K", "location_type": "location_key", "location_search": "Prague", "country_code": "CZ"},
    )
    c._client.search_cities.return_value = [{"Key": "125594", "LocalizedName": "Prague"}]
    out = c.search_locations()
    assert out[0].value == "125594"
    c._client.search_cities.assert_called_once_with("Prague", "CZ")


def test_search_locations_no_query_raises(monkeypatch):
    # location_key mode with no location_search term -> nothing to search on
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "location_key", "location_key": "1"})
    with pytest.raises(UserException):
        c.search_locations()
