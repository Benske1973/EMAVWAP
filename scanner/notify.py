"""Report formatting (Dutch) and delivery to console, Telegram and Discord."""
from __future__ import annotations

import logging
import math
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .app import ScanResult
from .config import BAR_SECONDS, Settings
from .portfolio import Portfolio

log = logging.getLogger(__name__)


def fp(x: float) -> str:
    """Price with ~5 significant digits, no thousands separator (copy-paste safe for KuCoin)."""
    if x is None or not math.isfinite(x) or x == 0:
        return str(x)
    decimals = max(2, 4 - math.floor(math.log10(abs(x))))
    return f"{x:.{decimals}f}"


def fq(x: float) -> str:
    return f"{x:.8f}".rstrip("0").rstrip(".")


def local(ts: pd.Timestamp, s: Settings) -> str:
    try:
        tz = ZoneInfo(s.timezone)
    except Exception:  # missing tz database (Windows without tzdata)
        return ts.strftime("%d-%m-%Y %H:%M UTC")
    return ts.tz_convert(tz).strftime("%d-%m-%Y %H:%M")


def format_report(res: ScanResult, pf: Portfolio, s: Settings) -> str:
    close_time = res.bar + pd.Timedelta(seconds=BAR_SECONDS)
    r = res.regime
    lines = [
        f"EMA/VWAP scanner | 4h-candle gesloten {local(close_time, s)} ({s.timezone})",
        f"Regime: {'AAN' if r.on else 'UIT'} | BTC dag-close {fp(r.close)} {'>' if r.on else '<='} EMA{s.regime_ema} {fp(r.ema)}"
        + (" -> long toegestaan" if r.on else " -> geen nieuwe entries"),
        f"Universum: {res.universe} coins (omzet >= ${s.min_turnover_usd / 1e6:.1f}M), {res.scanned} gescand, "
        f"{len(res.uptrend)} in uptrend",
        f"Paper-portefeuille: {res.open_positions}/{s.max_positions} posities, equity {res.equity:.2f} USDT",
    ]
    if res.regime_changed:
        lines.append("")
        lines.append(f"[REGIME] Gewijzigd naar {'AAN: longs weer toegestaan' if r.on else 'UIT: geen nieuwe entries, open posities volgen hun exit'}")
    for x in res.opened:
        o, st = x.order, x.setup
        base = st.symbol.split("-")[0]
        m = st.metrics
        lines += [
            "",
            f"[KOOP] {st.symbol}  entry ~{fp(o.entry)}  stop {fp(o.stop)} (-{o.stop_pct:.1f}%)",
            f"  {fq(o.qty)} {base} = {o.notional:.2f} USDT ({o.notional / res.equity * 100:.1f}% van kapitaal), "
            f"risico {o.risk_usdt:.2f} USDT ({o.risk_pct:.2f}%)" + (" [max positiegrootte]" if o.capped else ""),
            f"  ATR {m['atr_pct']:.1f}% | volume {m['vol_ratio']:.1f}x gem. | 7d {m['ret_7d']:+.1f}% | 30d {m['ret_30d']:+.1f}%",
            f"  Exit zodra een 4h-close < EMA{s.ema_mid} - {s.exit_atr_buf} ATR (nu {fp(st.exit_level)}). "
            f"Zet direct een stop-loss op KuCoin.",
        ]
    for t in res.exits:
        tag = "[STOP]" if t.reason == "stop" else "[VERKOOP]"
        why = "stop geraakt" if t.reason == "stop" else f"trend-exit (4h-close < EMA{s.ema_mid} - {s.exit_atr_buf} ATR)"
        lines += ["", f"{tag} {t.symbol}  {why} @ {fp(t.exit)} | entry {fp(t.entry)} -> {t.ret_pct:+.1f}% "
                      f"({t.pnl_usdt:+.2f} USDT)"]
    groups = {"no-slot": "Signaal zonder vrije plek", "regime-off": "Signaal onderdrukt (regime UIT)",
              "too-small": "Signaal onder KuCoin-minimum", "held": "Signaal, al in positie"}
    for status, label in groups.items():
        names = [x.setup.symbol for x in res.signals if x.status == status]
        if names:
            lines += ["", f"{label}: {', '.join(names)}"]
    if pf.positions:
        lines += ["", "Open posities: " + ", ".join(
            f"{p.symbol} (entry {fp(p.entry)}, stop {fp(p.stop)})" for p in pf.positions.values())]
    if res.errors:
        lines += ["", f"Waarschuwingen ({len(res.errors)}): " + "; ".join(res.errors[:5])]
    if not res.has_events and not res.signals:
        lines += ["", "Geen nieuwe signalen."]
    return "\n".join(lines)


def _chunks(text: str, limit: int) -> list[str]:
    out, cur = [], ""
    for line in text.splitlines():
        for piece in [line[i:i + limit] for i in range(0, len(line), limit)] or [""]:
            if cur and len(cur) + 1 + len(piece) > limit:
                out.append(cur)
                cur = piece
            else:
                cur = f"{cur}\n{piece}" if cur else piece
    if cur:
        out.append(cur)
    return out


class Notifier:
    def __init__(self, s: Settings, session: requests.Session | None = None):
        self.s = s
        self.session = session or requests.Session()

    @property
    def channels(self) -> list[str]:
        ch = []
        if self.s.telegram_token and self.s.telegram_chat_id:
            ch.append("telegram")
        if self.s.discord_webhook:
            ch.append("discord")
        return ch

    def send(self, text: str) -> bool:
        """Deliver to every configured channel; failures are logged, never raised."""
        ok = True
        if "telegram" in self.channels:
            url = f"https://api.telegram.org/bot{self.s.telegram_token}/sendMessage"
            for part in _chunks(text, 4000):
                ok &= self._post(url, {"chat_id": self.s.telegram_chat_id, "text": part,
                                       "disable_web_page_preview": True}, "Telegram")
        if "discord" in self.channels:
            for part in _chunks(text, 1900):
                ok &= self._post(self.s.discord_webhook, {"content": f"```\n{part}\n```"}, "Discord")
        return ok

    def _post(self, url: str, payload: dict, name: str) -> bool:
        try:
            r = self.session.post(url, json=payload, timeout=15)
            if r.status_code >= 300:
                log.error("%s-melding mislukt: HTTP %s %s", name, r.status_code, r.text[:200])
                return False
            return True
        except requests.RequestException as e:
            log.error("%s-melding mislukt: %s", name, e)
            return False
