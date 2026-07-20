"""Extraction-dispatch tests: per-dataset details flags, per-dataset ranges, indices filter."""

from unittest.mock import MagicMock

import component as comp_mod
from configuration import Configuration


def _make(monkeypatch, datasets):
    monkeypatch.setattr(comp_mod.Component, "__init__", lambda self: None)
    c = comp_mod.Component()
    c._config = Configuration(**{"#api_key": "K", "location_type": "search", "location_key": "1", "datasets": datasets})
    c._client = MagicMock()
    c._write_table = MagicMock()
    return c


def test_per_dataset_details_and_ranges_reach_client(monkeypatch):
    # Flatteners are exercised elsewhere; here we only assert what is sent to the client.
    monkeypatch.setattr(comp_mod, "flatten_current_conditions", lambda *a, **k: [])
    monkeypatch.setattr(comp_mod, "flatten_daily_forecast", lambda *a, **k: [])
    monkeypatch.setattr(comp_mod, "flatten_hourly_forecast", lambda *a, **k: [])
    c = _make(
        monkeypatch,
        {
            "current_conditions": True,
            "current_conditions_details": True,
            "daily_forecast": True,
            "daily_forecast_details": False,
            "daily_range": 10,
            "hourly_forecast": True,
            "hourly_forecast_details": True,
            "hourly_range": 24,
        },
    )
    c._client.get_current_conditions.return_value = []
    c._client.get_daily_forecast.return_value = {"DailyForecasts": []}
    c._client.get_hourly_forecast.return_value = []

    c._extract_current_conditions("1")
    c._extract_daily_forecast("1")
    c._extract_hourly_forecast("1")

    # Each dataset carries its own details flag (not a shared global one)
    assert c._client.get_current_conditions.call_args.kwargs["details"] is True
    assert c._client.get_daily_forecast.call_args.kwargs["details"] is False
    assert c._client.get_hourly_forecast.call_args.kwargs["details"] is True
    # And its own range
    assert c._client.get_daily_forecast.call_args.kwargs["days"] == 10
    assert c._client.get_hourly_forecast.call_args.kwargs["hours"] == 24


def test_indices_uses_its_own_range(monkeypatch):
    monkeypatch.setattr(comp_mod, "flatten_indices", lambda *a, **k: [])
    c = _make(monkeypatch, {"current_conditions": False, "indices": True, "indices_range": 15})
    c._client.get_indices.return_value = []
    c._extract_indices("1")
    assert c._client.get_indices.call_args.kwargs["days"] == 15


def test_indices_filter_keeps_only_requested_ids(monkeypatch):
    c = _make(monkeypatch, {"current_conditions": False, "indices": True, "indices_ids": [1, 5]})
    rows = [{"index_id": 1}, {"index_id": 5}, {"index_id": 26}]
    assert c._filter_indices(rows) == [{"index_id": 1}, {"index_id": 5}]


def test_indices_filter_empty_keeps_all(monkeypatch):
    c = _make(monkeypatch, {"current_conditions": False, "indices": True})
    rows = [{"index_id": 1}, {"index_id": 26}]
    assert c._filter_indices(rows) == rows


def test_run_dispatches_only_selected_datasets(monkeypatch):
    # search mode with a confirmed key and a dataset selected -> validate_location() passes.
    c = _make(monkeypatch, {"current_conditions": False, "hourly_forecast": True})
    monkeypatch.setattr(c, "_resolve_location_key", lambda: "1")
    c._extract_current_conditions = MagicMock()
    c._extract_daily_forecast = MagicMock()
    c._extract_hourly_forecast = MagicMock()
    c._extract_indices = MagicMock()
    c.run()
    c._extract_current_conditions.assert_not_called()
    c._extract_daily_forecast.assert_not_called()
    c._extract_hourly_forecast.assert_called_once()
    c._extract_indices.assert_not_called()
