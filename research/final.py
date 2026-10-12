"""Detail stats + equity chart for the recommended configuration."""
import os, warnings, numpy as np, pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from bt import *
from study import *
from extras import s_pullback_param, per_coin
warnings.filterwarnings("ignore")

P = dict(fast=21, mid=50, slow=200, vwn=7, trail="mid", buf=0.5, swing=5, vol=True)
univ = load_universe("4h", symbols())
reg = btc_regimes(univ["BTC-USDT"].index)["btc>d50"]
ts = []
for s, d in univ.items():
    t = run(d, s_pullback_param(d, **P), regime=reg); t["sym"] = s; ts.append(t)
t = pd.concat(ts, ignore_index=True)
t.to_csv(os.path.join(RES, "final_trades.csv"), index=False)

w, l = t.ret[t.ret > 0], t.ret[t.ret <= 0]
print("trades", len(t), "win%", round(100 * len(w) / len(t), 1), "avg win%", round(100 * w.mean(), 2), "avg loss%", round(100 * l.mean(), 2),
      "payoff", round(w.mean() / -l.mean(), 2), "median hold (4h bars)", t.bars.median(), "=", t.bars.median() * 4 / 24, "days")
print("largest win%", round(100 * t.ret.max(), 1), "largest loss%", round(100 * t.ret.min(), 1))
print("trades per month", round(len(t) / 24, 1))
top = t.ret.sort_values(ascending=False)
print("share of profit from top 10% trades:", round(top.head(len(t) // 10).sum() / t.ret.sum(), 2))
# losing streak
streak = mx = 0
for r in t.sort_values("entry_t").ret:
    streak = streak + 1 if r <= 0 else 0; mx = max(mx, streak)
print("max losing streak (chronological, all coins)", mx)

pc = per_coin(t); print("coins positive:", (pc["sum"] > 0).sum(), "/", len(pc)); print(pc.to_string())

curves = {}
for lab, kw in {"5 slots x 20%": dict(slots=5), "1% risk/trade, max 8": dict(slots=8, risk=0.01)}.items():
    _, cv, taken = portfolio(t, **kw)
    curves[lab] = cv
    print(lab, curve_stats(cv), "taken", len(taken))
    m = cv.resample("ME").last().ffill()
    m = pd.concat([pd.Series([1.0], index=[m.index[0] - pd.offsets.MonthEnd()]), m]).pct_change().dropna()
    print("  monthly %:", (m * 100).round(1).to_dict().values().__repr__()[:400])
    print("  positive months:", (m > 0).sum(), "/", len(m))

# exposure (share of time with >=1 open position)
spans = pd.Series(0, index=univ["BTC-USDT"].index)
for r in t.itertuples():
    spans.loc[r.entry_t:r.exit_t] += 1
print("time with >=1 signal-position open:", round((spans > 0).mean(), 2), "avg concurrent:", round(spans.mean(), 2), "max:", spans.max())

# benchmarks curves
closes = pd.concat({s: d.close for s, d in univ.items()}, axis=1).ffill()
start = t.entry_t.min()
bh = (closes[closes.index >= start].pct_change().fillna(0).mean(axis=1) + 1).cumprod()
btc = closes["BTC-USDT"][closes.index >= start]; btc = btc / btc.iloc[0]
fig, ax = plt.subplots(figsize=(11, 5.5))
for lab, cv in curves.items():
    s = pd.concat([pd.Series([1.0], index=[start]), cv]); ax.step(s.index, s.values, where="post", lw=2, label=f"Strategie: {lab}")
ax.plot(bh.index, bh.values, lw=1.2, color="grey", label="Buy & hold 36 coins (gelijk gewogen)")
ax.plot(btc.index, btc.values, lw=1.2, color="orange", alpha=.8, label="Buy & hold BTC")
on = reg.reindex(bh.index).fillna(False)
ax.fill_between(bh.index, 0, 1, where=on.values, transform=ax.get_xaxis_transform(), color="green", alpha=.07, label="BTC > EMA50 (dag): long toegestaan")
ax.axvline(SPLIT, color="k", ls="--", lw=1); ax.text(SPLIT, ax.get_ylim()[1] * .97, "  out-of-sample →", va="top")
ax.set_yscale("log"); ax.set_ylabel("equity (start = 1, log)"); ax.grid(alpha=.3); ax.legend(loc="upper left", fontsize=8)
ax.set_title("4h EMA/VWAP trend-pullback, KuCoin spot, 36 coins, kosten 0,15%/kant")
fig.tight_layout(); fig.savefig(os.path.join(RES, "equity.png"), dpi=110)
print("saved equity.png")
