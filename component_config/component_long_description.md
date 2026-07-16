The AccuWeather extractor pulls weather data from the [AccuWeather APIs](https://developer.accuweather.com/apis)
into Keboola Storage as a per-location time series.

Each configuration row represents one **location**, identified by a search query (a city name or
postal code) or a geo-position. For every location the component resolves an AccuWeather
`locationKey` (cached in state to conserve API quota) and fetches the datasets you enable:

- **Current conditions** — the latest observation for the location.
- **Daily forecast** — 1, 5, 10, or 15 days.
- **Hourly forecast** — 1, 12, 24, 72, or 120 hours.

Each dataset is written to its own table (`current_conditions`, `daily_forecast`,
`hourly_forecast`) with **incremental upsert** on a `location_key`-prefixed primary key, so
re-running accumulates a time series while replacing rows within the same observation or forecast
window. All rows in a configuration share the same tables in the default bucket.

**Authentication** uses a single API key sent as a Bearer token. Create a developer account at
[developer.accuweather.com](https://developer.accuweather.com), add an app, and copy its API key.

**Limitations:** AccuWeather exposes no server-side incremental cursor, so each run re-polls the
current snapshot. The public trial tier is limited to 500 requests/day.
