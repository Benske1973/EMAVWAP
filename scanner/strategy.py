"""Strategy v1: 4h trend pullback to EMA21 above the 7-day rolling VWAP, BTC regime filter.

Rules (docs/ANALYSE.md §6), evaluated on the close of a 4h candle:
  1. trend     EMA21 > EMA50 > EMA200
  2. value     close > rolling 7-day VWAP
  3. pullback  low of one of the last 3 candles <= EMA21 * 1.002
  4. trigger   close > previous high and close > EMA9
  5. volume    volume > SMA20(volume)
  stop  = min(lowest low of 5 candles - 0.25 ATR, close - 1 ATR)
  exit  = close < EMA50 - 0.5 ATR
  regime: long entries only while the BTC daily close > daily EMA50.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import BARS_PER_DAY, Settings
from .indicators import atr, ema, rolling_vwap, sma


def compute(df: pd.DataFrame, s: Settings) -> pd.DataFrame:
    """Add indicator, condition, stop and exit columns to a 4h candle frame."""
    d = df.copy()
    d["ema_trigger"] = ema(d.close, s.ema_trigger)
    d["ema_fast"] = ema(d.close, s.ema_fast)
    d["ema_mid"] = ema(d.close, s.ema_mid)
    d["ema_slow"] = ema(d.close, s.ema_slow)
    d["vwap"] = rolling_vwap(d, s.vwap_days * BARS_PER_DAY)
    d["atr"] = atr(d, s.atr_len)
    d["vol_sma"] = sma(d.vol, s.vol_len)

    d["c_trend"] = (d.ema_fast > d.ema_mid) & (d.ema_mid > d.ema_slow)
    d["c_value"] = d.close > d.vwap
    d["c_pullback"] = (d.low <= d.ema_fast * (1 + s.pullback_tol)).rolling(s.pullback_bars).max().fillna(0).astype(bool)
    d["c_trigger"] = (d.close > d.high.shift()) & (d.close > d.ema_trigger)
    d["c_volume"] = d.vol > d.vol_sma

    d["stop"] = np.minimum(d.low.rolling(s.swing_bars).min() - s.swing_atr_buf * d.atr,
                           d.close - s.min_stop_atr * d.atr)
    d["exit_level"] = d.ema_mid - s.exit_atr_buf * d.atr
    d["exit"] = d.close < d.exit_level
    d["entry"] = (d.c_trend & d.c_value & d.c_pullback & d.c_trigger & d.c_volume
                  & np.isfinite(d.stop) & (d.stop < d.close))
    return d


@dataclass
class Setup:
    symbol: str
    time: pd.Timestamp            # start of the evaluated (closed) candle
    close: float
    entry: bool
    stop: float
    atr: float
    exit_level: float
    conditions: dict[str, bool]
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def in_uptrend(self) -> bool:
        return self.conditions["trend"] and self.conditions["value"]


def evaluate(symbol: str, df: pd.DataFrame, s: Settings) -> Setup:
    """Evaluate the last closed candle of `df`."""
    d = compute(df, s)
    last = d.iloc[-1]
    close = float(last.close)

    def pct(n):
        return float(close / d.close.iloc[-1 - n] - 1) * 100 if len(d) > n else float("nan")

    return Setup(
        symbol=symbol, time=d.index[-1], close=close, entry=bool(last.entry),
        stop=float(last.stop), atr=float(last.atr), exit_level=float(last.exit_level),
        conditions=dict(trend=bool(last.c_trend), value=bool(last.c_value), pullback=bool(last.c_pullback),
                        trigger=bool(last.c_trigger), volume=bool(last.c_volume)),
        metrics=dict(atr_pct=float(last.atr / close * 100),
                     vol_ratio=float(last.vol / last.vol_sma) if last.vol_sma else float("nan"),
                     dist_vwap_pct=float((close / last.vwap - 1) * 100),
                     ret_7d=pct(7 * BARS_PER_DAY), ret_30d=pct(30 * BARS_PER_DAY)),
    )


@dataclass
class Regime:
    on: bool
    close: float
    ema: float
    time: pd.Timestamp            # start of the last closed daily candle


def regime(daily: pd.DataFrame, s: Settings) -> Regime:
    e = ema(daily.close, s.regime_ema)
    close, level = float(daily.close.iloc[-1]), float(e.iloc[-1])
    return Regime(on=close > level, close=close, ema=level, time=daily.index[-1])
