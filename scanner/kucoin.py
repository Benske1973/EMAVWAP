"""Minimal read-only client for KuCoin's public spot market data (no API key needed)."""
from __future__ import annotations

import logging
import time

import pandas as pd
import requests

BASE_URL = "https://api.kucoin.com"
INTERVALS = {"1hour": 3600, "4hour": 4 * 3600, "1day": 86400}
MAX_CANDLES = 1500  # KuCoin returns at most 1500 candles per request

log = logging.getLogger(__name__)


class KuCoinError(RuntimeError):
    pass


class KuCoin:
    def __init__(self, base_url: str = BASE_URL, session: requests.Session | None = None,
                 timeout: float = 15.0, retries: int = 4, backoff: float = 1.0):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff

    def _get(self, path: str, params: dict | None = None):
        delay, err = self.backoff, None
        for attempt in range(self.retries + 1):
            try:
                r = self.session.get(self.base_url + path, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                err = e
            else:
                if r.status_code == 429 or r.status_code >= 500:
                    err = KuCoinError(f"HTTP {r.status_code}")
                else:
                    try:
                        body = r.json()
                    except ValueError:
                        raise KuCoinError(f"{path}: HTTP {r.status_code}, geen JSON") from None
                    if body.get("code") != "200000":
                        raise KuCoinError(f"{path}: {body.get('code')} {body.get('msg')}")
                    return body["data"]
            if attempt < self.retries:
                log.warning("KuCoin %s mislukt (%s), nieuwe poging over %.0fs", path, err, delay)
                time.sleep(delay)
                delay *= 2
        raise KuCoinError(f"{path} mislukt na {self.retries + 1} pogingen: {err}")

    def symbols(self) -> list[dict]:
        return self._get("/api/v2/symbols")

    def tickers(self) -> list[dict]:
        return self._get("/api/v1/market/allTickers")["ticker"]

    def candles(self, symbol: str, interval: str = "4hour", limit: int = MAX_CANDLES,
                now: float | None = None) -> pd.DataFrame:
        """Closed candles only, oldest first, indexed by UTC candle start time."""
        sec = INTERVALS[interval]
        now = int(time.time() if now is None else now)
        end = now - now % sec  # start of the candle that is still forming
        start = end - min(limit, MAX_CANDLES) * sec
        rows = self._get("/api/v1/market/candles",
                         {"symbol": symbol, "type": interval, "startAt": start, "endAt": end})
        return parse_candles(rows, sec, now)


def parse_candles(rows: list[list], sec: int, now: float) -> pd.DataFrame:
    cols = ["ts", "open", "close", "high", "low", "vol", "turnover"]
    df = pd.DataFrame(rows, columns=cols).astype(float)
    df = df[df.ts + sec <= now].drop_duplicates("ts").sort_values("ts")
    df.index = pd.to_datetime(df.ts.astype("int64"), unit="s", utc=True)
    df.index.name = "time"
    return df[["open", "high", "low", "close", "vol", "turnover"]]
