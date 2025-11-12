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
    
    def __init__(self, message: str):
        super().__init__(message)
        self.retry_after: int | None = None  # Retry-After header value in seconds


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
    try:
        response = opts.session.request(
            opts.method,
            opts.url,
            params=opts.params,
            json=opts.json_body,
            headers=opts.headers,
            timeout=(
                10,
                120,
            ),  # (connect_timeout, read_timeout) - 10s to connect, 120s max for response
        )
    except requests.RequestException as exc:
        raise TransientHTTPError(f"Request failed: {exc}") from exc
    
    # Check for rate limit headers and attach to exception for retry logic
    retry_after_seconds = None
    if response.status_code == 429:
        import logging
        logger = logging.getLogger(__name__)
        
        # Log all headers for debugging
        logger.info("429 Response Headers:")
        for header_name, header_value in response.headers.items():
            logger.info("  %s: %s", header_name, header_value)
        
        # Check common rate limit headers
        retry_after = response.headers.get("Retry-After")
        retry_after_raw = response.headers.get("retry-after")  # lowercase variant
        x_rate_limit_limit = response.headers.get("X-RateLimit-Limit")
        x_rate_limit_remaining = response.headers.get("X-RateLimit-Remaining")
        x_rate_limit_reset = response.headers.get("X-RateLimit-Reset")
        ratelimit_reset = response.headers.get("ratelimit-reset")
        x_ratelimit_remaining_month = response.headers.get("x-ratelimit-remaining-stacks-month")
        x_ratelimit_limit_month = response.headers.get("x-ratelimit-limit-stacks-month")
        
        # Check monthly limit status
        if x_ratelimit_remaining_month is not None:
            remaining = int(x_ratelimit_remaining_month)
            limit = int(x_ratelimit_limit_month) if x_ratelimit_limit_month else None
            logger.info("Monthly rate limit - Remaining: %s/%s", remaining, limit or "unknown")
            if remaining == 0:
                logger.warning("Monthly rate limit EXHAUSTED! Need to wait until next month.")
        
        # Calculate wait time from reset timestamp
        reset_timestamp = None
        if ratelimit_reset:
            try:
                reset_timestamp = int(ratelimit_reset)
            except (ValueError, TypeError):
                pass
        
        if reset_timestamp:
            import time
            now = int(time.time())
            wait_seconds = reset_timestamp - now
            if wait_seconds > 0 and wait_seconds < 86400 * 32:  # Less than ~32 days (reasonable)
                logger.info("Rate limit resets at timestamp %d (in %d seconds = ~%d hours)",
                           reset_timestamp, wait_seconds, wait_seconds // 3600)
                retry_after_seconds = wait_seconds
            else:
                logger.warning("Reset timestamp %d seems invalid (wait would be %d seconds)",
                             reset_timestamp, wait_seconds)
        
        # Fallback to Retry-After header if no reset timestamp
        if retry_after_seconds is None and (retry_after or retry_after_raw):
            retry_after_value = retry_after or retry_after_raw
            try:
                retry_after_seconds = int(retry_after_value)
                # If it's a large number, it might be a timestamp
                if retry_after_seconds > 1000000000:  # Looks like Unix timestamp
                    import time
                    now = int(time.time())
                    wait_seconds = retry_after_seconds - now
                    if wait_seconds > 0 and wait_seconds < 86400 * 32:
                        logger.info("Retry-After appears to be timestamp %d (wait %d seconds)",
                                   retry_after_seconds, wait_seconds)
                        retry_after_seconds = wait_seconds
                    else:
                        retry_after_seconds = None
                elif retry_after_seconds > 3600:  # More than 1 hour
                    logger.warning(
                        "Retry-After header seems unrealistic: %d seconds (~%d hours). "
                        "Will use exponential backoff instead.",
                        retry_after_seconds,
                        retry_after_seconds // 3600,
                    )
                    retry_after_seconds = None
                else:
                    logger.info("Retry-After header: %d seconds", retry_after_seconds)
            except (ValueError, TypeError):
                pass
    
    if _should_retry(response.status_code):
        error = TransientHTTPError(f"Status {response.status_code} for {opts.url}")
        # Attach retry_after to exception so retry logic can use it
        if retry_after_seconds is not None:
            error.retry_after = retry_after_seconds
        raise error
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
    import logging
    logger = logging.getLogger(__name__)
    
    # Create exponential backoff wait function
    _exponential_wait = wait_exponential_jitter(
        initial=retry_config.wait_min_seconds,
        max=retry_config.wait_max_seconds,
    )
    
    def _wait_with_retry_after(retry_state):
        """Custom wait function that respects Retry-After header when available."""
        exc = retry_state.outcome.exception()
        if isinstance(exc, TransientHTTPError) and exc.retry_after is not None:
            wait_time = exc.retry_after
            logger.info(
                "Waiting %d seconds as specified by Retry-After header",
                wait_time,
            )
            return wait_time
        # Otherwise use exponential backoff
        return _exponential_wait(retry_state)

    @retry(
        retry=retry_if_exception(_retry_condition),
        wait=_wait_with_retry_after,
        stop=stop_after_attempt(retry_config.max_attempts),
        reraise=True,
        before_sleep=lambda retry_state: logger.info(
            "Retrying request (attempt %d/%d) - %s",
            retry_state.attempt_number,
            retry_config.max_attempts,
            str(retry_state.outcome.exception()) if retry_state.outcome else "unknown error",
        ),
    )
    def _execute() -> Any:
        return _request_once(opts)

    payload = _execute()
    _store_cache(cache_path, payload)
    return payload
