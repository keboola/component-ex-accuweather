import logging
import time
from typing import Any

import requests

BASE_URL = "https://dataservice.accuweather.com"
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}
_REQUEST_TIMEOUT = 60
_MAX_ERROR_BODY = 200

LOG = logging.getLogger(__name__)


class AccuWeatherApiError(Exception):
    """Base error for any AccuWeather API failure.

    Covers network faults (timeouts, connection/SSL errors) and unmapped HTTP
    statuses (terminal 5xx after retries, unexpected 4xx). Typed subclasses below
    stay for callers that need to distinguish auth / not-found / rate-limit.
    """


class AuthError(AccuWeatherApiError):
    """401/403 — key invalid or lacks access/quota."""


class LocationNotFoundError(AccuWeatherApiError):
    """404 or empty search result."""


class RateLimitError(AccuWeatherApiError):
    """429 persisted past all retries."""


class AccuWeatherClient:
    """Thin AccuWeather REST client: Bearer auth, bounded retry, RFC7807 error mapping.

    No Keboola imports — unit-testable in isolation. Every failure mode — network
    fault or HTTP error — is surfaced as an ``AccuWeatherApiError`` (or a typed
    subclass), so callers never see a bare ``requests`` exception.
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

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self._base_url}{path}"
        last_status = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._session.get(url, params=params, timeout=_REQUEST_TIMEOUT)
            except requests.RequestException as exc:
                # Timeouts, connection errors, SSL failures — a transient upstream
                # fault, not a component bug. Surface as a mapped (exit-1) error.
                raise AccuWeatherApiError(f"Network error calling AccuWeather {path}: {exc}") from exc
            last_status = resp.status_code
            if 200 <= resp.status_code < 300:
                return resp.json()
            if resp.status_code in (401, 403):
                raise AuthError(self._describe(resp))
            if resp.status_code == 404:
                raise LocationNotFoundError(self._describe(resp))
            if resp.status_code in _RETRY_STATUSES:
                if attempt < self._max_retries:
                    backoff = self._backoff_base * (2**attempt)
                    LOG.debug(
                        "AccuWeather %s returned %s; retrying in %.1fs (attempt %d/%d)",
                        path,
                        resp.status_code,
                        backoff,
                        attempt + 1,
                        self._max_retries,
                    )
                    time.sleep(backoff)
                    continue
                LOG.warning("AccuWeather %s failed with %s after %d retries", path, resp.status_code, self._max_retries)
                if resp.status_code == 429:
                    raise RateLimitError(self._describe(resp))
                raise AccuWeatherApiError(self._describe(resp))
            # Any other unmapped status (400/405/422/...): terminal, map to base error.
            raise AccuWeatherApiError(self._describe(resp))
        raise AccuWeatherApiError(f"Unreachable retry loop, last status {last_status}")

    @staticmethod
    def _describe(resp: requests.Response) -> str:
        try:
            body = resp.json()
        except ValueError:
            # Non-JSON body (e.g. an HTML error/proxy page): collapse whitespace and
            # cap length so large payloads / hostnames don't leak into user messages.
            snippet = " ".join(resp.text.split())[:_MAX_ERROR_BODY]
            return f"HTTP {resp.status_code}: {snippet}" if snippet else f"HTTP {resp.status_code}"
        if not isinstance(body, dict):
            return f"HTTP {resp.status_code}"
        # RFC 7807 or legacy AccuWeather body
        title = body.get("title") or body.get("Message") or body.get("Code") or "error"
        req_id = (body.get("trace") or {}).get("requestId")
        suffix = f" (requestId={req_id})" if req_id else ""
        return f"HTTP {resp.status_code}: {str(title)[:_MAX_ERROR_BODY]}{suffix}"

    def search_cities(self, q: str, country_code: str | None = None) -> list[dict[str, Any]]:
        if country_code:
            return self._get(f"/locations/v1/cities/{country_code}/search", {"q": q})
        return self._get("/locations/v1/cities/search", {"q": q})

    def search_postal_codes(self, q: str, country_code: str | None = None) -> list[dict[str, Any]]:
        path = (
            f"/locations/v1/postalcodes/{country_code}/search" if country_code else "/locations/v1/postalcodes/search"
        )
        return self._get(path, {"q": q})

    def search_geoposition(self, lat: float, lon: float) -> dict[str, Any] | None:
        return self._get("/locations/v1/cities/geoposition/search", {"q": f"{lat},{lon}"})

    def get_location(self, location_key: str) -> dict[str, Any]:
        return self._get(f"/locations/v1/{location_key}")

    def get_current_conditions(
        self, location_key: str, *, details: bool, language: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"details": str(details).lower()}
        if language:
            params["language"] = language
        return self._get(f"/currentconditions/v1/{location_key}", params)

    def get_daily_forecast(
        self, location_key: str, *, days: int, metric: bool, details: bool, language: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"metric": str(metric).lower(), "details": str(details).lower()}
        if language:
            params["language"] = language
        return self._get(f"/forecasts/v1/daily/{days}day/{location_key}", params)

    def get_hourly_forecast(
        self, location_key: str, *, hours: int, metric: bool, details: bool, language: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"metric": str(metric).lower(), "details": str(details).lower()}
        if language:
            params["language"] = language
        return self._get(f"/forecasts/v1/hourly/{hours}hour/{location_key}", params)

    def get_indices(self, location_key: str, *, days: int, language: str | None = None) -> list[dict[str, Any]]:
        # Lifestyle indices endpoint: no metric/details params, only optional language.
        params: dict[str, Any] = {}
        if language:
            params["language"] = language
        return self._get(f"/indices/v1/daily/{days}day/{location_key}", params)
