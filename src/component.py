import csv
import hashlib
import logging
from collections.abc import Callable

from keboola.component.base import ComponentBase, sync_action
from keboola.component.dao import BaseType, ColumnDefinition
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement

from client import AccuWeatherClient, AuthError, LocationNotFoundError, RateLimitError
from configuration import Configuration, Dataset, LocationType
from parsers import (
    CURRENT_COLUMNS,
    CURRENT_PK,
    DAILY_COLUMNS,
    DAILY_PK,
    HOURLY_COLUMNS,
    HOURLY_PK,
    flatten_current_conditions,
    flatten_daily_forecast,
    flatten_hourly_forecast,
)

_STATE_KEY = "location_key"
_STATE_RESOLVED_FROM = "resolved_from"

TABLE_CURRENT = "current_conditions"
TABLE_DAILY = "daily_forecast"
TABLE_HOURLY = "hourly_forecast"

# column name -> BaseType factory (authoritative native type); default STRING
_TYPE_MAP: dict[str, Callable[[], BaseType]] = {
    "temperature": BaseType.numeric,
    "temperature_min": BaseType.numeric,
    "temperature_max": BaseType.numeric,
    "realfeel_temperature": BaseType.numeric,
    "wind_speed": BaseType.numeric,
    "visibility": BaseType.numeric,
    "pressure": BaseType.numeric,
    "latitude": BaseType.numeric,
    "longitude": BaseType.numeric,
    "epoch_time": BaseType.integer,
    "epoch_date": BaseType.integer,
    "epoch_datetime": BaseType.integer,
    "weather_icon": BaseType.integer,
    "day_icon": BaseType.integer,
    "night_icon": BaseType.integer,
    "relative_humidity": BaseType.integer,
    "cloud_cover": BaseType.integer,
    "uv_index": BaseType.integer,
    "wind_direction_degrees": BaseType.integer,
    "day_precipitation_probability": BaseType.integer,
    "night_precipitation_probability": BaseType.integer,
    "precipitation_probability": BaseType.integer,
    "has_precipitation": BaseType.boolean,
    "is_day_time": BaseType.boolean,
    "is_daylight": BaseType.boolean,
    "day_has_precipitation": BaseType.boolean,
    "observation_datetime": BaseType.timestamp,
    "forecast_date": BaseType.timestamp,
    "forecast_datetime": BaseType.timestamp,
    "sun_rise": BaseType.timestamp,
    "sun_set": BaseType.timestamp,
}


class Component(ComponentBase):
    def __init__(self):
        super().__init__()
        self._config = Configuration(**self.configuration.parameters)
        self._client = AccuWeatherClient(self._config.api_key)

    def run(self) -> None:
        location_key = self._resolve_location_key()
        datasets = self._config.datasets
        if Dataset.current_conditions in datasets:
            self._extract_current_conditions(location_key)
        if Dataset.daily_forecast in datasets:
            self._extract_daily_forecast(location_key)
        if Dataset.hourly_forecast in datasets:
            self._extract_hourly_forecast(location_key)

    # --- location resolution -------------------------------------------------
    def _resolved_from(self) -> str:
        cfg = self._config
        raw = (
            f"{cfg.location_type}|{cfg.location_query}|{cfg.country_code}"
            f"|{cfg.latitude}|{cfg.longitude}|{cfg.location_key}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _resolve_location_key(self) -> str:
        cfg = self._config
        if cfg.location_type == LocationType.location_key:
            return cfg.location_key

        state = self.get_state_file() or {}
        if state.get(_STATE_KEY) and state.get(_STATE_RESOLVED_FROM) == self._resolved_from():
            logging.info("Using cached locationKey %s", state[_STATE_KEY])
            return state[_STATE_KEY]

        key = self._search_location_key()
        self.write_state_file({_STATE_KEY: key, _STATE_RESOLVED_FROM: self._resolved_from()})
        return key

    def _search_location_key(self) -> str:
        cfg = self._config
        if cfg.location_type == LocationType.city:
            results = self._client.search_cities(cfg.location_query, cfg.country_code)
        elif cfg.location_type == LocationType.postal_code:
            results = self._client.search_postal_codes(cfg.location_query, cfg.country_code)
        elif cfg.location_type == LocationType.geoposition:
            geo = self._client.search_geoposition(cfg.latitude, cfg.longitude)
            results = [geo] if geo else []
        else:  # pragma: no cover - guarded above
            results = []
        if not results or not results[0].get("Key"):
            raise UserException(f"No AccuWeather location found for {cfg.location_type} input.")
        return results[0]["Key"]

    # --- dataset extraction --------------------------------------------------
    def _extract_current_conditions(self, key: str) -> None:
        payload = self._client.get_current_conditions(key, details=self._config.include_details)
        rows = flatten_current_conditions(key, payload)
        self._write_table(TABLE_CURRENT, CURRENT_COLUMNS, CURRENT_PK, rows)

    def _extract_daily_forecast(self, key: str) -> None:
        payload = self._client.get_daily_forecast(
            key, days=self._config.daily_range, metric=self._config.metric, details=self._config.include_details
        )
        rows = flatten_daily_forecast(key, payload)
        self._write_table(TABLE_DAILY, DAILY_COLUMNS, DAILY_PK, rows)

    def _extract_hourly_forecast(self, key: str) -> None:
        payload = self._client.get_hourly_forecast(
            key, hours=self._config.hourly_range, metric=self._config.metric, details=self._config.include_details
        )
        rows = flatten_hourly_forecast(key, payload)
        self._write_table(TABLE_HOURLY, HOURLY_COLUMNS, HOURLY_PK, rows)

    # --- sync actions --------------------------------------------------------
    @sync_action("testConnection")
    def test_connection(self) -> None:
        try:
            self._client.search_cities("London")
        except (AuthError, RateLimitError, LocationNotFoundError) as exc:
            raise UserException(f"Connection test failed: {exc}")

    @sync_action("search_locations")
    def search_locations(self) -> list[SelectElement]:
        q = self._config.location_query
        if not q:
            raise UserException("Enter a location query to search.")
        matches = self._client.search_cities(q, self._config.country_code)
        elements = []
        for m in matches:
            area = (m.get("AdministrativeArea") or {}).get("LocalizedName", "")
            country = (m.get("Country") or {}).get("LocalizedName", "")
            label = ", ".join(p for p in (m.get("LocalizedName"), area, country) if p)
            elements.append(SelectElement(value=m["Key"], label=label))
        return elements

    # --- table writing -------------------------------------------------------
    def _write_table(self, name: str, columns: list[str], pk: list[str], rows: list[dict]) -> None:
        schema = {
            col: ColumnDefinition(
                data_types=_TYPE_MAP.get(col, BaseType.string)(),
                primary_key=col in pk,
                nullable=col not in pk,
            )
            for col in columns
        }
        table = self.create_out_table_definition(
            f"{name}.csv", primary_key=pk, incremental=True, schema=schema, has_header=False
        )
        with open(table.full_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            for row in rows:
                writer.writerow(row)  # headerless: schema names columns, has_header stays False
        self.write_manifest(table)
        logging.info("Wrote %d rows to %s", len(rows), name)


"""
        Main entrypoint
"""
if __name__ == "__main__":
    try:
        Component().execute_action()
    except (UserException, AuthError, LocationNotFoundError, RateLimitError) as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
