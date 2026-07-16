import logging
from datetime import UTC, datetime
from typing import Any

LOG = logging.getLogger(__name__)

CURRENT_PK = ["location_key", "observation_datetime"]
DAILY_PK = ["location_key", "forecast_date"]
HOURLY_PK = ["location_key", "forecast_datetime"]
INDICES_PK = ["location_key", "index_id", "date"]

CURRENT_COLUMNS = [
    "location_key",
    "observation_datetime",
    "epoch_time",
    "weather_text",
    "weather_icon",
    "has_precipitation",
    "precipitation_type",
    "is_day_time",
    "temperature",
    "temperature_unit",
    "realfeel_temperature",
    "relative_humidity",
    "wind_speed",
    "wind_direction_degrees",
    "wind_direction",
    "uv_index",
    "uv_index_text",
    "visibility",
    "cloud_cover",
    "pressure",
    "link",
    "mobile_link",
]
DAILY_COLUMNS = [
    "location_key",
    "forecast_date",
    "epoch_date",
    "temperature_min",
    "temperature_max",
    "temperature_unit",
    "day_icon",
    "day_phrase",
    "day_precipitation_probability",
    "day_has_precipitation",
    "night_icon",
    "night_phrase",
    "night_precipitation_probability",
    "sun_rise",
    "sun_set",
    # detail-only columns (populated when details=true; empty otherwise)
    "realfeel_temperature_min",
    "realfeel_temperature_max",
    "hours_of_sun",
    "day_wind_speed",
    "day_wind_direction",
    "day_wind_direction_degrees",
    "day_thunderstorm_probability",
    "day_rain_probability",
    "night_wind_speed",
    "night_wind_direction",
    "night_wind_direction_degrees",
    "night_thunderstorm_probability",
    "night_rain_probability",
    "uv_index",
    "uv_index_category",
    "air_quality_category",
    "link",
    "mobile_link",
]
HOURLY_COLUMNS = [
    "location_key",
    "forecast_datetime",
    "epoch_datetime",
    "weather_icon",
    "icon_phrase",
    "is_daylight",
    "temperature",
    "temperature_unit",
    "precipitation_probability",
    "has_precipitation",
    # detail-only columns (populated when details=true; empty otherwise)
    "realfeel_temperature",
    "wind_speed",
    "wind_direction",
    "wind_direction_degrees",
    "relative_humidity",
    "dew_point",
    "uv_index",
    "uv_index_text",
    "visibility",
    "cloud_cover",
    "precipitation_type",
    "rain",
    "link",
    "mobile_link",
]
INDICES_COLUMNS = [
    "location_key",
    "index_id",
    "index_name",
    "date",
    "value",
    "category",
    "category_value",
    "text",
    "ascending",
]


def _epoch_to_iso(epoch: Any) -> str | None:
    # AccuWeather EpochDateTime is Unix seconds (UTC). The `date` column is a TIMESTAMP
    # (and part of the indices PK), so the epoch fallback must stay a timestamp string —
    # never a bare int — to keep authoritative typing and the PK consistent.
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=UTC).isoformat()
    except ValueError, TypeError, OSError, OverflowError:
        return None


def _dig(d: dict[str, Any] | None, *keys: str) -> Any:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


# A column spec maps output column -> source path. A string path is a top-level
# ``.get``; a tuple is a nested lookup via ``_dig``. This keeps the flatteners a
# declarative column->path table instead of a large repeated dict literal.
_Path = str | tuple[str, ...]


def _extract(d: dict[str, Any], path: _Path) -> Any:
    if isinstance(path, tuple):
        return _dig(d, *path)
    return d.get(path)


def _map_row(d: dict[str, Any], spec: dict[str, _Path], **extra: Any) -> dict[str, Any]:
    row = {col: _extract(d, path) for col, path in spec.items()}
    row.update(extra)
    return row


def _air_and_pollen(d: dict[str, Any], name: str, key: str = "Value") -> Any:
    # daily details expose UV / air-quality / pollen as a flat list of named entries;
    # pull one entry by its Name and return the requested sub-field (Value or Category).
    for entry in d.get("AirAndPollen") or []:
        if isinstance(entry, dict) and entry.get("Name") == name:
            return entry.get(key)
    return None


def flatten_current_conditions(
    location_key: str, payload: list[dict[str, Any]], *, metric: bool = True
) -> list[dict[str, Any]]:
    # currentconditions has no metric= query param — the payload always carries both
    # Metric and Imperial sub-objects, so honor the configured units here in the parser.
    units = "Metric" if metric else "Imperial"
    spec: dict[str, _Path] = {
        "observation_datetime": "LocalObservationDateTime",
        "epoch_time": "EpochTime",
        "weather_text": "WeatherText",
        "weather_icon": "WeatherIcon",
        "has_precipitation": "HasPrecipitation",
        "precipitation_type": "PrecipitationType",
        "is_day_time": "IsDayTime",
        "temperature": ("Temperature", units, "Value"),
        "temperature_unit": ("Temperature", units, "Unit"),
        "realfeel_temperature": ("RealFeelTemperature", units, "Value"),
        "relative_humidity": "RelativeHumidity",
        "wind_speed": ("Wind", "Speed", units, "Value"),
        "wind_direction_degrees": ("Wind", "Direction", "Degrees"),
        "wind_direction": ("Wind", "Direction", "Localized"),
        "uv_index": "UVIndex",
        "uv_index_text": "UVIndexText",
        "visibility": ("Visibility", units, "Value"),
        "cloud_cover": "CloudCover",
        "pressure": ("Pressure", units, "Value"),
        "link": "Link",
        "mobile_link": "MobileLink",
    }
    return [_map_row(o, spec, location_key=location_key) for o in payload]


def flatten_daily_forecast(location_key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    # The daily-forecast endpoint takes a `metric` query param, so numeric values already
    # arrive in the configured unit system (single Value, no Metric/Imperial sub-objects) —
    # units are honored upstream by the client, unlike the current-conditions payload.
    # Detail-only fields (realfeel, day/night wind, thunderstorm/rain probability, hours of
    # sun, UV / air quality) are present only when details=true; they resolve to None (empty)
    # otherwise, exactly like the current-conditions detail columns.
    spec: dict[str, _Path] = {
        "forecast_date": "Date",
        "epoch_date": "EpochDate",
        "temperature_min": ("Temperature", "Minimum", "Value"),
        "temperature_max": ("Temperature", "Maximum", "Value"),
        "temperature_unit": ("Temperature", "Maximum", "Unit"),
        "day_icon": ("Day", "Icon"),
        "day_phrase": ("Day", "IconPhrase"),
        "day_precipitation_probability": ("Day", "PrecipitationProbability"),
        "day_has_precipitation": ("Day", "HasPrecipitation"),
        "night_icon": ("Night", "Icon"),
        "night_phrase": ("Night", "IconPhrase"),
        "night_precipitation_probability": ("Night", "PrecipitationProbability"),
        "sun_rise": ("Sun", "Rise"),
        "sun_set": ("Sun", "Set"),
        # detail-only fields (details=true)
        "realfeel_temperature_min": ("RealFeelTemperature", "Minimum", "Value"),
        "realfeel_temperature_max": ("RealFeelTemperature", "Maximum", "Value"),
        "hours_of_sun": "HoursOfSun",
        "day_wind_speed": ("Day", "Wind", "Speed", "Value"),
        "day_wind_direction": ("Day", "Wind", "Direction", "Localized"),
        "day_wind_direction_degrees": ("Day", "Wind", "Direction", "Degrees"),
        "day_thunderstorm_probability": ("Day", "ThunderstormProbability"),
        "day_rain_probability": ("Day", "RainProbability"),
        "night_wind_speed": ("Night", "Wind", "Speed", "Value"),
        "night_wind_direction": ("Night", "Wind", "Direction", "Localized"),
        "night_wind_direction_degrees": ("Night", "Wind", "Direction", "Degrees"),
        "night_thunderstorm_probability": ("Night", "ThunderstormProbability"),
        "night_rain_probability": ("Night", "RainProbability"),
        "link": "Link",
        "mobile_link": "MobileLink",
    }
    rows = []
    for d in payload.get("DailyForecasts", []):
        # air-and-pollen entries aren't a fixed path (looked up by Name), so they
        # stay as explicit extras alongside the declarative column->path spec.
        rows.append(
            _map_row(
                d,
                spec,
                location_key=location_key,
                uv_index=_air_and_pollen(d, "UVIndex", "Value"),
                uv_index_category=_air_and_pollen(d, "UVIndex", "Category"),
                air_quality_category=_air_and_pollen(d, "AirQuality", "Category"),
            )
        )
    return rows


def flatten_indices(location_key: str, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spec: dict[str, _Path] = {
        "index_id": "ID",
        "index_name": "Name",
        "value": "Value",
        "category": "Category",
        "category_value": "CategoryValue",
        "text": "Text",
        "ascending": "Ascending",
    }
    rows = []
    for i in payload:
        # `date` prefers LocalDateTime, falling back to the epoch converted to an
        # ISO timestamp — not a plain path, so it stays an explicit extra.
        date = i.get("LocalDateTime") or _epoch_to_iso(i.get("EpochDateTime"))
        if date is None:
            # `date` is part of INDICES_PK (non-nullable), so an index entry with no
            # resolvable timestamp can't be written — skip it rather than emit a null PK.
            LOG.debug(
                "Skipping index entry with no resolvable date (index_id=%s, name=%s)",
                i.get("ID"),
                i.get("Name"),
            )
            continue
        rows.append(_map_row(i, spec, location_key=location_key, date=date))
    return rows


def flatten_hourly_forecast(location_key: str, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Like the daily endpoint, the hourly endpoint takes a `metric` query param, so numeric
    # values already arrive in the configured unit system (single Value, no Metric/Imperial
    # sub-objects). Detail-only fields (realfeel, wind, humidity, dew point, UV, visibility,
    # cloud cover, precipitation type/intensity) appear only when details=true and resolve to
    # None (empty) otherwise, matching the current-conditions detail-column pattern.
    spec: dict[str, _Path] = {
        "forecast_datetime": "DateTime",
        "epoch_datetime": "EpochDateTime",
        "weather_icon": "WeatherIcon",
        "icon_phrase": "IconPhrase",
        "is_daylight": "IsDaylight",
        "temperature": ("Temperature", "Value"),
        "temperature_unit": ("Temperature", "Unit"),
        "precipitation_probability": "PrecipitationProbability",
        "has_precipitation": "HasPrecipitation",
        # detail-only fields (details=true)
        "realfeel_temperature": ("RealFeelTemperature", "Value"),
        "wind_speed": ("Wind", "Speed", "Value"),
        "wind_direction": ("Wind", "Direction", "Localized"),
        "wind_direction_degrees": ("Wind", "Direction", "Degrees"),
        "relative_humidity": "RelativeHumidity",
        "dew_point": ("DewPoint", "Value"),
        "uv_index": "UVIndex",
        "uv_index_text": "UVIndexText",
        "visibility": ("Visibility", "Value"),
        "cloud_cover": "CloudCover",
        "precipitation_type": "PrecipitationType",
        "rain": ("Rain", "Value"),
        "link": "Link",
        "mobile_link": "MobileLink",
    }
    return [_map_row(h, spec, location_key=location_key) for h in payload]
