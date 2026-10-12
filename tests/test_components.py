import numpy as np
import pandas as pd
import pytest

from conftest import T0, FakeClient, meta, rising_daily, synthetic, ticker
from scanner import strategy
from scanner.app import append_log, last_closed_bar, run_scan
from scanner.config import BAR_SECONDS, Settings, load_settings
from scanner.indicators import atr, ema, rolling_vwap
from scanner.kucoin import KuCoin, KuCoinError, parse_candles
from scanner.notify import Notifier, _chunks, format_report, fp
from scanner.portfolio import Portfolio
from scanner.risk import size_order
from scanner.universe import build_universe


# ------------------------------------------------------------- indicators
def test_ema_and_vwap_by_hand():
    s = pd.Series([1.0, 2.0, 3.0])
    a = 2 / (3 + 1)
    assert ema(s, 3).iloc[-1] == pytest.approx(((1 * (1 - a) + 2 * a) * (1 - a)) + 3 * a)
    df = pd.DataFrame(dict(vol=[1.0, 3.0], turnover=[10.0, 60.0]))
    assert rolling_vwap(df, 2).iloc[-1] == pytest.approx(70 / 4)


def test_atr_uses_true_range_with_gaps():
    df = pd.DataFrame(dict(high=[10.0, 12.0], low=[9.0, 11.5], close=[9.5, 12.0]))
    # second TR = max(0.5, |12-9.5|, |11.5-9.5|) = 2.5; Wilder: 1 + (2.5-1)/14
    assert atr(df, 14).iloc[-1] == pytest.approx(1 + 1.5 / 14)


# ------------------------------------------------------------- kucoin client
def test_parse_candles_drops_forming_candle_and_sorts():
    sec = BAR_SECONDS
    rows = [[str(T0 + 2 * sec), "3", "3", "3", "3", "1", "3"],   # still forming at now
            [str(T0 + sec), "2", "2", "2", "2", "1", "2"],
            [str(T0), "1", "1.5", "1.6", "0.9", "1", "1"]]
    df = parse_candles(rows, sec, now=T0 + 2 * sec + 60)
    assert list(df.close) == [1.5, 2.0]
    assert df.index[0] == pd.Timestamp(T0, unit="s", tz="UTC")


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Session:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


def test_client_retries_on_429_then_succeeds():
    sess = _Session([_Resp(429, {}), _Resp(200, {"code": "200000", "data": {"ticker": [1]}})])
    assert KuCoin(session=sess, backoff=0).tickers() == [1]
    assert len(sess.calls) == 2


def test_client_raises_on_api_error_and_candle_window():
    with pytest.raises(KuCoinError):
        KuCoin(session=_Session([_Resp(200, {"code": "400100", "msg": "bad"})]), backoff=0).symbols()
    sess = _Session([_Resp(200, {"code": "200000", "data": []})])
    KuCoin(session=sess, backoff=0).candles("ETH-USDT", "4hour", now=T0 + 100)
    params = sess.calls[0][1]
    assert params["endAt"] == T0 and params["endAt"] - params["startAt"] == 1500 * BAR_SECONDS


# ------------------------------------------------------------- universe
def test_universe_filters_and_sorts():
    syms = [meta(s) for s in ("BTC-USDT", "ETH-USDT", "USDC-USDT", "BTC3L-USDT", "SOL-BTC", "WIDE-USDT",
                              "THIN-USDT", "OFF-USDT", "ST-USDT", "SKIP-USDT", "JUP-USDT")]
    syms[7]["enableTrading"] = False
    syms[8]["st"] = True
    tick = [ticker("BTC-USDT", 9e8), ticker("ETH-USDT", 5e8), ticker("USDC-USDT", 9e8), ticker("BTC3L-USDT", 9e7),
            ticker("SOL-BTC", 9e7), ticker("WIDE-USDT", 9e7, spread=0.01), ticker("THIN-USDT", 1e6),
            ticker("OFF-USDT", 9e7), ticker("ST-USDT", 9e7), ticker("SKIP-USDT", 9e7), ticker("JUP-USDT", 3e6)]
    s = Settings(exclude=["SKIP"])
    assert [c.symbol for c in build_universe(syms, tick, s)] == ["BTC-USDT", "ETH-USDT", "JUP-USDT"]


# ------------------------------------------------------------- sizing
def test_size_order_risk_cap_and_rounding():
    s = Settings(risk_pct=1.0, max_position_pct=12.5)
    o = size_order(1000, entry=10.0, stop=9.0, s=s, meta=meta("X-USDT", "0.01"))
    assert o.qty == 10.0 and o.risk_usdt == pytest.approx(10.0) and not o.capped
    o = size_order(1000, entry=10.0, stop=9.9, s=s, meta=meta("X-USDT", "0.01"))   # tight stop -> notional cap
    assert o.capped and o.notional == pytest.approx(125.0) and o.risk_pct == pytest.approx(0.125)
    m = meta("X-USDT", "0.01") | {"baseMinSize": "1000"}
    assert size_order(1000, 10.0, 9.0, s, m) is None
    assert size_order(1000, 10.0, 10.0, s) is None


# ------------------------------------------------------------- portfolio
def test_portfolio_costs_stop_gap_and_persistence(tmp_path):
    pf = Portfolio(1000, cost_pct=0.15)
    bar = pd.Timestamp(T0, unit="s", tz="UTC")
    pf.open("AAA-USDT", bar, entry=10.0, stop=9.0, qty=10, risk_usdt=10)
    idx = pd.to_datetime([T0 + BAR_SECONDS, T0 + 2 * BAR_SECONDS], unit="s", utc=True)
    sig = pd.DataFrame(dict(open=[10.2, 8.5], high=[10.5, 8.6], low=[9.6, 8.0], close=[10.3, 8.2],
                            exit=[False, False]), index=idx)
    t = pf.manage("AAA-USDT", sig)
    assert t.reason == "stop" and t.exit == 8.5                     # gapped below the stop -> open
    assert t.pnl_usdt == pytest.approx(10 * 8.5 * 0.9985 - 10 * 10 * 1.0015)
    assert pf.equity == pytest.approx(1000 + t.pnl_usdt)
    pf.save(tmp_path / "s.json")
    again = Portfolio.load(tmp_path / "s.json", 5, 0.15)
    assert again.equity == pytest.approx(pf.equity) and len(again.trades) == 1


def test_trend_exit_on_close_after_checked_candles():
    pf = Portfolio(1000, 0.0)
    bar = pd.Timestamp(T0, unit="s", tz="UTC")
    pf.open("AAA-USDT", bar, 10.0, 9.0, 1, 1)
    idx = pd.to_datetime([T0, T0 + BAR_SECONDS, T0 + 2 * BAR_SECONDS], unit="s", utc=True)
    sig = pd.DataFrame(dict(open=[9, 10, 11], high=[9, 11, 12], low=[1, 9.5, 10.5], close=[10, 10.8, 11.5],
                            exit=[True, False, True]), index=idx)   # signal candle itself is ignored
    t = pf.manage("AAA-USDT", sig)
    assert t.reason == "trend-exit" and t.exit == 11.5
    assert t.closed == (idx[-1] + pd.Timedelta(seconds=BAR_SECONDS)).isoformat()


# ------------------------------------------------------------- scan orchestration
def _first_signal(df, s):
    sig = strategy.compute(df, s)
    hits = sig.index[sig.entry & (np.arange(len(sig)) >= 400)]
    assert len(hits)
    return hits[0]


def test_regime_off_suppresses_entries(settings):
    df = synthetic(seed=7)
    bar = _first_signal(df, settings)
    falling = rising_daily().iloc[::-1].set_axis(rising_daily().index)
    client = FakeClient({"AAA-USDT": df}, daily=falling)
    pf = Portfolio(1000, 0.15)
    res = run_scan(client, settings, pf, now=bar.timestamp() + BAR_SECONDS + 90)
    assert not res.regime.on
    assert [x.status for x in res.signals] == ["regime-off"] and not pf.positions


def test_slots_and_rerun_do_not_double_open(settings):
    df = synthetic(seed=7)
    bar = _first_signal(df, settings)
    client = FakeClient({"AAA-USDT": df, "BBB-USDT": df.copy()})
    settings.max_positions = 1
    pf = Portfolio(1000, 0.15)
    now = bar.timestamp() + BAR_SECONDS + 90
    res = run_scan(client, settings, pf, now=now)
    assert sorted(x.status for x in res.signals) == ["no-slot", "opened"]
    assert res.has_events and len(pf.positions) == 1
    again = run_scan(client, settings, pf, now=now + 600)
    assert again.repeated and not again.opened and len(pf.positions) == 1
    append_log(settings.signal_log, res)
    log = pd.read_csv(settings.signal_log)
    assert set(log.status) == {"no-slot", "opened"}
    text = format_report(res, pf, settings)
    assert "[KOOP]" in text and "Signaal zonder vrije plek" in text and "Regime: AAN" in text


def test_loop_schedule():
    from scanner.__main__ import next_run_time
    assert next_run_time(T0 + 30, 90) == T0 + 90                       # just after a close: still due
    assert next_run_time(T0 + 91, 90) == T0 + BAR_SECONDS + 90
    assert next_run_time(T0 + BAR_SECONDS - 1, 90) == T0 + BAR_SECONDS + 90


def test_last_closed_bar():
    assert last_closed_bar(T0 + BAR_SECONDS + 5) == pd.Timestamp(T0, unit="s", tz="UTC")


# ------------------------------------------------------------- notify & config
def test_price_format_and_chunks():
    assert fp(83756.9) == "83756.90" and fp(0.0000042) == "0.0000042000" and fp(1.23456) == "1.2346"
    parts = _chunks("\n".join(["x" * 30] * 10), 100)
    assert all(len(p) <= 100 for p in parts) and "".join(parts).count("x") == 300


def test_notifier_posts_to_telegram():
    class S:
        def __init__(self):
            self.posts = []

        def post(self, url, json=None, timeout=None):
            self.posts.append((url, json))
            return _Resp(200, {})

    sess = S()
    n = Notifier(Settings(telegram_token="T", telegram_chat_id="42"), session=sess)
    assert n.channels == ["telegram"] and n.send("hallo")
    assert sess.posts[0][0].endswith("/botT/sendMessage") and sess.posts[0][1]["chat_id"] == "42"


def test_load_settings_sections_env_and_validation(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text('[risk]\nequity_usdt = 2500\nrisk_pct = 0.5\n[universe]\nexclude = ["PEPE"]\n')
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc")
    s = load_settings(cfg, env_file=tmp_path / "none.env")
    assert s.equity_usdt == 2500.0 and s.risk_pct == 0.5 and s.exclude == ["PEPE"] and s.telegram_token == "abc"
    cfg.write_text("[risk]\nrisk_pct = 9\n")
    with pytest.raises(ValueError):
        load_settings(cfg, env_file=tmp_path / "none.env")
    cfg.write_text("typo_setting = 1\n")
    with pytest.raises(ValueError, match="typo_setting"):
        load_settings(cfg, env_file=tmp_path / "none.env")


def test_example_config_is_valid(monkeypatch):
    from conftest import ROOT
    for var in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "DISCORD_WEBHOOK_URL"):
        monkeypatch.delenv(var, raising=False)
    assert load_settings(ROOT / "config.example.toml", env_file=ROOT / "nonexistent.env") == Settings()
