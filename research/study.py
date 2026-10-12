"""Universe-wide study: strategies x timeframes x filters, IS/OOS split, portfolio sim."""
import os, sys, warnings
import numpy as np
import pandas as pd
from bt import *

warnings.filterwarnings("ignore")
SPLIT = pd.Timestamp("2025-10-12", tz="UTC")
BPD = {"1h": 24, "4h": 6}


def htf(df_l, rule, fn):
    """Compute fn on a higher timeframe and map it back without look-ahead
    (value becomes available at the HTF bar close)."""
    h = df_l.resample(rule).agg(dict(open="first", high="max", low="min", close="last",
                                      vol="sum", turnover="sum")).dropna(subset=["close"])
    v = fn(h)
    v.index = v.index + pd.Timedelta(rule)
    return v.reindex(df_l.index.union(v.index)).ffill().reindex(df_l.index)


def btc_regimes(idx):
    b = load("BTC-USDT", "1h")
    day = lambda f: htf(b, "1D", f).reindex(idx).ffill()
    return {
        "none": None,
        "btc>d50": day(lambda h: h.close > ema(h.close, 50)),
        "btc d20>d50": day(lambda h: ema(h.close, 20) > ema(h.close, 50)),
    }


def add_htf(d1h):
    d1h["h4_trend"] = htf(d1h, "4h", lambda h: (ema(h.close, 21) > ema(h.close, 50)) & (h.close > ema(h.close, 200)))
    d1h["d_trend"] = htf(d1h, "1D", lambda h: h.close > ema(h.close, 20))
    return d1h


# ----------------------------------------------------------- refined set
def s_avwap_reclaim(d, exit_mode="chand"):
    """Reclaim of the rolling 7d VWAP (weekly value) inside an EMA uptrend."""
    entry = crossed_up(d.close, d.rvwap7) & (d.e21 > d.e50) & (d.close > d.e200)
    out = dict(entry=entry, stop=np.minimum(d.low.rolling(5).min() - 0.25 * d.atr, d.close - 1.5 * d.atr))
    if exit_mode == "chand":
        out["chand"] = 3.0
    else:
        out["exit"] = d.close < d.rvwap7 - 0.5 * d.atr
    return out


def s_mtf_pullback(d, exit_mode="chand"):
    """1h entry in a 4h uptrend: price above weekly value (rvwap7), dip into
    daily VWAP / EMA21 zone, resume with close > prior high."""
    trend = d.h4_trend.astype(bool) & (d.close > d.rvwap7) & (d.e21 > d.e50)
    zone = np.maximum(d.e21, d.vwap_d)
    dipped = (d.low <= zone * 1.002).rolling(4).max().astype(bool)
    trigger = (d.close > d.high.shift()) & (d.close > d.e9) & (d.close > d.vwap_d)
    out = dict(entry=trend & dipped & trigger,
               stop=np.minimum(d.low.rolling(6).min() - 0.25 * d.atr, d.close - 1.5 * d.atr))
    if exit_mode == "chand":
        out["chand"] = 4.0
    else:
        out["exit"] = d.close < d.e50 - 0.5 * d.atr
    return out


STRATS = {
    "4h": {
        "ema_cross": sig_ema_cross,
        "vwap_cross_w": lambda d: sig_vwap_cross(d, "vwap_w"),
        "pullback_trail": lambda d: sig_pullback(d, vw="rvwap7"),
        "pullback_chand": lambda d: sig_pullback(d, vw="rvwap7", exit_mode="chand"),
        "vwap_breakout": sig_vwap_breakout,
        "avwap_reclaim_ch": s_avwap_reclaim,
        "avwap_reclaim_vw": lambda d: s_avwap_reclaim(d, "vwap"),
    },
    "1h": {
        "ema_cross": sig_ema_cross,
        "pullback_trail": lambda d: sig_pullback(d, vw="rvwap7"),
        "mtf_pullback_ch": s_mtf_pullback,
        "mtf_pullback_e50": lambda d: s_mtf_pullback(d, "e50"),
        "avwap_reclaim_ch": s_avwap_reclaim,
    },
}


def load_universe(tf, syms):
    out = {}
    for s in syms:
        d = prepare(load(s, tf), BPD[tf])
        if tf == "1h":
            d = add_htf(d)
        out[s] = d
    return out


def collect(univ, fn, regime):
    ts = []
    for s, d in univ.items():
        t = run(d, fn(d), regime=regime)
        t["sym"] = s
        ts.append(t)
    return pd.concat(ts, ignore_index=True)


def summarize(t, label):
    rows = []
    for part, sub in (("IS", t[t.entry_t < SPLIT]), ("OOS", t[t.entry_t >= SPLIT])):
        st = stats(sub)
        eq, cv, _ = portfolio(sub, slots=5)
        rows.append(dict(label=label, part=part, **st, **{f"P_{k}": v for k, v in curve_stats(cv).items()}))
    return rows


if __name__ == "__main__":
    syms = symbols()
    print("universe:", len(syms), syms)
    all_rows = []
    tfs = sys.argv[1:] or ["4h", "1h"]
    os.makedirs(os.path.join(RES, "trades"), exist_ok=True)
    for tf in tfs:
        univ = load_universe(tf, syms)
        regs = btc_regimes(univ["BTC-USDT"].index)
        for name, fn in STRATS[tf].items():
            for rname, reg in regs.items():
                t = collect(univ, fn, reg)
                all_rows += summarize(t, f"{tf}|{name}|{rname}")
                t.to_csv(os.path.join(RES, "trades", f"{tf}_{name}_{rname.replace(' ', '_').replace('>', 'gt')}.csv"), index=False)
                print(pd.DataFrame(all_rows[-2:]).to_string(index=False, header=len(all_rows) == 2), flush=True)
    pd.DataFrame(all_rows).to_csv(os.path.join(RES, f"study_results_{'_'.join(tfs)}.csv"), index=False)
