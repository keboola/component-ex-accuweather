from datetime import UTC, datetime
from typing import Any

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
    rows = []
    for o in payload:
        rows.append(
            {
                "location_key": location_key,
                "observation_datetime": o.get("LocalObservationDateTime"),
                "epoch_time": o.get("EpochTime"),
                "weather_text": o.get("WeatherText"),
                "weather_icon": o.get("WeatherIcon"),
                "has_precipitation": o.get("HasPrecipitation"),
                "precipitation_type": o.get("PrecipitationType"),
                "is_day_time": o.get("IsDayTime"),
                "temperature": _dig(o, "Temperature", units, "Value"),
                "temperature_unit": _dig(o, "Temperature", units, "Unit"),
                "realfeel_temperature": _dig(o, "RealFeelTemperature", units, "Value"),
                "relative_humidity": o.get("RelativeHumidity"),
                "wind_speed": _dig(o, "Wind", "Speed", units, "Value"),
                "wind_direction_degrees": _dig(o, "Wind", "Direction", "Degrees"),
                "wind_direction": _dig(o, "Wind", "Direction", "Localized"),
                "uv_index": o.get("UVIndex"),
                "uv_index_text": o.get("UVIndexText"),
                "visibility": _dig(o, "Visibility", units, "Value"),
                "cloud_cover": o.get("CloudCover"),
                "pressure": _dig(o, "Pressure", units, "Value"),
                "link": o.get("Link"),
                "mobile_link": o.get("MobileLink"),
            }
        )
    return rows


def flatten_daily_forecast(location_key: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    # The daily-forecast endpoint takes a `metric` query param, so numeric values already
    # arrive in the configured unit system (single Value, no Metric/Imperial sub-objects) —
    # units are honored upstream by the client, unlike the current-conditions payload.
    # Detail-only fields (realfeel, day/night wind, thunderstorm/rain probability, hours of
    # sun, UV / air quality) are present only when details=true; they resolve to None (empty)
    # otherwise, exactly like the current-conditions detail columns.
    rows = []
    for d in payload.get("DailyForecasts", []):
        rows.append(
            {
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
                # detail-only fields (details=true)
                "realfeel_temperature_min": _dig(d, "RealFeelTemperature", "Minimum", "Value"),
                "realfeel_temperature_max": _dig(d, "RealFeelTemperature", "Maximum", "Value"),
                "hours_of_sun": d.get("HoursOfSun"),
                "day_wind_speed": _dig(d, "Day", "Wind", "Speed", "Value"),
                "day_wind_direction": _dig(d, "Day", "Wind", "Direction", "Localized"),
                "day_wind_direction_degrees": _dig(d, "Day", "Wind", "Direction", "Degrees"),
                "day_thunderstorm_probability": _dig(d, "Day", "ThunderstormProbability"),
                "day_rain_probability": _dig(d, "Day", "RainProbability"),
                "night_wind_speed": _dig(d, "Night", "Wind", "Speed", "Value"),
                "night_wind_direction": _dig(d, "Night", "Wind", "Direction", "Localized"),
                "night_wind_direction_degrees": _dig(d, "Night", "Wind", "Direction", "Degrees"),
                "night_thunderstorm_probability": _dig(d, "Night", "ThunderstormProbability"),
                "night_rain_probability": _dig(d, "Night", "RainProbability"),
                "uv_index": _air_and_pollen(d, "UVIndex", "Value"),
                "uv_index_category": _air_and_pollen(d, "UVIndex", "Category"),
                "air_quality_category": _air_and_pollen(d, "AirQuality", "Category"),
                "link": d.get("Link"),
                "mobile_link": d.get("MobileLink"),
            }
        )
    return rows


def flatten_indices(location_key: str, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for i in payload:
        rows.append(
            {
                "location_key": location_key,
                "index_id": i.get("ID"),
                "index_name": i.get("Name"),
                "date": i.get("LocalDateTime") or _epoch_to_iso(i.get("EpochDateTime")),
                "value": i.get("Value"),
                "category": i.get("Category"),
                "category_value": i.get("CategoryValue"),
                "text": i.get("Text"),
                "ascending": i.get("Ascending"),
            }
        )
    return rows


def flatten_hourly_forecast(location_key: str, payload: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Like the daily endpoint, the hourly endpoint takes a `metric` query param, so numeric
    # values already arrive in the configured unit system (single Value, no Metric/Imperial
    # sub-objects). Detail-only fields (realfeel, wind, humidity, dew point, UV, visibility,
    # cloud cover, precipitation type/intensity) appear only when details=true and resolve to
    # None (empty) otherwise, matching the current-conditions detail-column pattern.
    rows = []
    for h in payload:
        rows.append(
            {
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
                # detail-only fields (details=true)
                "realfeel_temperature": _dig(h, "RealFeelTemperature", "Value"),
                "wind_speed": _dig(h, "Wind", "Speed", "Value"),
                "wind_direction": _dig(h, "Wind", "Direction", "Localized"),
                "wind_direction_degrees": _dig(h, "Wind", "Direction", "Degrees"),
                "relative_humidity": h.get("RelativeHumidity"),
                "dew_point": _dig(h, "DewPoint", "Value"),
                "uv_index": h.get("UVIndex"),
                "uv_index_text": h.get("UVIndexText"),
                "visibility": _dig(h, "Visibility", "Value"),
                "cloud_cover": h.get("CloudCover"),
                "precipitation_type": h.get("PrecipitationType"),
                "rain": _dig(h, "Rain", "Value"),
                "link": h.get("Link"),
                "mobile_link": h.get("MobileLink"),
            }
        )
    return rows
