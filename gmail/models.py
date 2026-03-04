"""Email data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Email:
    """Represents a single Gmail message."""

    id: str
    thread_id: str
    subject: str
    sender: str  # Display name
    sender_email: str
    recipients: list[str]
    date: datetime
    snippet: str  # Short preview text from Gmail
    body_text: str  # Plain-text body
    body_html: str  # HTML body (may be empty)
    is_unread: bool
    labels: list[str] = field(default_factory=list)
    in_reply_to: str = ""  # For threading replies
    message_id_header: str = ""  # RFC 2822 Message-ID
    references: str = ""  # For threading replies
    # For forwarded emails: the original sender
    original_sender: str = ""
    original_sender_email: str = ""

    @property
    def is_forwarded(self) -> bool:
        """Check if this email was forwarded."""
        return bool(self.original_sender_email)

    @property
    def reply_to_email(self) -> str:
        """The email address to reply to (original sender if forwarded)."""
        return self.original_sender_email if self.is_forwarded else self.sender_email

    @property
    def reply_to_name(self) -> str:
        """The name to reply to (original sender if forwarded)."""
        return self.original_sender if self.is_forwarded else self.sender

    @property
    def short_sender(self) -> str:
        """Return sender display name or email if name is empty."""
        if self.is_forwarded:
            name = self.original_sender or self.original_sender_email
            return f"{name} (via fwd)"
        return self.sender if self.sender else self.sender_email

    @property
    def preview(self) -> str:
        """Return a 100-char preview of the email body."""
        text = self.body_text or self.snippet
        return text[:100] + ("…" if len(text) > 100 else "")


@dataclass
class ClassificationResult:
    """Result of AI email classification."""

    email_id: str
    needs_reply: bool
    priority: str  # high / medium / low
    category: str  # question / request / notification / newsletter / auto-reply / other
    summary: str  # One-line summary in Chinese
    reason: str  # Why this needs / doesn't need a reply
    detail_summary: str = ""  # Detailed Chinese summary with key original quotes


@dataclass
class ReplyOptions:
    """Generated reply drafts for an email."""

    email_id: str
    positive_reply: str
    negative_reply: str
    neutral_reply: str = ""
    user_instructions: Optional[str] = None  # What the user asked to modify
