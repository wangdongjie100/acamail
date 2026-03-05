"""Gmail + Telegram Intelligent Email Assistant — Entry Point."""

from __future__ import annotations

import logging
import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram.ext import ApplicationBuilder

from ai.classifier import EmailClassifier
from ai.reply_generator import ReplyGenerator
from bot.handlers import BotHandlers
from config import Config
from gmail.client import GmailClient
from scheduler.jobs import EmailScheduler
from storage.database import Database

# ── Logging ───────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Application entry point."""

    # 0. Start health check server immediately (Cloud Run needs a listening port ASAP)
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

    # 1. Validate configuration
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

    # 2. Initialize components
    logger.info("Initializing components...")

    db = Database()
    logger.info("  Database ✓")

    gmail_client = GmailClient()
    logger.info("  Gmail client ✓")

    classifier = EmailClassifier()
    logger.info("  AI classifier ✓")

    reply_generator = ReplyGenerator()
    logger.info("  Reply generator ✓")

    # 3. Build Telegram application
    application = (
        ApplicationBuilder()
        .token(Config.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # 4. Set up bot handlers
    handlers = BotHandlers(gmail_client, classifier, reply_generator, db)
    handlers.register(application)
    logger.info("  Telegram bot handlers ✓")

    # 5. Set up scheduler
    scheduler = EmailScheduler(handlers, application)

    # Use post_init to start scheduler and register commands
    async def post_init(app):
        scheduler.start()
        logger.info("  Scheduler started ✓")
        # Register bot commands so they show up in Telegram's command menu
        from telegram import BotCommand
        commands = [
            BotCommand("check", "📬 查收新邮件并分类"),
            BotCommand("digest", "📋 查看今日邮件处理记录"),
            BotCommand("status", "📊 查看系统状态"),
            BotCommand("help", "📖 使用帮助"),
            BotCommand("start", "👋 启动/重置"),
        ]
        await app.bot.set_my_commands(commands)
        logger.info("  Bot commands registered ✓")

    application.post_init = post_init

    # 6. Run the bot (blocking)
    logger.info("=" * 50)
    logger.info("🚀 Gmail Assistant is running!")
    logger.info("=" * 50)
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
