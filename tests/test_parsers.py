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
    assert rows[0]["date"] == 1783573200
