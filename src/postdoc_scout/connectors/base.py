"""Shared HTTP behavior for external evidence connectors."""

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ConnectorError(Exception):
    """Structured connector failure that can be surfaced as a warning."""

    connector: str
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        status = f" status={self.status_code}" if self.status_code else ""
        return f"{self.connector}: {self.message}{status}"


class BaseHTTPConnector:
    """Small rate-limit-friendly HTTP client wrapper for publication connectors."""

    connector_name = "base"
    base_url = ""

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout_seconds: float = 20.0,
        max_retries: int = 2,
        delay_seconds: float = 0.34,
        contact_email: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.contact_email = contact_email or os.getenv("POSTDOC_SCOUT_CONTACT_EMAIL")
        self.api_key = api_key
        self.max_retries = max_retries
        self.delay_seconds = delay_seconds
        self.requests_made = 0
        self._owns_client = client is None
        self.client = client or httpx.Client(
            base_url=self.base_url,
            timeout=httpx.Timeout(timeout_seconds),
            headers={"User-Agent": self._user_agent()},
        )

    def close(self) -> None:
        """Close the underlying client if this connector created it."""
        if self._owns_client:
            self.client.close()

    def _user_agent(self) -> str:
        if self.contact_email:
            return f"postdoc-scout-agent/0.1 ({self.contact_email})"
        return "postdoc-scout-agent/0.1"

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self._get(url, params)
        try:
            data = response.json()
        except ValueError as exc:
            raise ConnectorError(self.connector_name, "Response was not valid JSON") from exc
        if not isinstance(data, dict):
            raise ConnectorError(self.connector_name, "Response JSON was not an object")
        return data

    def _get_text(self, url: str, params: dict[str, Any]) -> str:
        return self._get(url, params).text

    def _get(self, url: str, params: dict[str, Any]) -> httpx.Response:
        last_error: ConnectorError | None = None
        for attempt in range(self.max_retries + 1):
            if self.delay_seconds > 0:
                time.sleep(self.delay_seconds)
            try:
                response = self.client.get(url, params=params)
                self.requests_made += 1
                if response.status_code in {429, 500, 502, 503, 504}:
                    last_error = ConnectorError(
                        self.connector_name,
                        response.text[:200] or "Transient HTTP failure",
                        response.status_code,
                    )
                    if attempt < self.max_retries:
                        time.sleep(2**attempt * max(self.delay_seconds, 0.1))
                        continue
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                raise ConnectorError(
                    self.connector_name,
                    exc.response.text[:200] or "HTTP status error",
                    exc.response.status_code,
                ) from exc
            except httpx.RequestError as exc:
                last_error = ConnectorError(self.connector_name, str(exc))
                if attempt < self.max_retries:
                    time.sleep(2**attempt * max(self.delay_seconds, 0.1))
                    continue
        if last_error is not None:
            raise last_error
        raise ConnectorError(self.connector_name, "Unknown connector failure")
