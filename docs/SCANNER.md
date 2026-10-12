# Scanner v1: handleiding

De scanner volgt de regels uit [ANALYSE.md §6](ANALYSE.md#6-aanbevolen-strategie-v1-specificatie-voor-de-scanner).

- Hij controleert alle liquide KuCoin USDT-paren na elke 4h-candle-close (00, 04, 08, 12, 16 en 20 uur UTC).
- Hij **meldt** koop-, stop- en verkoopsignalen met entry, stop en positiegrootte.
- Hij **plaatst zelf geen orders** en heeft geen API-key nodig. Hij gebruikt alleen publieke marktdata.
- Hij houdt een **papieren portefeuille** bij met zijn eigen signalen. Daarmee kan hij ook melden wanneer een positie verkocht moet worden, en zie je meteen hoe de strategie live presteert (paper trading).

## Installatie

Je hebt Python 3.11 of nieuwer nodig.

```bash
git clone https://github.com/Benske1973/EMAVWAP.git
cd EMAVWAP
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp config.example.toml config.toml   # optioneel: pas kapitaal en risico aan
cp .env.example .env                 # optioneel: Telegram/Discord
```

## Gebruik

| Commando | Wat het doet |
|---|---|
| `python -m scanner scan` | Eén scan van de laatst gesloten 4h-candle. Werkt de portefeuille bij en stuurt een melding als er iets gebeurt. |
| `python -m scanner scan --dry-run` | Proefscan: niets opslaan, niets versturen. |
| `python -m scanner loop` | Blijft draaien en scant elke 4h-close + 90 s. Laat dit 24/7 draaien. |
| `python -m scanner status` | Toont het regime, de open posities met hun actuele resultaat en de gesloten trades. |
| `python -m scanner close ZEC-USDT [--price 1234.5]` | Sluit een paper-positie handmatig, bijvoorbeeld als je zelf eerder verkocht. |
| `python -m scanner test-notify` | Stuurt een testbericht naar Telegram of Discord. |

Voorbeeld van een melding:

```
EMA/VWAP scanner | 4h-candle gesloten 14-09-2026 22:00 (Europe/Amsterdam)
Regime: AAN | BTC dag-close 76849.00 > EMA50 73200.26 -> long toegestaan
Universum: 61 coins (omzet >= $2.0M), 55 gescand, 12 in uptrend
Paper-portefeuille: 8/8 posities, equity 1000.00 USDT

[KOOP] NEAR-USDT  entry ~2.5327  stop 2.2550 (-11.0%)
  36.01 NEAR = 91.20 USDT (9.1% van kapitaal), risico 10.00 USDT (1.00%)
  ATR 3.7% | volume 1.3x gem. | 7d +9.1% | 30d +54.4%
  Exit zodra een 4h-close < EMA50 - 0.5 ATR (nu 2.2996). Zet direct een stop-loss op KuCoin.
```

## Wat je met een melding doet

1. **[KOOP]**: koop rond de genoemde entry, bijvoorbeeld met een limietorder (maker-fee). Zet **direct** een stop-loss-order op KuCoin op de genoemde stop.
   - De positiegrootte is gebaseerd op het paper-kapitaal. Handel je met een ander bedrag, reken dan naar verhouding om: het risico is telkens 1% van je kapitaal.
2. **[VERKOOP]**: een 4h-candle sloot onder EMA50 − 0,5 × ATR. Verkoop de positie en annuleer de stop-order.
3. **[STOP]**: de stop is geraakt. Op KuCoin heeft je stop-order dit al afgehandeld; de melding is een bevestiging.
4. **[REGIME]**: BTC ging door zijn dag-EMA50.
   - Bij **UIT** komen er geen nieuwe koopsignalen. Open posities volgen hun eigen stop en exit.

**Neem alle signalen**, ook na een reeks verliezers. De analyse laat zien dat de winst uit een paar grote trends komt (winrate ±25%, gemiddelde winnaar ±4× de gemiddelde verliezer). Wie signalen overslaat, mist juist die trades.

## Meldingen instellen

**Telegram**

1. Open in Telegram een chat met **@BotFather** en stuur `/newbot`. Je krijgt een *token*.
2. Stuur je nieuwe bot een bericht (bijvoorbeeld "hoi").
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` in je browser en zoek `"chat":{"id":...}`. Dat getal is je chat-id.
4. Zet in `.env`:
   ```
   TELEGRAM_BOT_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```
5. Test met `python -m scanner test-notify`.

**Discord**

Ga naar Serverinstellingen → Integraties → Webhooks → Nieuwe webhook en kopieer de URL. Zet in `.env`:

```
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
```

Standaard krijg je alleen een bericht als er iets gebeurt: een koop, stop, verkoop of regimewissel. Wil je na elke scan een samenvatting, zet dan in `config.toml` `notify_summary = true`.

## 24/7 laten draaien

- **Eigen pc (Windows, macOS, Linux):** laat `python -m scanner loop` openstaan in een terminal.
- **Linux-server of Raspberry Pi, met cron** (scant elke 4 uur om hh:01:30 UTC; zet de servertijd op UTC):
  ```
  1 0,4,8,12,16,20 * * *  cd /pad/naar/EMAVWAP && sleep 30 && .venv/bin/python -m scanner scan >> state/cron.log 2>&1
  ```
- **Docker:**
  ```bash
  cp config.example.toml config.toml   # eerst aanmaken, anders maakt Docker er een map van
  docker compose up -d                 # gebruikt config.toml en .env uit deze map, bewaart state/ op de host
  docker compose logs -f
  ```
- **Windows Taakplanner:** maak een taak die elke 4 uur `python -m scanner scan` uitvoert, telkens 2 minuten na 02:00, 06:00, 10:00, 14:00, 18:00 en 22:00 (zomertijd; in de wintertijd een uur eerder). Stel als "Beginnen in" de EMAVWAP-map in.

## Bestanden

| Bestand | Inhoud |
|---|---|
| `state/portfolio.json` | Paper-portefeuille: open posities, gesloten trades en equity. Verwijder dit bestand om opnieuw te beginnen. |
| `state/signals.csv` | Logboek van elk signaal en elke exit. Gebruik dit om live met de backtest te vergelijken. |
| `config.toml` | Jouw instellingen (zie `config.example.toml`). |
| `.env` | Telegram/Discord-geheimen. Zet dit bestand niet in git. |

## Hoe de scanner de backtest volgt

De tests in `tests/test_parity.py` controleren dat de scanner **exact dezelfde signalen, stops en exits** geeft als de backtest in `research/`. Ze spelen de scanner candle voor candle af en vergelijken elke trade met de backtest-engine:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Er zijn drie kleine verschillen met de backtest:

1. **Universum:** de scanner kiest de coins **op het moment zelf**, op basis van de 24h-omzet en de spread. Dat voorkomt de survivorship bias uit de analyse.
2. **BTC-regime:** de scanner gebruikt de laatst gesloten dag-candle. De backtest gebruikte die van een dag eerder, dus de scanner is iets actueler.
3. **Fills:** de paper-fills gebruiken de candle-close. In een markt die 24/7 open is, is dat praktisch gelijk aan de open van de volgende candle.

## Beperkingen

- Alleen long, alleen spot, alleen 4h. Alleen deze combinatie is gevalideerd.
- De paper-portefeuille weet niet wat je echt hebt gekocht. Wijk je af, gebruik dan `close` of verwijder `state/portfolio.json`.
- Als de scanner een tijd uit heeft gestaan, controleert hij bij de volgende scan alle gemiste candles op stops en exits. Gemiste koopsignalen haalt hij niet in, want die zijn dan verouderd.
- Dit is geen financieel advies. Begin met paper trading (4-8 weken) en daarna met een klein bedrag.
