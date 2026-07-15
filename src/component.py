import csv
import hashlib
import logging
from collections.abc import Callable
from typing import Any

from keboola.component.base import ComponentBase, sync_action
from keboola.component.dao import BaseType, ColumnDefinition
from keboola.component.exceptions import UserException
from keboola.component.sync_actions import SelectElement

from client import AccuWeatherApiError, AccuWeatherClient
from configuration import Configuration, LocationType
from parsers import (
    CURRENT_COLUMNS,
    CURRENT_PK,
    DAILY_COLUMNS,
    DAILY_PK,
    HOURLY_COLUMNS,
    HOURLY_PK,
    INDICES_COLUMNS,
    INDICES_PK,
    flatten_current_conditions,
    flatten_daily_forecast,
    flatten_hourly_forecast,
    flatten_indices,
)

# VCR cassette sanitizers — picked up by the keboola.datadirtest scaffolder during
# recording. keboola.vcr is a dev-only (test) dependency, absent in the production
# image (uv sync --no-dev), so the import is guarded to avoid breaking runtime.
# The Bearer api_key lives in the Authorization header, which DefaultSanitizer strips
# by default (only content-type/content-length/accept survive); the extra field names
# cover any api_key/apikey that could appear in a URL or body.
try:
    from keboola.vcr import DefaultSanitizer

    VCR_SANITIZERS = [DefaultSanitizer(additional_sensitive_fields=["api_key", "apikey"])]
except ImportError:
    VCR_SANITIZERS = []

_STATE_KEY = "location_key"
_STATE_RESOLVED_FROM = "resolved_from"

TABLE_CURRENT = "current_conditions"
TABLE_DAILY = "daily_forecast"
TABLE_HOURLY = "hourly_forecast"
TABLE_INDICES = "indices"

# column name -> BaseType factory (authoritative native type); default STRING
_TYPE_MAP: dict[str, Callable[[], BaseType]] = {
    "temperature": BaseType.numeric,
    "temperature_min": BaseType.numeric,
    "temperature_max": BaseType.numeric,
    "realfeel_temperature": BaseType.numeric,
    "realfeel_temperature_min": BaseType.numeric,
    "realfeel_temperature_max": BaseType.numeric,
    "hours_of_sun": BaseType.numeric,
    "wind_speed": BaseType.numeric,
    "day_wind_speed": BaseType.numeric,
    "night_wind_speed": BaseType.numeric,
    "dew_point": BaseType.numeric,
    "rain": BaseType.numeric,
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
    "day_wind_direction_degrees": BaseType.integer,
    "night_wind_direction_degrees": BaseType.integer,
    "day_precipitation_probability": BaseType.integer,
    "night_precipitation_probability": BaseType.integer,
    "precipitation_probability": BaseType.integer,
    "day_thunderstorm_probability": BaseType.integer,
    "night_thunderstorm_probability": BaseType.integer,
    "day_rain_probability": BaseType.integer,
    "night_rain_probability": BaseType.integer,
    "has_precipitation": BaseType.boolean,
    "is_day_time": BaseType.boolean,
    "is_daylight": BaseType.boolean,
    "day_has_precipitation": BaseType.boolean,
    "ascending": BaseType.boolean,
    "index_id": BaseType.integer,
    "value": BaseType.numeric,
    "category_value": BaseType.integer,
    "observation_datetime": BaseType.timestamp,
    "forecast_date": BaseType.timestamp,
    "forecast_datetime": BaseType.timestamp,
    "date": BaseType.timestamp,
    "sun_rise": BaseType.timestamp,
    "sun_set": BaseType.timestamp,
}


class Component(ComponentBase):
    def __init__(self):
        super().__init__()
        # Construction validates types/required fields only. The row-level location
        # cross-field checks run in run() below — NOT here — so sync actions
        # (testConnection, search_locations) can dispatch without a resolved location.
        self._config = Configuration(**self.configuration.parameters)
        self._client = AccuWeatherClient(self._config.api_key)

    def run(self) -> None:
        self._config.validate_location()
        location_key = self._resolve_location_key()
        datasets = self._config.datasets
        if datasets.current_conditions:
            self._extract_current_conditions(location_key)
        if datasets.daily_forecast:
            self._extract_daily_forecast(location_key)
        if datasets.hourly_forecast:
            self._extract_hourly_forecast(location_key)
        if datasets.indices:
            self._extract_indices(location_key)

    # --- location resolution -------------------------------------------------
    def _resolved_from(self) -> str:
        cfg = self._config
        raw = (
            f"{cfg.location_type}|{cfg.city_query}|{cfg.postal_query}|{cfg.location_search}"
            f"|{cfg.country_code}|{cfg.latitude}|{cfg.longitude}|{cfg.location_key}"
            f"|{cfg.city_location_key}|{cfg.postal_location_key}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _resolve_location_key(self) -> str:
        cfg = self._config
        if cfg.location_type == LocationType.location_key:
            assert cfg.location_key is not None  # guaranteed by validate_location()
            return cfg.location_key

        # A key confirmed via the config-time picker (city / postal modes) is authoritative:
        # use it directly, skipping the free-text search. Headless configs never set this,
        # so they fall through to the search path below unchanged.
        if cfg.picked_location_key:
            logging.info("Using picker-confirmed locationKey %s", cfg.picked_location_key)
            return cfg.picked_location_key

        state = self.get_state_file() or {}
        if state.get(_STATE_KEY) and state.get(_STATE_RESOLVED_FROM) == self._resolved_from():
            logging.info("Using cached locationKey %s", state[_STATE_KEY])
            return state[_STATE_KEY]

        key = self._search_location_key()
        self.write_state_file({_STATE_KEY: key, _STATE_RESOLVED_FROM: self._resolved_from()})
        return key

    def _search_location_key(self) -> str:
        cfg = self._config
        # validate_location() (run() entrypoint) guarantees the fields each branch needs.
        if cfg.location_type == LocationType.city:
            assert cfg.city_query is not None
            results = self._client.search_cities(cfg.city_query, cfg.country_code)
        elif cfg.location_type == LocationType.postal_code:
            assert cfg.postal_query is not None
            results = self._client.search_postal_codes(cfg.postal_query, cfg.country_code)
        elif cfg.location_type == LocationType.geoposition:
            assert cfg.latitude is not None and cfg.longitude is not None
            geo = self._client.search_geoposition(cfg.latitude, cfg.longitude)
            results = [geo] if geo else []
        else:  # pragma: no cover - guarded above
            results = []
        if not results or not results[0].get("Key"):
            raise UserException(f"No AccuWeather location found for {cfg.location_type} input.")
        return results[0]["Key"]

    # --- dataset extraction --------------------------------------------------
    def _extract_current_conditions(self, key: str) -> None:
        payload = self._client.get_current_conditions(
            key, details=self._config.datasets.current_conditions_details, language=self._config.language
        )
        rows = flatten_current_conditions(key, payload, metric=self._config.metric)
        self._write_table(TABLE_CURRENT, CURRENT_COLUMNS, CURRENT_PK, rows)

    def _extract_daily_forecast(self, key: str) -> None:
        payload = self._client.get_daily_forecast(
            key,
            days=self._config.datasets.daily_range,
            metric=self._config.metric,
            details=self._config.datasets.daily_forecast_details,
            language=self._config.language,
        )
        rows = flatten_daily_forecast(key, payload)
        self._write_table(TABLE_DAILY, DAILY_COLUMNS, DAILY_PK, rows)

    def _extract_hourly_forecast(self, key: str) -> None:
        payload = self._client.get_hourly_forecast(
            key,
            hours=self._config.datasets.hourly_range,
            metric=self._config.metric,
            details=self._config.datasets.hourly_forecast_details,
            language=self._config.language,
        )
        rows = flatten_hourly_forecast(key, payload)
        self._write_table(TABLE_HOURLY, HOURLY_COLUMNS, HOURLY_PK, rows)

    def _extract_indices(self, key: str) -> None:
        payload = self._client.get_indices(
            key,
            days=self._config.datasets.indices_range,
            language=self._config.language,
        )
        rows = flatten_indices(key, payload)
        rows = self._filter_indices(rows)
        self._write_table(TABLE_INDICES, INDICES_COLUMNS, INDICES_PK, rows)

    def _filter_indices(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Client-side filter: keep only the requested AccuWeather index IDs.

        Empty / unset `indices_ids` means keep everything (no URL change — the
        AccuWeather indices endpoint has no per-ID filter, so we fetch all and prune).
        """
        wanted = self._config.datasets.indices_ids
        if not wanted:
            return rows
        wanted_set = set(wanted)
        return [r for r in rows if r.get("index_id") in wanted_set]

    # --- sync actions --------------------------------------------------------
    @sync_action("testConnection")
    def test_connection(self) -> None:
        try:
            self._client.search_cities("London")
        except (AccuWeatherApiError, ValueError) as exc:
            # AccuWeatherApiError covers network faults, auth/rate-limit/not-found and any
            # unmapped HTTP status; ValueError covers a malformed JSON body from the API.
            raise UserException(f"Connection test failed: {exc}") from exc

    @sync_action("search_locations")
    def search_locations(self) -> list[SelectElement]:
        # Mode-aware confirmation picker. Reads the query field committed by the active mode
        # (city_query / postal_query / location_search) and hits the matching endpoint:
        # postal_code mode searches postal codes, every other mode searches cities.
        cfg = self._config
        q = cfg.search_query
        if not q:
            raise UserException("Enter a location query to search.")
        try:
            if cfg.location_type == LocationType.postal_code:
                matches = self._client.search_postal_codes(q, cfg.country_code)
            else:
                matches = self._client.search_cities(q, cfg.country_code)
        except (AccuWeatherApiError, ValueError) as exc:
            raise UserException(f"Location search failed: {exc}") from exc
        elements = []
        for m in matches:
            key = m.get("Key")
            if not key:
                continue
            area = (m.get("AdministrativeArea") or {}).get("LocalizedName", "")
            country = (m.get("Country") or {}).get("LocalizedName", "")
            label = ", ".join(p for p in (m.get("LocalizedName"), area, country) if p)
            elements.append(SelectElement(value=key, label=label))
        return elements

    # --- table writing -------------------------------------------------------
    def _write_table(self, name: str, columns: list[str], pk: list[str], rows: list[dict[str, Any]]) -> None:
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
    except (UserException, AccuWeatherApiError) as exc:
        # AccuWeatherApiError is the base for AuthError/LocationNotFoundError/RateLimitError
        # and every mapped upstream failure (network fault, terminal 5xx, unmapped 4xx),
        # so a transient upstream problem surfaces as a user error (exit 1), not exit 2.
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
