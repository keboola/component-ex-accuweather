import time
from typing import Any

import requests

BASE_URL = "https://dataservice.accuweather.com"
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_REQUEST_TIMEOUT = 60


class AuthError(Exception):
    """401/403 — key invalid or lacks access/quota."""


class LocationNotFoundError(Exception):
    """404 or empty search result."""


class RateLimitError(Exception):
    """429 persisted past all retries."""


class AccuWeatherClient:
    """Thin AccuWeather REST client: Bearer auth, bounded retry, RFC7807 error mapping.

    No Keboola imports — unit-testable in isolation.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        max_retries: int = 4,
        backoff_base: float = 1.0,
        session: requests.Session | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._session = session or requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {api_key}", "Accept": "application/json"})

    def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self._base_url}{path}"
        last_status = None
        for attempt in range(self._max_retries + 1):
            resp = self._session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            last_status = resp.status_code
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                raise AuthError(self._describe(resp))
            if resp.status_code == 404:
                raise LocationNotFoundError(self._describe(resp))
            if resp.status_code in _RETRY_STATUSES:
                if attempt < self._max_retries:
                    time.sleep(self._backoff_base * (2**attempt))
                    continue
                if resp.status_code == 429:
                    raise RateLimitError(self._describe(resp))
                resp.raise_for_status()
            resp.raise_for_status()
        raise RuntimeError(f"Unreachable retry loop, last status {last_status}")

    @staticmethod
    def _describe(resp: requests.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            return f"HTTP {resp.status_code}: {resp.text[:200]}"
        if not isinstance(body, dict):
            return f"HTTP {resp.status_code}"
        # RFC 7807 or legacy AccuWeather body
        title = body.get("title") or body.get("Message") or body.get("Code") or "error"
        req_id = (body.get("trace") or {}).get("requestId")
        suffix = f" (requestId={req_id})" if req_id else ""
        return f"HTTP {resp.status_code}: {title}{suffix}"

    def search_cities(self, q: str, country_code: str | None = None) -> list[dict]:
        if country_code:
            return self._get(f"/locations/v1/cities/{country_code}/search", {"q": q})
        return self._get("/locations/v1/cities/search", {"q": q})

    def search_postal_codes(self, q: str, country_code: str | None = None) -> list[dict]:
        path = (
            f"/locations/v1/postalcodes/{country_code}/search" if country_code else "/locations/v1/postalcodes/search"
        )
        return self._get(path, {"q": q})

    def search_geoposition(self, lat: float, lon: float) -> dict | None:
        return self._get("/locations/v1/cities/geoposition/search", {"q": f"{lat},{lon}"})

    def get_location(self, location_key: str) -> dict:
        return self._get(f"/locations/v1/{location_key}")

    def get_current_conditions(self, location_key: str, *, details: bool) -> list[dict]:
        return self._get(f"/currentconditions/v1/{location_key}", {"details": str(details).lower()})

    def get_daily_forecast(self, location_key: str, *, days: int, metric: bool, details: bool) -> dict:
        return self._get(
            f"/forecasts/v1/daily/{days}day/{location_key}",
            {"metric": str(metric).lower(), "details": str(details).lower()},
        )

    def get_hourly_forecast(self, location_key: str, *, hours: int, metric: bool, details: bool) -> list[dict]:
        return self._get(
            f"/forecasts/v1/hourly/{hours}hour/{location_key}",
            {"metric": str(metric).lower(), "details": str(details).lower()},
        )
