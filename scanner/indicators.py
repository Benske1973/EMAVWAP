"""Indicators, kept numerically identical to research/bt.py."""
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    """Wilder ATR."""
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def rolling_vwap(df: pd.DataFrame, n: int) -> pd.Series:
    """Volume-weighted average price over the last n candles (quote turnover / base volume)."""
    return df.turnover.rolling(n).sum() / df.vol.rolling(n).sum()
