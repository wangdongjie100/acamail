"""Inline keyboard definitions for Telegram Bot interactions."""

from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


# ──────────────────────────────────────────────────────────
# Callback data prefixes
# ──────────────────────────────────────────────────────────
# Format: "prefix:email_id[:extra]"

PREFIX_VIEW = "view"          # View email detail
PREFIX_GEN_POS = "gen_pos"    # Generate positive reply
PREFIX_GEN_NEG = "gen_neg"    # Generate negative reply
PREFIX_GEN_NEU = "gen_neu"    # Generate neutral reply
PREFIX_CUSTOM = "custom"      # Enter custom instructions
PREFIX_CONFIRM = "confirm"    # Confirm send
PREFIX_REGEN = "regen"        # Regenerate reply
PREFIX_SWITCH = "switch"      # Switch reply type
PREFIX_SKIP = "skip"          # Skip this email
PREFIX_BACK = "back"          # Back to list
PREFIX_SEND = "send"          # Final send (reply to sender only)
PREFIX_SEND_ALL = "sendall"   # Final send (reply all)


def email_list_keyboard(email_ids: list[str]) -> InlineKeyboardMarkup:
    """Keyboard shown under the push summary — one button per email."""
    buttons = []
    for i, eid in enumerate(email_ids, 1):
        buttons.append(
            [InlineKeyboardButton(f"📧 查看第 {i} 封", callback_data=f"{PREFIX_VIEW}:{eid}")]
        )

    # Add a "view all" button if multiple emails
    if len(email_ids) > 1:
        buttons.append(
            [InlineKeyboardButton("📊 查看全部摘要", callback_data=f"{PREFIX_VIEW}:all")]
        )

    return InlineKeyboardMarkup(buttons)


def email_detail_keyboard(email_id: str) -> InlineKeyboardMarkup:
    """Keyboard shown under email detail — generate replies or skip."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🟢 正面回复", callback_data=f"{PREFIX_GEN_POS}:{email_id}"),
                InlineKeyboardButton("🔴 负面回复", callback_data=f"{PREFIX_GEN_NEG}:{email_id}"),
            ],
            [
                InlineKeyboardButton("⚪ 中性回复", callback_data=f"{PREFIX_GEN_NEU}:{email_id}"),
                InlineKeyboardButton("✍️ 自定义指令", callback_data=f"{PREFIX_CUSTOM}:{email_id}"),
            ],
            [
                InlineKeyboardButton("⏭️ 跳过", callback_data=f"{PREFIX_SKIP}:{email_id}"),
                InlineKeyboardButton("⬅️ 返回列表", callback_data=f"{PREFIX_BACK}:list"),
            ],
        ]
    )


def reply_preview_keyboard(email_id: str, reply_type: str) -> InlineKeyboardMarkup:
    """Keyboard shown under reply preview — confirm, regenerate, switch, or cancel."""
    switch_options = []
    if reply_type != "positive":
        switch_options.append(
            InlineKeyboardButton("🟢 切换正面", callback_data=f"{PREFIX_SWITCH}:{email_id}:positive")
        )
    if reply_type != "negative":
        switch_options.append(
            InlineKeyboardButton("🔴 切换负面", callback_data=f"{PREFIX_SWITCH}:{email_id}:negative")
        )
    if reply_type != "neutral":
        switch_options.append(
            InlineKeyboardButton("⚪ 切换中性", callback_data=f"{PREFIX_SWITCH}:{email_id}:neutral")
        )

    buttons = [
        [
            InlineKeyboardButton("✅ 确认发送", callback_data=f"{PREFIX_CONFIRM}:{email_id}:{reply_type}"),
            InlineKeyboardButton("🔄 重新生成", callback_data=f"{PREFIX_REGEN}:{email_id}"),
        ],
        switch_options,
        [
            InlineKeyboardButton("✍️ 添加修改意见", callback_data=f"{PREFIX_CUSTOM}:{email_id}"),
            InlineKeyboardButton("❌ 取消", callback_data=f"{PREFIX_BACK}:list"),
        ],
    ]

    # Remove empty rows
    buttons = [row for row in buttons if row]

    return InlineKeyboardMarkup(buttons)


def confirm_send_keyboard(email_id: str, reply_type: str) -> InlineKeyboardMarkup:
    """Final confirmation before sending."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ 发送 (Reply)",
                    callback_data=f"{PREFIX_SEND}:{email_id}:{reply_type}",
                ),
                InlineKeyboardButton(
                    "✅ 发送 (Reply All)",
                    callback_data=f"{PREFIX_SEND_ALL}:{email_id}:{reply_type}",
                ),
            ],
            [
                InlineKeyboardButton(
                    "❌ 取消",
                    callback_data=f"{PREFIX_BACK}:list",
                ),
            ]
        ]
    )
