import pytest
from keboola.component.exceptions import UserException

from configuration import Configuration, LocationType, Units


def test_minimal_search_config():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "search", "location_search": "Prague"})
    assert cfg.api_key == "KEY"
    assert cfg.units == Units.metric
    # datasets defaults: current_conditions on, everything else off, details off
    assert cfg.datasets.current_conditions is True
    assert cfg.datasets.current_conditions_details is False
    assert cfg.datasets.daily_forecast is False
    assert cfg.datasets.hourly_forecast is False
    assert cfg.datasets.indices is False
    assert cfg.datasets.indices_ids is None


def test_search_is_the_default_location_type():
    cfg = Configuration(**{"#api_key": "KEY", "location_search": "Prague"})
    assert cfg.location_type == LocationType.search


def test_missing_api_key_raises_userexception():
    with pytest.raises(UserException):
        Configuration(**{"location_type": "search", "location_search": "Prague"})


def test_geoposition_requires_lat_lon():
    # Location cross-field checks run via validate_location() (in run()), not at construction,
    # so sync actions can dispatch without a resolved location.
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "geoposition"})
    with pytest.raises(UserException):
        cfg.validate_location()


def test_geoposition_ok_with_lat_lon():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "geoposition", "latitude": 50.08, "longitude": 14.42})
    cfg.validate_location()  # must not raise
    assert cfg.latitude == 50.08


def test_extra_keys_ignored():
    cfg = Configuration(
        **{"#api_key": "KEY", "location_type": "search", "location_key": "125594", "debug": True, "unknown": 1}
    )
    assert cfg.location_key == "125594"


def test_search_requires_query_or_key():
    # search mode with neither a query nor a confirmed key -> fails validate_location()
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "search"})
    with pytest.raises(UserException):
        cfg.validate_location()


def test_indices_ids_accepts_ui_labels():
    # The multi-select UI can persist the label ("Name (id)"); the model normalizes to the int.
    cfg = Configuration(
        **{
            "#api_key": "KEY",
            "location_search": "Prague",
            "datasets": {"indices": True, "indices_ids": ["Carwashing Forecast (51)", "UV Index (-15)"]},
        }
    )
    assert cfg.datasets.indices_ids == [51, -15]


def test_indices_ids_accepts_ints_and_numeric_strings():
    cfg = Configuration(**{"#api_key": "KEY", "datasets": {"indices_ids": [26, "5", "-10"]}})
    assert cfg.datasets.indices_ids == [26, 5, -10]


def test_indices_ids_rejects_unparseable_value():
    with pytest.raises(UserException):
        Configuration(**{"#api_key": "KEY", "datasets": {"indices_ids": ["not an index"]}})


def test_search_ok_with_query():
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "search", "location_search": "Prague"})
    cfg.validate_location()  # must not raise
    assert cfg.search_query == "Prague"


def test_search_ok_with_confirmed_key():
    # A confirmed/pasted key alone satisfies validation (no free-text query needed).
    cfg = Configuration(**{"#api_key": "KEY", "location_type": "search", "location_key": "125594"})
    cfg.validate_location()  # must not raise


def test_search_query_none_outside_search_mode():
    cfg = Configuration(**{"#api_key": "K", "location_type": "geoposition", "latitude": 1.0, "longitude": 2.0})
    assert cfg.search_query is None


def test_metric_property():
    metric_cfg = Configuration(**{"#api_key": "K", "location_type": "search", "location_key": "1"})
    assert metric_cfg.metric is True
    imperial_cfg = Configuration(
        **{"#api_key": "K", "location_type": "search", "location_key": "1", "units": "imperial"}
    )
    assert imperial_cfg.metric is False


def test_valid_ranges_accepted():
    cfg = Configuration(
        **{
            "#api_key": "K",
            "location_type": "search",
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
                "location_type": "search",
                "location_key": "1",
                "datasets": {"daily_range": 7},
            }
        )


def test_out_of_range_hourly_raises_userexception():
    with pytest.raises(UserException):
        Configuration(
            **{
                "#api_key": "K",
                "location_type": "search",
                "location_key": "1",
                "datasets": {"hourly_range": 48},
            }
        )


def test_out_of_range_indices_raises_userexception():
    with pytest.raises(UserException):
        Configuration(
            **{
                "#api_key": "K",
                "location_type": "search",
                "location_key": "1",
                "datasets": {"indices_range": 3},
            }
        )


def test_no_dataset_selected_rejected_by_validate_location():
    # All four toggles off is constructible (sync actions need it) but must fail validate_location().
    cfg = Configuration(
        **{
            "#api_key": "K",
            "location_type": "search",
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
            "location_type": "search",
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
            "location_type": "search",
            "location_key": "1",
            "datasets": {"indices": True, "indices_ids": [1, 5, 26]},
        }
    )
    assert cfg.datasets.indices_ids == [1, 5, 26]
