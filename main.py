"""Gmail + Telegram Intelligent Email Assistant — Entry Point.

Supports two modes:
  - WEBHOOK mode (Cloud Run): set WEBHOOK_URL in .env → min-instances=0, ~$0/month
  - POLLING mode (local dev): leave WEBHOOK_URL empty → long-polling
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys

from telegram import Bot, Update, BotCommand
from telegram.ext import ApplicationBuilder

from ai.classifier import EmailClassifier
from ai.reply_generator import ReplyGenerator
from bot.handlers import BotHandlers
from config import Config
from gmail.client import GmailClient
from storage.database import Database

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _build_components():
    """Initialize and return all application components."""
    errors = Config.validate()
    if errors:
        logger.error("Configuration errors:")
        for e in errors:
            logger.error("  ✗ %s", e)
        logger.error("Please fix your .env file (see .env.example)")
        sys.exit(1)

    logger.info("Configuration validated ✓")
    logger.info("  User email : %s", Config.USER_EMAIL)
    logger.info("  Timezone   : %s", Config.TIMEZONE)
    logger.info("  Push hours : %s", Config.PUSH_HOURS)
    logger.info("  AI model   : %s", Config.GEMINI_MODEL)

    db = Database()
    logger.info("  Database ✓")

    gmail_client = GmailClient()
    logger.info("  Gmail client ✓")

    classifier = EmailClassifier()
    logger.info("  AI classifier ✓")

    reply_generator = ReplyGenerator()
    logger.info("  Reply generator ✓")

    # Build Telegram application — no updater for webhook mode
    use_webhook = bool(Config.WEBHOOK_URL)
    builder = ApplicationBuilder().token(Config.TELEGRAM_BOT_TOKEN)
    if use_webhook:
        builder = builder.updater(None)
    application = builder.build()

    handlers = BotHandlers(gmail_client, classifier, reply_generator, db)
    handlers.register(application)
    logger.info("  Telegram bot handlers ✓")

    return application, handlers


async def _register_commands(bot: Bot) -> None:
    """Register bot commands in Telegram's command menu."""
    commands = [
        BotCommand("check", "📬 查收新邮件并分类"),
        BotCommand("compose", "✏️ 写新邮件"),
        BotCommand("digest", "📋 查看今日邮件处理记录"),
        BotCommand("status", "📊 查看系统状态"),
        BotCommand("help", "📖 使用帮助"),
        BotCommand("start", "👋 启动/重置"),
    ]
    await bot.set_my_commands(commands)
    logger.info("  Bot commands registered ✓")


# ══════════════════════════════════════════════════════════
# Webhook mode (Cloud Run)
# ══════════════════════════════════════════════════════════

def _run_webhook(application, handlers: BotHandlers) -> None:
    """Run in webhook mode with aiohttp — for Cloud Run deployment."""
    from aiohttp import web

    port = int(os.getenv("PORT", "8080"))
    webhook_url = f"{Config.WEBHOOK_URL.rstrip('/')}/webhook"

    async def telegram_webhook(request: web.Request) -> web.Response:
        """Handle incoming Telegram updates via webhook."""
        try:
            data = await request.json()
            update = Update.de_json(data, application.bot)
            await application.update_queue.put(update)
            return web.Response(status=200)
        except Exception:
            logger.exception("Error processing webhook update")
            return web.Response(status=500)

    async def trigger_digest(request: web.Request) -> web.Response:
        """Trigger daily digest — called by Cloud Scheduler."""
        secret = request.headers.get("X-Scheduler-Secret", "")
        if Config.CLOUD_SCHEDULER_SECRET and secret != Config.CLOUD_SCHEDULER_SECRET:
            logger.warning("Digest trigger rejected: invalid secret")
            return web.Response(status=403, text="Forbidden")

        logger.info("Digest trigger received from Cloud Scheduler")
        try:
            await handlers.push_emails(application)
            return web.Response(status=200, text="OK")
        except Exception:
            logger.exception("Digest trigger failed")
            return web.Response(status=500, text="Error")

    async def health(request: web.Request) -> web.Response:
        """Health check endpoint for Cloud Run."""
        return web.Response(status=200, text="OK")

    async def on_startup(app: web.Application) -> None:
        """Initialize the Telegram application and set webhook."""
        await application.initialize()
        await application.start()
        await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        await _register_commands(application.bot)
        logger.info("Webhook set to %s", webhook_url)

    async def on_shutdown(app: web.Application) -> None:
        """Clean up on shutdown."""
        await application.stop()
        await application.shutdown()

    # Build aiohttp app
    app = web.Application()
    app.router.add_post("/webhook", telegram_webhook)
    app.router.add_post("/trigger/digest", trigger_digest)
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    logger.info("=" * 50)
    logger.info("🚀 Starting in WEBHOOK mode")
    logger.info("   Port: %d", port)
    logger.info("   Webhook: %s", webhook_url)
    logger.info("=" * 50)

    web.run_app(app, host="0.0.0.0", port=port)


# ══════════════════════════════════════════════════════════
# Polling mode (local development)
# ══════════════════════════════════════════════════════════

def _run_polling(application, handlers: BotHandlers) -> None:
    """Run in polling mode — for local development."""
    import threading
    from http.server import HTTPServer, BaseHTTPRequestHandler

    port = int(os.getenv("PORT", "8080"))

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        def log_message(self, *args):
            pass

    health_server = HTTPServer(("", port), HealthHandler)
    threading.Thread(target=health_server.serve_forever, daemon=True).start()
    logger.info("Health check listening on port %d ✓", port)

    # Use APScheduler for scheduled pushes in polling mode
    try:
        from scheduler.jobs import EmailScheduler
        scheduler = EmailScheduler(handlers, application)

        async def post_init(app):
            await _register_commands(app.bot)
            scheduler.start()
            logger.info("  Scheduler started ✓")

        application.post_init = post_init
    except ImportError:
        logger.warning("APScheduler not available, scheduled pushes disabled")

        async def post_init(app):
            await _register_commands(app.bot)

        application.post_init = post_init

    logger.info("=" * 50)
    logger.info("🚀 Starting in POLLING mode (local dev)")
    logger.info("=" * 50)
    application.run_polling(drop_pending_updates=True)


# ══════════════════════════════════════════════════════════
# Entry point
# ══════════════════════════════════════════════════════════

def main() -> None:
    """Application entry point."""
    application, handlers = _build_components()

    if Config.WEBHOOK_URL:
        _run_webhook(application, handlers)
    else:
        _run_polling(application, handlers)


if __name__ == "__main__":
    main()
