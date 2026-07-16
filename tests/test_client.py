import pytest
import requests
import requests_mock

from client import (
    AccuWeatherApiError,
    AccuWeatherClient,
    AuthError,
    LocationNotFoundError,
    RateLimitError,
)

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


def test_generic_search_sends_only_query():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/search", json=[{"Key": "125594"}])
        out = c.search_locations("Prague")
        assert out[0]["Key"] == "125594"
        assert m.last_request.qs["q"] == ["prague"]
        # generic search ignores country, so the client never sends it
        assert "country" not in m.last_request.qs


def test_generic_search_resolves_postal_code():
    # The same generic endpoint resolves a postal code (PostalCode-type result).
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/search", json=[{"Key": "373889_PC", "Type": "PostalCode"}])
        out = c.search_locations("110 00")
        assert out[0]["Key"] == "373889_PC"
        assert m.last_request.qs["q"] == ["110 00"]


def test_hourly_forecast_path():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/forecasts/v1/hourly/12hour/125594", json=[{"Temperature": {"Value": 1}}])
        out = c.get_hourly_forecast("125594", hours=12, metric=True, details=False)
        assert out[0]["Temperature"]["Value"] == 1


def test_indices_builds_correct_path_and_no_metric_details():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/indices/v1/daily/5day/125594", json=[{"ID": 26, "Name": "UV Index"}])
        out = c.get_indices("125594", days=5)
        assert out[0]["ID"] == 26
        assert "metric" not in m.last_request.qs
        assert "details" not in m.last_request.qs
        assert "language" not in m.last_request.qs


def test_indices_language_param_sent():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/indices/v1/daily/1day/125594", json=[])
        c.get_indices("125594", days=1, language="cs-cz")
        assert m.last_request.qs["language"] == ["cs-cz"]


def test_language_param_sent_on_current_conditions():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/currentconditions/v1/125594", json=[{"WeatherText": "Ensoleillé"}])
        c.get_current_conditions("125594", details=True, language="fr-fr")
        assert m.last_request.qs["language"] == ["fr-fr"]


def test_language_param_sent_on_forecasts():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/forecasts/v1/daily/5day/125594", json={"DailyForecasts": []})
        m.get(f"{BASE}/forecasts/v1/hourly/12hour/125594", json=[])
        c.get_daily_forecast("125594", days=5, metric=True, details=True, language="de-de")
        assert m.last_request.qs["language"] == ["de-de"]
        c.get_hourly_forecast("125594", hours=12, metric=True, details=True, language="es-es")
        assert m.last_request.qs["language"] == ["es-es"]


def test_language_param_omitted_when_none():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/currentconditions/v1/125594", json=[])
        c.get_current_conditions("125594", details=True)
        assert "language" not in m.last_request.qs


def test_network_error_maps_to_api_error():
    c = AccuWeatherClient("KEY", max_retries=0)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/125594", exc=requests.exceptions.ConnectTimeout)
        with pytest.raises(AccuWeatherApiError):
            c.get_location("125594")


def test_unmapped_4xx_maps_to_api_error():
    c = AccuWeatherClient("KEY")
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/locations/v1/125594", status_code=400, json={"Message": "Bad Request"})
        with pytest.raises(AccuWeatherApiError):
            c.get_location("125594")


def test_terminal_5xx_after_retries_maps_to_api_error():
    c = AccuWeatherClient("KEY", max_retries=1, backoff_base=0)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/currentconditions/v1/125594", status_code=500, json={})
        with pytest.raises(AccuWeatherApiError):
            c.get_current_conditions("125594", details=True)
        assert m.call_count == 2  # initial + 1 retry


def test_408_is_retried():
    c = AccuWeatherClient("KEY", max_retries=2, backoff_base=0)
    with requests_mock.Mocker() as m:
        m.get(
            f"{BASE}/currentconditions/v1/125594",
            [{"status_code": 408, "json": {}}, {"status_code": 200, "json": [{"WeatherText": "Sunny"}]}],
        )
        out = c.get_current_conditions("125594", details=True)
        assert out[0]["WeatherText"] == "Sunny"
        assert m.call_count == 2


def test_521_is_retried():
    # 521 (and any 5xx) is now part of the transient set and must be retried.
    c = AccuWeatherClient("KEY", max_retries=2, backoff_base=0)
    with requests_mock.Mocker() as m:
        m.get(
            f"{BASE}/currentconditions/v1/125594",
            [{"status_code": 521, "json": {}}, {"status_code": 200, "json": [{"WeatherText": "Sunny"}]}],
        )
        out = c.get_current_conditions("125594", details=True)
        assert out[0]["WeatherText"] == "Sunny"
        assert m.call_count == 2


def test_521_exhaustion_maps_to_api_error():
    c = AccuWeatherClient("KEY", max_retries=1, backoff_base=0)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/currentconditions/v1/125594", status_code=521, json={})
        with pytest.raises(AccuWeatherApiError):
            c.get_current_conditions("125594", details=True)
        assert m.call_count == 2  # initial + 1 retry


def test_429_exhaustion_maps_to_rate_limit_error():
    c = AccuWeatherClient("KEY", max_retries=1, backoff_base=0)
    with requests_mock.Mocker() as m:
        m.get(f"{BASE}/currentconditions/v1/125594", status_code=429, json={})
        with pytest.raises(RateLimitError):
            c.get_current_conditions("125594", details=True)
        assert m.call_count == 2  # initial + 1 retry


def test_network_error_is_retried_then_succeeds():
    c = AccuWeatherClient("KEY", max_retries=2, backoff_base=0)
    with requests_mock.Mocker() as m:
        m.get(
            f"{BASE}/currentconditions/v1/125594",
            [{"exc": requests.exceptions.ConnectTimeout}, {"status_code": 200, "json": [{"WeatherText": "Sunny"}]}],
        )
        out = c.get_current_conditions("125594", details=True)
        assert out[0]["WeatherText"] == "Sunny"
        assert m.call_count == 2


def test_typed_errors_are_api_error_subclasses():
    assert issubclass(AuthError, AccuWeatherApiError)
    assert issubclass(LocationNotFoundError, AccuWeatherApiError)
    assert issubclass(RateLimitError, AccuWeatherApiError)
