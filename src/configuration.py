from enum import IntEnum, StrEnum

from keboola.component.exceptions import UserException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


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


class Dataset(StrEnum):
    current_conditions = "current_conditions"
    daily_forecast = "daily_forecast"
    hourly_forecast = "hourly_forecast"


class Configuration(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    api_key: str = Field(alias="#api_key")
    units: Units = Units.metric
    language: str = "en-us"
    include_details: bool = True

    location_type: LocationType = LocationType.city
    location_query: str | None = None
    country_code: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_key: str | None = None

    datasets: list[Dataset] = Field(default_factory=lambda: [Dataset.current_conditions])
    daily_range: DailyRange = DailyRange.five
    hourly_range: HourlyRange = HourlyRange.twelve

    def __init__(self, **data):
        try:
            super().__init__(**data)
        except ValidationError as e:
            msgs = [f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()]
            raise UserException(f"Configuration validation error: {', '.join(msgs)}")

    @model_validator(mode="after")
    def _check_location_fields(self):
        lt = self.location_type
        if lt in (LocationType.city, LocationType.postal_code) and not self.location_query:
            raise UserException(f"location_query is required when location_type is '{lt}'.")
        if lt == LocationType.geoposition and (self.latitude is None or self.longitude is None):
            raise UserException("latitude and longitude are required for geoposition.")
        if lt == LocationType.location_key and not self.location_key:
            raise UserException("location_key is required when location_type is 'location_key'.")
        return self

    @property
    def metric(self) -> bool:
        return self.units == Units.metric
