from typing import Any

CURRENT_PK = ["location_key", "observation_datetime"]
DAILY_PK = ["location_key", "forecast_date"]
HOURLY_PK = ["location_key", "forecast_datetime"]

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
    "link",
    "mobile_link",
]


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
            }
        )
    return rows


def flatten_daily_forecast(location_key: str, payload: dict) -> list[dict]:
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
                "link": d.get("Link"),
                "mobile_link": d.get("MobileLink"),
            }
        )
    return rows


def flatten_hourly_forecast(location_key: str, payload: list[dict]) -> list[dict]:
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
                "link": h.get("Link"),
                "mobile_link": h.get("MobileLink"),
            }
        )
    return rows
