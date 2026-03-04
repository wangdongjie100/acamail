"""Telegram Bot command and callback handlers."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytz

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from ai.classifier import EmailClassifier
from ai.reply_generator import ReplyGenerator
from bot.formatter import (
    format_check_summary,
    format_daily_digest,
    format_email_detail,
    format_push_summary,
    format_reply_preview,
    format_status,
)
from bot.keyboards import (
    PREFIX_BACK,
    PREFIX_CONFIRM,
    PREFIX_CUSTOM,
    PREFIX_GEN_NEG,
    PREFIX_GEN_NEU,
    PREFIX_GEN_POS,
    PREFIX_REGEN,
    PREFIX_SEND,
    PREFIX_SEND_ALL,
    PREFIX_SKIP,
    PREFIX_SWITCH,
    PREFIX_VIEW,
    confirm_send_keyboard,
    email_detail_keyboard,
    email_list_keyboard,
    reply_preview_keyboard,
)
from config import Config
from gmail.client import GmailClient
from gmail.models import ClassificationResult, Email, ReplyOptions
from storage.database import Database

logger = logging.getLogger(__name__)

# Conversation states for custom instructions
WAITING_CUSTOM_INSTRUCTIONS = 1


class BotHandlers:
    """Manages all Telegram bot interactions."""

    def __init__(
        self,
        gmail_client: GmailClient,
        classifier: EmailClassifier,
        reply_generator: ReplyGenerator,
        db: Database,
    ) -> None:
        self.gmail = gmail_client
        self.classifier = classifier
        self.reply_gen = reply_generator
        self.db = db

        # In-memory cache for current session
        # Maps email_id -> Email
        self._email_cache: dict[str, Email] = {}
        # Maps email_id -> ClassificationResult
        self._clf_cache: dict[str, ClassificationResult] = {}
        # Maps email_id -> ReplyOptions
        self._reply_cache: dict[str, ReplyOptions] = {}
        # Currently active email list (for push summary)
        self._active_email_ids: list[str] = []
        # Local timezone for display
        self._local_tz = pytz.timezone(Config.TIMEZONE)

    # Telegram message length limit
    MAX_MSG_LEN = 4000  # Leave some margin under the 4096 limit

    def _is_authorized(self, update: Update) -> bool:
        """Only respond to the configured user."""
        user_id = update.effective_chat.id if update.effective_chat else 0
        return user_id == Config.TELEGRAM_CHAT_ID

    def _to_local(self, dt: datetime) -> datetime:
        """Convert a UTC datetime to the user's local timezone."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(self._local_tz)

    @staticmethod
    def _split_message(text: str, max_len: int = 4000) -> list[str]:
        """Split a long message into parts that fit Telegram's limit."""
        if len(text) <= max_len:
            return [text]

        parts = []
        while text:
            if len(text) <= max_len:
                parts.append(text)
                break
            # Try to split at a newline
            split_pos = text.rfind("\n", 0, max_len)
            if split_pos == -1:
                split_pos = max_len
            parts.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        return parts

    # ──────────────────────────────────────────────────────────
    # Command Handlers
    # ──────────────────────────────────────────────────────────

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command."""
        if not self._is_authorized(update):
            return

        welcome = (
            "👋 <b>欢迎使用 Gmail 智能助手!</b>\n\n"
            "我可以帮你处理邮件：\n"
            "📬 每天 12:00 和 18:00 自动推送需要回复的邮件\n"
            "🤖 AI 生成正面/负面/中性回复草稿\n"
            "✍️ 你可以添加修改意见重新生成\n"
            "📨 确认后一键发送回复\n\n"
            "<b>可用命令：</b>\n"
            "/check — 立刻查收新邮件\n"
            "/status — 查看系统状态\n"
            "/help — 使用帮助"
        )
        await update.message.reply_text(welcome, parse_mode=ParseMode.HTML)

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not self._is_authorized(update):
            return

        help_text = (
            "📖 <b>使用帮助</b>\n\n"
            "<b>命令列表</b>\n"
            "/check — 📬 检查新邮件并分类\n"
            "/digest — 📋 查看今日邮件处理记录\n"
            "/status — 📊 查看系统状态\n"
            "/help — 📖 使用帮助\n\n"
            "<b>自动推送</b>\n"
            "• 每天 12:00 和 21:00 自动推送邮件日报\n"
            "• 包含今日邮件总数、已处理、待处理统计\n\n"
            "<b>回复邮件</b>\n"
            "1. 点击 [查看] 查看邮件详情\n"
            "2. 选择 [正面/负面/中性回复] 生成草稿\n"
            "3. 不满意可以 [切换类型] 或 [重新生成]\n"
            "4. 点击 [✍️ 添加修改意见] 输入你的要求后重新生成\n"
            "5. 满意后点击 [发送(Reply)] 或 [发送(Reply All)]\n"
        )
        await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

    async def cmd_digest(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /digest — show today's email processing record."""
        if not self._is_authorized(update):
            return

        today_local = self._to_local(datetime.now(timezone.utc))
        today_str = today_local.strftime("%Y-%m-%d")
        date_label = today_local.strftime("%m月%d日 %A")

        digest = self.db.get_daily_digest(today_str)
        text = format_daily_digest(digest, date_label)

        # If there are pending emails, add actionable buttons
        pending_ids = [row["email_id"] for row in digest.get("pending_list", [])]
        if pending_ids:
            for eid in pending_ids:
                if eid not in self._email_cache:
                    try:
                        email = self.gmail.get_email_detail(eid)
                        self._email_cache[eid] = email
                    except Exception:
                        pass
            self._active_email_ids = pending_ids
            keyboard = email_list_keyboard(pending_ids)

            parts = self._split_message(text)
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    await update.message.reply_text(
                        part, parse_mode=ParseMode.HTML, reply_markup=keyboard
                    )
                else:
                    await update.message.reply_text(part, parse_mode=ParseMode.HTML)
        else:
            parts = self._split_message(text)
            for part in parts:
                await update.message.reply_text(part, parse_mode=ParseMode.HTML)

    async def cmd_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /check — manually pull and summarize new emails."""
        if not self._is_authorized(update):
            return

        await update.message.reply_text("🔍 正在检查新邮件...")

        last_push = self.db.get_last_push_time()
        if last_push is None:
            since = datetime.now(timezone.utc) - timedelta(hours=2)
            since_label = "过去2小时"
        else:
            since = last_push
            since_label = self._to_local(last_push).strftime("%m-%d %H:%M")

        try:
            actionable, non_actionable = self._fetch_and_classify(since)
        except Exception:
            logger.exception("Failed to fetch and classify emails")
            await update.message.reply_text("⚠️ 获取邮件时出错，请稍后重试。")
            return

        if not actionable and not non_actionable:
            # No new emails — check for pending (unprocessed) emails in DB
            pending = self.db.get_pending_emails()
            if pending:
                await update.message.reply_text(
                    f"✅ 没有新增邮件，但有 {len(pending)} 封待处理邮件，正在加载..."
                )
                # Re-fetch pending emails from Gmail and rebuild cache
                for row in pending:
                    eid = row["email_id"]
                    try:
                        email = self.gmail.get_email_detail(eid)
                        clf = ClassificationResult(
                            email_id=eid,
                            needs_reply=True,
                            priority=row.get("priority", "medium"),
                            category=row.get("category", "other"),
                            summary=row.get("summary", ""),
                            reason=row.get("reason", ""),
                        )
                        self._email_cache[eid] = email
                        self._clf_cache[eid] = clf
                        actionable.append((email, clf))
                    except Exception:
                        logger.warning("Failed to re-fetch pending email %s", eid)
                
                if not actionable:
                    await update.message.reply_text("✅ 当前没有新增邮件。")
                    return
                    
                since_label = "待处理"
            else:
                await update.message.reply_text("✅ 当前没有新增邮件。")
                return

        text = format_check_summary(actionable, non_actionable, since_label)

        if actionable:
            self._active_email_ids = [e.id for e, _ in actionable]
            keyboard = email_list_keyboard(self._active_email_ids)

            parts = self._split_message(text)
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    await update.message.reply_text(
                        part, parse_mode=ParseMode.HTML, reply_markup=keyboard
                    )
                else:
                    await update.message.reply_text(part, parse_mode=ParseMode.HTML)
        else:
            parts = self._split_message(text)
            for part in parts:
                await update.message.reply_text(part, parse_mode=ParseMode.HTML)

        # Record this check as a push
        self.db.record_push(
            push_time=datetime.now(timezone.utc),
            email_count=len(actionable) + len(non_actionable),
            actionable_count=len(actionable),
        )

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command."""
        if not self._is_authorized(update):
            return

        last_push = self.db.get_last_push_time()
        last_push_str = last_push.strftime("%Y-%m-%d %H:%M") if last_push else "从未"
        pending = self.db.get_pending_emails()
        pending_count = len(pending)

        # Count total processed
        conn = self.db._connect()
        try:
            row = conn.execute("SELECT COUNT(*) as c FROM email_status").fetchone()
            total = row["c"] if row else 0
        finally:
            conn.close()

        text = format_status(last_push_str, pending_count, total)
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

    # ──────────────────────────────────────────────────────────
    # Callback Query Handlers
    # ──────────────────────────────────────────────────────────

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
        """Route callback queries based on prefix."""
        query = update.callback_query
        await query.answer()

        if not self._is_authorized(update):
            return None

        data = query.data or ""
        parts = data.split(":")

        if len(parts) < 2:
            return None

        prefix = parts[0]
        email_id = parts[1]

        try:
            if prefix == PREFIX_VIEW:
                await self._handle_view(query, email_id)
            elif prefix in (PREFIX_GEN_POS, PREFIX_GEN_NEG, PREFIX_GEN_NEU):
                reply_type = {"gen_pos": "positive", "gen_neg": "negative", "gen_neu": "neutral"}[prefix]
                await self._handle_generate(query, email_id, reply_type)
            elif prefix == PREFIX_SWITCH:
                reply_type = parts[2] if len(parts) > 2 else "positive"
                await self._handle_switch(query, email_id, reply_type)
            elif prefix == PREFIX_CONFIRM:
                reply_type = parts[2] if len(parts) > 2 else "positive"
                await self._handle_confirm(query, email_id, reply_type)
            elif prefix == PREFIX_SEND:
                reply_type = parts[2] if len(parts) > 2 else "positive"
                await self._handle_send(query, email_id, reply_type, reply_all=False)
            elif prefix == PREFIX_SEND_ALL:
                reply_type = parts[2] if len(parts) > 2 else "positive"
                await self._handle_send(query, email_id, reply_type, reply_all=True)
            elif prefix == PREFIX_REGEN:
                await self._handle_regenerate(query, email_id)
            elif prefix == PREFIX_CUSTOM:
                await self._handle_custom_prompt(query, email_id, context)
                return WAITING_CUSTOM_INSTRUCTIONS
            elif prefix == PREFIX_SKIP:
                await self._handle_skip(query, email_id)
            elif prefix == PREFIX_BACK:
                await self._handle_back(query)
        except Exception:
            logger.exception("Error handling callback: %s", data)
            await query.edit_message_text("⚠️ 处理时出错，请重试。")

        return None

    async def _handle_view(self, query, email_id: str) -> None:
        """Show email detail."""
        if email_id == "all":
            # Re-show the summary with back/list keyboard
            if self._active_email_ids:
                text_parts = []
                for eid in self._active_email_ids:
                    if eid in self._clf_cache:
                        clf = self._clf_cache[eid]
                        text_parts.append(f"• <b>{clf.summary}</b>")
                keyboard = email_list_keyboard(self._active_email_ids)
                await query.edit_message_text(
                    "\n".join(text_parts) or "没有缓存的邮件",
                    parse_mode=ParseMode.HTML,
                    reply_markup=keyboard,
                )
            return

        email = self._get_cached_email(email_id)
        clf = self._clf_cache.get(email_id)

        if not email or not clf:
            await query.edit_message_text("⚠️ 邮件信息已过期，请重新 /check")
            return

        text = format_email_detail(email, clf)
        keyboard = email_detail_keyboard(email_id)
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )

    async def _handle_generate(self, query, email_id: str, reply_type: str) -> None:
        """Generate a reply of the specified type."""
        email = self._get_cached_email(email_id)
        if not email:
            await query.edit_message_text("⚠️ 邮件信息已过期，请重新 /check")
            return

        await query.edit_message_text("🤖 AI 正在生成回复...")

        # Generate if not cached
        if email_id not in self._reply_cache:
            options = self.reply_gen.generate_replies(email)
            self._reply_cache[email_id] = options
        else:
            options = self._reply_cache[email_id]

        reply_text = getattr(options, f"{reply_type}_reply", "")
        text = format_reply_preview(reply_text, reply_type)
        keyboard = reply_preview_keyboard(email_id, reply_type)

        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )

    async def _handle_switch(self, query, email_id: str, reply_type: str) -> None:
        """Switch to a different reply type."""
        options = self._reply_cache.get(email_id)
        if not options:
            await query.edit_message_text("⚠️ 回复已过期，请重新生成")
            return

        reply_text = getattr(options, f"{reply_type}_reply", "")
        text = format_reply_preview(reply_text, reply_type)
        keyboard = reply_preview_keyboard(email_id, reply_type)

        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )

    async def _handle_confirm(self, query, email_id: str, reply_type: str) -> None:
        """Show final confirmation before sending."""
        options = self._reply_cache.get(email_id)
        if not options:
            await query.edit_message_text("⚠️ 回复已过期，请重新生成")
            return

        reply_text = getattr(options, f"{reply_type}_reply", "")
        text = (
            f"⚠️ <b>确认发送以下回复？</b>\n\n"
            f"{format_reply_preview(reply_text, reply_type)}\n\n"
            f"⚠️ 发送后无法撤回！"
        )
        keyboard = confirm_send_keyboard(email_id, reply_type)

        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )

    async def _handle_send(self, query, email_id: str, reply_type: str, reply_all: bool = False) -> None:
        """Actually send the reply via Gmail."""
        email = self._get_cached_email(email_id)
        options = self._reply_cache.get(email_id)

        if not email or not options:
            await query.edit_message_text("⚠️ 信息已过期，请重新 /check")
            return

        reply_text = getattr(options, f"{reply_type}_reply", "")

        await query.edit_message_text("📨 正在发送回复...")

        try:
            if reply_all:
                self.gmail.send_reply_all(email, reply_text)
            else:
                self.gmail.send_reply(email, reply_text)
            self.db.mark_replied(email_id, reply_text)

            # Remove from active list
            if email_id in self._active_email_ids:
                self._active_email_ids.remove(email_id)
            self._email_cache.pop(email_id, None)
            self._clf_cache.pop(email_id, None)
            self._reply_cache.pop(email_id, None)

            sent_msg = (
                f"✅ <b>回复已发送！</b>\n\n"
                f"收件人: {email.reply_to_email}\n"
                f"主题: Re: {email.subject}"
            )

            # Show remaining emails if any
            if self._active_email_ids:
                remaining = len(self._active_email_ids)
                sent_msg += f"\n\n📬 还有 {remaining} 封邮件待处理 ⬇️"
                keyboard = email_list_keyboard(self._active_email_ids)
                await query.edit_message_text(
                    sent_msg, parse_mode=ParseMode.HTML, reply_markup=keyboard
                )
            else:
                sent_msg += "\n\n🎉 所有邮件已处理完毕！"
                await query.edit_message_text(sent_msg, parse_mode=ParseMode.HTML)

        except Exception as e:
            logger.exception("Failed to send reply for %s", email_id)
            await query.edit_message_text(
                f"❌ <b>发送失败</b>\n\n错误: {str(e)[:200]}",
                parse_mode=ParseMode.HTML,
            )

    async def _handle_regenerate(self, query, email_id: str) -> None:
        """Regenerate all reply options."""
        email = self._get_cached_email(email_id)
        if not email:
            await query.edit_message_text("⚠️ 邮件信息已过期，请重新 /check")
            return

        await query.edit_message_text("🔄 正在重新生成回复...")

        options = self.reply_gen.generate_replies(email)
        self._reply_cache[email_id] = options

        text = format_reply_preview(options.positive_reply, "positive")
        keyboard = reply_preview_keyboard(email_id, "positive")
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )

    async def _handle_custom_prompt(self, query, email_id: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Prompt user to enter custom instructions."""
        context.user_data["custom_email_id"] = email_id
        await query.edit_message_text(
            "✍️ 请输入你的修改意见或补充指令：\n\n"
            "例如：\n"
            "• <i>语气更礼貌一些</i>\n"
            "• <i>提到我下周有空</i>\n"
            "• <i>拒绝但是提议下个月再讨论</i>\n\n"
            "直接输入文字发送即可 👇",
            parse_mode=ParseMode.HTML,
        )

    async def handle_custom_instructions(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Handle the user's custom instruction text input."""
        if not self._is_authorized(update):
            return ConversationHandler.END

        email_id = context.user_data.get("custom_email_id", "")
        if not email_id:
            await update.message.reply_text("⚠️ 操作已过期，请重新 /check")
            return ConversationHandler.END

        user_instructions = update.message.text
        email = self._get_cached_email(email_id)
        if not email:
            await update.message.reply_text("⚠️ 邮件信息已过期，请重新 /check")
            return ConversationHandler.END

        await update.message.reply_text("🤖 正在根据你的指令重新生成回复...")

        # Use the previous reply as context
        previous_reply = ""
        if email_id in self._reply_cache:
            previous_reply = self._reply_cache[email_id].positive_reply

        options = self.reply_gen.regenerate_with_instructions(
            email, previous_reply, user_instructions
        )
        self._reply_cache[email_id] = options

        text = format_reply_preview(options.positive_reply, "positive")
        keyboard = reply_preview_keyboard(email_id, "positive")
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )

        return ConversationHandler.END

    async def _handle_skip(self, query, email_id: str) -> None:
        """Skip this email without replying."""
        self.db.mark_skipped(email_id)
        if email_id in self._active_email_ids:
            self._active_email_ids.remove(email_id)
        self._email_cache.pop(email_id, None)
        self._clf_cache.pop(email_id, None)
        self._reply_cache.pop(email_id, None)

        # Show remaining emails if any
        if self._active_email_ids:
            remaining = len(self._active_email_ids)
            keyboard = email_list_keyboard(self._active_email_ids)
            await query.edit_message_text(
                f"⏭️ 已跳过。\n\n📬 还有 {remaining} 封邮件待处理 ⬇️",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        else:
            await query.edit_message_text("⏭️ 已跳过。\n\n🎉 所有邮件已处理完毕！")

    async def _handle_back(self, query) -> None:
        """Go back to the email list."""
        if not self._active_email_ids:
            await query.edit_message_text("📭 没有待处理的邮件。")
            return

        # Rebuild the summary
        actionable = []
        for eid in self._active_email_ids:
            email = self._email_cache.get(eid)
            clf = self._clf_cache.get(eid)
            if email and clf:
                actionable.append((email, clf))

        if not actionable:
            await query.edit_message_text("📭 所有邮件已处理完毕!")
            return

        text = format_push_summary(actionable, 0)
        keyboard = email_list_keyboard([e.id for e, _ in actionable])
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=keyboard
        )

    # ──────────────────────────────────────────────────────────
    # Push (called by scheduler)
    # ──────────────────────────────────────────────────────────

    async def push_emails(self, application: Application) -> None:
        """Scheduled job: daily digest — fetch new emails, then send summary."""
        # Step 1: Fetch and classify any new emails since last push
        last_push = self.db.get_last_push_time()
        if last_push is None:
            since = datetime.now(timezone.utc) - timedelta(hours=12)
        else:
            since = last_push

        try:
            actionable, non_actionable = self._fetch_and_classify(since)
        except Exception:
            logger.exception("Scheduled push: fetch failed")
            # Continue to still show digest from DB
            actionable, non_actionable = [], []

        # Step 2: Build daily digest from DB
        today_local = self._to_local(datetime.now(timezone.utc))
        today_str = today_local.strftime("%Y-%m-%d")
        date_label = today_local.strftime("%m月%d日 %A")

        digest = self.db.get_daily_digest(today_str)
        text = format_daily_digest(digest, date_label)

        # Step 3: Collect pending emails for actionable buttons
        pending_ids = [row["email_id"] for row in digest.get("pending_list", [])]
        for eid in pending_ids:
            if eid not in self._email_cache:
                try:
                    email = self.gmail.get_email_detail(eid)
                    self._email_cache[eid] = email
                except Exception:
                    logger.warning("Failed to fetch pending email %s for push", eid)

        # Step 4: Send message
        if pending_ids:
            self._active_email_ids = pending_ids
            keyboard = email_list_keyboard(pending_ids)

            parts = self._split_message(text)
            for i, part in enumerate(parts):
                if i == len(parts) - 1:
                    await application.bot.send_message(
                        chat_id=Config.TELEGRAM_CHAT_ID,
                        text=part,
                        parse_mode=ParseMode.HTML,
                        reply_markup=keyboard,
                    )
                else:
                    await application.bot.send_message(
                        chat_id=Config.TELEGRAM_CHAT_ID,
                        text=part,
                        parse_mode=ParseMode.HTML,
                    )
        else:
            parts = self._split_message(text)
            for part in parts:
                await application.bot.send_message(
                    chat_id=Config.TELEGRAM_CHAT_ID,
                    text=part,
                    parse_mode=ParseMode.HTML,
                )

        self.db.record_push(
            push_time=datetime.now(timezone.utc),
            email_count=digest["total"],
            actionable_count=digest["pending_count"],
        )
        logger.info(
            "Daily digest pushed: %d total, %d pending, %d replied",
            digest["total"], digest["pending_count"], digest["replied_count"],
        )

    # ──────────────────────────────────────────────────────────
    # Shared Logic
    # ──────────────────────────────────────────────────────────

    def _fetch_and_classify(
        self, since: datetime
    ) -> tuple[
        list[tuple[Email, ClassificationResult]],
        list[tuple[Email, ClassificationResult]],
    ]:
        """Fetch emails since a time, batch-classify them, and split into actionable vs. not.

        Uses batch classification for token efficiency.
        Also filters out emails where the user already replied in the thread.
        """
        emails = self.gmail.get_emails_since(since)
        logger.info("Fetched %d emails since %s", len(emails), since)

        # Pre-filter: skip already processed and self-sent emails
        to_classify: list[Email] = []
        for email in emails:
            if self.db.is_email_processed(email.id):
                continue
            if Config.USER_EMAIL.lower() in email.sender_email.lower():
                continue
            to_classify.append(email)

        if not to_classify:
            return [], []

        # Batch classify for token efficiency
        results = self.classifier.classify_batch(to_classify)

        actionable: list[tuple[Email, ClassificationResult]] = []
        non_actionable: list[tuple[Email, ClassificationResult]] = []

        for email, clf in zip(to_classify, results):
            # If classified as needs_reply, double-check thread hasn't been replied to
            if clf.needs_reply:
                try:
                    already_replied = self.gmail.check_thread_has_my_reply(email.thread_id)
                    if already_replied:
                        clf.needs_reply = False
                        clf.reason = "你已经在该会话中回复过了"
                except Exception:
                    logger.warning("Failed to check thread %s for existing reply", email.thread_id)

            # Cache for the session
            self._email_cache[email.id] = email
            self._clf_cache[email.id] = clf

            # Store in DB
            self.db.upsert_email_status(
                email_id=email.id,
                thread_id=email.thread_id,
                subject=email.subject,
                sender=email.sender,
                sender_email=email.sender_email,
                received_at=email.date,
                needs_reply=clf.needs_reply,
                priority=clf.priority,
                category=clf.category,
                summary=clf.summary,
                reason=clf.reason,
            )

            if clf.needs_reply:
                actionable.append((email, clf))
            else:
                non_actionable.append((email, clf))

        # Sort actionable by priority
        priority_order = {"high": 0, "medium": 1, "low": 2}
        actionable.sort(key=lambda x: priority_order.get(x[1].priority, 3))

        return actionable, non_actionable

    def _get_cached_email(self, email_id: str) -> Email | None:
        """Get email from cache or try to fetch from Gmail."""
        if email_id in self._email_cache:
            return self._email_cache[email_id]

        try:
            email = self.gmail.get_email_detail(email_id)
            self._email_cache[email_id] = email
            return email
        except Exception:
            logger.warning("Could not fetch email %s", email_id)
            return None

    # ──────────────────────────────────────────────────────────
    # Registration
    # ──────────────────────────────────────────────────────────

    def register(self, application: Application) -> None:
        """Register all handlers with the Telegram Application."""
        # Conversation handler for custom instructions
        conv_handler = ConversationHandler(
            entry_points=[
                CallbackQueryHandler(self.handle_callback),
            ],
            states={
                WAITING_CUSTOM_INSTRUCTIONS: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        self.handle_custom_instructions,
                    ),
                ],
            },
            fallbacks=[
                CommandHandler("check", self.cmd_check),
                CommandHandler("digest", self.cmd_digest),
                CommandHandler("start", self.cmd_start),
                CommandHandler("help", self.cmd_help),
                CommandHandler("status", self.cmd_status),
            ],
            per_message=False,
        )

        application.add_handler(CommandHandler("start", self.cmd_start))
        application.add_handler(CommandHandler("help", self.cmd_help))
        application.add_handler(CommandHandler("check", self.cmd_check))
        application.add_handler(CommandHandler("digest", self.cmd_digest))
        application.add_handler(CommandHandler("status", self.cmd_status))
        application.add_handler(conv_handler)
