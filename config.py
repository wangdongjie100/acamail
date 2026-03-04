"""Configuration management for Gmail + Telegram Bot."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env — try multiple locations for macOS compatibility
_project_root = Path(__file__).parent
_env_candidates = [
    _project_root / ".env",
    Path.home() / "Downloads" / "gmail_bot.env",
]
for _env_path in _env_candidates:
    try:
        if _env_path.exists():
            load_dotenv(_env_path, override=True)
            break
    except PermissionError:
        continue


class Config:
    """Centralized configuration."""

    # ── Telegram ──────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: int = int(os.getenv("TELEGRAM_CHAT_ID", "0"))

    # ── Google OAuth2 ─────────────────────────────────────────
    GOOGLE_CREDENTIALS_FILE: str = os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")
    GOOGLE_TOKEN_FILE: str = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    GMAIL_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ]

    # ── Gemini AI ─────────────────────────────────────────────
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    # ── Schedule ──────────────────────────────────────────────
    TIMEZONE: str = os.getenv("TIMEZONE", "America/Chicago")
    PUSH_HOURS: list[int] = [
        int(h.strip()) for h in os.getenv("PUSH_HOURS", "12,21").split(",")
    ]

    # ── User ──────────────────────────────────────────────────
    USER_EMAIL: str = os.getenv("USER_EMAIL", "")

    # ── Database ──────────────────────────────────────────────
    DB_PATH: str = os.getenv("DB_PATH", str(Path.home() / "Downloads" / "gmail_bot.db"))

    # ── Validation ────────────────────────────────────────────
    @classmethod
    def validate(cls) -> list[str]:
        """Return list of missing required config items."""
        errors = []
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN is not set")
        if not cls.TELEGRAM_CHAT_ID:
            errors.append("TELEGRAM_CHAT_ID is not set")
        if not cls.GEMINI_API_KEY:
            errors.append("GEMINI_API_KEY is not set")
        if not cls.USER_EMAIL:
            errors.append("USER_EMAIL is not set")

        creds_cfg = Path(cls.GOOGLE_CREDENTIALS_FILE)
        creds_path = creds_cfg if creds_cfg.is_absolute() else _project_root / creds_cfg
        try:
            if not creds_path.exists():
                errors.append(f"Google credentials file not found: {creds_path}")
        except PermissionError:
            errors.append(f"Cannot access credentials file (permission denied): {creds_path}")

        return errors
