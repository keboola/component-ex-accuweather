# keboola.ex-accuweather Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Implementation tasks (1–6, 8) are owned by **`component-develop`**; the schema/UI task (7) is delegated to **`component-build-ui`**; the test task (9) is owned by **`component-test`** / **`generate-vcr-tests`**. Keep every subagent Keboola-aware by naming its owner skill.

**Goal:** Build a Keboola extractor that pulls AccuWeather current conditions and daily/hourly forecasts for one or more configured locations into typed Storage tables.

**Architecture:** A pure-Python `AccuWeatherClient` (Bearer auth, bounded retry, RFC7807 error mapping) is separated from `component.py`. A single Pydantic `Configuration` models the merged root+row config. `run()` is a thin orchestrator: resolve the `locationKey` (from per-row `state.json` cache or the Locations resolver), then extract each enabled dataset, flatten it to scalar columns, and write an authoritative-`schema`, headerless, incremental-upsert table keyed on `(location_key, timestamp)`. Config rows = one row per location.

**Tech Stack:** Python 3.12+, `keboola.component`, `pydantic` v2, `requests`; tests via `pytest` + `keboola.datadirtest` + `vcrpy`; `uv` build; `ruff` lint.

## Global Constraints

- Component ID: `keboola.ex-accuweather` (extractor). Spec: `docs/superpowers/specs/2026-07-09-ex-accuweather-design.md`.
- API host: `https://dataservice.accuweather.com`; REST/JSON, GET-only, no pagination.
- Auth: `Authorization: Bearer <#api_key>` header. The only secret is `#api_key` (`Field(alias="#api_key")`, `KBC::ProjectSecure`, decrypted plaintext at runtime).
- Retry on `429/500/502/503/504` with bounded exponential backoff (no `Retry-After` header exists); cap attempts then raise.
- Every output table: authoritative `schema` manifest, **headerless CSV** (no `writer.writeheader()`, `has_header` left `False`), explicit composite PK including `location_key`, `incremental=True` (upsert). No `full_load` toggle. Table names are fixed constants: `current_conditions`, `daily_forecast`, `hourly_forecast`.
- Rows run sequentially; root state unused, per-row `state.json` caches `{"location_key", "resolved_from"}`. First run handles empty state without `KeyError`.
- Error mapping: 401/403/404/quota/config-validation → `UserException` (exit 1); unexpected/exhausted-retry 5xx → exit 2.
- Scratch files → `/tmp`, never `data/out/tables/`.
- No `debug` field in the config model (handled by `ComponentBase`). Model `extra="ignore"`. Type hints on all public methods; built-in generics; Ruff `UP` ruleset. `ruff check` must be clean.
- Test fixtures use a single merged `config.json` (root+row already merged) and row-scoped `state.json`. Secrets never committed in cassettes — sanitize `Authorization` header and any `apikey` query param.

---

### Task 1: Typed Configuration model

**Files:**
- Modify: `src/configuration.py` (replace the cookiecutter template model)
- Test: `tests/test_configuration.py`

**Interfaces:**
- Produces: `LocationType(StrEnum)` = `city|postal_code|geoposition|location_key`; `Dataset(StrEnum)` = `current_conditions|daily_forecast|hourly_forecast`; `Units(StrEnum)` = `metric|imperial`. `Configuration(BaseModel)` with fields: `api_key: str = Field(alias="#api_key")`, `units: Units = Units.metric`, `language: str = "en-us"`, `include_details: bool = True`, `location_type: LocationType = LocationType.city`, `location_query: str | None = None`, `country_code: str | None = None`, `latitude: float | None = None`, `longitude: float | None = None`, `location_key: str | None = None`, `datasets: list[Dataset] = [Dataset.current_conditions]`, `daily_range: int = 5`, `hourly_range: int = 12`. `model_config = ConfigDict(extra="ignore", populate_by_name=True)`. A `@model_validator(mode="after")` asserts the value fields required by `location_type` are present, else raises `UserException`. Constructor maps `pydantic.ValidationError` → `UserException`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_configuration.py
import pytest
from keboola.component.exceptions import UserException
from configuration import Configuration, LocationType, Dataset, Units


def test_minimal_city_config():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "city", "location_query": "Prague"})
    assert cfg.api_key == "KEY"
    assert cfg.units == Units.metric
    assert cfg.datasets == [Dataset.current_conditions]
    assert cfg.include_details is True


def test_missing_api_key_raises_userexception():
    with pytest.raises(UserException):
        Configuration(**{"location_type": "city", "location_query": "Prague"})


def test_geoposition_requires_lat_lon():
    with pytest.raises(UserException):
        Configuration(**{"#api_key": "KEY", "location_type": "geoposition"})


def test_geoposition_ok_with_lat_lon():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "geoposition",
                           "latitude": 50.08, "longitude": 14.42})
    assert cfg.latitude == 50.08


def test_extra_keys_ignored():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "location_key",
                           "location_key": "125594", "debug": True, "unknown": 1})
    assert cfg.location_key == "125594"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_configuration.py -v`
Expected: FAIL (ImportError / model mismatch).

- [ ] **Step 3: Write the model**

```python
# src/configuration.py
import logging
from enum import StrEnum

from keboola.component.exceptions import UserException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class Units(StrEnum):
    metric = "metric"
    imperial = "imperial"


class LocationType(StrEnum):
    city = "city"
    postal_code = "postal_code"
    geoposition = "geoposition"
    location_key = "location_key"


class Dataset(StrEnum):
    current_conditions = "current_conditions"
    daily_forecast = "daily_forecast"
    hourly_forecast = "hourly_forecast"


class Configuration(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    api_key: str = Field(alias="#api_key")
    units: Units = Units.metric
    language: str = "en-us"
    include_details: bool = True

    location_type: LocationType = LocationType.city
    location_query: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_key: str | None = None

    datasets: list[Dataset] = Field(default_factory=lambda: [Dataset.current_conditions])
    daily_range: int = 5
    hourly_range: int = 12

    def __init__(self, **data):
        try:
            super().__init__(**data)
        except ValidationError as e:
            msgs = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
            raise UserException(f"Configuration validation error: {', '.join(msgs)}")

    @model_validator(mode="after")
    def _check_location_fields(self):
        lt = self.location_type
        if lt in (LocationType.city, LocationType.postal_code) and not self.location_query:
            raise UserException(f"location_query is required when location_type is '{lt}'.")
        if lt == LocationType.geoposition and (self.latitude is None or self.longitude is None):
            raise UserException("latitude and longitude are required for geoposition.")
        if lt == LocationType.location_key and not self.location_key:
            raise UserException("location_key is required when location_type is 'location_key'.")
        return self

    @property
    def metric(self) -> bool:
        return self.units == Units.metric
```

Note: the `@model_validator` runs inside `super().__init__`, so its `UserException` propagates before the `ValidationError` mapping — acceptable (both are `UserException`). If pydantic wraps it, the `__init__` handler re-raises as `UserException` anyway.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_configuration.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/configuration.py tests/test_configuration.py
git add src/configuration.py tests/test_configuration.py
git commit -m "feat: typed Configuration model for ex-accuweather"
```

---

### Task 2: AccuWeather API client with retry + error mapping

**Files:**
- Create: `src/client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: nothing from other tasks (no Keboola imports — pure client).
- Produces: `class LocationNotFoundError(Exception)`, `class AuthError(Exception)`, `class RateLimitError(Exception)`. `class AccuWeatherClient:` `__init__(self, api_key: str, *, base_url: str = "https://dataservice.accuweather.com", max_retries: int = 4, backoff_base: float = 1.0, session: requests.Session | None = None)`. Methods (all return parsed JSON): `search_cities(self, q: str, country_code: str | None = None) -> list[dict]`, `search_postal_codes(self, q: str, country_code: str | None = None) -> list[dict]`, `search_geoposition(self, lat: float, lon: float) -> dict | None`, `get_location(self, location_key: str) -> dict`, `get_current_conditions(self, location_key: str, *, details: bool) -> list[dict]`, `get_daily_forecast(self, location_key: str, *, days: int, metric: bool, details: bool) -> dict`, `get_hourly_forecast(self, location_key: str, *, hours: int, metric: bool, details: bool) -> list[dict]`. Private `_get(self, path: str, params: dict | None = None) -> Any`.

- [ ] **Step 1: Write the failing tests** (use `requests_mock` for deterministic HTTP)

```python
# tests/test_client.py
import pytest
import requests_mock
from client import AccuWeatherClient, AuthError, RateLimitError

BASE = "https://dataservice.accuweather.com"


def test_bearer_header_sent():
    c = AccuWeatherClient("SECRET")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/125594", json={"Key": "125594"})
        c.get_location("125594")
        assert m.last_request.headers["Authorization"] == "Bearer SECRET"


def test_401_maps_to_autherror():
    c = AccuWeatherClient("BAD")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/125594", status_code=401,
              json={"Code": "Unauthorized", "Message": "Api Authorization failed"})
        with pytest.raises(AuthError):
            c.get_location("125594")


def test_429_retries_then_raises():
    c = AccuWeatherClient("KEY", max_retries=2, backoff_base=0)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/currentconditions/v1/125594", status_code=429, json={})
        with pytest.raises(RateLimitError):
            c.get_current_conditions("125594", details=True)
        assert m.call_count == 3  # initial + 2 retries


def test_503_retries_then_succeeds():
    c = AccuWeatherClient("KEY", max_retries=3, backoff_base=0)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/currentconditions/v1/125594",
              [{"status_code": 503, "json": {}}, {"status_code": 200, "json": [{"WeatherText": "Sunny"}]}])
        out = c.get_current_conditions("125594", details=True)
        assert out[0]["WeatherText"] == "Sunny"


def test_daily_forecast_builds_correct_path_and_params():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/forecasts/v1/daily/5day/125594", json={"DailyForecasts": []})
        c.get_daily_forecast("125594", days=5, metric=True, details=True)
        assert m.last_request.qs["metric"] == ["true"]
        assert m.last_request.qs["details"] == ["true"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_client.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the client**

```python
# src/client.py
import logging
import time
from typing import Any

import requests

BASE_URL = "https://dataservice.accuweather.com"
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class AuthError(Exception):
    """401/403 — key invalid or lacks access/quota."""


class LocationNotFoundError(Exception):
    """404 or empty search result."""


class RateLimitError(Exception):
    """429 persisted past all retries."""


class AccuWeatherClient:
    def __init__(self, api_key: str, *, base_url: str = BASE_URL, max_retries: int = 4,
                 backoff_base: float = 1.0, session: requests.Session | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._session = session or requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {api_key}", "Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self._base_url}{path}"
        last_status = None
        for attempt in range(self._max_retries + 1):
            resp = self._session.get(url, params=params, timeout=60)
            last_status = resp.status_code
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                raise AuthError(self._describe(resp))
            if resp.status_code == 404:
                raise LocationNotFoundError(self._describe(resp))
            if resp.status_code in _RETRY_STATUSES:
                if attempt < self._max_retries:
                    time.sleep(self._backoff_base * (2 ** attempt))
                    continue
                if resp.status_code == 429:
                    raise RateLimitError(self._describe(resp))
                resp.raise_for_status()
            resp.raise_for_status()
        raise RuntimeError(f"Unreachable retry loop, last status {last_status}")

    @staticmethod
    def _describe(resp: requests.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return f"HTTP {resp.status_code}: {resp.text[:200]}"
        # RFC 7807 or legacy AccuWeather body
        title = body.get("title") or body.get("Message") or body.get("Code") or "error"
        req_id = (body.get("trace") or {}).get("requestId")
        suffix = f" (requestId={req_id})" if req_id else ""
        return f"HTTP {resp.status_code}: {title}{suffix}"

    def search_cities(self, q: str, country_code: str | None = None) -> list[dict]:
        if country_code:
            return self._get(f"/locations/v1/cities/{country_code}/search", {"q": q})
        return self._get("/locations/v1/cities/search", {"q": q})

    def search_postal_codes(self, q: str, country_code: str | None = None) -> list[dict]:
        path = f"/locations/v1/postalcodes/{country_code}/search" if country_code else "/locations/v1/postalcodes/search"
        return self._get(path, {"q": q})

    def search_geoposition(self, lat: float, lon: float) -> dict | None:
        return self._get("/locations/v1/cities/geoposition/search", {"q": f"{lat},{lon}"})

    def get_location(self, location_key: str) -> dict:
        return self._get(f"/locations/v1/{location_key}")

    def get_current_conditions(self, location_key: str, *, details: bool) -> list[dict]:
        return self._get(f"/currentconditions/v1/{location_key}", {"details": str(details).lower()})

    def get_daily_forecast(self, location_key: str, *, days: int, metric: bool, details: bool) -> dict:
        return self._get(f"/forecasts/v1/daily/{days}day/{location_key}",
                         {"metric": str(metric).lower(), "details": str(details).lower()})

    def get_hourly_forecast(self, location_key: str, *, hours: int, metric: bool, details: bool) -> list[dict]:
        return self._get(f"/forecasts/v1/hourly/{hours}hour/{location_key}",
                         {"metric": str(metric).lower(), "details": str(details).lower()})
```

- [ ] **Step 4: Add `requests-mock` dev dependency, run tests to verify they pass**

Run: `uv add --dev requests-mock && uv run pytest tests/test_client.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/client.py tests/test_client.py
git add src/client.py tests/test_client.py pyproject.toml uv.lock
git commit -m "feat: AccuWeatherClient with bounded retry and error mapping"
```

---

### Task 3: Dataset flatteners (nested JSON → scalar rows)

**Files:**
- Create: `src/parsers.py`
- Test: `tests/test_parsers.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `flatten_current_conditions(location_key: str, payload: list[dict]) -> list[dict]`; `flatten_daily_forecast(location_key: str, payload: dict) -> list[dict]`; `flatten_hourly_forecast(location_key: str, payload: list[dict]) -> list[dict]`. Each returns a list of flat dicts whose keys are the snake_case column names from spec §4, with `location_key` injected on every row. Also `CURRENT_COLUMNS`, `DAILY_COLUMNS`, `HOURLY_COLUMNS` — ordered `list[str]` of column names, and `CURRENT_PK=["location_key","observation_datetime"]`, `DAILY_PK=["location_key","forecast_date"]`, `HOURLY_PK=["location_key","forecast_datetime"]`.

- [ ] **Step 1: Write the failing tests** (fixtures mirror AccuWeather quick-start shapes)

```python
# tests/test_parsers.py
from parsers import (flatten_current_conditions, flatten_daily_forecast, flatten_hourly_forecast,
                     CURRENT_PK, DAILY_PK, HOURLY_PK)


def test_flatten_current_conditions():
    payload = [{
        "LocalObservationDateTime": "2026-07-09T14:00:00+02:00", "EpochTime": 1783000000,
        "WeatherText": "Sunny", "WeatherIcon": 1, "HasPrecipitation": False,
        "PrecipitationType": None, "IsDayTime": True,
        "Temperature": {"Metric": {"Value": 24.1, "Unit": "C"}, "Imperial": {"Value": 75.0, "Unit": "F"}},
        "RealFeelTemperature": {"Metric": {"Value": 25.0, "Unit": "C"}},
        "RelativeHumidity": 40, "Wind": {"Speed": {"Metric": {"Value": 10.0}}, "Direction": {"Degrees": 180, "Localized": "S"}},
        "UVIndex": 6, "UVIndexText": "High", "Visibility": {"Metric": {"Value": 16.1}},
        "CloudCover": 10, "Pressure": {"Metric": {"Value": 1015.0}},
        "Link": "http://x", "MobileLink": "http://m",
    }]
    rows = flatten_current_conditions("125594", payload)
    assert len(rows) == 1
    r = rows[0]
    assert r["location_key"] == "125594"
    assert r["temperature"] == 24.1
    assert r["temperature_unit"] == "C"
    assert r["weather_text"] == "Sunny"
    assert r["wind_direction"] == "S"
    assert set(CURRENT_PK).issubset(r.keys())


def test_flatten_daily_forecast():
    payload = {"DailyForecasts": [
        {"Date": "2026-07-09T07:00:00+02:00", "EpochDate": 1783000000,
         "Temperature": {"Minimum": {"Value": 15.0, "Unit": "C"}, "Maximum": {"Value": 26.0, "Unit": "C"}},
         "Day": {"Icon": 2, "IconPhrase": "Mostly sunny", "PrecipitationProbability": 10, "HasPrecipitation": False},
         "Night": {"Icon": 33, "IconPhrase": "Clear", "PrecipitationProbability": 5},
         "Sun": {"Rise": "2026-07-09T05:00:00+02:00", "Set": "2026-07-09T21:00:00+02:00"},
         "Link": "http://x", "MobileLink": "http://m"}]}
    rows = flatten_daily_forecast("125594", payload)
    assert len(rows) == 1
    assert rows[0]["temperature_max"] == 26.0
    assert rows[0]["day_phrase"] == "Mostly sunny"
    assert set(DAILY_PK).issubset(rows[0].keys())


def test_flatten_hourly_forecast():
    payload = [{"DateTime": "2026-07-09T15:00:00+02:00", "EpochDateTime": 1783000000,
                "WeatherIcon": 1, "IconPhrase": "Sunny", "IsDaylight": True,
                "Temperature": {"Value": 24.0, "Unit": "C"},
                "PrecipitationProbability": 0, "HasPrecipitation": False,
                "Link": "http://x", "MobileLink": "http://m"}]
    rows = flatten_hourly_forecast("125594", payload)
    assert rows[0]["temperature"] == 24.0
    assert set(HOURLY_PK).issubset(rows[0].keys())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_parsers.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement the flatteners**

```python
# src/parsers.py
from typing import Any

CURRENT_PK = ["location_key", "observation_datetime"]
DAILY_PK = ["location_key", "forecast_date"]
HOURLY_PK = ["location_key", "forecast_datetime"]

CURRENT_COLUMNS = ["location_key", "observation_datetime", "epoch_time", "weather_text", "weather_icon",
                   "has_precipitation", "precipitation_type", "is_day_time", "temperature", "temperature_unit",
                   "realfeel_temperature", "relative_humidity", "wind_speed", "wind_direction_degrees",
                   "wind_direction", "uv_index", "uv_index_text", "visibility", "cloud_cover", "pressure",
                   "link", "mobile_link"]
DAILY_COLUMNS = ["location_key", "forecast_date", "epoch_date", "temperature_min", "temperature_max",
                 "temperature_unit", "day_icon", "day_phrase", "day_precipitation_probability",
                 "day_has_precipitation", "night_icon", "night_phrase", "night_precipitation_probability",
                 "sun_rise", "sun_set", "link", "mobile_link"]
HOURLY_COLUMNS = ["location_key", "forecast_datetime", "epoch_datetime", "weather_icon", "icon_phrase",
                  "is_daylight", "temperature", "temperature_unit", "precipitation_probability",
                  "has_precipitation", "link", "mobile_link"]


def _dig(d: dict | None, *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def flatten_current_conditions(location_key: str, payload: list[dict]) -> list[dict]:
    rows = []
    for o in payload:
        rows.append({
            "location_key": location_key,
            "observation_datetime": o.get("LocalObservationDateTime"),
            "epoch_time": o.get("EpochTime"),
            "weather_text": o.get("WeatherText"),
            "weather_icon": o.get("WeatherIcon"),
            "has_precipitation": o.get("HasPrecipitation"),
            "precipitation_type": o.get("PrecipitationType"),
            "is_day_time": o.get("IsDayTime"),
            "temperature": _dig(o, "Temperature", "Metric", "Value"),
            "temperature_unit": _dig(o, "Temperature", "Metric", "Unit"),
            "realfeel_temperature": _dig(o, "RealFeelTemperature", "Metric", "Value"),
            "relative_humidity": o.get("RelativeHumidity"),
            "wind_speed": _dig(o, "Wind", "Speed", "Metric", "Value"),
            "wind_direction_degrees": _dig(o, "Wind", "Direction", "Degrees"),
            "wind_direction": _dig(o, "Wind", "Direction", "Localized"),
            "uv_index": o.get("UVIndex"),
            "uv_index_text": o.get("UVIndexText"),
            "visibility": _dig(o, "Visibility", "Metric", "Value"),
            "cloud_cover": o.get("CloudCover"),
            "pressure": _dig(o, "Pressure", "Metric", "Value"),
            "link": o.get("Link"),
            "mobile_link": o.get("MobileLink"),
        })
    return rows


def flatten_daily_forecast(location_key: str, payload: dict) -> list[dict]:
    rows = []
    for d in payload.get("DailyForecasts", []):
        rows.append({
            "location_key": location_key,
            "forecast_date": d.get("Date"),
            "epoch_date": d.get("EpochDate"),
            "temperature_min": _dig(d, "Temperature", "Minimum", "Value"),
            "temperature_max": _dig(d, "Temperature", "Maximum", "Value"),
            "temperature_unit": _dig(d, "Temperature", "Maximum", "Unit"),
            "day_icon": _dig(d, "Day", "Icon"),
            "day_phrase": _dig(d, "Day", "IconPhrase"),
            "day_precipitation_probability": _dig(d, "Day", "PrecipitationProbability"),
            "day_has_precipitation": _dig(d, "Day", "HasPrecipitation"),
            "night_icon": _dig(d, "Night", "Icon"),
            "night_phrase": _dig(d, "Night", "IconPhrase"),
            "night_precipitation_probability": _dig(d, "Night", "PrecipitationProbability"),
            "sun_rise": _dig(d, "Sun", "Rise"),
            "sun_set": _dig(d, "Sun", "Set"),
            "link": d.get("Link"),
            "mobile_link": d.get("MobileLink"),
        })
    return rows


def flatten_hourly_forecast(location_key: str, payload: list[dict]) -> list[dict]:
    rows = []
    for h in payload:
        rows.append({
            "location_key": location_key,
            "forecast_datetime": h.get("DateTime"),
            "epoch_datetime": h.get("EpochDateTime"),
            "weather_icon": h.get("WeatherIcon"),
            "icon_phrase": h.get("IconPhrase"),
            "is_daylight": h.get("IsDaylight"),
            "temperature": _dig(h, "Temperature", "Value"),
            "temperature_unit": _dig(h, "Temperature", "Unit"),
            "precipitation_probability": h.get("PrecipitationProbability"),
            "has_precipitation": h.get("HasPrecipitation"),
            "link": h.get("Link"),
            "mobile_link": h.get("MobileLink"),
        })
    return rows
```

Note: exact column set is refined against the first recorded cassette payloads (spec §4); keep column-list constants and flatteners in lockstep.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_parsers.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/parsers.py tests/test_parsers.py
git add src/parsers.py tests/test_parsers.py
git commit -m "feat: dataset flatteners for current/daily/hourly"
```

---

### Task 4: Location resolution with state caching

**Files:**
- Create: `src/component.py` (replace cookiecutter template) — resolution + `__init__` + table-write helper only in this task; extraction wired in Task 5.
- Test: `tests/test_resolve_location.py` (unit-test `_resolve_location_key` via a fake client + monkeypatched state)

**Interfaces:**
- Consumes: `Configuration` (Task 1), `AccuWeatherClient` + `LocationNotFoundError` (Task 2).
- Produces: `class Component(ComponentBase)` with `self._client: AccuWeatherClient`, `self._config: Configuration`; `_resolve_location_key(self) -> str` (returns the key, using state cache keyed on `_resolved_from()` and writing state); `_resolved_from(self) -> str` (stable string of the row's location inputs); `_write_table(self, name: str, columns: list[str], pk: list[str], rows: list[dict]) -> None`. State shape `{"location_key": str, "resolved_from": str}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_resolve_location.py
from unittest.mock import MagicMock
import component as comp_mod
from configuration import Configuration


def _make_component(monkeypatch, cfg_kwargs, state):
    monkeypatch.setattr(comp_mod.ComponentBase, "__init__", lambda self: None)
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
    from keboola.component.exceptions import UserException
    import pytest
    cfg = {"#api_key": "K", "location_type": "city", "location_query": "Nowhere"}
    c = _make_component(monkeypatch, cfg, {})
    c._client.search_cities.return_value = []
    with pytest.raises(UserException):
        c._resolve_location_key()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_resolve_location.py -v`
Expected: FAIL (ImportError / attribute errors).

- [ ] **Step 3: Implement `component.py` (resolution + write helper + init)**

```python
# src/component.py
import csv
import hashlib
import logging
from pathlib import Path

from keboola.component.base import ComponentBase
from keboola.component.exceptions import UserException

from client import AccuWeatherClient, AuthError, LocationNotFoundError, RateLimitError
from configuration import Configuration, Dataset, LocationType

_STATE_KEY = "location_key"
_STATE_RESOLVED_FROM = "resolved_from"

_TYPE_MAP = {  # column name -> Keboola authoritative base type
    "temperature": "NUMERIC", "temperature_min": "NUMERIC", "temperature_max": "NUMERIC",
    "realfeel_temperature": "NUMERIC", "wind_speed": "NUMERIC", "visibility": "NUMERIC",
    "pressure": "NUMERIC", "latitude": "NUMERIC", "longitude": "NUMERIC",
    "epoch_time": "INTEGER", "epoch_date": "INTEGER", "epoch_datetime": "INTEGER",
    "weather_icon": "INTEGER", "day_icon": "INTEGER", "night_icon": "INTEGER",
    "relative_humidity": "INTEGER", "cloud_cover": "INTEGER", "uv_index": "INTEGER",
    "wind_direction_degrees": "INTEGER", "day_precipitation_probability": "INTEGER",
    "night_precipitation_probability": "INTEGER", "precipitation_probability": "INTEGER",
    "has_precipitation": "BOOLEAN", "is_day_time": "BOOLEAN", "is_daylight": "BOOLEAN",
    "day_has_precipitation": "BOOLEAN",
    "observation_datetime": "TIMESTAMP", "forecast_date": "TIMESTAMP",
    "forecast_datetime": "TIMESTAMP", "sun_rise": "TIMESTAMP", "sun_set": "TIMESTAMP",
}


class Component(ComponentBase):
    def __init__(self):
        super().__init__()
        self._config = Configuration(**self.configuration.parameters)
        self._client = AccuWeatherClient(self._config.api_key)

    # --- location resolution -------------------------------------------------
    def _resolved_from(self) -> str:
        cfg = self._config
        raw = f"{cfg.location_type}|{cfg.location_query}|{cfg.country_code}|{cfg.latitude}|{cfg.longitude}|{cfg.location_key}"
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

    # --- table writing -------------------------------------------------------
    def _write_table(self, name: str, columns: list[str], pk: list[str], rows: list[dict]) -> None:
        schema = [{"name": c, "data_type": {"base": {"type": _TYPE_MAP.get(c, "STRING")}}} for c in columns]
        table = self.create_out_table_definition(
            f"{name}.csv", primary_key=pk, incremental=True, schema=schema)
        with open(table.full_path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            for row in rows:
                writer.writerow(row)  # headerless: schema names columns, has_header stays False
        self.write_manifest(table)
        logging.info("Wrote %d rows to %s", len(rows), name)
```

Note: `schema=` shape must match the installed `keboola.component` version's `create_out_table_definition` API; if that signature differs, build a `TableDefinition` with `TableColumn`/`table_metadata` per the library and keep `has_header=False`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_resolve_location.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/component.py tests/test_resolve_location.py
git add src/component.py tests/test_resolve_location.py
git commit -m "feat: locationKey resolution with state caching and table writer"
```

---

### Task 5: Extraction orchestrator (`run()`)

**Files:**
- Modify: `src/component.py` (add `run()`, extractors, and the `if __name__` entrypoint)
- Test: covered end-to-end by the datadir/VCR suite in Task 9 (no separate unit test here — `run()` is thin glue over already-tested units)

**Interfaces:**
- Consumes: everything from Tasks 1–4 plus `parsers` (Task 3).
- Produces: `run(self) -> None`; `_extract_current_conditions(self, key: str) -> None`, `_extract_daily_forecast(self, key: str) -> None`, `_extract_hourly_forecast(self, key: str) -> None`. Fixed table-name constants `TABLE_CURRENT="current_conditions"`, `TABLE_DAILY="daily_forecast"`, `TABLE_HOURLY="hourly_forecast"`.

- [ ] **Step 1: Add extractors + orchestrator**

```python
# src/component.py — additions
from parsers import (CURRENT_COLUMNS, CURRENT_PK, DAILY_COLUMNS, DAILY_PK, HOURLY_COLUMNS, HOURLY_PK,
                     flatten_current_conditions, flatten_daily_forecast, flatten_hourly_forecast)

TABLE_CURRENT = "current_conditions"
TABLE_DAILY = "daily_forecast"
TABLE_HOURLY = "hourly_forecast"


    def run(self) -> None:
        location_key = self._resolve_location_key()
        datasets = self._config.datasets
        if Dataset.current_conditions in datasets:
            self._extract_current_conditions(location_key)
        if Dataset.daily_forecast in datasets:
            self._extract_daily_forecast(location_key)
        if Dataset.hourly_forecast in datasets:
            self._extract_hourly_forecast(location_key)

    def _extract_current_conditions(self, key: str) -> None:
        payload = self._client.get_current_conditions(key, details=self._config.include_details)
        rows = flatten_current_conditions(key, payload)
        self._write_table(TABLE_CURRENT, CURRENT_COLUMNS, CURRENT_PK, rows)

    def _extract_daily_forecast(self, key: str) -> None:
        payload = self._client.get_daily_forecast(
            key, days=self._config.daily_range, metric=self._config.metric, details=self._config.include_details)
        rows = flatten_daily_forecast(key, payload)
        self._write_table(TABLE_DAILY, DAILY_COLUMNS, DAILY_PK, rows)

    def _extract_hourly_forecast(self, key: str) -> None:
        payload = self._client.get_hourly_forecast(
            key, hours=self._config.hourly_range, metric=self._config.metric, details=self._config.include_details)
        rows = flatten_hourly_forecast(key, payload)
        self._write_table(TABLE_HOURLY, HOURLY_COLUMNS, HOURLY_PK, rows)
```

And the entrypoint (maps client errors to exit codes):

```python
if __name__ == "__main__":
    try:
        Component().execute_action()
    except (UserException, AuthError, LocationNotFoundError, RateLimitError) as exc:
        logging.exception(exc)
        exit(1)
    except Exception as exc:
        logging.exception(exc)
        exit(2)
```

`run()` stays under 30 lines and delegates; `AuthError`/`LocationNotFoundError`/`RateLimitError` are user-actionable → exit 1.

- [ ] **Step 2: Verify `run()` orchestration compiles and lints**

Run: `uv run ruff check src/component.py && uv run python -c "import ast,sys; ast.parse(open('src/component.py').read())"`
Expected: no output / clean.

- [ ] **Step 3: Commit**

```bash
git add src/component.py
git commit -m "feat: run() orchestrator and dataset extractors"
```

---

### Task 6: Sync actions (testConnection + search_locations)

**Files:**
- Modify: `src/component.py` (add `@sync_action` methods)
- Test: `tests/test_sync_actions.py`

**Interfaces:**
- Consumes: `AccuWeatherClient`, `Configuration`.
- Produces: `@sync_action("testConnection") def test_connection(self) -> None` (raises `UserException` on failure, returns on success); `@sync_action("search_locations") def search_locations(self) -> list[SelectElement]` returning matches for `location_query` as `{value: Key, label: "Name, AdminArea, Country"}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sync_actions.py
from unittest.mock import MagicMock
import pytest
import component as comp_mod
from configuration import Configuration
from keboola.component.exceptions import UserException


def _make(monkeypatch, cfg_kwargs):
    monkeypatch.setattr(comp_mod.ComponentBase, "__init__", lambda self: None)
    c = comp_mod.Component()
    c._config = Configuration(**cfg_kwargs)
    c._client = MagicMock()
    return c


def test_test_connection_ok(monkeypatch):
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "location_key", "location_key": "1"})
    c._client.search_cities.return_value = [{"Key": "1"}]
    c.test_connection()  # must not raise


def test_test_connection_bad_key(monkeypatch):
    from client import AuthError
    c = _make(monkeypatch, {"#api_key": "BAD", "location_type": "location_key", "location_key": "1"})
    c._client.search_cities.side_effect = AuthError("401")
    with pytest.raises(UserException):
        c.test_connection()


def test_search_locations_returns_labels(monkeypatch):
    c = _make(monkeypatch, {"#api_key": "K", "location_type": "city", "location_query": "Prague"})
    c._client.search_cities.return_value = [
        {"Key": "125594", "LocalizedName": "Prague",
         "AdministrativeArea": {"LocalizedName": "Prague"}, "Country": {"LocalizedName": "Czechia"}}]
    out = c.search_locations()
    assert out[0].value == "125594"
    assert "Prague" in out[0].label
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sync_actions.py -v`
Expected: FAIL (no such methods).

- [ ] **Step 3: Implement the sync actions**

```python
# src/component.py — additions
from keboola.component.sync_actions import SelectElement
from keboola.component.base import sync_action


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
```

Note: confirm the exact import path for `sync_action` / `SelectElement` in the installed `keboola.component` version; adjust if the library exposes them elsewhere.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sync_actions.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
uv run ruff check src/component.py tests/test_sync_actions.py
git add src/component.py tests/test_sync_actions.py
git commit -m "feat: testConnection and search_locations sync actions"
```

---

### Task 7: Config schemas + component_config (owner: component-build-ui)

**Files:**
- Modify: `component_config/configSchema.json` (config-level fields)
- Create: `component_config/configRowSchema.json` (row-level fields)
- Modify: `component_config/sample-config/config.json`, `component_config/component_short_description.md`, `component_config/component_long_description.md`, `component_config/configuration_description.md`, `component_config/documentationUrl.md`

**Interfaces:**
- Consumes: field lists + aliases from spec §5 and Task 1's `Configuration` (property names must match the Pydantic aliases exactly).
- Produces: valid schemas the platform renders; async action names match `@sync_action` names in code (`testConnection`, `search_locations`).

- [ ] **Step 1: Write `configSchema.json`** (config-level: auth + global options)

Fields per spec §5: `#api_key` (string, secret, paired with `format: "test-connection"`), `units` (enum metric/imperial with `enum_titles`), `language` (string, default `en-us`), `include_details` (boolean, default true). Group into a `type: object` "Options" section if it reads better. Required: `["#api_key"]`.

- [ ] **Step 2: Write `configRowSchema.json`** (row-level: location + datasets)

Fields per spec §5: `location_type` (enum, drives `options.dependencies`), `location_query` / `country_code` / `latitude` / `longitude` / `location_key` (shown conditionally), `datasets` (array multi-select with `enum_titles`), `daily_range` / `hourly_range` (enums, shown conditionally on dataset selection). Wire `search_locations` as an async select helper on `location_query` where the library supports it (`"enum": []` present, `autoload` on first dropdown). Required: `["location_type", "datasets"]`.

- [ ] **Step 3: Validate schemas via the schema-tester**

Per `component-build-ui`, run the schema-tester / Playwright render check. Expected: schema renders; conditional fields toggle correctly; test-connection button present.

- [ ] **Step 4: Update sample-config + descriptions**

`sample-config/config.json` = a realistic merged example (city Prague, all three datasets). Fill short/long/configuration descriptions and `documentationUrl.md`.

- [ ] **Step 5: Commit**

```bash
git add component_config/
git commit -m "feat: config and row schemas, sample config, descriptions"
```

---

### Task 8: Cookiecutter cleanup + infra alignment

**Files:**
- Modify: `README.md` (component-specific), `src/component.py` (remove any leftover template comments), delete `tests/test_component.py` if it still holds the template test
- Verify: `pyproject.toml` deps (`pydantic`, `requests`, dev: `pytest`, `requests-mock`, `vcrpy` / `keboola.datadirtest`), `Dockerfile`, `.github` push pipeline unchanged from CF defaults

**Interfaces:** none (housekeeping).

- [ ] **Step 1: Remove template artifacts**

Delete the cookiecutter `tests/test_component.py` example if superseded; strip "EXAMPLE TO REMOVE" blocks. Rewrite `README.md` to describe the AccuWeather extractor (datasets, config, auth, incremental behaviour).

- [ ] **Step 2: Verify deps + lint whole tree**

Run: `uv sync && uv run ruff check src tests`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add README.md src tests pyproject.toml uv.lock
git commit -m "chore: remove cookiecutter template artifacts, update README"
```

---

### Task 9: Datadir + VCR functional tests (owner: component-test / generate-vcr-tests)

**Files:**
- Create: `tests/functional/<case>/` dirs (merged `config.json`, `source/data/in/state.json`, `expected/data/out/tables/*` + manifests)
- Create: `tests/test_functional.py` (datadirtest runner) and VCR cassettes under each case
- Modify: `pyproject.toml` / test config for `vcrpy` sanitizers

**Interfaces:**
- Consumes: the full component (Tasks 1–8).
- Produces: green `pytest` run; sanitized cassettes.

- [ ] **Step 1: Record cassettes against a trial key**

Using the key from repo-root `secrets.json` (`parameters.#api_key`, never printed), record real HTTP for: city search, current conditions, 5-day daily, 12-hour hourly, a 401, and a not-found. Configure VCR to sanitize the `Authorization` header and any `apikey` query param, and scrub the key from URIs/bodies.

- [ ] **Step 2: Build datadir cases** (merged config + row-scoped state per `config-rows.md`)

Cases from spec §7: `current_conditions_success`, `daily_forecast_success`, `hourly_forecast_success`, `all_datasets_success`, `location_key_cached` (pre-seeded `state.json`, cassette omits the search interaction), `city_not_found` (exit 1), `invalid_api_key` (exit 1). Each `config.json` is a single merged object with `parameters` at root. `expected/` holds headerless CSVs + `schema` manifests.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -v`
Expected: all green; paste the `N passed` line.

- [ ] **Step 4: Cassette validation gate**

Per `component-test` → `references/vcr-validation-gate.md`: grep every cassette for secret patterns (the `secrets.json` value, `token`/`password`/`authorization`/`api_key`, `apikey`) → clean; confirm success cases recorded 2xx + non-empty output and failure cases recorded their claimed status. Paste the per-test verdict.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: datadir + VCR functional suite with sanitized cassettes"
```

---

## Deferred to lifecycle phases (not coding tasks)

- **Phase 6 — Dev Portal (owner: component-dev-portal):** publish schemas + sync actions; set `default_bucket: true` and `dataTypeSupport=authoritative` (`kbagent dev-portal patch`, dry-run → TTY confirm), *after* the `0.0.1` release. Confirm via fresh GET.
- **Phase 7 — cf-dev smoke test (owner: component-test):** build `initial-implementation` image, create a cf-dev config via `kbagent` with encrypted `#api_key` + one city row (all datasets), override `runtime.tag` to the branch build, run a job. Verify job `success`, resolved tag == branch build, and the three tables land in `in.c-keboola.ex-accuweather-{configId}` with expected row counts (1 / 5 / 12). This also verifies the `has_header`/native-type Storage load path that local tests can't catch.
- **Phase 8 — Final review (owner: component-checklist-review + babysit-pr):** full CF-standards audit; open PR to `main`.

## Self-Review

- **Spec coverage:** §2 mapping → Tasks 1/4/5/7; §3 auth → Task 2; §4 data model/flattening/types → Tasks 2/3/4; §5 config/schema → Tasks 1/7; §6 architecture → Tasks 2/4/5/6; §7 testing → Task 9; §8 deployment → deferred-phases section; §9 risks → addressed by Task 9 (VCR) and Phase 6/7 (types/has_header). No uncovered section.
- **Placeholder scan:** no TBD/TODO; every code step carries real code; the two "confirm library signature" notes are explicit fallback instructions, not placeholders.
- **Type consistency:** `Configuration` fields/aliases identical across Tasks 1/4/5/6/7; client method signatures match their calls in Tasks 4/5/6; parser column constants (`CURRENT_COLUMNS` etc.) and PKs used identically in Tasks 3/4/5; table-name constants consistent in Task 5.
