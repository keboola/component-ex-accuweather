import pytest
import requests_mock

from client import AccuWeatherClient, AuthError, LocationNotFoundError, RateLimitError

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
        m.get(
            f"{BASE}/locations/v1/125594",
            status_code=401,
            json={"Code": "Unauthorized", "Message": "Api Authorization failed"},
        )
        with pytest.raises(AuthError):
            c.get_location("125594")


def test_403_maps_to_autherror():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/125594", status_code=403, json={"Message": "quota"})
        with pytest.raises(AuthError):
            c.get_location("125594")


def test_404_maps_to_location_not_found():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/999", status_code=404, json={})
        with pytest.raises(LocationNotFoundError):
            c.get_location("999")


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
        m.get(
            f"{BASE}/currentconditions/v1/125594",
            [{"status_code": 503, "json": {}}, {"status_code": 200, "json": [{"WeatherText": "Sunny"}]}],
        )
        out = c.get_current_conditions("125594", details=True)
        assert out[0]["WeatherText"] == "Sunny"


def test_daily_forecast_builds_correct_path_and_params():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/forecasts/v1/daily/5day/125594", json={"DailyForecasts": []})
        c.get_daily_forecast("125594", days=5, metric=True, details=True)
        assert m.last_request.qs["metric"] == ["true"]
        assert m.last_request.qs["details"] == ["true"]


def test_city_search_with_country_code():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/cities/CZ/search", json=[{"Key": "125594"}])
        out = c.search_cities("Prague", "CZ")
        assert out[0]["Key"] == "125594"
        assert m.last_request.qs["q"] == ["prague"]


def test_hourly_forecast_path():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/forecasts/v1/hourly/12hour/125594", json=[{"Temperature": {"Value": 1}}])
        out = c.get_hourly_forecast("125594", hours=12, metric=True, details=False)
        assert out[0]["Temperature"]["Value"] == 1
