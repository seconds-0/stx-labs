from __future__ import annotations

from pathlib import Path

import pytest

from src import config
from src import http_utils


class DummyResponse:
    def __init__(self, status_code: int, payload: dict[str, object]):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class DummySession:
    def __init__(self, payload: dict[str, object]):
        self.payload = payload
        self.calls = 0

    def request(self, method, url, params=None, json=None, headers=None, timeout=None):
        self.calls += 1
        return DummyResponse(200, self.payload)


@pytest.fixture()
def temp_cache(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config, "RAW_DATA_DIR", tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    yield tmp_path


def test_cached_json_request_hits_cache(temp_cache):
    session = DummySession({"value": 1})
    opts = http_utils.RequestOptions(
        prefix="test",
        session=session,
        method="GET",
        url="https://example.com",
    )

    first = http_utils.cached_json_request(opts)
    second = http_utils.cached_json_request(opts)

    assert first == {"value": 1}
    assert second == {"value": 1}
    # Only first call should hit network because of cache reuse.
    assert session.calls == 1
