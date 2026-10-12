"""Benchmarks, ranking test, robustness and cost sensitivity for the leading candidates."""
import sys, warnings
import numpy as np
import pandas as pd
import bt
from bt import *
from study import *

warnings.filterwarnings("ignore")


def benchmarks(univ, regime):
    rows = []
    for part, (a, b) in {"IS": (None, SPLIT), "OOS": (SPLIT, None)}.items():
        rets, reg_rets = [], []
        for s, d in univ.items():
            c = d.close[(d.index >= a) if a is not None else slice(None)]
            c = c[c.index < b] if b is not None else c
            rets.append(c.iloc[-1] / c.iloc[0] - 1)
            r = c.pct_change().fillna(0)
            on = regime.reindex(c.index).ffill().fillna(False).shift().fillna(False).astype(bool)
            reg_rets.append(r.where(on, 0))
        bh = pd.Series(rets)
        basket = pd.concat(reg_rets, axis=1).mean(axis=1)
        eqc = (1 + basket).cumprod()
        rows.append(dict(part=part, bh_mean=round(100 * bh.mean(), 1), bh_median=round(100 * bh.median(), 1),
                         bh_pct_positive=round(100 * (bh > 0).mean(), 1),
                         regime_basket=round(100 * (eqc.iloc[-1] - 1), 1),
                         regime_basket_dd=round(100 * (eqc / eqc.cummax() - 1).min(), 1)))
    return pd.DataFrame(rows)


def rank_test(t, slots=5, seeds=20):
    out = {}
    for part, sub in (("IS", t[t.entry_t < SPLIT]), ("OOS", t[t.entry_t >= SPLIT])):
        sub = sub.copy()
        res = {}
        for lab, col in (("RS high first", "score"), ("RS low first", "neg")):
            sub["neg"] = -sub.score
            _, cv, _ = portfolio(sub, slots=slots, rank=col)
            res[lab] = curve_stats(cv)["total"]
        rnd = []
        for k in range(seeds):
            sub["rnd"] = np.random.default_rng(k).random(len(sub))
            _, cv, _ = portfolio(sub, slots=slots, rank="rnd")
            rnd.append(curve_stats(cv)["total"])
        res["random (mean)"] = round(float(np.mean(rnd)), 1)
        # quintiles of the RS score at signal time
        q = pd.qcut(sub.score.rank(method="first"), 5, labels=["Q1 zwak", "Q2", "Q3", "Q4", "Q5 sterk"])
        res["avg% per RS quintile"] = sub.groupby(q, observed=True).ret.mean().mul(100).round(2).to_dict()
        out[part] = res
    return out


def per_coin(t):
    g = t.groupby("sym").ret
    return pd.DataFrame(dict(n=g.size(), avg=g.mean().mul(100).round(2), sum=g.sum().mul(100).round(1))).sort_values("sum")


def s_pullback_param(d, fast=21, mid=50, slow=200, vwn=7, trail="fast", buf=0.5, swing=5, vol=False):
    bpd = 6
    ef, em, es = ema(d.close, fast), ema(d.close, mid), ema(d.close, slow)
    vw = d.vwap_w if vwn == "W" else rolling_vwap(d, vwn * bpd)
    trend = (ef > em) & (em > es) & (d.close > vw)
    dipped = (d.low <= ef * 1.002).rolling(3).max().astype(bool)
    trigger = (d.close > d.high.shift()) & (d.close > d.e9)
    if vol:
        trigger &= d.vol > d.volma
    te = ef if trail == "fast" else em
    return dict(entry=trend & dipped & trigger,
                stop=np.minimum(d.low.rolling(swing).min() - 0.25 * d.atr, d.close - 1.0 * d.atr),
                exit=d.close < te - buf * d.atr)


def grid(univ, reg):
    rows = []
    base = dict(fast=21, mid=50, slow=200, vwn=7, trail="fast", buf=0.5, swing=5, vol=False)
    variants = [{}] + [{"fast": f, "mid": m} for f, m in ((13, 34), (20, 50), (34, 89))] \
        + [{"slow": s} for s in (100, 150, 300)] + [{"vwn": v} for v in (3, 14, 30, "W")] \
        + [{"buf": b} for b in (0.0, 1.0)] + [{"trail": "mid"}] + [{"swing": s} for s in (3, 10)] + [{"vol": True}]
    for v in variants:
        p = {**base, **v}
        ts = []
        for s, d in univ.items():
            t = run(d, s_pullback_param(d, **p), regime=reg); t["sym"] = s; ts.append(t)
        t = pd.concat(ts, ignore_index=True)
        row = {"variant": str(v or "basis")}
        for part, sub in (("IS", t[t.entry_t < SPLIT]), ("OOS", t[t.entry_t >= SPLIT])):
            st = stats(sub); _, cv, _ = portfolio(sub, slots=5); cs = curve_stats(cv)
            row.update({f"{part}_n": st["trades"], f"{part}_avg%": st["avg"], f"{part}_pf": st["pf"],
                        f"{part}_port%": cs.get("total"), f"{part}_dd%": cs.get("maxdd")})
        rows.append(row); print(row, flush=True)
    return pd.DataFrame(rows)


def cost_sens(univ, reg, fn):
    rows = []
    for c in (0.0, 0.0008, 0.0015, 0.0025, 0.004):
        ts = []
        for s, d in univ.items():
            t = run(d, fn(d), regime=reg, cost=c); t["sym"] = s; ts.append(t)
        t = pd.concat(ts, ignore_index=True)
        st = stats(t); _, cv, _ = portfolio(t, slots=5)
        rows.append(dict(cost_per_side=c, trades=st["trades"], avg=st["avg"], pf=st["pf"], **curve_stats(cv)))
    return pd.DataFrame(rows)


if __name__ == "__main__":
    syms = symbols()
    univ = load_universe("4h", syms)
    reg = btc_regimes(univ["BTC-USDT"].index)["btc>d50"]
    print("== Benchmarks (4h data, equal weight universe)")
    print(benchmarks(univ, reg).to_string(index=False))
