"""Download 15m KuCoin spot candles (paged, 1500/req) into parquet-less CSV cache."""
import requests, time, sys, os, pandas as pd
BASE = "https://api.kucoin.com/api/v1/market/candles"
OUT = os.path.join(os.path.dirname(__file__), "data")
TF, SEC = "15min", 900
END = int(time.time()) // SEC * SEC
START = END - 2 * 365 * 86400

def fetch(sym):
    path = os.path.join(OUT, f"{sym}_{TF}.csv")
    if os.path.exists(path):
        return
    rows, end = [], END
    while end > START:
        for attempt in range(5):
            try:
                r = requests.get(BASE, params=dict(symbol=sym, type=TF, startAt=max(START, end - 1500 * SEC), endAt=end), timeout=20)
                j = r.json()
                if j.get("code") == "200000":
                    break
            except Exception:
                pass
            time.sleep(2 ** attempt)
        data = j.get("data") or []
        if not data:
            break
        rows += data
        end = int(data[-1][0]) - 1
        time.sleep(0.12)
    if not rows:
        print(sym, "no data"); return
    df = pd.DataFrame(rows, columns=["ts", "open", "close", "high", "low", "vol", "turnover"]).astype(float)
    df = df.drop_duplicates("ts").sort_values("ts")
    df.to_csv(path, index=False)
    print(sym, len(df), pd.to_datetime(df.ts.iloc[0], unit="s"), flush=True)

if __name__ == "__main__":
    for s in sys.argv[1:]:
        fetch(s)
