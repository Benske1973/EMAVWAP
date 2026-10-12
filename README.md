# EMAVWAP

Multi-coin scanner voor **KuCoin spot** op basis van **EMA + VWAP**.

**Status:** analysefase. De strategie-analyse met backtest op 36 coins (okt 2024 - okt 2026) staat in
[`docs/ANALYSE.md`](docs/ANALYSE.md).

**Kernpunten**

- Draai op 4h-candles. Op 1h en lager vreten de kosten de edge op.
- Gebruik een trend-pullback: EMA21 > EMA50 > EMA200, prijs boven de 7-daagse rolling VWAP, pullback naar de EMA21 en hervatting met volume.
- Neem alleen nieuwe posities als BTC boven zijn dag-EMA50 staat.
- Exit onder EMA50 − 0,5 ATR. Risico 1% per trade, max 8 posities.

| Map | Inhoud |
|---|---|
| `docs/` | Analyse en grafieken |
| `research/` | Data-download, backtest-engine en studies (Python) |
| `research/results/` | Uitkomsten van de studies (CSV en logs) |
