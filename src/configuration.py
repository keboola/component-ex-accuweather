from enum import IntEnum, StrEnum

from keboola.component.exceptions import UserException
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Units(StrEnum):
    metric = "metric"
    imperial = "imperial"


class DailyRange(IntEnum):
    one = 1
    five = 5
    ten = 10
    fifteen = 15


class HourlyRange(IntEnum):
    one = 1
    twelve = 12
    twenty_four = 24
    seventy_two = 72
    one_twenty = 120


class LocationType(StrEnum):
    city = "city"
    postal_code = "postal_code"
    geoposition = "geoposition"
    location_key = "location_key"


class DatasetsConfig(BaseModel):
    """Nested per-dataset selection (mirrors the row schema's `datasets` object).

    Each of the four dataset toggles is a boolean; the range / details / filter
    sub-options are gated on the matching toggle in the UI but always constructible
    here (defaults fill in when a toggle is off).
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    current_conditions: bool = True
    current_conditions_details: bool = False

    daily_forecast: bool = False
    daily_range: DailyRange = DailyRange.five
    daily_forecast_details: bool = False

    hourly_forecast: bool = False
    hourly_range: HourlyRange = HourlyRange.twelve
    hourly_forecast_details: bool = False

    indices: bool = False
    indices_range: DailyRange = DailyRange.five
    indices_ids: list[int] | None = None

    @property
    def any_selected(self) -> bool:
        return self.current_conditions or self.daily_forecast or self.hourly_forecast or self.indices


class Configuration(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    api_key: str = Field(alias="#api_key")
    units: Units = Units.metric
    language: str = "en-us"

    location_type: LocationType = LocationType.location_key
    city_query: str | None = None
    postal_query: str | None = None
    location_search: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_key: str | None = None
    # Optional keys committed by the config-time confirmation picker in city / postal modes.
    # UI-only add-on: when set they pin the exact place; when empty the free-text query resolves
    # at runtime exactly as before (headless configs never populate these).
    city_location_key: str | None = None
    postal_location_key: str | None = None

    datasets: DatasetsConfig = Field(default_factory=DatasetsConfig)

    def __init__(self, **data):
        try:
            super().__init__(**data)
        except ValidationError as e:
            msgs = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
            raise UserException(f"Configuration validation error: {', '.join(msgs)}") from e

    def validate_location(self) -> None:
        """Validate the row-level location cross-field requirements.

        Called from run() (extraction) only — NOT during construction — because sync-action
        dispatch (testConnection validates auth only; search_locations is *how* the user finds
        a location key) legitimately runs before a location is resolved. Running this at
        construction crashed those actions (UserException is not a ValueError, so pydantic
        does not wrap it and the ``except ValidationError`` above never catches it).
        """
        lt = self.location_type
        if lt == LocationType.city and not (self.city_query or self.city_location_key):
            raise UserException("city_query is required when location_type is 'city'.")
        if lt == LocationType.postal_code:
            # A picker-confirmed key stands on its own; the free-text path still needs both
            # the postal code and a country code (unchanged headless behaviour).
            if not (self.postal_query or self.postal_location_key):
                raise UserException("postal_query is required when location_type is 'postal_code'.")
            if self.postal_query and not self.postal_location_key and not self.country_code:
                raise UserException("country_code is required when location_type is 'postal_code'.")
        if lt == LocationType.geoposition and (self.latitude is None or self.longitude is None):
            raise UserException("latitude and longitude are required for geoposition.")
        if lt == LocationType.location_key and not self.location_key:
            raise UserException("location_key is required when location_type is 'location_key'.")
        if not self.datasets.any_selected:
            raise UserException("Select at least one dataset to extract for this location.")

    @property
    def search_query(self) -> str | None:
        """Mode-specific free-text query used for location search (city/postal/location-key modes)."""
        if self.location_type == LocationType.city:
            return self.city_query
        if self.location_type == LocationType.postal_code:
            return self.postal_query
        if self.location_type == LocationType.location_key:
            return self.location_search
        return None

    @property
    def picked_location_key(self) -> str | None:
        """Location key confirmed via the config-time picker (city / postal modes only).

        None for headless configs and modes without a picker, so the runtime resolver
        falls back to free-text search exactly as before.
        """
        if self.location_type == LocationType.city:
            return self.city_location_key
        if self.location_type == LocationType.postal_code:
            return self.postal_location_key
        return None

    @property
    def metric(self) -> bool:
        return self.units == Units.metric
