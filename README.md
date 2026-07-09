ex-accuweather
=============

Keboola extractor for the [AccuWeather APIs](https://developer.accuweather.com/apis). For each
configured location it resolves an AccuWeather `locationKey` and pulls the enabled weather
datasets — current conditions and/or daily & hourly forecasts — into typed Storage tables as a
timestamped time series.

**Table of Contents:**

[TOC]

Functionality Notes
===================

- One **config row per location**. Within a row you pick which datasets to pull via the
  `datasets` multi-select.
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
- `include_details` — include detail fields, default `true`.

Row-level (per location)
-------
- `location_type` — `city` (default), `postal_code`, `geoposition`, or `location_key`.
- `location_query` — free-text query (for `city`/`postal_code`); aided by the `search_locations`
  sync action.
- `country_code` — optional ISO country code to disambiguate city/postal search.
- `latitude` / `longitude` — for `geoposition`.
- `location_key` — a directly-supplied AccuWeather key (skips resolution).
- `datasets` — multi-select of `current_conditions`, `daily_forecast`, `hourly_forecast`.
- `daily_range` — number of forecast days (`1`/`5`/`10`/`15`), default `5`.
- `hourly_range` — number of forecast hours (`1`/`12`/`24`/`72`/`120`), default `12`.

Sync actions
-------
- `testConnection` — validates the API key.
- `search_locations` — returns matching locations for the typed query.

Output
======

Up to three tables (`current_conditions`, `daily_forecast`, `hourly_forecast`) routed to the
config's default bucket, each with an authoritative schema and a composite primary key.

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
