"""SQLite storage for push logs and email status tracking."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pytz

from config import Config

logger = logging.getLogger(__name__)


def _now_local() -> datetime:
    """Return current time in the user's configured timezone."""
    tz = pytz.timezone(Config.TIMEZONE)
    return datetime.now(timezone.utc).astimezone(tz)


class Database:
    """Synchronous SQLite database for tracking push history and email states."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self._db_path = db_path or Config.DB_PATH
        # Ensure parent directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_tables(self) -> None:
        """Create tables if they don't exist."""
        conn = self._connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS push_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    push_time TEXT NOT NULL,
                    email_count INTEGER DEFAULT 0,
                    actionable_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS email_status (
                    email_id TEXT PRIMARY KEY,
                    thread_id TEXT,
                    subject TEXT,
                    sender TEXT,
                    sender_email TEXT,
                    received_at TEXT,
                    classified_at TEXT,
                    needs_reply INTEGER DEFAULT 0,
                    priority TEXT DEFAULT 'low',
                    category TEXT DEFAULT 'other',
                    summary TEXT,
                    reason TEXT,
                    status TEXT DEFAULT 'pending',
                    replied_at TEXT,
                    reply_content TEXT
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )
            conn.commit()
            logger.info("Database tables ensured at %s", self._db_path)
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────
    # Push Log
    # ──────────────────────────────────────────────────────────

    def record_push(
        self,
        push_time: datetime,
        email_count: int,
        actionable_count: int,
    ) -> None:
        """Record a push event."""
        conn = self._connect()
        try:
            # Store in local timezone for correct date grouping
            local_time = push_time.astimezone(pytz.timezone(Config.TIMEZONE))
            conn.execute(
                "INSERT INTO push_log (push_time, email_count, actionable_count) VALUES (?, ?, ?)",
                (local_time.isoformat(), email_count, actionable_count),
            )
            conn.commit()
        finally:
            conn.close()

    def get_last_push_time(self) -> Optional[datetime]:
        """Return the most recent push timestamp, or None if no pushes yet."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT push_time FROM push_log ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if row:
                return datetime.fromisoformat(row["push_time"])
            return None
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────
    # Email Status
    # ──────────────────────────────────────────────────────────

    def upsert_email_status(
        self,
        email_id: str,
        thread_id: str = "",
        subject: str = "",
        sender: str = "",
        sender_email: str = "",
        received_at: Optional[datetime] = None,
        needs_reply: bool = False,
        priority: str = "low",
        category: str = "other",
        summary: str = "",
        reason: str = "",
    ) -> None:
        """Insert or update email classification result."""
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO email_status 
                    (email_id, thread_id, subject, sender, sender_email,
                     received_at, classified_at, needs_reply, priority, category, summary, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email_id) DO UPDATE SET
                    classified_at = excluded.classified_at,
                    needs_reply = excluded.needs_reply,
                    priority = excluded.priority,
                    category = excluded.category,
                    summary = excluded.summary,
                    reason = excluded.reason
                """,
                (
                    email_id,
                    thread_id,
                    subject,
                    sender,
                    sender_email,
                    received_at.astimezone(pytz.timezone(Config.TIMEZONE)).isoformat() if received_at else _now_local().isoformat(),
                    _now_local().isoformat(),
                    int(needs_reply),
                    priority,
                    category,
                    summary,
                    reason,
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_replied(self, email_id: str, reply_content: str) -> None:
        """Mark an email as replied."""
        conn = self._connect()
        try:
            conn.execute(
                """
                UPDATE email_status 
                SET status = 'replied', replied_at = ?, reply_content = ?
                WHERE email_id = ?
                """,
                (datetime.utcnow().isoformat(), reply_content, email_id),
            )
            conn.commit()
        finally:
            conn.close()

    def mark_skipped(self, email_id: str) -> None:
        """Mark an email as skipped (user chose not to reply)."""
        conn = self._connect()
        try:
            conn.execute(
                "UPDATE email_status SET status = 'skipped' WHERE email_id = ?",
                (email_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def is_email_processed(self, email_id: str) -> bool:
        """Check if an email has already been classified."""
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT email_id FROM email_status WHERE email_id = ?",
                (email_id,),
            ).fetchone()
            return row is not None
        finally:
            conn.close()

    def get_pending_emails(self) -> list[dict]:
        """Get emails that still need user action."""
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT * FROM email_status 
                WHERE needs_reply = 1 AND status = 'pending'
                ORDER BY received_at DESC
                """
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_daily_digest(self, today_str: str) -> dict:
        """Get a daily email digest for the given date (YYYY-MM-DD).
        
        Returns dict with keys: total, replied, skipped, pending, 
        replied_list, skipped_list, pending_list.
        """
        conn = self._connect()
        try:
            # All emails received today
            all_rows = conn.execute(
                """
                SELECT * FROM email_status
                WHERE received_at LIKE ?
                ORDER BY received_at DESC
                """,
                (f"{today_str}%",),
            ).fetchall()

            replied = [dict(r) for r in all_rows if r["status"] == "replied"]
            skipped = [dict(r) for r in all_rows if r["status"] == "skipped"]
            pending = [dict(r) for r in all_rows if r["status"] == "pending" and r["needs_reply"]]
            non_actionable = [dict(r) for r in all_rows if r["status"] == "pending" and not r["needs_reply"]]

            return {
                "total": len(all_rows),
                "replied_count": len(replied),
                "skipped_count": len(skipped),
                "pending_count": len(pending),
                "non_actionable_count": len(non_actionable),
                "replied_list": replied,
                "skipped_list": skipped,
                "pending_list": pending,
                "non_actionable_list": non_actionable,
            }
        finally:
            conn.close()

    # ──────────────────────────────────────────────────────────
    # Settings
    # ──────────────────────────────────────────────────────────

    def get_setting(self, key: str, default: str = "") -> str:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default
        finally:
            conn.close()

    def set_setting(self, key: str, value: str) -> None:
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            conn.commit()
        finally:
            conn.close()
