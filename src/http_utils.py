"""HTTP utilities with retry and simple file-based caching."""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

import requests
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .config import DEFAULT_RETRY_CONFIG, resolve_cache_path


class TransientHTTPError(Exception):
    """Raised when the upstream service indicates a retryable failure."""


def _hash_payload(*parts: Any) -> str:
    digest = sha256()
    for part in parts:
        digest.update(json.dumps(part, sort_keys=True, default=str).encode())
    return digest.hexdigest()


def _build_cache_path(
    prefix: str, *, method: str, url: str, params: Any, payload: Any
) -> Path:
    cache_key = _hash_payload(method.upper(), url, params, payload)
    return resolve_cache_path(prefix, cache_key)


def _serialize_response(content: Any) -> bytes:
    if isinstance(content, (str, bytes)):
        return content if isinstance(content, bytes) else content.encode()
    return json.dumps(content).encode()


def _load_cache(path: Path, ttl_seconds: float | None) -> Any | None:
    if not path.exists():
        return None
    if ttl_seconds is not None:
        age = time.time() - path.stat().st_mtime
        if age > ttl_seconds:
            return None
    with path.open("rb") as fh:
        return json.loads(fh.read().decode())


def _store_cache(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(_serialize_response(payload))


def _should_retry(status_code: int, retry_config=DEFAULT_RETRY_CONFIG) -> bool:
    return status_code in retry_config.status_forcelist


def build_session(default_headers: Mapping[str, str] | None = None) -> requests.Session:
    session = requests.Session()
    if default_headers:
        session.headers.update(default_headers)
    return session


@dataclass
class RequestOptions:
    prefix: str
    session: requests.Session
    method: str
    url: str
    params: Mapping[str, Any] | None = None
    json_body: Any | None = None
    headers: MutableMapping[str, str] | None = None
    ttl_seconds: float | None = 3600
    force_refresh: bool = False


def _retry_condition(exc: Exception) -> bool:
    return isinstance(exc, TransientHTTPError)


def _request_once(opts: RequestOptions) -> Any:
    response = opts.session.request(
        opts.method,
        opts.url,
        params=opts.params,
        json=opts.json_body,
        headers=opts.headers,
        timeout=30,
    )
    if _should_retry(response.status_code):
        raise TransientHTTPError(f"Status {response.status_code} for {opts.url}")
    response.raise_for_status()
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Non-JSON response from {opts.url}") from exc


def cached_json_request(opts: RequestOptions) -> Any:
    """Perform a JSON HTTP request with retry and caching."""
    cache_path = _build_cache_path(
        opts.prefix,
        method=opts.method,
        url=opts.url,
        params=opts.params,
        payload=opts.json_body,
    )
    if not opts.force_refresh:
        cached = _load_cache(cache_path, opts.ttl_seconds)
        if cached is not None:
            return cached

    retry_config = DEFAULT_RETRY_CONFIG

    @retry(
        retry=retry_if_exception(_retry_condition),
        wait=wait_exponential_jitter(
            initial=retry_config.wait_min_seconds, max=retry_config.wait_max_seconds
        ),
        stop=stop_after_attempt(retry_config.max_attempts),
        reraise=True,
    )
    def _execute() -> Any:
        return _request_once(opts)

    payload = _execute()
    _store_cache(cache_path, payload)
    return payload
