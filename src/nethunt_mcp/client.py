from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from .config import Settings
from .errors import NethuntMCPError

JSONMapping = dict[str, Any]
QueryParams = dict[str, Any] | list[tuple[str, Any]] | None


class NetHuntClient:
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        retry_attempts: int = 3,
        retry_backoff_seconds: float = 0.2,
    ) -> None:
        self.settings = settings
        self._client = http_client
        self._owns_client = http_client is None
        self._retry_attempts = retry_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._logger = logging.getLogger("nethunt_mcp.client")

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "Authorization": self.settings.basic_auth_header_value,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nethunt-mcp/0.1.0",
        }

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get_json(
        self,
        path: str,
        *,
        query: QueryParams = None,
        retryable: bool = True,
    ) -> Any:
        return await self._request_json("GET", path, query=query, retryable=retryable)

    async def post_json(
        self,
        path: str,
        *,
        query: QueryParams = None,
        json_body: JSONMapping | None = None,
        retryable: bool = False,
    ) -> Any:
        return await self._request_json("POST", path, query=query, json_body=json_body, retryable=retryable)

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: QueryParams = None,
        json_body: JSONMapping | None = None,
        retryable: bool,
    ) -> Any:
        client = await self._get_client()
        max_attempts = self._retry_attempts if retryable else 1

        for attempt in range(1, max_attempts + 1):
            try:
                response = await client.request(method, path, params=query, json=json_body)
            except httpx.RequestError as exc:
                if retryable and attempt < max_attempts:
                    await asyncio.sleep(self._retry_backoff_seconds * attempt)
                    continue
                raise NethuntMCPError(
                    code="network_error",
                    message="Could not reach NetHunt CRM.",
                    details={"method": method, "path": path, "reason": str(exc)},
                ) from exc

            if retryable and response.status_code in self.RETRYABLE_STATUS_CODES and attempt < max_attempts:
                await asyncio.sleep(self._retry_backoff_seconds * attempt)
                continue

            return self._parse_response(response, method=method, path=path)

        raise NethuntMCPError(
            code="internal_error",
            message="NetHunt request retries were exhausted unexpectedly.",
            details={"method": method, "path": path},
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.settings.api_base_url,
                headers=self.default_headers,
                timeout=self.settings.timeout_seconds,
            )
        return self._client

    def _parse_response(self, response: httpx.Response, *, method: str, path: str) -> Any:
        if response.is_success:
            if not response.content:
                return {}
            try:
                return response.json()
            except json.JSONDecodeError as exc:
                raise NethuntMCPError(
                    code="invalid_response",
                    message="NetHunt CRM returned invalid JSON.",
                    status_code=response.status_code,
                    details={"method": method, "path": path, "body": response.text[:500]},
                ) from exc

        details = {
            "method": method,
            "path": path,
            "status_code": response.status_code,
            "body": self._safe_response_body(response),
        }
        if response.status_code in {401, 403}:
            raise NethuntMCPError(
                code="auth_error",
                message="NetHunt CRM rejected the provided credentials.",
                status_code=response.status_code,
                details=details,
            )
        if response.status_code == 404:
            raise NethuntMCPError(
                code="not_found",
                message="The requested NetHunt resource was not found.",
                status_code=response.status_code,
                details=details,
            )
        if response.status_code == 429:
            raise NethuntMCPError(
                code="rate_limited",
                message="NetHunt CRM rate-limited the request.",
                status_code=response.status_code,
                details=details,
            )
        if 500 <= response.status_code:
            raise NethuntMCPError(
                code="upstream_error",
                message="NetHunt CRM returned a server error.",
                status_code=response.status_code,
                details=details,
            )
        raise NethuntMCPError(
            code="bad_request",
            message="NetHunt CRM rejected the request.",
            status_code=response.status_code,
            details=details,
        )

    def _safe_response_body(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except json.JSONDecodeError:
            self._logger.debug("NetHunt response body was not JSON for %s", response.request.url)
            return response.text[:500]
