import pytest
from keboola.component.exceptions import UserException

from configuration import Configuration, Units


def test_minimal_city_config():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "city", "city_query": "Prague"})
    assert cfg.api_key == "KEY"
    assert cfg.units == Units.metric
    # datasets defaults: current_conditions on, everything else off, details off
    assert cfg.datasets.current_conditions is True
    assert cfg.datasets.current_conditions_details is False
    assert cfg.datasets.daily_forecast is False
    assert cfg.datasets.hourly_forecast is False
    assert cfg.datasets.indices is False
    assert cfg.datasets.indices_ids is None


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
            "datasets": {"daily_range": 10, "hourly_range": 72, "indices_range": 15},
        }
    )
    assert cfg.datasets.daily_range == 10
    assert cfg.datasets.hourly_range == 72
    assert cfg.datasets.indices_range == 15


def test_out_of_range_daily_raises_userexception():
    with pytest.raises(UserException):
        Configuration(
            **{
                "#api_key": "K",
                "location_type": "location_key",
                "location_key": "1",
                "datasets": {"daily_range": 7},
            }
        )


def test_out_of_range_hourly_raises_userexception():
    with pytest.raises(UserException):
        Configuration(
            **{
                "#api_key": "K",
                "location_type": "location_key",
                "location_key": "1",
                "datasets": {"hourly_range": 48},
            }
        )


def test_out_of_range_indices_raises_userexception():
    with pytest.raises(UserException):
        Configuration(
            **{
                "#api_key": "K",
                "location_type": "location_key",
                "location_key": "1",
                "datasets": {"indices_range": 3},
            }
        )


def test_no_dataset_selected_rejected_by_validate_location():
    # All four toggles off is constructible (sync actions need it) but must fail validate_location().
    cfg = Configuration(
        **{
            "#api_key": "K",
            "location_type": "location_key",
            "location_key": "1",
            "datasets": {"current_conditions": False},
        }
    )
    assert cfg.datasets.any_selected is False
    with pytest.raises(UserException):
        cfg.validate_location()


def test_single_non_default_dataset_passes_validation():
    # current_conditions off but indices on -> at least one selected -> valid.
    cfg = Configuration(
        **{
            "#api_key": "K",
            "location_type": "location_key",
            "location_key": "1",
            "datasets": {"current_conditions": False, "indices": True},
        }
    )
    assert cfg.datasets.any_selected is True
    cfg.validate_location()  # must not raise


def test_indices_ids_parsed_as_int_list():
    cfg = Configuration(
        **{
            "#api_key": "K",
            "location_type": "location_key",
            "location_key": "1",
            "datasets": {"indices": True, "indices_ids": [1, 5, 26]},
        }
    )
    assert cfg.datasets.indices_ids == [1, 5, 26]
