import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(1, str(ROOT / "research"))

from scanner.config import BAR_SECONDS, Settings  # noqa: E402

T0 = 1_700_006_400  # 2023-11-15 00:00 UTC, aligned to 4h and 1d


def synthetic(n: int = 1200, seed: int = 7, start: int = T0, sec: int = BAR_SECONDS, base: float = 10.0) -> pd.DataFrame:
    """Continuous OHLCV (open = previous close) with alternating trend regimes and volume bursts."""
    rng = np.random.default_rng(seed)
    drift = np.repeat(rng.choice([0.004, 0.002, -0.003, 0.0], size=n // 60 + 1), 60)[:n]
    rets = drift + rng.normal(0, 0.012, n)
    close = base * np.exp(np.cumsum(rets))
    open_ = np.r_[base, close[:-1]]
    span = np.abs(rng.normal(0, 0.008, n)) * close
    high = np.maximum(open_, close) + span
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.008, n)) * close
    vol = rng.lognormal(10, 0.5, n) * (1 + 2 * (rng.random(n) < 0.15))
    df = pd.DataFrame(dict(open=open_, high=high, low=low, close=close, vol=vol, turnover=vol * close))
    df.index = pd.to_datetime(start + sec * np.arange(n), unit="s", utc=True)
    df.index.name = "time"
    return df


def rising_daily(n: int = 650, start: int = T0 - 400 * 86400) -> pd.DataFrame:
    close = np.linspace(20_000, 60_000, n)
    df = pd.DataFrame(dict(open=close, high=close * 1.01, low=close * 0.99, close=close, vol=1.0, turnover=close))
    df.index = pd.to_datetime(start + 86400 * np.arange(n), unit="s", utc=True)
    return df


def meta(symbol: str, inc: str = "0.00000001") -> dict:
    base, quote = symbol.split("-")
    return dict(symbol=symbol, baseCurrency=base, quoteCurrency=quote, enableTrading=True, st=False,
                callauctionIsEnabled=False, priceIncrement=inc, baseIncrement=inc, baseMinSize="0", minFunds="0.1")


def ticker(symbol: str, turnover: float = 5e6, price: float = 10.0, spread: float = 0.0005) -> dict:
    return dict(symbol=symbol, volValue=str(turnover), buy=str(price * (1 - spread / 2)),
                sell=str(price * (1 + spread / 2)), last=str(price))


class FakeClient:
    """Stands in for scanner.kucoin.KuCoin, serving closed candles as of `now`."""

    def __init__(self, frames: dict[str, pd.DataFrame], daily: pd.DataFrame | None = None, tickers=None):
        self.frames = frames
        self.daily = daily if daily is not None else rising_daily()
        self._tickers = tickers or [ticker(s) for s in frames]
        self.calls = 0

    def symbols(self):
        return [meta(s) for s in set(self.frames) | {"BTC-USDT"}]

    def tickers(self):
        return self._tickers

    def candles(self, symbol, interval="4hour", limit=1500, now=None):
        self.calls += 1
        if interval == "1day":
            df, sec = self.daily, 86400
        else:
            df, sec = self.frames[symbol], BAR_SECONDS
        closed = df[df.index.as_unit("s").astype("int64") + sec <= now]
        return closed.iloc[-limit:]


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(state_file=str(tmp_path / "state.json"), signal_log=str(tmp_path / "signals.csv"))
