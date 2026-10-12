"""Which signal-time features rank trades well (IS vs OOS)? -> scanner ranking score."""
import os, warnings, numpy as np, pandas as pd
from bt import *
from study import *
warnings.filterwarnings("ignore")


def feats(d, btc):
    f = pd.DataFrame(index=d.index)
    f["ret7d"] = d.close.pct_change(42)
    f["ret30d"] = d.close.pct_change(180)
    b30 = btc.close.reindex(d.index).ffill().pct_change(180)
    f["rs30_vs_btc"] = f.ret30d - b30
    ch = (d.close - d.close.shift(60)).abs()
    f["eff_ratio10d"] = ch / d.close.diff().abs().rolling(60).sum()
    f["dist_vwap7_atr"] = (d.close - d.rvwap7) / d.atr
    f["atr_pct"] = d.atr / d.close
    f["vol_ratio"] = d.vol / d.volma
    f["ema_spread"] = (d.e21 - d.e50) / d.atr
    f["turnover_usd_1d"] = d.turnover.rolling(6).sum()
    return f


if __name__ == "__main__":
    univ = load_universe("4h", symbols())
    btc = univ["BTC-USDT"]
    reg = btc_regimes(btc.index)["btc>d50"]
    rows = []
    for s, d in univ.items():
        t = run(d, sig_pullback(d, vw="rvwap7"), regime=reg)
        f = feats(d, btc)
        sig_t = d.index[d.index.get_indexer(t.entry_t) - 1]
        t = pd.concat([t.reset_index(drop=True), f.loc[sig_t].reset_index(drop=True)], axis=1)
        t["sym"] = s
        rows.append(t)
    t = pd.concat(rows, ignore_index=True)
    t.to_csv(os.path.join(RES, "pullback_features.csv"), index=False)
    out = []
    for col in ["ret7d", "ret30d", "rs30_vs_btc", "eff_ratio10d", "dist_vwap7_atr", "atr_pct", "vol_ratio", "ema_spread", "turnover_usd_1d"]:
        for part, sub in (("IS", t[t.entry_t < SPLIT]), ("OOS", t[t.entry_t >= SPLIT])):
            q = pd.qcut(sub[col].rank(method="first"), 5, labels=False)
            m = sub.groupby(q).ret.mean().mul(100).round(2).tolist()
            ic = sub[[col, "ret"]].corr(method="spearman").iloc[0, 1]
            out.append(dict(feature=col, part=part, Q1=m[0], Q2=m[1], Q3=m[2], Q4=m[3], Q5=m[4], spearman=round(ic, 3)))
    print(pd.DataFrame(out).to_string(index=False))
