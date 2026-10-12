# EMAVWAP

Multi-coin scanner voor **KuCoin spot** op basis van **EMA + VWAP**.

- **Analyse en backtest** (36 coins, okt 2024 - okt 2026): [`docs/ANALYSE.md`](docs/ANALYSE.md)
- **Scanner v1, handleiding**: [`docs/SCANNER.md`](docs/SCANNER.md)

```bash
pip install -r requirements.txt
python -m scanner scan --dry-run   # proefscan van de laatst gesloten 4h-candle
python -m scanner loop             # 24/7: scan na elke 4h-close, meldingen via Telegram/Discord
```

**Strategie v1**

- **Timeframe:** 4h-candles. Op 1h en lager vreten de kosten de edge op.
- **Setup:** EMA21 > EMA50 > EMA200, de prijs boven de 7-daagse rolling VWAP, een pullback naar de EMA21 en hervatting met volume.
- **Regime:** alleen nieuwe posities als BTC boven zijn dag-EMA50 staat.
- **Exit:** 4h-close onder EMA50 − 0,5 ATR. Stop onder de swing-low.
- **Risico:** 1% per trade, max 12,5% per positie, max 8 posities.

De scanner meldt signalen en houdt een papieren portefeuille bij. Hij plaatst zelf geen orders.

| Map | Inhoud |
|---|---|
| `scanner/` | De scanner (Python) |
| `tests/` | Unit-tests en een pariteitstest tegen de backtest |
| `docs/` | Analyse, handleiding en grafieken |
| `research/` | Data-download, backtest-engine en studies |
| `research/results/` | Uitkomsten van de studies (CSV en logs) |
