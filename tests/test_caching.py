from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from src import prices


def test_fetch_price_series_uses_cache(monkeypatch, tmp_path):
    cache_dir = tmp_path / "prices"
    cache_dir.mkdir()
    monkeypatch.setattr(prices, "PRICE_CACHE_DIR", cache_dir)

    call_count = {"coingecko": 0}

    def fake_coingecko(symbol, start, end, *, force_refresh):
        call_count["coingecko"] += 1
        ts = pd.date_range(start=start, end=end, freq="H", tz=UTC)
        return pd.DataFrame({"ts": ts, "px": [1.0] * len(ts)})

    monkeypatch.setattr(prices, "_fetch_prices_coingecko", fake_coingecko)

    def fake_fallback(*args, **kwargs):
        raise AssertionError("Fallback should not be used when primary succeeds")

    monkeypatch.setattr(prices, "_fetch_prices_fallback", fake_fallback)

    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=2)

    df_first = prices.fetch_price_series("STX-USD", start, end, force_refresh=True)
    assert not df_first.empty
    assert call_count["coingecko"] == 1

    df_second = prices.fetch_price_series("STX-USD", start, end, force_refresh=False)
    assert not df_second.empty
    assert call_count["coingecko"] == 1  # reused cache


def test_fetch_fees_by_tenure_cache(monkeypatch, tmp_path):
    from src import fees

    cache_dir = tmp_path / "signal21"
    cache_dir.mkdir()
    monkeypatch.setattr(fees, "SIGNAL21_CACHE_DIR", cache_dir)

    call_count = {"sql": 0}

    def fake_sql(query: str, force_refresh: bool = False):
        call_count["sql"] += 1
        return pd.DataFrame(
            {
                "burn_block_height": [1, 2],
                "fees_stx_sum": [1.0, 2.0],
                "tx_count": [10, 12],
            }
        )

    monkeypatch.setattr(fees, "run_sql_query", fake_sql)

    df_first = fees.fetch_fees_by_tenure(force_refresh=True)
    assert len(df_first) == 2
    assert call_count["sql"] == 1

    df_second = fees.fetch_fees_by_tenure()
    assert len(df_second) == 2
    assert call_count["sql"] == 1  # cache hit


def test_aggregate_rewards_cache(monkeypatch, tmp_path):
    from src import hiro

    cache_dir = tmp_path / "hiro"
    cache_dir.mkdir()
    monkeypatch.setattr(hiro, "HIRO_CACHE_DIR", cache_dir)

    call_count = {"iter": 0}

    def fake_iterate(**kwargs):
        call_count["iter"] += 1
        data = [
            {"burn_block_height": 1, "reward_amount": 100},
            {"burn_block_height": 1, "reward_amount": 200},
            {"burn_block_height": 2, "reward_amount": 300},
        ]
        yield from data

    monkeypatch.setattr(hiro, "iterate_burnchain_rewards", fake_iterate)

    df_first = hiro.aggregate_rewards_by_burn_block(force_refresh=True)
    assert len(df_first) == 2
    assert call_count["iter"] == 1

    df_second = hiro.aggregate_rewards_by_burn_block()
    assert len(df_second) == 2
    assert call_count["iter"] == 1  # loaded from cache
