"""Settings: strategy-v1 defaults (docs/ANALYSE.md §6), overridden by config.toml and env vars."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

TIMEFRAME = "4hour"          # the strategy was only validated on 4h candles
BAR_SECONDS = 4 * 3600
BARS_PER_DAY = 6


@dataclass
class Settings:
    # [universe]
    min_turnover_usd: float = 2_000_000
    max_spread_pct: float = 0.30
    min_history_days: int = 60
    exclude: list[str] = field(default_factory=list)
    # [strategy]
    ema_trigger: int = 9
    ema_fast: int = 21
    ema_mid: int = 50
    ema_slow: int = 200
    vwap_days: int = 7
    pullback_bars: int = 3
    pullback_tol: float = 0.002
    vol_len: int = 20
    atr_len: int = 14
    swing_bars: int = 5
    swing_atr_buf: float = 0.25
    min_stop_atr: float = 1.0
    exit_atr_buf: float = 0.5
    regime_symbol: str = "BTC-USDT"
    regime_ema: int = 50
    # [risk]
    equity_usdt: float = 1000.0
    risk_pct: float = 1.0
    max_position_pct: float = 12.5
    max_positions: int = 8
    cost_pct: float = 0.15
    # [runtime]
    state_file: str = "state/portfolio.json"
    signal_log: str = "state/signals.csv"
    run_delay_s: int = 90
    timezone: str = "Europe/Amsterdam"
    # [notify]
    notify_summary: bool = False
    telegram_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook: str = ""


ENV_VARS = {
    "telegram_token": "TELEGRAM_BOT_TOKEN",
    "telegram_chat_id": "TELEGRAM_CHAT_ID",
    "discord_webhook": "DISCORD_WEBHOOK_URL",
}


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env reader (KEY=VALUE per line); existing environment variables win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_settings(path: str | Path | None = "config.toml", env_file: str | Path = ".env") -> Settings:
    s = Settings()
    if path is not None and Path(path).is_file():
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
        flat: dict = {}
        for key, value in data.items():
            flat.update(value) if isinstance(value, dict) else flat.__setitem__(key, value)
        types = {f.name: f.type for f in fields(Settings)}
        unknown = sorted(set(flat) - set(types))
        if unknown:
            raise ValueError(f"Onbekende instelling(en) in {path}: {', '.join(unknown)}")
        for key, value in flat.items():
            if types[key] == "float" and isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            setattr(s, key, value)
    load_dotenv(env_file)
    for attr, var in ENV_VARS.items():
        if os.environ.get(var):
            setattr(s, attr, os.environ[var])
    validate(s)
    return s


def validate(s: Settings) -> None:
    problems = []
    if not 0 < s.risk_pct <= 5:
        problems.append("risk_pct moet tussen 0 en 5 liggen")
    if not 0 < s.max_position_pct <= 100:
        problems.append("max_position_pct moet tussen 0 en 100 liggen")
    if s.max_positions < 1:
        problems.append("max_positions moet minstens 1 zijn")
    if s.equity_usdt <= 0:
        problems.append("equity_usdt moet positief zijn")
    if not s.ema_fast < s.ema_mid < s.ema_slow:
        problems.append("ema_fast < ema_mid < ema_slow is vereist")
    if s.min_history_days * BARS_PER_DAY < s.ema_slow:
        problems.append("min_history_days is te kort voor ema_slow")
    if problems:
        raise ValueError("Ongeldige configuratie: " + "; ".join(problems))
