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

The generic Locations text-search endpoint (`/locations/v1/search`) is used internally to resolve the
`locationKey` from a city name or postal code; `geoposition` uses `/locations/v1/cities/geoposition/search`.

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
- `location_type` — `search` (default) or `geoposition`.
- **Search mode** (`search`): one free-text box that resolves both city names and postal codes.
  - `location_search` — the text to search (a city name like `Prague`, or a postal/ZIP code like `110 00`
    or `10001`). Resolved via AccuWeather's generic text-search endpoint, which matches cities,
    administrative areas AND postal codes.
  - `location_key` — the confirmed AccuWeather location key. Use **Find & confirm location** to search with
    the query above and pick a match, or paste a known key directly. When set it is authoritative and skips
    resolution; when empty the `location_search` query is resolved at run time (headless configs may leave it
    empty and rely on `location_search`).
- **Geo mode** (`geoposition`): `latitude` / `longitude` in decimal degrees.
- `datasets` — object of per-dataset toggles and their options (at least one dataset must be enabled):
  - `current_conditions` (default `true`) with `current_conditions_details` (default `false`).
  - `daily_forecast` (default `false`) with `daily_range` (`1`/`5`/`10`/`15`, default `5`) and
    `daily_forecast_details` (default `false`).
  - `hourly_forecast` (default `false`) with `hourly_range` (`1`/`12`/`24`/`72`/`120`, default `12`) and
    `hourly_forecast_details` (default `false`).
  - `indices` (default `false`) with `indices_range` (`1`/`5`/`10`/`15`, default `5`) and an optional
    `indices_ids` multi-select — pick specific AccuWeather indices from the built-in list (each shown as
    "Name (ID)"); empty means keep all indices, otherwise only the selected index IDs are kept (filtered
    client-side).
  - Each `*_details` toggle adds extra detail columns to that dataset's table (see Output below). The
    columns are always present in the schema and left empty when the toggle is off.

Sync actions
-------
- `testConnection` — validates the API key.
- `search_locations` — returns matching locations (cities and postal codes) for the typed query via the
  generic text-search endpoint.

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
