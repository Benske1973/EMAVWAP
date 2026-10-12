"""Position sizing: fixed fractional risk, capped notional, rounded to KuCoin increments."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from .config import Settings


@dataclass
class Order:
    qty: float
    entry: float
    stop: float
    notional: float
    risk_usdt: float
    risk_pct: float        # of equity
    stop_pct: float        # distance entry -> stop
    capped: bool           # notional cap hit, so risk < risk_pct


def _round(x: float, inc: str | float | None, mode) -> float:
    if not inc or float(inc) <= 0:
        return x
    step = Decimal(str(inc))
    return float((Decimal(str(x)) / step).to_integral_value(mode) * step)


def size_order(equity: float, entry: float, stop: float, s: Settings, meta: dict | None = None) -> Order | None:
    """None when the trade is invalid or below the exchange minimums."""
    meta = meta or {}
    entry = _round(entry, meta.get("priceIncrement"), ROUND_HALF_UP)
    stop = _round(stop, meta.get("priceIncrement"), ROUND_DOWN)
    if not 0 < stop < entry:
        return None
    risk_budget = equity * s.risk_pct / 100
    qty = risk_budget / (entry - stop)
    cap = equity * s.max_position_pct / 100 / entry
    capped = qty > cap
    qty = _round(min(qty, cap), meta.get("baseIncrement"), ROUND_DOWN)
    notional = qty * entry
    if qty <= 0 or qty < float(meta.get("baseMinSize") or 0) or notional < float(meta.get("minFunds") or 0):
        return None
    risk = qty * (entry - stop)
    return Order(qty=qty, entry=entry, stop=stop, notional=notional, risk_usdt=risk,
                 risk_pct=risk / equity * 100, stop_pct=(entry - stop) / entry * 100, capped=capped)
