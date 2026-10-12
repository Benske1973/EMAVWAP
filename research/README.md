# Research: EMA/VWAP backtests op KuCoin spot

```bash
pip install -r requirements-dev.txt
cd research
python fetch.py BTC-USDT ETH-USDT SOL-USDT ...   # 2 jaar 15m-candles -> data/ (niet in git)
python study.py 4h 1h    # alle strategieën x regimefilters, IS/OOS -> results/study_results_*.csv
python report.py         # benchmarks, ranking-test, kosten- en parametergevoeligheid
python features.py       # welke kenmerken rangschikken trades? (IS vs OOS)
python v2.py             # breadth-regime, tragere varianten, risico-sizing
python final.py          # details en equity-grafiek van de gekozen v1-configuratie
```

| Bestand | Doel |
|---|---|
| `bt.py` | Indicatoren (EMA, ATR, anchored/rolling VWAP), strategie-signalen, trade-engine (long-only, next-open fills, intrabar stops, kosten), portfolio-simulatie |
| `study.py` | Universum-brede vergelijking, BTC-regimefilters, IS/OOS-split (12-10-2025) |
| `extras.py` | Benchmarks, ranking-test, parametergrid, kostengevoeligheid |

Kosten in alle tests: 0,10% fee + 0,05% slippage per kant.
