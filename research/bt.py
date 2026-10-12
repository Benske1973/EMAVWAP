"""EMA/VWAP strategy research backtester for KuCoin spot (long-only).

Signals are evaluated on bar close; entries fill at the next bar open.
Stops are checked intrabar (gap-through fills at the open); when stop and
target are both touched in one bar the stop is assumed first (conservative).
"""
import os, glob
import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
FEE = 0.001        # KuCoin level-0 spot taker
SLIP = 0.0005      # assumed slippage per side for liquid alts
COST = FEE + SLIP  # per side


# ----------------------------------------------------------------- data
def load(sym, tf="1h"):
    df = pd.read_csv(os.path.join(DATA, f"{sym}_15min.csv"))
    df.index = pd.to_datetime(df.ts, unit="s", utc=True)
    df = df[["open", "high", "low", "close", "vol", "turnover"]]
    if tf != "15min":
        df = df.resample(tf).agg(dict(open="first", high="max", low="min", close="last",
                                      vol="sum", turnover="sum")).dropna(subset=["close"])
    return df[df.vol > 0]


def symbols():
    return sorted(os.path.basename(p).split("_")[0] for p in glob.glob(os.path.join(DATA, "*_15min.csv")))


# ----------------------------------------------------------- indicators
def ema(s, n):
    return s.ewm(span=n, adjust=False).mean()


def atr(df, n=14):
    pc = df.close.shift()
    tr = pd.concat([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def anchored_vwap(df, freq):
    """VWAP reset at each calendar period (D = 00:00 UTC, W-MON = Monday) + 1 sd band."""
    key = df.index.floor("D")
    if freq == "W":
        key = key - pd.to_timedelta(df.index.dayofweek, unit="D")
    tp = (df.high + df.low + df.close) / 3
    g = pd.DataFrame(dict(pv=df.turnover, v=df.vol, pv2=tp * tp * df.vol)).groupby(key).cumsum()
    vw = g.pv / g.v
    sd = np.sqrt((g.pv2 / g.v - vw * vw).clip(lower=0))
    return vw, sd


def rolling_vwap(df, n):
    return df.turnover.rolling(n).sum() / df.vol.rolling(n).sum()


def prepare(df, bars_per_day):
    d = df.copy()
    for n in (9, 21, 50, 200):
        d[f"e{n}"] = ema(d.close, n)
    d["atr"] = atr(d)
    d["vwap_d"], d["sd_d"] = anchored_vwap(d, "D")
    d["vwap_w"], _ = anchored_vwap(d, "W")
    d["rvwap1"] = rolling_vwap(d, bars_per_day)        # rolling 24h
    d["rvwap7"] = rolling_vwap(d, 7 * bars_per_day)    # rolling 7d
    d["volma"] = d.vol.rolling(20).mean()
    d["ret7"] = d.close.pct_change(7 * bars_per_day)
    return d


# ---------------------------------------------------------- strategies
def crossed_up(a, b):
    return (a > b) & (a.shift() <= b.shift())


def crossed_dn(a, b):
    return (a < b) & (a.shift() >= b.shift())


def sig_ema_cross(d):
    """Baseline: EMA9 x EMA21, exit on cross down."""
    return dict(entry=crossed_up(d.e9, d.e21), exit=crossed_dn(d.e9, d.e21),
                stop=d.close - 3 * d.atr)


def sig_vwap_cross(d, vw="vwap_d"):
    """Close crosses above VWAP while EMA50 > EMA200; exit on close below VWAP."""
    trend = (d.e50 > d.e200) & (d.close > d.e200)
    return dict(entry=crossed_up(d.close, d[vw]) & trend, exit=d.close < d[vw],
                stop=d.close - 2 * d.atr)


def sig_pullback(d, vw="rvwap7", touch="e21", exit_mode="trail", rr=2.0):
    """Trend pullback: uptrend (e21>e50>e200, close above VWAP), price dipped into
    the EMA21/VWAP zone in the last 3 bars, and resumes (close > prior high & > e9)."""
    trend = (d.e21 > d.e50) & (d.e50 > d.e200) & (d.close > d[vw])
    zone = np.maximum(d[touch], d["vwap_d"]) if touch == "zone" else d[touch]
    dipped = (d.low <= zone * 1.002).rolling(3).max().astype(bool)
    trigger = (d.close > d.high.shift()) & (d.close > d.e9)
    entry = trend & dipped & trigger
    swing = d.low.rolling(5).min()
    stop = np.minimum(swing - 0.25 * d.atr, d.close - 1.0 * d.atr)
    out = dict(entry=entry, stop=stop)
    if exit_mode == "trail":
        out["exit"] = d.close < d.e21 - 0.5 * d.atr
    elif exit_mode == "rr":
        out["rr"] = rr
    elif exit_mode == "chand":
        out["chand"] = 3.0
    return out


def sig_band_reversion(d):
    """Uptrend dip: close was below daily VWAP - 2sd, closes back above it -> target VWAP."""
    trend = (d.e50 > d.e200)
    lower = d.vwap_d - 2 * d.sd_d
    entry = trend & crossed_up(d.close, lower) & (d.sd_d > 0)
    return dict(entry=entry, stop=d.low.rolling(3).min() - 0.5 * d.atr,
                target=d.vwap_d, exit=None, maxbars=24)


def sig_vwap_breakout(d):
    """Weekly AVWAP reclaim with volume expansion, EMA21 > EMA50; chandelier exit."""
    entry = crossed_up(d.close, d.vwap_w) & (d.vol > 1.5 * d.volma) & (d.e21 > d.e50) & (d.close > d.e200)
    return dict(entry=entry, stop=d.close - 2 * d.atr, chand=3.0)


# ------------------------------------------------------------- engine
def run(d, spec, regime=None, cost=COST, start=None):
    o, h, l, c = (d[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = d.atr.to_numpy()
    entry = spec["entry"].fillna(False).to_numpy(bool).copy()
    if regime is not None:
        entry &= regime.reindex(d.index).ffill().fillna(False).to_numpy(bool)
    ex = spec.get("exit")
    ex = ex.fillna(False).to_numpy(bool) if ex is not None else np.zeros(len(d), bool)
    stop_s = spec["stop"].to_numpy()
    tgt_s = spec.get("target")
    tgt_s = tgt_s.to_numpy() if tgt_s is not None else None
    rr, chand, maxbars = spec.get("rr"), spec.get("chand"), spec.get("maxbars")
    score = d.ret7.to_numpy()
    idx = d.index
    i0 = 200 if start is None else max(200, idx.searchsorted(start))
    trades, n, i = [], len(d), i0
    while i < n - 1:
        if not entry[i] or not np.isfinite(stop_s[i]) or stop_s[i] >= c[i]:
            i += 1
            continue
        ep = o[i + 1]
        stop = stop_s[i]
        if stop >= ep:
            i += 1
            continue
        risk = ep - stop
        tgt = ep + rr * risk if rr else None
        hh, j, xp = h[i + 1], i + 1, None
        while j < n:
            if tgt_s is not None:
                tgt = tgt_s[j - 1] if tgt_s[j - 1] > ep else None
            if l[j] <= stop:                                   # stop first
                xp = min(o[j], stop); break
            if tgt is not None and h[j] >= tgt:
                xp = max(o[j], tgt); break
            hh = max(hh, h[j])
            if chand:
                stop = max(stop, hh - chand * a[j])
            if (ex[j] or (maxbars and j - i >= maxbars)) and j + 1 < n:
                xp = o[j + 1]; j += 1; break
            j += 1
        if xp is None:
            xp, j = c[-1], n - 1
        net = (xp * (1 - cost)) / (ep * (1 + cost)) - 1
        trades.append((idx[i + 1], idx[j], ep, xp, net, (xp - ep) / risk, j - i, score[i], risk / ep))
        i = j
    return pd.DataFrame(trades, columns=["entry_t", "exit_t", "ep", "xp", "ret", "R", "bars", "score", "risk_pct"])


def stats(t):
    if len(t) == 0:
        return dict(trades=0)
    w, ls = t.ret[t.ret > 0], t.ret[t.ret <= 0]
    return dict(trades=len(t), win=round(100 * len(w) / len(t), 1),
                avg=round(100 * t.ret.mean(), 3), med=round(100 * t.ret.median(), 3),
                pf=round(w.sum() / -ls.sum(), 2) if ls.sum() < 0 else np.inf,
                avgR=round(t.R.mean(), 2), bars=round(t.bars.mean(), 1))


def portfolio(trades, slots=5, rank="score", start_eq=1.0, risk=None):
    """Equal-slot portfolio over all coins' trades. Concurrent-signal priority by
    `rank` (higher first). Equity is booked at exit (realised)."""
    t = trades.sort_values(["entry_t", rank], ascending=[True, False]).reset_index(drop=True)
    eq, open_pos, curve = start_eq, [], []
    taken = []
    for r in t.itertuples():
        # close positions that exited before this entry
        still = []
        for p in sorted(open_pos, key=lambda p: p[0]):
            if p[0] <= r.entry_t:
                eq += p[1] * p[2]
                curve.append((p[0], eq))
            else:
                still.append(p)
        open_pos = still
        if len(open_pos) >= slots or any(p[3] == r.sym for p in open_pos):
            continue
        size = eq / slots if risk is None else min(eq / slots, eq * risk / r.risk_pct)
        open_pos.append((r.exit_t, size, r.ret, r.sym))
        taken.append(r.Index)
    for p in sorted(open_pos, key=lambda p: p[0]):
        eq += p[1] * p[2]
        curve.append((p[0], eq))
    cv = pd.Series([e for _, e in curve], index=[x for x, _ in curve]) if curve else pd.Series(dtype=float)
    return eq, cv, t.loc[taken]


def curve_stats(cv, start_eq=1.0):
    if cv.empty:
        return {}
    full = pd.concat([pd.Series([start_eq], index=[cv.index[0] - pd.Timedelta("1h")]), cv])
    dd = (full / full.cummax() - 1).min()
    daily = full.resample("1D").last().ffill().pct_change().dropna()
    yrs = (full.index[-1] - full.index[0]).days / 365
    cagr = full.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else np.nan
    sharpe = daily.mean() / daily.std() * np.sqrt(365) if daily.std() > 0 else np.nan
    return dict(total=round(100 * (full.iloc[-1] - 1), 1), cagr=round(100 * cagr, 1),
                maxdd=round(100 * dd, 1), sharpe=round(sharpe, 2))
