import pytest
from keboola.component.exceptions import UserException

from configuration import Configuration, Dataset, Units


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
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "geoposition", "latitude": 50.08, "longitude": 14.42})
    assert cfg.latitude == 50.08


def test_extra_keys_ignored():
    cfg = Configuration(
        **{"#api_key": "KEY", "location_type": "location_key", "location_key": "125594", "debug": True, "unknown": 1}
    )
    assert cfg.location_key == "125594"


def test_city_requires_location_query():
    with pytest.raises(UserException):
        Configuration(**{"#api_key": "KEY", "location_type": "city"})


def test_metric_property():
    metric_cfg = Configuration(**{"#api_key": "K", "location_type": "location_key", "location_key": "1"})
    assert metric_cfg.metric is True
    imperial_cfg = Configuration(
        **{"#api_key": "K", "location_type": "location_key", "location_key": "1", "units": "imperial"}
    )
    assert imperial_cfg.metric is False


def test_valid_ranges_accepted():
    cfg = Configuration(
        **{
            "#api_key": "K",
            "location_type": "location_key",
            "location_key": "1",
            "daily_range": 10,
            "hourly_range": 72,
        }
    )
    assert cfg.daily_range == 10
    assert cfg.hourly_range == 72


def test_out_of_range_daily_raises_userexception():
    with pytest.raises(UserException):
        Configuration(**{"#api_key": "K", "location_type": "location_key", "location_key": "1", "daily_range": 7})


def test_out_of_range_hourly_raises_userexception():
    with pytest.raises(UserException):
        Configuration(**{"#api_key": "K", "location_type": "location_key", "location_key": "1", "hourly_range": 48})
