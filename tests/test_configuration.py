import pytest
from keboola.component.exceptions import UserException

from configuration import Configuration, Dataset, Units


def test_minimal_city_config():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "city", "city_query": "Prague"})
    assert cfg.api_key == "KEY"
    assert cfg.units == Units.metric
    assert cfg.datasets == [Dataset.current_conditions]
    assert cfg.include_details is True


def test_missing_api_key_raises_userexception():
    with pytest.raises(UserException):
        Configuration(**{"location_type": "city", "city_query": "Prague"})


def test_geoposition_requires_lat_lon():
    # Location cross-field checks run via validate_location() (in run()), not at construction,
    # so sync actions can dispatch without a resolved location.
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "geoposition"})
    with pytest.raises(UserException):
        cfg.validate_location()


def test_geoposition_ok_with_lat_lon():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "geoposition", "latitude": 50.08, "longitude": 14.42})
    assert cfg.latitude == 50.08


def test_extra_keys_ignored():
    cfg = Configuration(
        **{"#api_key": "KEY", "location_type": "location_key", "location_key": "125594", "debug": True, "unknown": 1}
    )
    assert cfg.location_key == "125594"


def test_city_requires_city_query():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "city"})
    with pytest.raises(UserException):
        cfg.validate_location()


def test_postal_requires_postal_query_and_country_code():
    # postal_query missing -> fails
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "postal_code", "country_code": "US"})
    with pytest.raises(UserException):
        cfg.validate_location()
    # postal_query present but country_code missing -> still fails (required for postal lookup)
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "postal_code", "postal_query": "10001"})
    with pytest.raises(UserException):
        cfg.validate_location()


def test_postal_ok_with_postal_query_and_country_code():
    cfg = Configuration(
        **{"#api_key": "KEY", "location_type": "postal_code", "postal_query": "10001", "country_code": "US"}
    )
    cfg.validate_location()  # must not raise
    assert cfg.search_query == "10001"


def test_city_picker_key_satisfies_validation_without_query():
    # A picker-confirmed key alone is a valid city location (UI confirmation path).
    cfg = Configuration(**{"#api_key": "K", "location_type": "city", "city_location_key": "125594"})
    cfg.validate_location()  # must not raise
    assert cfg.picked_location_key == "125594"


def test_postal_picker_key_satisfies_validation_without_country_code():
    # A picker-confirmed key alone is valid; country_code is only needed for free-text postal lookup.
    cfg = Configuration(**{"#api_key": "K", "location_type": "postal_code", "postal_location_key": "349727"})
    cfg.validate_location()  # must not raise
    assert cfg.picked_location_key == "349727"


def test_picked_location_key_none_outside_city_postal():
    cfg = Configuration(**{"#api_key": "K", "location_type": "location_key", "location_key": "1"})
    assert cfg.picked_location_key is None


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


def test_empty_datasets_rejected_by_validate_location():
    # Empty datasets is constructible (sync actions need it) but must fail validate_location().
    cfg = Configuration(**{"#api_key": "K", "location_type": "location_key", "location_key": "1", "datasets": []})
    with pytest.raises(UserException):
        cfg.validate_location()
