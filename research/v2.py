"""v2: breadth regime, slower confirmation variants, risk-based sizing, final benchmark."""
import os, warnings, numpy as np, pandas as pd
from bt import *
from study import *
from extras import s_pullback_param, benchmarks
warnings.filterwarnings("ignore")

univ = load_universe("4h", symbols())
idx = univ["BTC-USDT"].index
regs = btc_regimes(idx)
# breadth: share of universe with daily close > daily EMA50 (no look-ahead, shifted to day close)
above = pd.concat({s: htf(d, "1D", lambda h: (h.close > ema(h.close, 50)).astype(float)).reindex(idx)
                   for s, d in univ.items()}, axis=1)
breadth = above.mean(axis=1)
regs["breadth>50%"] = breadth > 0.5
regs["btc>d50 & breadth>40%"] = regs["btc>d50"] & (breadth > 0.4)
regs["btc>d50 & breadth>50%"] = regs["btc>d50"] & (breadth > 0.5)
print("time in regime:", {k: round(float(v.mean()), 2) for k, v in regs.items() if v is not None})

variants = {
    "basis (21/50/200, trail e21)": {},
    "trail e50": {"trail": "mid"},
    "trail e50 + vol": {"trail": "mid", "vol": True},
    "34/89 trail e34": {"fast": 34, "mid": 89},
    "34/89 + vol": {"fast": 34, "mid": 89, "vol": True},
}
rows = []
for vname, p in variants.items():
    for rname in ["btc>d50", "breadth>50%", "btc>d50 & breadth>40%", "btc>d50 & breadth>50%"]:
        ts = []
        for s, d in univ.items():
            t = run(d, s_pullback_param(d, **p), regime=regs[rname]); t["sym"] = s; ts.append(t)
        t = pd.concat(ts, ignore_index=True)
        row = dict(variant=vname, regime=rname)
        for part, sub in (("IS", t[t.entry_t < SPLIT]), ("OOS", t[t.entry_t >= SPLIT])):
            st = stats(sub)
            _, cv, _ = portfolio(sub, slots=5); cs = curve_stats(cv)
            _, cvr, _ = portfolio(sub, slots=8, risk=0.01); csr = curve_stats(cvr)
            row.update({f"{part}_n": st["trades"], f"{part}_win": st["win"], f"{part}_avg": st["avg"], f"{part}_pf": st["pf"],
                        f"{part}_eq5": cs["total"], f"{part}_dd5": cs["maxdd"],
                        f"{part}_risk1%": csr["total"], f"{part}_ddr": csr["maxdd"]})
        rows.append(row)
        print(row, flush=True)
df = pd.DataFrame(rows)
df.to_csv(os.path.join(RES, "v2_results.csv"), index=False)
pd.set_option("display.width", 250)
print(df.to_string(index=False))
for rname in ["btc>d50", "breadth>50%", "btc>d50 & breadth>50%"]:
    print(rname); print(benchmarks(univ, regs[rname]).to_string(index=False))
