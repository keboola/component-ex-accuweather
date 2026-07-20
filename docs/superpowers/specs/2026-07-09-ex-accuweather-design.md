# keboola.ex-accuweather — Design Spec

> Type: extractor
> Component ID: keboola.ex-accuweather
> Status: draft
> Date: 2026-07-09
> Research: `docs/superpowers/specs/2026-07-09-ex-accuweather-research.md` (Phase 2)

## 1. Overview & source system

`keboola.ex-accuweather` is a Keboola **extractor** that pulls weather data from the
**AccuWeather APIs** (`https://dataservice.accuweather.com`) into Storage tables. For each
configured location it resolves an AccuWeather `locationKey` and then fetches the enabled
weather datasets — current conditions and/or daily & hourly forecasts — appending them as a
timestamped time series.

- Source system: AccuWeather developer APIs. Docs:
  <https://developer.accuweather.com/apis>, quick-start
  <https://developer.accuweather.com/documentation/core-weather-quick-start>.
- Primary use case: build a per-location weather time series (observations + forecasts) in
  Keboola for analytics/BI — e.g. correlating sales or logistics with weather, or dashboards
  that track forecast accuracy over time.

## 2. Keboola mapping

How AccuWeather concepts map onto how Keboola runs a component.

### Config rows: one row per **location**

- The natural independent object a user configures is a **location**. Multiple locations →
  **config rows, one row per location**, per Keboola convention (`config-rows.md`). Each row
  can be enabled/disabled, scheduled, run and retried independently, and gets its own
  `state.json` (the cached `locationKey`).
- **Within a row**, the user picks which datasets to pull (current conditions, daily forecast,
  hourly forecast) via a multipick. The object-level granularity is deliberately the **location**,
  not the dataset, because all three datasets hang off the **same resolved `locationKey`** for
  the same location and share the same per-row state (the cached key). Splitting a location's
  datasets into three separate rows would re-resolve and re-cache the same `locationKey` three
  times (three extra Locations calls against the tight trial quota) and fragment one location's
  state across rows — the datasets meet the convention's "fetched together, share a logical
  transaction" override rather than the "independent objects" case. A multipick *inside* a row
  for selecting these co-located sub-resources is therefore the right granularity.
- Rows execute **sequentially by default** (parallelism is opt-in and off here). Each row runs
  its full input-mapping → run → output-mapping cycle and its outputs are committed before the
  next row starts. Because all rows target the **same stable table names** with incremental
  upsert, locations accumulate into shared datasets across rows within a single job.

### Config-level vs row-level parameters

- **Config level (root):** `#api_key` (secret), `units` (metric/imperial), `language`,
  `include_details`. Credentials + global rendering options entered once.
- **Row level:** `location_type`, the location value field(s), `country_code`, `datasets`
  (multipick), `daily_range`, `hourly_range`. Per-location selection scales per row.
- At runtime the platform **merges** each row's `parameters` onto the root `parameters` and the
  component receives one flat merged `config.json` — the component never sees the root/row
  split. A single Pydantic `Configuration` model covers the merged shape.

### Source objects/endpoints → output tables

| Dataset (row multipick) | Endpoint | Output table | Grain / PK |
|---|---|---|---|
| Current conditions | `/currentconditions/v1/{locationKey}` | `current_conditions` | one obs per fetch · PK `(location_key, observation_datetime)` |
| Daily forecast | `/forecasts/v1/daily/{n}day/{locationKey}` | `daily_forecast` | one row per forecast day · PK `(location_key, forecast_date)` |
| Hourly forecast | `/forecasts/v1/hourly/{n}hour/{locationKey}` | `hourly_forecast` | one row per forecast hour · PK `(location_key, forecast_datetime)` |

Locations endpoints are **not** a user-facing dataset — they are the internal key resolver.

### Incremental strategy → output mapping + state

- AccuWeather exposes **no server-side `since`/cursor** (weather = timestamped snapshots, not an
  append-only event log). So the model is **per-run re-poll + incremental upsert on the PK**,
  not a watermark-filtered fetch.
- Every output table is written with **`incremental=True` + an explicit primary key** → the
  platform **upserts** on the PK (`output-mapping.md`). Re-running within the same
  observation/forecast window replaces rows rather than duplicating them; running over time
  accumulates a time series. This is a deliberate deviation from the `last_run` watermark
  pattern (`incremental-state.md`): the source has no incremental signal, so there is no
  watermark to filter on — stated here as the override reason. **There is deliberately no
  `full_load`/`incremental_load` toggle** (the usual `incremental-state.md` default): because all
  rows write into the same shared per-config tables, a `full_load` on one location's row would
  overwrite (wipe) every other location's already-written rows in the same job. Incremental
  upsert on a `location_key`-prefixed PK is the only safe mode here, so it is fixed, not exposed.
- **`state.json` caches the resolved `locationKey`** per row so we don't spend a Locations API
  call on every run (conserves the tight trial quota — 500/day). State shape:
  `{"location_key": "349727", "resolved_from": "<stable hash of the row's location inputs>"}`.
  On each run: if `resolved_from` still matches the current row inputs, reuse the cached key;
  otherwise re-resolve and rewrite state. State is **per-row and automatic** — no cross-row
  nesting. First run has empty state → resolve and populate (no `KeyError`).

### Secrets

- `#api_key` — the only secret; `#`-prefixed so the platform encrypts it (`KBC::ProjectSecure`).
  The component receives the decrypted plaintext at runtime.

### Sync actions

- **`testConnection`** (required) — validate the API key by making one cheap authenticated call
  (a fixed-key lookup, `/locations/v1/{knownKey}` or a trivial city search) and reporting
  success/failure so the key is validated in the UI, not only at runtime.
- **`search_locations`** (recommended) — given a typed query, call `/locations/v1/cities/search`
  and return matches (name, admin area, country, `locationKey`) to help the user pick the right
  key. Enumerable → surfaced as a helper rather than free-text guessing. Exact UI wiring is the
  `component-build-ui` phase's job.

### Output bucket / table naming

- Rely on **default-bucket** behaviour: the app's `default_bucket: true` routes all rows'
  outputs to `in.c-keboola.ex-accuweather-{configId}`, so every row shares the bucket and the
  three table names are stable and shared. The component does **not** hard-code a bucket
  destination (it would be silently overridden anyway; `default-bucket.md`). Table names
  (`current_conditions`, `daily_forecast`, `hourly_forecast`) are fixed constants, never
  generated at runtime.

## 3. Authentication & connection

- **Chosen auth:** `Authorization: Bearer <#api_key>` header (AccuWeather's current
  portal-recommended method). The legacy `apikey` query-parameter method also works today but is
  not used. Single static secret — no OAuth, no per-request signing → **fully headless**.
- **Connection method:** REST/JSON over HTTPS, GET-only, host `dataservice.accuweather.com`.
- **Provisioning (headless, self-service):** create a developer account at
  `developer.accuweather.com`, create an app/subscription, copy the API key from the dashboard.
  No admin/enterprise approval for the trial tier. The key is stored in the component config as
  `#api_key`. For this build it is supplied in the repo-root `secrets.json` as
  `parameters.#api_key` (used only for VCR recording; its value is never read or printed).
- **Blockers / access:** the free tier was **retired**; only a **14-day time-limited trial**
  remains (Core Weather 500 calls/day). A trial key **cannot back a perpetual live CI test**.
  Mitigation (locked): record VCR cassettes once against a fresh trial key and run CI purely on
  replay. No customer/enterprise credentials are required for v1.

## 4. Data model & endpoints

### In scope for v1

- **Locations resolver** — `/locations/v1/cities/search`, `/locations/v1/cities/{country}/search`,
  `/locations/v1/postalcodes/search`, `/locations/v1/cities/geoposition/search`,
  `/locations/v1/{locationKey}` (validate a directly-supplied key).
- **Current Conditions** — `/currentconditions/v1/{locationKey}?details={bool}`.
- **Daily Forecast** — `/forecasts/v1/daily/{1,5,10,15}day/{locationKey}?metric={bool}&details={bool}`.
- **Hourly Forecast** — `/forecasts/v1/hourly/{1,12,24,72,120}hour/{locationKey}?metric={bool}&details={bool}`.

### Explicitly deferred (not v1)

Indices, Alerts, Alarms, Imagery/Maps (returns image URLs, not tabular — poor extractor fit),
Tropical, Climatology, MinuteCast (separate paid product), Translations. Indices/Alerts are the
natural fast-follow.

### Pagination, rate limits, throttling

- **Pagination: none.** Every endpoint returns a bounded, complete result set (a 5-day forecast
  returns all 5 days; a city search returns its full match list). No cursors/pages/offsets.
- **Rate limits:** trial = 500 requests/day over a rolling 24-h window from first request.
  Per-minute/second limits are undocumented; there is no `Retry-After` header.
- **Throttling handling:** the client retries on **429/500/502/503/504** with **bounded
  exponential backoff** (fixed schedule, no `Retry-After` to honor), capped attempts, then
  raises. `locationKey` caching in state minimises calls.

### Response shapes → flattening

Responses are UTF-8 JSON with no envelope; each endpoint returns an object or an array directly.
Nested measurement objects (e.g. `Temperature.Metric.Value` / `.Unit`) are **flattened to scalar
columns** — no JSON blobs dumped into cells. Representative flattened columns:

- **current_conditions:** `location_key`, `observation_datetime` (`LocalObservationDateTime`),
  `epoch_time`, `weather_text`, `weather_icon`, `has_precipitation`, `precipitation_type`,
  `is_day_time`, `temperature`, `temperature_unit`, `realfeel_temperature`,
  `relative_humidity`, `wind_speed`, `wind_direction_degrees`, `wind_direction`, `uv_index`,
  `uv_index_text`, `visibility`, `cloud_cover`, `pressure`, `link`, `mobile_link`.
  (Detail-only fields populated when `include_details=true`.)
- **daily_forecast:** `location_key`, `forecast_date` (`Date`), `epoch_date`,
  `temperature_min`, `temperature_max`, `temperature_unit`, `day_icon`, `day_phrase`,
  `day_precipitation_probability`, `day_has_precipitation`, `day_precipitation_type`,
  `night_icon`, `night_phrase`, `night_precipitation_probability`, `sun_rise`, `sun_set`,
  `link`, `mobile_link`. (Plus the forecast `Headline` fields where useful.)
- **hourly_forecast:** `location_key`, `forecast_datetime` (`DateTime`), `epoch_datetime`,
  `weather_icon`, `icon_phrase`, `is_daylight`, `temperature`, `temperature_unit`,
  `realfeel_temperature`, `precipitation_probability`, `has_precipitation`,
  `precipitation_type`, `wind_speed`, `wind_direction_degrees`, `link`, `mobile_link`.

Exact column list is finalised against the recorded sample payloads during implementation; the
grain and PKs above are fixed. Internal/echo keys are stripped; `location_key` is injected on
every row (the API responses don't carry it back).

### Native data types

Emit **authoritative `schema` manifests** (`native-data-types.md`): temperatures/wind/pressure/
visibility as `NUMERIC`, humidity/cloud-cover/UV/icon codes as `INTEGER`, timestamps as
`TIMESTAMP`, booleans as `BOOLEAN`, phrases/links/units as `STRING`. This requires the app's
Developer-Portal **`dataTypeSupport=authoritative`** to be set in Phase 6 — until then the
platform silently downgrades the `schema` manifest to legacy hints. The write path and manifest
must agree on `has_header`: we write **headerless CSVs** (the `schema` names the columns), so
`has_header` stays at its default `false` — no `writer.writeheader()`.

### Error → exit-code mapping

| Condition | HTTP | Handling |
|---|---|---|
| Missing/invalid API key | 401 | `UserException` (exit 1) — "Invalid or missing AccuWeather API key." |
| Key lacks access / quota exhausted | 403 | `UserException` — "API key lacks access or quota exhausted." |
| Location not found / bad key | 404 (or empty search result) | `UserException` — actionable message naming the row's location input. |
| Rate limited after bounded retries | 429 | `UserException` — surface trial daily-cap guidance. |
| Config validation failure | — | `UserException` (Pydantic `ValidationError` mapped). |
| Transient 5xx after retries, or truly unexpected | 5xx / other | bubble up → exit 2. |

RFC 7807 error bodies (`type`, `title`, `status`, `instance`, `trace.requestId`) are parsed and
`trace.requestId` is included in error logs.

## 5. Configuration & schema

The actual `configSchema.json` / `configRowSchema.json` are built by **`component-build-ui`** in
Phase 6 — described here, not written as JSON.

### Config-level fields (root `configSchema.json`)

| Field | Type | Req | Default | Notes |
|---|---|---|---|---|
| `#api_key` | string (secret) | yes | — | `#`-prefixed; alias must match model. Paired with `format: "test-connection"` widget. |
| `units` | enum `metric`/`imperial` | no | `metric` | Maps to `metric=true/false` query param. `enum_titles` = Metric / Imperial. |
| `language` | string | no | `en-us` | AccuWeather `language` param. |
| `include_details` | boolean | no | `true` | Maps to `details=true/false`; adds detail fields. |

### Row-level fields (`configRowSchema.json`)

| Field | Type | Req | Default | Notes |
|---|---|---|---|---|
| `location_type` | enum `city`/`postal_code`/`geoposition`/`location_key` | yes | `city` | Drives which value fields show via `options.dependencies`. |
| `location_query` | string | cond | — | Shown for `city`/`postal_code`; free-text, aided by the `search_locations` sync action. |
| `country_code` | string | cond | — | Optional ISO country for city/postal search to disambiguate. |
| `latitude` | number | cond | — | Shown for `geoposition`. |
| `longitude` | number | cond | — | Shown for `geoposition`. |
| `location_key` | string | cond | — | Shown for `location_key` (skip resolution). |
| `datasets` | multi-select `current_conditions`/`daily_forecast`/`hourly_forecast` | yes | `[current_conditions]` | Which datasets to pull for this location. |
| `daily_range` | enum `1`/`5`/`10`/`15` | cond | `5` | Shown when `daily_forecast` selected. |
| `hourly_range` | enum `1`/`12`/`24`/`72`/`120` | cond | `12` | Shown when `hourly_forecast` selected. |

Conditional fields use `options.dependencies` (not root-level `dependencies`). Fixed enums carry
`options.enum_titles`. The schema groups auth vs options into named `type: object` sections given
the field count. Test/sandbox location values are kept out of the customer-facing schema
defaults and enums — only in test fixtures.

## 6. Code architecture

- **`src/client.py` — `AccuWeatherClient`.** Owns the `requests.Session` with the Bearer header
  and base URL; a private `_get(path, params)` that applies bounded exponential-backoff retry on
  429/500/502/503/504 and maps 401/403/404 + RFC 7807 bodies to typed exceptions. Public methods:
  `search_cities`, `search_postal_codes`, `search_geoposition`, `get_location`,
  `get_current_conditions`, `get_daily_forecast`, `get_hourly_forecast`. No Keboola imports —
  pure API client, unit-testable in isolation.
- **`src/configuration.py` — Pydantic `Configuration`.** One model over the merged config;
  `#api_key` via `Field(alias="#api_key")`; enums as `StrEnum`; `model_config = {"extra":
  "ignore"}`. **No `debug` field** (the platform `debug` param is handled by `ComponentBase`).
  `ValidationError` → `UserException`. Fields typed — no `Any`/raw `dict`. Datasets/ranges typed
  as enums/lists.
- **`src/component.py` — `Component(ComponentBase)`.** Client built in `__init__`. `run()` is a
  thin (<30-line) orchestrator: parse config → resolve `locationKey` (from state cache or the
  resolver) → for each enabled dataset call the matching private extractor → write tables +
  state. Private methods: `_resolve_location_key`, `_extract_current_conditions`,
  `_extract_daily_forecast`, `_extract_hourly_forecast`, `_write_table` (builds the authoritative
  `schema` manifest, headerless CSV, PK, `incremental=True`). Sync actions
  `@sync_action("testConnection")` and `@sync_action("search_locations")` reuse the same client.
  Flattening helpers are `@staticmethod`/module functions.
- **Scratch files → `/tmp`**, never `data/out/tables/` (everything under `data/out/tables/` is
  uploaded as a table).
- **Key dependencies:** `keboola.component` (Common Interface, manifests, state, sync actions),
  `pydantic` (typed config), `requests` (HTTP). No AccuWeather SDK exists — a thin hand-rolled
  client is the right call. Type hints on all public methods; built-in generics (no deprecated
  `typing.List` etc.); Ruff `UP` ruleset.

## 7. Testing

- **Framework:** `keboola.datadirtest` datadir tests under `tests/functional/<case>/`, each with
  a merged `config.json` (root+row already merged — the shape the component receives), row-scoped
  `source/data/in/state.json`, and an `expected/` output (tables + manifests) plus expected exit
  code. VCR cassettes replay recorded HTTP so CI needs no live key.
- **Cases:**
  - `current_conditions_success` — 2xx, non-empty `current_conditions` table, exit 0.
  - `daily_forecast_success` — 5-day forecast, 5 rows, exit 0.
  - `hourly_forecast_success` — 12-hour forecast, 12 rows, exit 0.
  - `all_datasets_success` — one location, all three datasets → three tables.
  - `location_key_cached` — state pre-seeded with `location_key`; assert no Locations call is
    made (cassette omits the search interaction).
  - `city_not_found` — empty/404 search → `UserException`, exit 1.
  - `invalid_api_key` — 401 → `UserException`, exit 1.
- **Sync-action tests:** `testConnection` success + failure (401); `search_locations` returns
  parsed matches.
- **VCR strategy:** record the interactions above once against a trial key. Sanitizers strip the
  `Authorization` header and any `apikey` query param, and scrub the key value from bodies/URIs,
  so no secret lands in a committed cassette. The cassette sanitization + intent-match gate
  (Phase 5) verifies both axes before the tests are accepted.
- **Sample payloads:** none captured live during research (no creds at research time); the first
  recording session seeds the cassettes. The AccuWeather quick-start documents representative
  response shapes to structure fixtures against.

## 8. Deployment & validation (cf-dev)

- **Phase 6 (Dev Portal):** `component-build-ui` produces the schemas + sync actions;
  `component-dev-portal` publishes them and sets portal-owned properties, including
  `default_bucket: true` and **`dataTypeSupport=authoritative`** (via `kbagent dev-portal patch`,
  dry-run then TTY-confirmed), *after* the `0.0.1` bootstrap release so CI-sync doesn't overwrite.
- **Phase 7 (cf-dev smoke test):** build an image from `initial-implementation`; via `kbagent`
  create a config in **cf-dev** with `#api_key` (encrypted) and one city row pulling all three
  datasets, override the image via **`runtime.tag`** on the config to the branch build, and run a
  job. Success = job `success`, resolved image tag == the branch build (not a stable release),
  and `current_conditions` / `daily_forecast` / `hourly_forecast` tables land in
  `in.c-keboola.ex-accuweather-{configId}` with expected row counts (1 / 5 / 12). This is also
  where the `has_header`/native-type load path is verified (datadir tests can't catch a Storage
  typing mismatch).

## 9. Open risks & blockers

1. **Trial-key expiry / low cap (medium).** The 14-day, 500/day trial can't back live CI —
   mitigated by VCR replay; only recording needs a live key. Owner: recording done in Phase 5.
2. **`dataTypeSupport` / `has_header` mismatch (medium).** Authoritative `schema` manifest is
   silently downgraded unless the portal property is flipped, and a header written without
   `has_header=True` corrupts the Storage load. Local tests can't catch either — both are
   verified on the Phase 7 cf-dev smoke run. Owner: Phases 6 + 7.
3. **Auth-method drift (low).** Vendor could deprecate Bearer or the legacy query param; both
   work today and we standardise on Bearer. Low likelihood in v1 window.
4. **Column/shape finalisation (low).** Exact flattened columns are pinned from the first
   recorded payloads during implementation; grain and PKs are already fixed, so this is
   refinement, not redesign.

---

## Grounding reconciliation (keboola-context)

Fresh-context reconciliation subagent (clean context, no authoring bias) read each behaviour-relevant
`keboola-context` reference in full and checked the spec against it. Per-reference verdict:

- `architecture-conventions.md` → corrected: the "one row per object" default vs. datasets-as-multipick
  reasoning was thin. **Fixed** in §2 — the object is the location because all datasets share the same
  resolved `locationKey` and per-row state; splitting them would triple Locations calls and fragment
  state (the "fetched together" override, not the "independent objects" case).
- `config-rows.md` → correct: sequential-by-default rows, per-row automatic state, merged-config model,
  and merged-`config.json` + row-scoped-state test fixtures all match.
- `incremental-state.md` → corrected: the deviation rationale only explained the missing cursor, not the
  missing `full_load` toggle. **Fixed** in §2 — the toggle is deliberately omitted because a `full_load`
  on one row would wipe other locations' rows in the shared per-config tables; incremental upsert on a
  `location_key`-prefixed PK is the only safe mode. PK-on-every-incremental-table confirmed correct.
- `output-mapping.md` → correct: incremental+PK upsert on all three tables with `location_key` in each
  composite PK (no cross-location collision); scratch → `/tmp`; no sliced tables.
- `native-data-types.md` → correct: authoritative `schema` manifest, `dataTypeSupport` portal gating and
  silent-downgrade behaviour, and headerless-CSV / `has_header=false` handling all correct.
- `encryption.md` → correct: `#api_key` only secret, `#`-prefixed, `KBC::ProjectSecure`, decrypted at runtime.
- `exit-codes.md` → correct: `UserException`→exit 1 for user-actionable conditions; unexpected/5xx→exit 2.
- `default-bucket.md` → correct: `in.c-keboola.ex-accuweather-{configId}` shared across rows; no hard-coded
  destination.

Both `corrected:` items were folded back into §2 above before the spec was locked. No structural
platform-behaviour violations were found.
