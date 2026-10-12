"""The live scanner must reproduce the validated backtest (research/), signal for signal."""
import numpy as np
import pandas as pd
import pytest

from conftest import FakeClient, synthetic
from scanner import strategy
from scanner.app import run_scan
from scanner.config import BAR_SECONDS, Settings
from scanner.portfolio import Portfolio

bt = pytest.importorskip("bt")
extras = pytest.importorskip("extras")

V1 = dict(fast=21, mid=50, slow=200, vwn=7, trail="mid", buf=0.5, swing=5, vol=True)


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_signals_match_research(seed):
    df = synthetic(seed=seed)
    ref = extras.s_pullback_param(bt.prepare(df, 6), **V1)
    got = strategy.compute(df, Settings())
    warm = slice(200, None)
    ref_entry = (ref["entry"] & np.isfinite(ref["stop"]) & (ref["stop"] < df.close)).iloc[warm]
    pd.testing.assert_series_equal(got.entry.iloc[warm], ref_entry, check_names=False)
    pd.testing.assert_series_equal(got.exit.iloc[warm], ref["exit"].iloc[warm], check_names=False)
    np.testing.assert_allclose(got.stop.iloc[warm], ref["stop"].iloc[warm], rtol=1e-12)
    assert got.entry.iloc[warm].sum() > 0


@pytest.mark.parametrize("seed", [7, 16, 29])
def test_bar_by_bar_replay_matches_backtest_trades(seed, settings):
    df = synthetic(n=1100, seed=seed)
    start = 700
    client = FakeClient({"AAA-USDT": df})
    settings.exclude = ["BTC-USDT"]
    pf = Portfolio(settings.equity_usdt, settings.cost_pct)
    for t in df.index[start:]:
        run_scan(client, settings, pf, now=t.timestamp() + BAR_SECONDS + 90)

    prep = bt.prepare(df, 6)
    ref = bt.run(prep, extras.s_pullback_param(prep, **V1), cost=settings.cost_pct / 100, start=df.index[start])
    assert len(ref) >= 3
    # the research engine marks a still-open trade to the last close; the scanner keeps it open
    assert len(pf.trades) + len(pf.positions) == len(ref)
    for mine, (_, r) in zip(pf.trades, ref.iterrows()):
        assert pd.Timestamp(mine.opened) == r.entry_t
        assert mine.entry == pytest.approx(r.ep, rel=1e-9)
        assert mine.exit == pytest.approx(r.xp, rel=1e-6)
        assert mine.ret_pct / 100 == pytest.approx(r.ret, abs=1e-6)
