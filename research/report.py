"""Deep-dive on the candidates picked from the in-sample study."""
import json, os, warnings
import pandas as pd
from bt import *
from study import *
from extras import *

warnings.filterwarnings("ignore")

if __name__ == "__main__":
    syms = symbols()
    univ = load_universe("4h", syms)
    regs = btc_regimes(univ["BTC-USDT"].index)
    reg = regs["btc>d50"]

    print("== Benchmarks")
    print(benchmarks(univ, reg).to_string(index=False), flush=True)

    cands = {
        "pullback_trail": lambda d: sig_pullback(d, vw="rvwap7"),
        "avwap_reclaim_vw": lambda d: s_avwap_reclaim(d, "vwap"),
        "vwap_cross_w": lambda d: sig_vwap_cross(d, "vwap_w"),
    }
    for name, fn in cands.items():
        t = collect(univ, fn, reg)
        print(f"\n== {name} | ranking test (5 slots)")
        print(json.dumps(rank_test(t), indent=1, default=str), flush=True)
        for slots in (3, 5, 8):
            for part, sub in (("IS", t[t.entry_t < SPLIT]), ("OOS", t[t.entry_t >= SPLIT])):
                _, cv, taken = portfolio(sub, slots=slots)
                print(f"  slots={slots} {part}: {curve_stats(cv)} taken={len(taken)}/{len(sub)}")
        pc = per_coin(t)
        print("  per coin (worst 5 / best 5):")
        print(pc.head(5).to_string(), "\n", pc.tail(5).to_string())
        print(f"  coins with positive sum: {(pc['sum'] > 0).sum()}/{len(pc)}")

    print("\n== Cost sensitivity (pullback_trail, btc>d50, full period)")
    print(cost_sens(univ, reg, cands["pullback_trail"]).to_string(index=False), flush=True)

    print("\n== Parameter grid (pullback, btc>d50)")
    g = grid(univ, reg)
    g.to_csv(os.path.join(RES, "grid.csv"), index=False)
    print(g.to_string(index=False))
