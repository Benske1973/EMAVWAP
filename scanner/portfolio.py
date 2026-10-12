"""Paper portfolio: tracks the scanner's own positions so it can alert stops and exits.

Fills follow the backtest (research/bt.py): entry at the signal close (= next open in a
24/7 market), stop hit intrabar at min(open, stop), trend exit at the candle close.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .config import BAR_SECONDS


@dataclass
class Position:
    symbol: str
    opened: str            # ISO time of entry (close of the signal candle)
    entry: float
    stop: float
    qty: float
    risk_usdt: float
    checked_until: str     # ISO start time of the last candle already managed


@dataclass
class Trade:
    symbol: str
    opened: str
    closed: str
    entry: float
    exit: float
    qty: float
    pnl_usdt: float
    ret_pct: float
    reason: str            # stop | trend-exit | manual


class Portfolio:
    def __init__(self, start_equity: float, cost_pct: float):
        self.start_equity = start_equity
        self.cost = cost_pct / 100
        self.realized = 0.0
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.last_scan_bar: str | None = None
        self.regime_on: bool | None = None

    @property
    def equity(self) -> float:
        return self.start_equity + self.realized

    # ------------------------------------------------------------ persistence
    @classmethod
    def load(cls, path: str | Path, start_equity: float, cost_pct: float) -> "Portfolio":
        p = cls(start_equity, cost_pct)
        path = Path(path)
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            p.start_equity = data.get("start_equity", start_equity)
            p.realized = data.get("realized", 0.0)
            p.positions = {k: Position(**v) for k, v in data.get("positions", {}).items()}
            p.trades = [Trade(**t) for t in data.get("trades", [])]
            p.last_scan_bar = data.get("last_scan_bar")
            p.regime_on = data.get("regime_on")
        return p

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = dict(start_equity=self.start_equity, realized=self.realized,
                    positions={k: asdict(v) for k, v in self.positions.items()},
                    trades=[asdict(t) for t in self.trades],
                    last_scan_bar=self.last_scan_bar, regime_on=self.regime_on)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    # ------------------------------------------------------------ trading
    def open(self, symbol: str, signal_bar: pd.Timestamp, entry: float, stop: float, qty: float,
             risk_usdt: float) -> Position:
        opened = signal_bar + pd.Timedelta(seconds=BAR_SECONDS)
        pos = Position(symbol, opened.isoformat(), entry, stop, qty, risk_usdt, signal_bar.isoformat())
        self.positions[symbol] = pos
        return pos

    def close(self, symbol: str, price: float, when: pd.Timestamp | str, reason: str) -> Trade:
        pos = self.positions.pop(symbol)
        cost_in = pos.qty * pos.entry * (1 + self.cost)
        proceeds = pos.qty * price * (1 - self.cost)
        pnl = proceeds - cost_in
        trade = Trade(symbol, pos.opened, pd.Timestamp(when).isoformat(), pos.entry, price, pos.qty,
                      pnl, (proceeds / cost_in - 1) * 100, reason)
        self.realized += pnl
        self.trades.append(trade)
        return trade

    def manage(self, symbol: str, sig: pd.DataFrame) -> Trade | None:
        """Walk candles newer than the position's last check (output of strategy.compute):
        stop first (intrabar, gaps fill at the open), then the trend exit on the close."""
        pos = self.positions[symbol]
        for t, row in sig[sig.index > pd.Timestamp(pos.checked_until)].iterrows():
            if row.low <= pos.stop:
                return self.close(symbol, min(row.open, pos.stop), t, "stop")
            if row.exit:
                return self.close(symbol, row.close, t + pd.Timedelta(seconds=BAR_SECONDS), "trend-exit")
            pos.checked_until = t.isoformat()
        return None

    def unrealized(self, prices: dict[str, float]) -> float:
        return sum(p.qty * (prices[s] * (1 - self.cost) - p.entry * (1 + self.cost))
                   for s, p in self.positions.items() if s in prices)
