# Phase 2 Research — AccuWeather API → `keboola.ex-accuweather` (EXTRACTOR)

Research date: 2026-07-09. All claims cited to current AccuWeather developer docs.

> **Headline finding (provisioning blocker):** AccuWeather **retired its indefinite free tier**.
> What remains is a **14-day time-limited trial** (Core Weather: 500 calls/day; MinuteCast: 50
> calls/day). A key minted today stops working in ~14 days, so it **cannot power a live CI test
> indefinitely**. Mitigation: record VCR cassettes during the trial window and replay in CI (the
> standard Keboola approach) — live calls are only needed once, during recording.

---

## 1. API style

Plain **REST / JSON over HTTPS** (GET-only for extraction). Responses are JSON, UTF-8, no wrapper
envelope — each endpoint returns either a JSON object or a JSON array directly. This is a textbook
REST extractor shape.

- **Base host:** `https://dataservice.accuweather.com` (unchanged in the new portal — endpoints
  still live here even though the docs site moved to `developer.accuweather.com`).
- Docs: <https://developer.accuweather.com/documentation/core-weather-quick-start>,
  <https://developer.accuweather.com/core-weather/location-key-currentconditions>

### Endpoint families (what matters for an extractor)

Everything except Locations requires a **`locationKey`** — an AccuWeather-internal location ID you
first resolve via a Locations endpoint. This two-step (resolve key → fetch weather) is the core
data-flow of the component.

| Family | Base path (v1) | Notes / value for extractor |
|---|---|---|
| **Locations** ⭐ | `/locations/v1/cities/search`, `/locations/v1/cities/{country}/search`, `/locations/v1/postalcodes/search`, `/locations/v1/cities/geoposition/search`, `/locations/v1/cities/autocomplete`, `/locations/v1/{locationKey}` | **Mandatory prerequisite** — turns city name / postal code / lat-lon into a `locationKey`. Autocomplete is ideal for a UI sync-action dropdown. |
| **Current Conditions** ⭐ | `/currentconditions/v1/{locationKey}` (+ `/historical`, `/historical/24`) | Real-time obs: temp, RealFeel, humidity, wind, pressure, UV, visibility, cloud cover. **Highest-value core dataset.** |
| **Forecasts** ⭐ | daily: `/forecasts/v1/daily/{1,5,10,15}day/{locationKey}` · hourly: `/forecasts/v1/hourly/{1,12,24,72,120}hour/{locationKey}` | Temp, wind, precip probability, phrases, sun/moon. **Second core dataset.** (Docs also mention 7-day daily on the new portal.) |
| **Indices** | `/indices/v1/daily/{n}day/{locationKey}[/{indexID}]` | Lifestyle indices (Travel, Running, Ski, Cold & Flu, Dog-Walking). Nice-to-have. |
| **Alerts** | `/alerts/v1/{locationKey}` | Government / provider severe-weather warnings. Valuable but sparse (often empty). |
| **Alarms** | `/alarms/v1/...` | Threshold alarms derived from daily forecasts. Lower priority. |
| **Imagery / Maps** | `/maps/v1/radar/...` (satellite & radar tiles/images) | Returns image URLs, not tabular data — **poor fit for a table extractor; skip in v1.** |
| **Tropical** | `/tropical/v1/...` | Cyclone tracking (position, wind, pressure). Niche. |
| **Climatology / MinuteCast / Translations** | separate products | Climatology (historical/normals) is niche; MinuteCast is a *separate paid product & trial*; Translations is a helper, not a dataset. |

**Recommended v1 surface to expose:** Locations (as the key-resolution helper, not a user dataset) +
**Current Conditions** + **Daily & Hourly Forecasts**. Indices/Alerts as fast-follow. Skip
Imagery/Maps, Tropical, Climatology, MinuteCast in v1.
Family overview: <https://developer.accuweather.com/documentation/overview.md>

---

## 2. Authentication

**Two accepted methods — this is a live nuance the spec must decide:**

1. **Legacy / classic:** `apikey` **query parameter** — e.g.
   `GET https://dataservice.accuweather.com/currentconditions/v1/349727?apikey=YOUR_KEY`.
   This is what nearly every existing AccuWeather integration and third-party example uses, and it
   still works against `dataservice.accuweather.com`.
2. **New portal (currently recommended):** `Authorization: Bearer YOUR_API_KEY` **header**.
   The revamped docs now present Bearer-in-header as *the* method and no longer show the query param.
   <https://developer.accuweather.com/documentation/authentication>

**Recommendation for the component:** send the key as `Authorization: Bearer` (vendor's current
recommendation) but treat this as a Tier C confirmation — both work today. Either way the key is a
single secret stored as `#api_key` (`KBC::ProjectSecure`). No OAuth, no per-request signing → fully
**headless-capable auth** (no admin UI dance beyond one-time key copy).

**Key provisioning:** self-service — create a developer account at `developer.accuweather.com`,
create an "app"/subscription, copy the key from the dashboard's subscriptions page. No admin/enterprise
approval needed for the trial. (Enterprise keys via `sales@accuweather.com` for higher tiers.)

- `401` = missing/invalid key; `403` = key lacks access / subscription limit hit.
  <https://developer.accuweather.com/documentation/http-status-codes>

---

## 3. Pagination

**None.** No AccuWeather weather endpoint paginates — each returns a bounded, complete result set
(e.g. a 5-day forecast returns all 5 days; a city search returns its full match list). There are no
cursors, `page`/`offset`, or `next` links to implement. Simplifies the client considerably.

---

## 4. Rate limits & throttling

- **Trial caps:** Core Weather trial = **500 requests/day**; MinuteCast trial = **50 requests/day**.
  A "day" is a **rolling 24-hour window starting at your first request** (not calendar-midnight).
- **Paid monthly caps:** Starter 15k/mo ($2/mo, $0.25 CPM overage) · Standard 225k/mo · Prime 1.8M/mo ·
  Elite 2.4M/mo · MinuteCast Lite 10k/mo · MinuteCast Full 675k/mo. Over the cap you are **not hard-
  blocked** — you're billed a CPM (cost-per-thousand) overage rate. (FAQ:
  <https://developer.accuweather.com/faq>)
- **Per-minute / per-second limits:** **not documented.** No published QPS or `Retry-After` guidance.
- **Throttling / errors:** `429 Too Many Requests` when the rate limit is exceeded; `503 Service
  Unavailable` for temporary overload/maintenance; `500/502/504` server-side. Error bodies follow
  **RFC 7807** (`type`, `title`, `status`, `instance`, `trace.requestId`) with legacy fields retained.
  → Component should implement **bounded exponential-backoff retry on 429/500/502/503/504** (no
  `Retry-After` header to honor, so use fixed backoff) and surface `trace.requestId` in error logs.
  <https://developer.accuweather.com/documentation/http-status-codes>

---

## 5. Incremental / cursor support

Weather data is **time-stamped snapshots, not an append-only event log** — there is **no `since`/
cursor parameter** on current-conditions or forecast endpoints. Realistic incremental model:

- **Per-run re-fetch:** every run pulls the current snapshot (current conditions, and/or the forecast
  windows) for each configured location. Output is **incremental append-load**, primary-keyed on
  `(locationKey, observation/forecast datetime)` so repeated runs accumulate a time series and
  re-runs within the same period upsert rather than duplicate.
- **Location-key caching in `state.json`:** resolving a location key costs a Locations call. Cache the
  resolved `locationKey` per configured location in state and reuse it across runs — this conserves
  the tight daily quota (relevant on the 50/day MinuteCast trial, comfortable on 500/day Core).
- **Limited historical backfill:** `currentconditions/.../historical/24` gives the past 24 h of obs —
  usable for a one-time-ish backfill, but there is no deep historical cursor on the standard product.

Net: incremental = "re-poll on schedule + append with timestamp + cache keys," **not** a
server-side delta cursor.

---

## 6. Feasibility & provisioning verdict

**Feasible to build, with one real caveat around live CI.**

- ✅ **Auth is headless** — single API key, no OAuth/admin flow. Self-service key from the dev portal.
- ✅ **REST + JSON + no pagination** → straightforward extractor; Locations→weather two-step is the
  only structural wrinkle.
- ✅ **Sandbox/test key obtainable by the user directly** (developer portal signup, no admin gate).
- ⚠️ **BLOCKER — trial is 14-day time-limited, no permanent free tier.** A trial key expires in ~14
  days and daily caps are low (500/day Core, 50/day MinuteCast). It **cannot back a perpetual live
  CI test.** → **Mitigation:** record **VCR cassettes** against a fresh trial key during development,
  commit the sanitized cassettes, and run CI purely on replay. Live calls only during recording.
  A cheap Starter plan ($2/mo, 15k/mo) is an option if occasional live smoke tests are wanted.
- ⚠️ **Auth-method ambiguity (Tier C for the user):** classic `apikey` query param vs new
  `Authorization: Bearer` header — both work today; recommend Bearer, but confirm with whoever owns
  the AccuWeather account which subscription/portal the key comes from.
- ℹ️ No customer/enterprise credentials required for v1; the user just needs to mint a trial key to
  record cassettes.

**Verdict: proceed.** No hard blocker to building or to CI (VCR replay sidesteps the trial expiry).
The only thing needing a human decision is (a) who provides the trial key for cassette recording and
(b) which auth method to standardize on.

---

## Sources
- Overview / families: https://developer.accuweather.com/documentation/overview.md
- Authentication: https://developer.accuweather.com/documentation/authentication
- HTTP status codes: https://developer.accuweather.com/documentation/http-status-codes
- Core Weather quick-start: https://developer.accuweather.com/documentation/core-weather-quick-start
- Location key / current conditions: https://developer.accuweather.com/core-weather/location-key-currentconditions
- FAQ (trial caps, rolling-day, paid tiers): https://developer.accuweather.com/faq
- Pricing overview: https://developer.accuweather.com/pricing
- Classic endpoint host confirmation (dataservice.accuweather.com): search-corroborated; developer.accuweather.com/core-weather
