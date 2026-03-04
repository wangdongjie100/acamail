"""Scheduled jobs for periodic email pushing."""

from __future__ import annotations

import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application

from bot.handlers import BotHandlers
from config import Config

logger = logging.getLogger(__name__)


class EmailScheduler:
    """Manages scheduled email digest pushes."""

    def __init__(self, handlers: BotHandlers, application: Application) -> None:
        self._handlers = handlers
        self._application = application
        tz = pytz.timezone(Config.TIMEZONE)
        self._scheduler = AsyncIOScheduler(timezone=tz)

    def start(self) -> None:
        """Register and start scheduled jobs."""
        tz = pytz.timezone(Config.TIMEZONE)

        for hour in Config.PUSH_HOURS:
            trigger = CronTrigger(hour=hour, minute=0, timezone=tz)
            self._scheduler.add_job(
                self._push_job,
                trigger=trigger,
                id=f"push_{hour}",
                name=f"Email push at {hour}:00",
                replace_existing=True,
            )
            logger.info("Scheduled email push at %02d:00 %s", hour, Config.TIMEZONE)

        self._scheduler.start()
        logger.info("Scheduler started with %d jobs", len(Config.PUSH_HOURS))

    async def _push_job(self) -> None:
        """Execute the push job — called by APScheduler."""
        logger.info("Running scheduled push at %s", datetime.now())
        try:
            await self._handlers.push_emails(self._application)
        except Exception:
            logger.exception("Scheduled push failed")

    def stop(self) -> None:
        """Gracefully shut down the scheduler."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
