"""Command line: python -m scanner {scan,loop,status,close,test-notify}."""
from __future__ import annotations

import argparse
import logging
import sys
import time

import pandas as pd

from .app import append_log, run_scan
from .config import BAR_SECONDS, Settings, load_settings
from .kucoin import KuCoin
from .notify import Notifier, format_report, fp
from .portfolio import Portfolio
from . import strategy

log = logging.getLogger("scanner")


def _portfolio(s: Settings) -> Portfolio:
    return Portfolio.load(s.state_file, s.equity_usdt, s.cost_pct)


def scan_once(s: Settings, client: KuCoin, notifier: Notifier | None, dry_run: bool = False) -> None:
    pf = _portfolio(s)
    res = run_scan(client, s, pf)
    report = format_report(res, pf, s)
    print(report, flush=True)
    if dry_run:
        return
    pf.save(s.state_file)
    append_log(s.signal_log, res)
    if notifier and (res.has_events or s.notify_summary):
        notifier.send(report)


def next_run_time(now: float, delay: float) -> float:
    """First 4h close + delay that is still ahead of `now`."""
    run = (now // BAR_SECONDS) * BAR_SECONDS + delay
    return run if run > now else run + BAR_SECONDS


def cmd_loop(s: Settings, client: KuCoin, notifier: Notifier | None) -> None:
    log.info("Scanner gestart: elke 4h-candle-close + %ss. Stoppen met Ctrl+C.", s.run_delay_s)
    while True:
        next_run = next_run_time(time.time(), s.run_delay_s)
        log.info("Volgende scan om %s UTC", pd.Timestamp(next_run, unit="s").strftime("%Y-%m-%d %H:%M:%S"))
        while (wait := next_run - time.time()) > 0:
            time.sleep(min(wait, 60))
        try:
            scan_once(s, client, notifier)
        except Exception as e:  # keep the loop alive; report and retry next candle
            log.exception("Scan mislukt")
            if notifier:
                notifier.send(f"[FOUT] EMA/VWAP-scan mislukt: {e}")
        time.sleep(1)


def cmd_status(s: Settings, client: KuCoin) -> None:
    pf = _portfolio(s)
    reg = strategy.regime(client.candles(s.regime_symbol, "1day", limit=400), s)
    prices = {t["symbol"]: float(t["last"]) for t in client.tickers() if t.get("last")}
    print(f"Regime: {'AAN' if reg.on else 'UIT'} (BTC dag-close {fp(reg.close)} vs EMA{s.regime_ema} {fp(reg.ema)})")
    unreal = pf.unrealized(prices)
    print(f"Equity (gerealiseerd): {pf.equity:.2f} USDT | ongerealiseerd {unreal:+.2f} USDT | "
          f"start {pf.start_equity:.2f} USDT | laatste scan-candle {pf.last_scan_bar or '-'}")
    print(f"\nOpen posities ({len(pf.positions)}/{s.max_positions}):")
    for p in pf.positions.values():
        px = prices.get(p.symbol)
        now = f"nu {fp(px)} ({(px / p.entry - 1) * 100:+.1f}%)" if px else "nu ?"
        print(f"  {p.symbol:14s} sinds {p.opened[:16]}  entry {fp(p.entry)}  stop {fp(p.stop)}  {now}  qty {p.qty:g}")
    if pf.trades:
        wins = [t for t in pf.trades if t.pnl_usdt > 0]
        print(f"\nGesloten trades: {len(pf.trades)}, winrate {len(wins) / len(pf.trades) * 100:.0f}%, "
              f"resultaat {sum(t.pnl_usdt for t in pf.trades):+.2f} USDT. Laatste 10:")
        for t in pf.trades[-10:]:
            print(f"  {t.closed[:16]} {t.symbol:14s} {t.reason:10s} {t.ret_pct:+6.1f}%  {t.pnl_usdt:+.2f} USDT")


def cmd_close(s: Settings, client: KuCoin, symbol: str, price: float | None) -> None:
    pf = _portfolio(s)
    symbol = symbol.upper()
    if symbol not in pf.positions:
        sys.exit(f"Geen open paper-positie in {symbol}. Open: {', '.join(pf.positions) or '-'}")
    if price is None:
        price = next((float(t["last"]) for t in client.tickers() if t["symbol"] == symbol and t.get("last")), None)
        if price is None:
            sys.exit(f"Geen actuele prijs voor {symbol}; geef de exit-prijs op met --price")
    t = pf.close(symbol, price, pd.Timestamp.now(tz="UTC"), "manual")
    pf.save(s.state_file)
    print(f"{symbol} gesloten @ {fp(price)}: {t.ret_pct:+.1f}% ({t.pnl_usdt:+.2f} USDT). Equity {pf.equity:.2f} USDT")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scanner", description="EMA/VWAP multi-coin scanner voor KuCoin spot")
    ap.add_argument("--config", default="config.toml", help="pad naar config.toml (optioneel)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan", help="eenmalige scan van de laatst gesloten 4h-candle")
    p.add_argument("--no-notify", action="store_true", help="geen Telegram/Discord-melding")
    p.add_argument("--dry-run", action="store_true", help="niets opslaan en niets versturen")
    p = sub.add_parser("loop", help="blijf draaien en scan na elke 4h-close")
    p.add_argument("--no-notify", action="store_true")
    sub.add_parser("status", help="regime, open posities en resultaten van de paper-portefeuille")
    p = sub.add_parser("close", help="paper-positie handmatig sluiten")
    p.add_argument("symbol")
    p.add_argument("--price", type=float, help="exit-prijs (standaard: laatste prijs)")
    sub.add_parser("test-notify", help="stuur een testbericht naar Telegram/Discord")
    a = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = load_settings(a.config)
    client = KuCoin()
    notifier = None if getattr(a, "no_notify", False) else Notifier(s)

    if a.cmd == "scan":
        scan_once(s, client, None if a.dry_run else notifier, dry_run=a.dry_run)
    elif a.cmd == "loop":
        cmd_loop(s, client, notifier)
    elif a.cmd == "status":
        cmd_status(s, client)
    elif a.cmd == "close":
        cmd_close(s, client, a.symbol, a.price)
    elif a.cmd == "test-notify":
        n = Notifier(s)
        if not n.channels:
            sys.exit("Geen kanaal ingesteld: zet TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID of DISCORD_WEBHOOK_URL in .env")
        ok = n.send("Testbericht van de EMA/VWAP-scanner: meldingen werken.")
        print("Verstuurd naar " + ", ".join(n.channels) if ok else "Versturen mislukt, zie log")


if __name__ == "__main__":
    main()
