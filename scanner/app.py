"""One scan: universe -> regime -> manage open positions -> new entries -> state + log."""
from __future__ import annotations

import csv
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from . import strategy
from .config import BAR_SECONDS, BARS_PER_DAY, TIMEFRAME, Settings
from .kucoin import KuCoinError
from .portfolio import Portfolio, Trade
from .risk import Order, size_order
from .universe import Candidate, build_universe

log = logging.getLogger(__name__)


@dataclass
class Signal:
    setup: strategy.Setup
    candidate: Candidate
    status: str                    # opened | no-slot | regime-off | held | too-small | stale
    order: Order | None = None


@dataclass
class ScanResult:
    bar: pd.Timestamp                          # start of the evaluated 4h candle
    regime: strategy.Regime
    regime_changed: bool
    universe: int
    scanned: int
    uptrend: list[str]
    signals: list[Signal]
    exits: list[Trade]
    errors: list[str]
    equity: float
    open_positions: int
    repeated: bool                             # same candle as the previous scan (re-run)
    setups: dict[str, strategy.Setup] = field(default_factory=dict)

    @property
    def opened(self) -> list[Signal]:
        return [x for x in self.signals if x.status == "opened"]

    @property
    def has_events(self) -> bool:
        return bool(self.opened or self.exits or self.regime_changed)


def last_closed_bar(now: float) -> pd.Timestamp:
    return pd.Timestamp(int(now // BAR_SECONDS - 1) * BAR_SECONDS, unit="s", tz="UTC")


def run_scan(client, s: Settings, pf: Portfolio, now: float | None = None) -> ScanResult:
    now = time.time() if now is None else now
    bar = last_closed_bar(now)
    errors: list[str] = []

    symbols = client.symbols()
    meta = {m["symbol"]: m for m in symbols}
    universe = build_universe(symbols, client.tickers(), s)

    reg = strategy.regime(client.candles(s.regime_symbol, "1day", limit=400, now=now), s)
    changed = pf.regime_on is not None and pf.regime_on != reg.on
    pf.regime_on = reg.on

    by_symbol = {c.symbol: c for c in universe}
    wanted = list(by_symbol) + [p for p in pf.positions if p not in by_symbol]
    data: dict[str, pd.DataFrame] = {}
    for sym in wanted:
        try:
            df = client.candles(sym, TIMEFRAME, now=now)
        except KuCoinError as e:
            errors.append(f"{sym}: {e}")
            continue
        if len(df):
            data[sym] = df

    # 1) open positions: stops and trend exits on every candle since the last check
    exits = []
    for sym in list(pf.positions):
        if sym not in data:
            errors.append(f"{sym}: geen candles, positie niet gecontroleerd")
            continue
        trade = pf.manage(sym, strategy.compute(data[sym], s))
        if trade:
            exits.append(trade)

    # 2) entries on the last closed candle, most liquid first
    repeated = pf.last_scan_bar == bar.isoformat()
    # like the backtest: no re-entry on the candle that just gave a trend exit
    bar_close = (bar + pd.Timedelta(seconds=BAR_SECONDS)).isoformat()
    just_exited = {t.symbol for t in exits if t.reason == "trend-exit" and t.closed == bar_close}
    signals, uptrend, setups = [], [], {}
    min_bars = s.min_history_days * BARS_PER_DAY
    for c in universe:
        df = data.get(c.symbol)
        if df is None or len(df) < min_bars:
            continue
        setup = strategy.evaluate(c.symbol, df, s)
        setups[c.symbol] = setup
        if setup.in_uptrend:
            uptrend.append(c.symbol)
        if not setup.entry or c.symbol in just_exited:
            continue
        sig = Signal(setup, c, "")
        if setup.time != bar:
            sig.status = "stale"
        elif c.symbol in pf.positions:
            sig.status = "held"
        elif not reg.on:
            sig.status = "regime-off"
        elif len(pf.positions) >= s.max_positions:
            sig.status = "no-slot"
        else:
            sig.order = size_order(pf.equity, setup.close, setup.stop, s, meta.get(c.symbol))
            sig.status = "too-small" if sig.order is None else "opened"
        if sig.status == "opened":
            o = sig.order
            pf.open(c.symbol, setup.time, o.entry, o.stop, o.qty, o.risk_usdt)
        signals.append(sig)
    pf.last_scan_bar = bar.isoformat()

    return ScanResult(bar=bar, regime=reg, regime_changed=changed, universe=len(universe), scanned=len(setups),
                      uptrend=uptrend, signals=signals, exits=exits, errors=errors, equity=pf.equity,
                      open_positions=len(pf.positions), repeated=repeated, setups=setups)


SIGNAL_LOG_FIELDS = ["scan_bar", "event", "symbol", "status", "price", "stop", "qty", "notional", "risk_usdt",
                     "pnl_usdt", "ret_pct", "reason", "atr_pct", "vol_ratio", "ret_7d", "ret_30d", "turnover_usd"]


def append_log(path: str | Path, res: ScanResult) -> None:
    rows = []
    for x in res.signals:
        o, st = x.order, x.setup
        rows.append(dict(scan_bar=res.bar.isoformat(), event="signal", symbol=st.symbol, status=x.status,
                         price=st.close, stop=o.stop if o else st.stop, qty=o.qty if o else "",
                         notional=round(o.notional, 2) if o else "", risk_usdt=round(o.risk_usdt, 2) if o else "",
                         atr_pct=round(st.metrics["atr_pct"], 2), vol_ratio=round(st.metrics["vol_ratio"], 2),
                         ret_7d=round(st.metrics["ret_7d"], 2), ret_30d=round(st.metrics["ret_30d"], 2),
                         turnover_usd=round(x.candidate.turnover_usd)))
    for t in res.exits:
        rows.append(dict(scan_bar=res.bar.isoformat(), event="exit", symbol=t.symbol, status="closed", price=t.exit,
                         qty=t.qty, pnl_usdt=round(t.pnl_usdt, 2), ret_pct=round(t.ret_pct, 2), reason=t.reason))
    if not rows:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=SIGNAL_LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerows(rows)
