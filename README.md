ex-accuweather
=============

Keboola extractor for the [AccuWeather APIs](https://developer.accuweather.com/apis). For each
configured location it resolves an AccuWeather `locationKey` and pulls the enabled weather
datasets — current conditions, daily & hourly forecasts, and/or lifestyle indices — into typed
Storage tables as a timestamped time series.

**Table of Contents:**

[TOC]

Functionality Notes
===================

- One **config row per location**. Within a row you pick which datasets to pull via the
  `datasets` object — a toggle per dataset, each with its own range / details / filter sub-options.
- The resolved `locationKey` is cached in the row's `state.json` (keyed by a hash of the location
  inputs) so a Locations API call is only spent when the inputs change — conserving the tight
  trial quota.
- All datasets are written with `incremental=True` and a composite primary key that includes
  `location_key`, so re-running upserts on the key and running over time accumulates a time
  series. There is deliberately no full-load toggle (it would wipe other locations' rows in the
  shared per-config tables).
- Output tables carry an authoritative `schema` manifest (native data types) and are written as
  **headerless CSVs**.

Prerequisites
=============

Create a developer account at [developer.accuweather.com](https://developer.accuweather.com),
create an app/subscription, and copy the API key. Provide it as the secret `#api_key`.
Authentication uses `Authorization: Bearer <#api_key>`.

Supported Endpoints
===================

| Dataset | Endpoint | Output table | PK |
|---|---|---|---|
| Current conditions | `/currentconditions/v1/{locationKey}` | `current_conditions` | `(location_key, observation_datetime)` |
| Daily forecast | `/forecasts/v1/daily/{n}day/{locationKey}` | `daily_forecast` | `(location_key, forecast_date)` |
| Hourly forecast | `/forecasts/v1/hourly/{n}hour/{locationKey}` | `hourly_forecast` | `(location_key, forecast_datetime)` |
| Lifestyle indices | `/indices/v1/daily/{n}day/{locationKey}` | `indices` | `(location_key, index_id, date)` |

Locations endpoints are used internally to resolve the `locationKey`.

If you need additional endpoints, please submit your request to
[ideas.keboola.com](https://ideas.keboola.com/).

Configuration
=============

Config-level (root)
-------
- `#api_key` (secret, required) — AccuWeather API key.
- `units` — `metric` (default) or `imperial`.
- `language` — AccuWeather language code, default `en-us`.

Row-level (per location)
-------
- `location_type` — `city` (default), `postal_code`, `geoposition`, or `location_key`.
- `city_query` — city name to search (`city` mode).
- `postal_query` — postal/ZIP code to look up (`postal_code` mode; `country_code` required).
- `location_search` — free-text term for the `search_locations` sync action (`location_key` mode).
- `country_code` — ISO 3166 2-letter country code to disambiguate city/postal search; required for postal lookup.
- `city_location_key` / `postal_location_key` — optional key confirmed by the "Find & confirm location" picker
  in `city` / `postal_code` mode. When set it pins the exact place and skips resolution; when empty the
  free-text query above resolves at run time (headless configs leave these empty).
- `latitude` / `longitude` — for `geoposition`.
- `location_key` — a directly-supplied AccuWeather key (skips resolution).
- `datasets` — object of per-dataset toggles and their options (at least one dataset must be enabled):
  - `current_conditions` (default `true`) with `current_conditions_details` (default `false`).
  - `daily_forecast` (default `false`) with `daily_range` (`1`/`5`/`10`/`15`, default `5`) and
    `daily_forecast_details` (default `false`).
  - `hourly_forecast` (default `false`) with `hourly_range` (`1`/`12`/`24`/`72`/`120`, default `12`) and
    `hourly_forecast_details` (default `false`).
  - `indices` (default `false`) with `indices_range` (`1`/`5`/`10`/`15`, default `5`) and an optional
    `indices_ids` integer list — empty means all indices, otherwise only the listed AccuWeather index IDs
    are kept (filtered client-side).
  - Each `*_details` toggle adds extra detail columns to that dataset's table (see Output below). The
    columns are always present in the schema and left empty when the toggle is off.

Sync actions
-------
- `testConnection` — validates the API key.
- `search_locations` — returns matching locations for the typed query.

Output
======

Up to four tables (`current_conditions`, `daily_forecast`, `hourly_forecast`, `indices`) routed to
the config's default bucket, each with an authoritative schema and a composite primary key.

Detail columns (populated only when the matching `*_details` toggle is on; empty otherwise):

- `current_conditions` — `realfeel_temperature`, `relative_humidity`, `wind_speed`,
  `wind_direction_degrees`, `wind_direction`, `uv_index`, `uv_index_text`, `visibility`,
  `cloud_cover`, `pressure`.
- `daily_forecast` — `realfeel_temperature_min`, `realfeel_temperature_max`, `hours_of_sun`,
  `day_wind_speed`, `day_wind_direction`, `day_wind_direction_degrees`,
  `day_thunderstorm_probability`, `day_rain_probability`, `night_wind_speed`,
  `night_wind_direction`, `night_wind_direction_degrees`, `night_thunderstorm_probability`,
  `night_rain_probability`, `uv_index`, `uv_index_category`, `air_quality_category`.
- `hourly_forecast` — `realfeel_temperature`, `wind_speed`, `wind_direction`,
  `wind_direction_degrees`, `relative_humidity`, `dew_point`, `uv_index`, `uv_index_text`,
  `visibility`, `cloud_cover`, `precipitation_type`, `rain`.

Forecast values follow the configured `units` (Metric/Imperial): the daily and hourly endpoints take a
`metric` query parameter, so their values arrive already in the chosen system; `current_conditions`
returns both systems and the parser selects the configured one.

Development
-----------

To customize the local data folder path, replace the `CUSTOM_FOLDER` placeholder with your desired path in the `docker-compose.yml` file:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    volumes:
      - ./:/code
      - ./CUSTOM_FOLDER:/data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Clone this repository, initialize the workspace, and run the component using the following
commands:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
git clone  component-ex-accuweather
cd component-ex-accuweather
docker-compose build
docker-compose run --rm dev
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the test suite and perform lint checks using this command:

~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
docker-compose run --rm test
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Integration
===========

For details about deployment and integration with Keboola, refer to the
[deployment section of the developer
documentation](https://developers.keboola.com/extend/component/deployment/).
