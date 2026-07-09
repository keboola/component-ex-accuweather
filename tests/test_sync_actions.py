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
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "city", "location_query": "Prague"})
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


def test_search_locations_no_query_raises(monkeypatch):
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "location_key", "location_key": "1"})
    with pytest.raises(UserException):
        c.search_locations()
