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


def test_flatten_current_conditions():
    payload = [
        {
            "LocalObservationDateTime": "2026-07-09T14:00:00+02:00",
            "EpochTime": 1783000000,
            "WeatherText": "Sunny",
            "WeatherIcon": 1,
            "HasPrecipitation": False,
            "PrecipitationType": None,
            "IsDayTime": True,
            "Temperature": {"Metric": {"Value": 24.1, "Unit": "C"}, "Imperial": {"Value": 75.0, "Unit": "F"}},
            "RealFeelTemperature": {"Metric": {"Value": 25.0, "Unit": "C"}},
            "RelativeHumidity": 40,
            "Wind": {"Speed": {"Metric": {"Value": 10.0}}, "Direction": {"Degrees": 180, "Localized": "S"}},
            "UVIndex": 6,
            "UVIndexText": "High",
            "Visibility": {"Metric": {"Value": 16.1}},
            "CloudCover": 10,
            "Pressure": {"Metric": {"Value": 1015.0}},
            "Link": "http://x",
            "MobileLink": "http://m",
        }
    ]
    rows = flatten_current_conditions("125594", payload)
    assert len(rows) == 1
    r = rows[0]
    assert r["location_key"] == "125594"
    assert r["temperature"] == 24.1
    assert r["temperature_unit"] == "C"
    assert r["weather_text"] == "Sunny"
    assert r["wind_direction"] == "S"
    assert set(CURRENT_PK).issubset(r.keys())
    assert set(r.keys()) == set(CURRENT_COLUMNS)


def _current_conditions_payload():
    return [
        {
            "Temperature": {"Metric": {"Value": 24.1, "Unit": "C"}, "Imperial": {"Value": 75.4, "Unit": "F"}},
            "RealFeelTemperature": {"Metric": {"Value": 25.0, "Unit": "C"}, "Imperial": {"Value": 77.0, "Unit": "F"}},
            "Wind": {"Speed": {"Metric": {"Value": 10.0}, "Imperial": {"Value": 6.2}}},
            "Visibility": {"Metric": {"Value": 16.1}, "Imperial": {"Value": 10.0}},
            "Pressure": {"Metric": {"Value": 1015.0}, "Imperial": {"Value": 29.97}},
        }
    ]


def test_current_conditions_metric_selects_metric_branch():
    r = flatten_current_conditions("1", _current_conditions_payload(), metric=True)[0]
    assert r["temperature"] == 24.1
    assert r["temperature_unit"] == "C"
    assert r["realfeel_temperature"] == 25.0
    assert r["wind_speed"] == 10.0
    assert r["visibility"] == 16.1
    assert r["pressure"] == 1015.0


def test_current_conditions_imperial_selects_imperial_branch():
    r = flatten_current_conditions("1", _current_conditions_payload(), metric=False)[0]
    assert r["temperature"] == 75.4
    assert r["temperature_unit"] == "F"
    assert r["realfeel_temperature"] == 77.0
    assert r["wind_speed"] == 6.2
    assert r["visibility"] == 10.0
    assert r["pressure"] == 29.97


def test_flatten_daily_forecast():
    payload = {
        "DailyForecasts": [
            {
                "Date": "2026-07-09T07:00:00+02:00",
                "EpochDate": 1783000000,
                "Temperature": {"Minimum": {"Value": 15.0, "Unit": "C"}, "Maximum": {"Value": 26.0, "Unit": "C"}},
                "Day": {
                    "Icon": 2,
                    "IconPhrase": "Mostly sunny",
                    "PrecipitationProbability": 10,
                    "HasPrecipitation": False,
                },
                "Night": {"Icon": 33, "IconPhrase": "Clear", "PrecipitationProbability": 5},
                "Sun": {"Rise": "2026-07-09T05:00:00+02:00", "Set": "2026-07-09T21:00:00+02:00"},
                "Link": "http://x",
                "MobileLink": "http://m",
            }
        ]
    }
    rows = flatten_daily_forecast("125594", payload)
    assert len(rows) == 1
    assert rows[0]["temperature_max"] == 26.0
    assert rows[0]["day_phrase"] == "Mostly sunny"
    assert set(DAILY_PK).issubset(rows[0].keys())
    assert set(rows[0].keys()) == set(DAILY_COLUMNS)


_DAILY_DETAIL_COLUMNS = [
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
]


def test_flatten_daily_forecast_details_false_leaves_detail_columns_empty():
    # No details=true payload -> every detail column is present but None (empty in CSV),
    # exactly like the current-conditions detail columns.
    payload = {"DailyForecasts": [{"Date": "2026-07-09T07:00:00+02:00", "Temperature": {}}]}
    r = flatten_daily_forecast("1", payload)[0]
    assert set(_DAILY_DETAIL_COLUMNS).issubset(r.keys())
    assert all(r[c] is None for c in _DAILY_DETAIL_COLUMNS)


def test_flatten_daily_forecast_details_true_populates_detail_columns():
    payload = {
        "DailyForecasts": [
            {
                "Date": "2026-07-09T07:00:00+02:00",
                "RealFeelTemperature": {"Minimum": {"Value": 13.5}, "Maximum": {"Value": 26.6}},
                "HoursOfSun": 14.7,
                "Day": {
                    "ThunderstormProbability": 0,
                    "RainProbability": 1,
                    "Wind": {"Speed": {"Value": 16.7}, "Direction": {"Degrees": 329, "Localized": "NNW"}},
                },
                "Night": {
                    "ThunderstormProbability": 2,
                    "RainProbability": 5,
                    "Wind": {"Speed": {"Value": 5.6}, "Direction": {"Degrees": 200, "Localized": "SSW"}},
                },
                "AirAndPollen": [
                    {"Name": "AirQuality", "Category": "Good"},
                    {"Name": "UVIndex", "Value": 8, "Category": "Very High"},
                ],
            }
        ]
    }
    r = flatten_daily_forecast("1", payload)[0]
    assert r["realfeel_temperature_min"] == 13.5
    assert r["realfeel_temperature_max"] == 26.6
    assert r["hours_of_sun"] == 14.7
    assert r["day_wind_speed"] == 16.7
    assert r["day_wind_direction"] == "NNW"
    assert r["day_wind_direction_degrees"] == 329
    assert r["day_rain_probability"] == 1
    assert r["night_wind_speed"] == 5.6
    assert r["night_thunderstorm_probability"] == 2
    assert r["uv_index"] == 8
    assert r["uv_index_category"] == "Very High"
    assert r["air_quality_category"] == "Good"


def test_flatten_hourly_forecast():
    payload = [
        {
            "DateTime": "2026-07-09T15:00:00+02:00",
            "EpochDateTime": 1783000000,
            "WeatherIcon": 1,
            "IconPhrase": "Sunny",
            "IsDaylight": True,
            "Temperature": {"Value": 24.0, "Unit": "C"},
            "PrecipitationProbability": 0,
            "HasPrecipitation": False,
            "Link": "http://x",
            "MobileLink": "http://m",
        }
    ]
    rows = flatten_hourly_forecast("125594", payload)
    assert rows[0]["temperature"] == 24.0
    assert set(HOURLY_PK).issubset(rows[0].keys())
    assert set(rows[0].keys()) == set(HOURLY_COLUMNS)


_HOURLY_DETAIL_COLUMNS = [
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
]


def test_flatten_hourly_forecast_details_false_leaves_detail_columns_empty():
    payload = [{"DateTime": "2026-07-09T15:00:00+02:00", "Temperature": {"Value": 24.0}}]
    r = flatten_hourly_forecast("1", payload)[0]
    assert set(_HOURLY_DETAIL_COLUMNS).issubset(r.keys())
    assert all(r[c] is None for c in _HOURLY_DETAIL_COLUMNS)


def test_flatten_hourly_forecast_details_true_populates_detail_columns():
    payload = [
        {
            "DateTime": "2026-07-09T17:00:00+02:00",
            "Temperature": {"Value": 25.4, "Unit": "C"},
            "RealFeelTemperature": {"Value": 26.0},
            "Wind": {"Speed": {"Value": 14.8}, "Direction": {"Degrees": 341, "Localized": "NNW"}},
            "RelativeHumidity": 32,
            "DewPoint": {"Value": 7.8},
            "UVIndex": 3,
            "UVIndexText": "Moderate",
            "Visibility": {"Value": 16.1},
            "CloudCover": 3,
            "PrecipitationType": "Rain",
            "Rain": {"Value": 0.5},
        }
    ]
    r = flatten_hourly_forecast("1", payload)[0]
    assert r["realfeel_temperature"] == 26.0
    assert r["wind_speed"] == 14.8
    assert r["wind_direction"] == "NNW"
    assert r["wind_direction_degrees"] == 341
    assert r["relative_humidity"] == 32
    assert r["dew_point"] == 7.8
    assert r["uv_index"] == 3
    assert r["uv_index_text"] == "Moderate"
    assert r["visibility"] == 16.1
    assert r["cloud_cover"] == 3
    assert r["precipitation_type"] == "Rain"
    assert r["rain"] == 0.5


def test_flatten_handles_missing_nested_keys():
    rows = flatten_current_conditions("1", [{"WeatherText": "Sunny"}])
    assert rows[0]["temperature"] is None
    assert rows[0]["wind_direction"] is None


def test_flatten_indices():
    payload = [
        {
            "Name": "UV Index",
            "ID": 26,
            "LocalDateTime": "2026-07-09T07:00:00+02:00",
            "EpochDateTime": 1783573200,
            "Value": 8.0,
            "Category": "High",
            "CategoryValue": 3,
            "Text": "Very high UV; wear sunscreen.",
            "Ascending": True,
        }
    ]
    rows = flatten_indices("125594", payload)
    assert len(rows) == 1
    r = rows[0]
    assert r["location_key"] == "125594"
    assert r["index_id"] == 26
    assert r["index_name"] == "UV Index"
    assert r["date"] == "2026-07-09T07:00:00+02:00"
    assert r["value"] == 8.0
    assert r["category"] == "High"
    assert r["category_value"] == 3
    assert r["text"] == "Very high UV; wear sunscreen."
    assert r["ascending"] is True
    assert set(INDICES_PK).issubset(r.keys())
    assert set(r.keys()) == set(INDICES_COLUMNS)


def test_flatten_indices_falls_back_to_epoch_when_no_local_datetime():
    rows = flatten_indices("1", [{"ID": 1, "Name": "Ski", "EpochDateTime": 1783573200}])
    # The epoch fallback is converted to an ISO timestamp string so the TIMESTAMP-typed
    # `date` PK column never carries a bare integer.
    assert rows[0]["date"] == "2026-07-09T05:00:00+00:00"
