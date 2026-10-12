"""Pick the tradable universe at scan time (no hindsight: liquidity as of now)."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Settings

QUOTE = "USDT"
STABLES = {
    "USDC", "USDT", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD", "USD1", "USDD", "USDP", "BUSD", "UST", "USTC",
    "USDS", "USDG", "RLUSD", "FRAX", "USDQ", "GUSD", "LUSD", "SUSD", "USDX", "EUR", "EURC", "EURI", "AEUR",
    "PAXG", "XAUT",
}
LEVERAGED = re.compile(r"[2-5][LS]$")  # KuCoin leveraged tokens: BTC3L, ETH3S, ...


@dataclass
class Candidate:
    symbol: str
    turnover_usd: float
    spread_pct: float
    last: float


def build_universe(symbols: list[dict], tickers: list[dict], s: Settings) -> list[Candidate]:
    meta = {m["symbol"]: m for m in symbols}
    excluded = {x.upper() for x in s.exclude}
    out = []
    for t in tickers:
        sym = t.get("symbol", "")
        m = meta.get(sym)
        if m is None or m.get("quoteCurrency") != QUOTE or not m.get("enableTrading"):
            continue
        base = m.get("baseCurrency", "")
        if m.get("st") or m.get("callauctionIsEnabled") or base in STABLES or LEVERAGED.search(base):
            continue
        if sym in excluded or base in excluded:
            continue
        try:
            turnover = float(t.get("volValue") or 0)
            bid, ask, last = float(t.get("buy") or 0), float(t.get("sell") or 0), float(t.get("last") or 0)
        except (TypeError, ValueError):
            continue
        if turnover < s.min_turnover_usd or bid <= 0 or ask <= 0:
            continue
        spread = (ask - bid) / ((ask + bid) / 2) * 100
        if spread > s.max_spread_pct:
            continue
        out.append(Candidate(sym, turnover, spread, last))
    out.sort(key=lambda c: c.turnover_usd, reverse=True)
    return out
