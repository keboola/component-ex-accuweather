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


def test_flatten_handles_missing_nested_keys():
    rows = flatten_current_conditions("1", [{"WeatherText": "Sunny"}])
    assert rows[0]["temperature"] is None
    assert rows[0]["wind_direction"] is None
