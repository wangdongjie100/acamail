"""Telegram message formatter — pretty-prints emails and summaries."""

from __future__ import annotations

from gmail.models import ClassificationResult, Email, ReplyOptions


def format_push_summary(
    actionable: list[tuple[Email, ClassificationResult]],
    non_actionable_count: int,
) -> str:
    """Format the scheduled push summary message."""
    if not actionable:
        return ""

    lines = [f"📬 <b>你有 {len(actionable)} 封邮件需要处理</b>"]
    if non_actionable_count > 0:
        lines.append(f"📭 另有 {non_actionable_count} 封通知类邮件已忽略\n")
    else:
        lines.append("")

    for i, (email, clf) in enumerate(actionable, 1):
        priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
            clf.priority, "⚪"
        )
        lines.append(
            f"{i}️⃣ {priority_icon} <b>{_escape(email.subject)}</b>"
        )
        lines.append(f"   👤 {_escape(email.short_sender)}")
        lines.append(f"   📝 {_escape(clf.summary)}")
        lines.append("")

    return "\n".join(lines)


def format_check_summary(
    actionable: list[tuple[Email, ClassificationResult]],
    non_actionable: list[tuple[Email, ClassificationResult]],
    since_label: str,
) -> str:
    """Format the /check command summary message."""
    total = len(actionable) + len(non_actionable)

    lines = [
        f"📊 <b>邮件摘要</b> ({_escape(since_label)} 至今)",
        f"共 {total} 封新邮件\n",
    ]

    if actionable:
        lines.append(f"━━ 🔔 需要处理 ({len(actionable)} 封) ━━")
        for i, (email, clf) in enumerate(actionable, 1):
            priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                clf.priority, "⚪"
            )
            lines.append(f"{i}. {priority_icon} <b>{_escape(email.subject)}</b>")
            lines.append(f"   👤 {_escape(email.short_sender)} | 📝 {_escape(clf.summary)}")
        lines.append("")

    if non_actionable:
        lines.append(f"━━ 📭 无需处理 ({len(non_actionable)} 封) ━━")
        for email, clf in non_actionable:
            lines.append(f"• {_escape(email.subject)} — {_escape(clf.summary)}")
        lines.append("")

    if not actionable and not non_actionable:
        lines.append("✅ 没有新邮件！")

    return "\n".join(lines)


def format_email_detail(email: Email, clf: ClassificationResult) -> str:
    """Format a single email for detailed view."""
    import pytz
    from config import Config
    
    priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
        clf.priority, "⚪"
    )

    # Use detailed summary with original quotes if available, otherwise fallback
    detail = clf.detail_summary or clf.summary

    # Convert date to local timezone
    local_tz = pytz.timezone(Config.TIMEZONE)
    local_date = email.date.astimezone(local_tz) if email.date.tzinfo else email.date

    lines = [
        f"📧 <b>邮件详情</b>",
        f"━━━━━━━━━━━━━━━━━━",
        f"📌 <b>主题</b>: {_escape(email.subject)}",
        f"👤 <b>发件人</b>: {_escape(email.short_sender)} &lt;{_escape(email.reply_to_email)}&gt;",
        f"📅 <b>时间</b>: {local_date.strftime('%Y-%m-%d %H:%M')}",
        f"{priority_icon} <b>优先级</b>: {clf.priority} | 📂 {clf.category}",
    ]

    if email.is_forwarded:
        lines.append(f"↪️ <b>转发自</b>: {_escape(email.sender_email)}")

    lines += [
        f"━━━━━━━━━━━━━━━━━━",
        f"",
        f"📝 <b>AI 摘要</b>",
        f"{_escape(detail)}",
        f"",
        f"💡 <b>AI 判断</b>: {_escape(clf.reason)}",
    ]

    # Add original email body (truncated)
    body = email.body_text or email.snippet or ""
    if body:
        body_preview = body.strip()[:800]
        if len(body.strip()) > 800:
            body_preview += "..."
        lines += [
            f"",
            f"━━━━━━━━━━━━━━━━━━",
            f"📄 <b>邮件原文</b>",
            f"<pre>{_escape(body_preview)}</pre>",
        ]

    return "\n".join(lines)


def format_reply_preview(reply_text: str, reply_type: str) -> str:
    """Format a reply preview for user confirmation."""
    type_label = {
        "positive": "🟢 正面回复",
        "negative": "🔴 负面回复",
        "neutral": "⚪ 中性回复",
    }.get(reply_type, "✏️ 回复")

    cleaned = _clean_reply(reply_text)

    return (
        f"✏️ <b>{type_label} 预览</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{_escape(cleaned)}\n\n"
        f"━━━━━━━━━━━━━━━━━━"
    )


def format_status(
    last_push: str,
    pending_count: int,
    total_processed: int,
) -> str:
    """Format /status command response."""
    return (
        f"📊 <b>系统状态</b>\n\n"
        f"⏰ 上次推送: {_escape(last_push)}\n"
        f"📬 待处理邮件: {pending_count} 封\n"
        f"📈 已处理总计: {total_processed} 封"
    )


def _escape(text: str) -> str:
    """Escape HTML special characters for Telegram HTML parse mode."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _clean_reply(text: str) -> str:
    """Clean up AI-generated reply text for display.
    
    - Converts <br>, <br/>, <br /> tags to newlines
    - Normalizes excessive blank lines
    - Strips leading/trailing whitespace
    """
    import re
    # Convert <br> variants to newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Remove any other HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Normalize: collapse 3+ newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_daily_digest(digest: dict, date_label: str) -> str:
    """Format the daily email digest for scheduled push.
    
    digest keys: total, replied_count, skipped_count, pending_count,
                 non_actionable_count, replied_list, skipped_list, pending_list
    """
    total = digest["total"]
    replied_count = digest["replied_count"]
    skipped_count = digest["skipped_count"]
    pending_count = digest["pending_count"]
    non_actionable_count = digest["non_actionable_count"]
    processed_count = replied_count + skipped_count

    lines = [
        f"📊 <b>邮件日报</b> ({_escape(date_label)})",
        f"━━━━━━━━━━━━━━━━━━",
        f"📬 今日共收到 <b>{total}</b> 封邮件",
        f"✅ 已处理: <b>{processed_count}</b> 封（回复 {replied_count} / 跳过 {skipped_count}）",
        f"⏳ 待处理: <b>{pending_count}</b> 封",
        f"📭 无需处理: {non_actionable_count} 封",
        f"",
    ]

    # Processed emails (replied)
    replied_list = digest.get("replied_list", [])
    if replied_list:
        lines.append(f"━━ ✅ 已回复 ({len(replied_list)} 封) ━━")
        for row in replied_list:
            subject = row.get("subject", "")
            sender = row.get("sender", "") or row.get("sender_email", "")
            summary = row.get("summary", "")
            reply_snippet = (row.get("reply_content", "") or "")[:80]
            lines.append(f"• <b>{_escape(subject)}</b>")
            lines.append(f"  👤 {_escape(sender)}")
            lines.append(f"  📝 {_escape(summary)}")
            if reply_snippet:
                lines.append(f"  💬 回复: {_escape(reply_snippet)}...")
            lines.append("")

    # Processed emails (skipped)
    skipped_list = digest.get("skipped_list", [])
    if skipped_list:
        lines.append(f"━━ ⏭️ 已跳过 ({len(skipped_list)} 封) ━━")
        for row in skipped_list:
            subject = row.get("subject", "")
            summary = row.get("summary", "")
            lines.append(f"• <b>{_escape(subject)}</b> — {_escape(summary)}")
        lines.append("")

    # Pending emails
    pending_list = digest.get("pending_list", [])
    if pending_list:
        lines.append(f"━━ ⏳ 待处理 ({len(pending_list)} 封) ━━")
        for row in pending_list:
            subject = row.get("subject", "")
            sender = row.get("sender", "") or row.get("sender_email", "")
            summary = row.get("summary", "")
            reason = row.get("reason", "")
            priority = row.get("priority", "low")
            priority_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(priority, "⚪")
            lines.append(f"• {priority_icon} <b>{_escape(subject)}</b>")
            lines.append(f"  👤 {_escape(sender)}")
            lines.append(f"  📝 {_escape(summary)}")
            if reason:
                lines.append(f"  💡 {_escape(reason)}")
            lines.append("")

    # Non-actionable emails
    non_actionable_list = digest.get("non_actionable_list", [])
    if non_actionable_list:
        lines.append(f"━━ 📭 无需处理 ({len(non_actionable_list)} 封) ━━")
        for row in non_actionable_list:
            subject = row.get("subject", "")
            sender = row.get("sender", "") or row.get("sender_email", "")
            summary = row.get("summary", "")
            lines.append(f"• <b>{_escape(subject)}</b>")
            lines.append(f"  👤 {_escape(sender)} — {_escape(summary)}")
        lines.append("")

    if total == 0:
        lines.append("📭 今日暂无邮件。")

    return "\n".join(lines)

