"""Gmail API client – read, search, and reply to emails."""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

from googleapiclient.discovery import build

from config import Config
from gmail.auth import get_gmail_credentials
from gmail.models import Email

logger = logging.getLogger(__name__)


class GmailClient:
    """High-level wrapper around the Gmail API."""

    def __init__(self) -> None:
        creds = get_gmail_credentials()
        self._service = build("gmail", "v1", credentials=creds)
        self._user = "me"

    # ──────────────────────────────────────────────────────────
    # Read
    # ──────────────────────────────────────────────────────────

    def get_emails_since(
        self, since: datetime, max_results: int = 50
    ) -> list[Email]:
        """Fetch emails received after *since* (UTC)."""
        # Gmail query uses epoch seconds
        after_ts = int(since.timestamp())
        query = f"after:{after_ts}"
        return self._search_emails(query, max_results)

    def get_unread_emails(self, max_results: int = 50) -> list[Email]:
        """Fetch unread emails in INBOX."""
        return self._search_emails("is:unread in:inbox", max_results)

    def get_latest_emails(self, max_results: int = 3) -> list[Email]:
        """Fetch the N most recent emails in INBOX."""
        return self._search_emails("in:inbox", max_results)

    def get_email_detail(self, msg_id: str) -> Email:
        """Fetch full detail of a single message."""
        raw = (
            self._service.users()
            .messages()
            .get(userId=self._user, id=msg_id, format="full")
            .execute()
        )
        return self._parse_message(raw)

    # ──────────────────────────────────────────────────────────
    # Compose / Send new email
    # ──────────────────────────────────────────────────────────

    def send_new_email(self, to_email: str, subject: str, body: str) -> str:
        """Send a brand-new email (not a reply)."""
        html_body = self._build_reply_html(body)
        mime = MIMEText(html_body, "html", "utf-8")
        mime["To"] = to_email
        mime["Subject"] = subject
        mime["From"] = Config.USER_EMAIL

        raw_msg = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
        sent = (
            self._service.users()
            .messages()
            .send(userId=self._user, body={"raw": raw_msg})
            .execute()
        )
        msg_id = sent.get("id", "")
        logger.info("New email sent – id=%s to=%s subject=%s", msg_id, to_email, subject)
        return msg_id

    # ──────────────────────────────────────────────────────────
    # Calendar invite response
    # ──────────────────────────────────────────────────────────

    def respond_to_calendar_invite(
        self, original: Email, response: str, ics_data: str
    ) -> str:
        """Respond to a calendar invite (ACCEPTED / DECLINED / TENTATIVE).

        Sends a reply with an updated ICS attachment indicating the response.
        """
        from email.mime.multipart import MIMEMultipart
        from email.mime.base import MIMEBase
        from email import encoders

        # Build multipart message with ICS response
        msg = MIMEMultipart("mixed")
        msg["To"] = original.reply_to_email
        msg["Subject"] = (
            original.subject
            if original.subject.lower().startswith("re:")
            else f"Re: {original.subject}"
        )
        msg["In-Reply-To"] = original.message_id_header
        msg["References"] = (
            f"{original.references} {original.message_id_header}".strip()
        )

        # Update the ICS with the response
        try:
            import icalendar

            cal = icalendar.Calendar.from_ical(ics_data)
            for component in cal.walk():
                if component.name == "VEVENT":
                    # Add attendee response
                    component.add("STATUS", response)
            updated_ics = cal.to_ical()
        except Exception:
            logger.warning("Could not update ICS, sending text response only")
            updated_ics = None

        # Add text body
        response_text = {
            "ACCEPTED": "I have accepted this calendar invitation.",
            "DECLINED": "I have declined this calendar invitation.",
            "TENTATIVE": "I have tentatively accepted this calendar invitation.",
        }.get(response, "Calendar response sent.")

        text_part = MIMEText(response_text, "plain", "utf-8")
        msg.attach(text_part)

        # Attach updated ICS if available
        if updated_ics:
            ics_part = MIMEBase("text", "calendar", method="REPLY")
            ics_part.set_payload(updated_ics)
            encoders.encode_base64(ics_part)
            ics_part.add_header("Content-Disposition", "attachment", filename="invite.ics")
            msg.attach(ics_part)

        raw_msg = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
        body = {
            "raw": raw_msg,
            "threadId": original.thread_id,
        }
        sent = (
            self._service.users()
            .messages()
            .send(userId=self._user, body=body)
            .execute()
        )
        msg_id = sent.get("id", "")
        logger.info("Calendar response sent – %s to=%s", response, original.reply_to_email)
        return msg_id

    # ──────────────────────────────────────────────────────────
    # Reply / Send
    # ──────────────────────────────────────────────────────────

    def send_reply(
        self,
        original: Email,
        reply_body: str,
    ) -> str:
        """Send a reply to *original* (To sender only), keeping the same thread."""
        html_body = self._build_reply_html(reply_body)
        
        mime = MIMEText(html_body, "html", "utf-8")
        mime["To"] = original.reply_to_email
        return self._send_mime_reply(mime, original)

    def send_reply_all(
        self,
        original: Email,
        reply_body: str,
    ) -> str:
        """Send a reply-all to *original* (To sender, CC all other recipients)."""
        html_body = self._build_reply_html(reply_body)
        
        mime = MIMEText(html_body, "html", "utf-8")
        mime["To"] = original.reply_to_email
        
        # CC: all recipients except ourselves
        my_emails = {Config.USER_EMAIL.lower()}
        cc_list = [
            r for r in original.recipients
            if r.lower().strip() not in my_emails
            and original.reply_to_email.lower() not in r.lower()
        ]
        if cc_list:
            mime["Cc"] = ", ".join(cc_list)
            
        return self._send_mime_reply(mime, original)

    def _build_reply_html(self, reply_body: str) -> str:
        """Clean AI reply text and convert to HTML for email."""
        # Clean up AI reply: strip stray HTML tags like <br>
        clean_body = re.sub(r"<br\s*/?>", "\n", reply_body, flags=re.IGNORECASE)
        clean_body = re.sub(r"<[^>]+>", "", clean_body)
        clean_body = clean_body.strip()
        
        # Convert to HTML: split into paragraphs and wrap in <p> tags
        paragraphs = clean_body.split("\n\n")
        html_parts = []
        for para in paragraphs:
            para_html = para.strip().replace("\n", "<br>")
            if para_html:
                html_parts.append(f"<p>{para_html}</p>")
        return "\n".join(html_parts)

    def _send_mime_reply(self, mime: MIMEText, original: Email) -> str:
        """Send a prepared MIME reply message."""
        mime["Subject"] = (
            original.subject
            if original.subject.lower().startswith("re:")
            else f"Re: {original.subject}"
        )
        mime["In-Reply-To"] = original.message_id_header
        mime["References"] = (
            f"{original.references} {original.message_id_header}".strip()
        )

        raw_msg = base64.urlsafe_b64encode(mime.as_bytes()).decode("ascii")
        body = {
            "raw": raw_msg,
            "threadId": original.thread_id,
        }

        sent = (
            self._service.users()
            .messages()
            .send(userId=self._user, body=body)
            .execute()
        )
        msg_id = sent.get("id", "")
        to_addr = mime["To"]
        cc_addr = mime.get("Cc", "")
        logger.info("Reply sent – id=%s to=%s cc=%s thread=%s", msg_id, to_addr, cc_addr, original.thread_id)
        return msg_id

    # ──────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────

    def _search_emails(self, query: str, max_results: int) -> list[Email]:
        """Run a Gmail search query and return parsed Email objects."""
        results = (
            self._service.users()
            .messages()
            .list(userId=self._user, q=query, maxResults=max_results)
            .execute()
        )
        messages = results.get("messages", [])
        if not messages:
            return []

        emails: list[Email] = []
        for msg_stub in messages:
            try:
                raw = (
                    self._service.users()
                    .messages()
                    .get(
                        userId=self._user, id=msg_stub["id"], format="full"
                    )
                    .execute()
                )
                emails.append(self._parse_message(raw))
            except Exception:
                logger.exception("Failed to parse message %s", msg_stub["id"])
        return emails

    def _parse_message(self, raw: dict) -> Email:
        """Parse a Gmail API message resource into an Email dataclass."""
        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }

        sender_full = headers.get("from", "")
        sender_name, sender_email = self._parse_sender(sender_full)

        to_full = headers.get("to", "")
        cc_full = headers.get("cc", "")
        recipients = [r.strip() for r in to_full.split(",") if r.strip()]
        # Include CC in recipients for Reply All
        if cc_full:
            recipients += [r.strip() for r in cc_full.split(",") if r.strip()]

        label_ids = raw.get("labelIds", [])

        # Parse date
        date_str = headers.get("date", "")
        date = self._parse_date(date_str)

        # Extract body
        body_text, body_html = self._extract_body(raw.get("payload", {}))

        # If only HTML body, strip to text for token efficiency
        if not body_text and body_html:
            body_text = self._strip_html_to_text(body_html)

        # Detect forwarded email and extract original sender
        original_sender = ""
        original_sender_email = ""
        subject = headers.get("subject", "(No Subject)")
        
        # Check X-Forwarded-To header or if sender is our own forwarding address
        forwarded_to = headers.get("x-forwarded-to", "")
        is_forwarded = bool(forwarded_to) or subject.lower().startswith("fwd:")
        
        # Also detect if the system-level from is our own address (auto-forward)
        my_emails = [Config.USER_EMAIL.lower()]
        # Add known forwarding addresses
        if hasattr(Config, 'FORWARD_FROM_EMAIL'):
            my_emails.append(Config.FORWARD_FROM_EMAIL.lower())
        # Common pattern: forwarded from another of user's accounts
        if sender_email.lower().endswith("@ku.edu"):
            is_forwarded = True
            
        if is_forwarded and body_text:
            orig_name, orig_email = self._extract_forwarded_sender(body_text)
            if orig_email:
                original_sender = orig_name
                original_sender_email = orig_email
            # Extract original To/CC from forwarded body for Reply All
            fwd_recipients = self._extract_forwarded_recipients(body_text)
            if fwd_recipients:
                recipients = fwd_recipients

        return Email(
            id=raw["id"],
            thread_id=raw.get("threadId", ""),
            subject=subject,
            sender=sender_name,
            sender_email=sender_email,
            recipients=recipients,
            date=date,
            snippet=raw.get("snippet", ""),
            body_text=body_text,
            body_html=body_html,
            is_unread="UNREAD" in label_ids,
            labels=label_ids,
            in_reply_to=headers.get("in-reply-to", ""),
            message_id_header=headers.get("message-id", ""),
            references=headers.get("references", ""),
            original_sender=original_sender,
            original_sender_email=original_sender_email,
        )

    @staticmethod
    def _parse_sender(from_header: str) -> tuple[str, str]:
        """Extract (display_name, email) from a From header value."""
        if "<" in from_header and ">" in from_header:
            name = from_header[: from_header.index("<")].strip().strip('"')
            email = from_header[from_header.index("<") + 1 : from_header.index(">")]
            return name, email
        return "", from_header.strip()

    @staticmethod
    def _parse_date(date_str: str) -> datetime:
        """Best-effort date parsing."""
        from email.utils import parsedate_to_datetime

        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.utcnow()

    @staticmethod
    def _extract_body(payload: dict) -> tuple[str, str]:
        """Recursively extract plain text and HTML bodies from MIME payload."""
        text = ""
        html = ""

        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif mime_type == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        elif "parts" in payload:
            for part in payload["parts"]:
                t, h = GmailClient._extract_body(part)
                if t and not text:
                    text = t
                if h and not html:
                    html = h

        return text, html

    def check_thread_has_my_reply(self, thread_id: str) -> bool:
        """Check if the thread already contains a reply sent by the user."""
        thread = (
            self._service.users()
            .threads()
            .get(userId=self._user, id=thread_id, format="metadata",
                 metadataHeaders=["From"])
            .execute()
        )
        my_email = Config.USER_EMAIL.lower()
        messages = thread.get("messages", [])
        
        # Skip the first message (original) — only check subsequent replies
        for msg in messages[1:]:
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            from_addr = headers.get("from", "").lower()
            if my_email in from_addr:
                return True
        return False

    @staticmethod
    def _extract_forwarded_sender(body_text: str) -> tuple[str, str]:
        """Extract the original From sender from a forwarded email body.
        
        Looks for patterns like:
        - 'From: John Doe <john@example.com>'
        - 'From: john@example.com'
        - '---------- Forwarded message ----------\nFrom: ...'
        """
        # Pattern: 'From: Name <email>' or 'From: email'
        patterns = [
            r'(?:^|\n)\s*From:\s*(.+?)\s*<([^>]+)>',
            r'(?:^|\n)\s*From:\s*<?([\w.+-]+@[\w.-]+)>?',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body_text, re.IGNORECASE)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    return groups[0].strip(), groups[1].strip()
                elif len(groups) == 1:
                    return "", groups[0].strip()
        return "", ""

    @staticmethod
    def _extract_forwarded_recipients(body_text: str) -> list[str]:
        """Extract original To and CC recipients from a forwarded email body.
        
        Looks for patterns like:
        - 'To: user1@example.com, Name <user2@example.com>'
        - 'Cc: user3@example.com'
        """
        recipients = []
        
        # Extract To: line from forwarded body
        to_match = re.search(
            r'(?:^|\n)\s*To:\s*(.+?)(?:\n\s*(?:Cc|CC|Subject|Date|From):)',
            body_text, re.IGNORECASE | re.DOTALL
        )
        if to_match:
            to_line = to_match.group(1).strip()
            recipients.extend([r.strip() for r in to_line.split(",") if r.strip()])
        
        # Extract Cc: line from forwarded body
        cc_match = re.search(
            r'(?:^|\n)\s*(?:Cc|CC):\s*(.+?)(?:\n\s*(?:Subject|Date|From|To):)',
            body_text, re.IGNORECASE | re.DOTALL
        )
        if cc_match:
            cc_line = cc_match.group(1).strip()
            recipients.extend([r.strip() for r in cc_line.split(",") if r.strip()])
        
        return recipients

    @staticmethod
    def _strip_html_to_text(html: str) -> str:
        """Convert HTML to plain text, stripping all tags and styles."""
        # Remove style/script blocks entirely
        text = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        # Convert <br> and </p> to newlines
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</div>', '\n', text, flags=re.IGNORECASE)
        # Strip all remaining tags
        text = re.sub(r'<[^>]+>', '', text)
        # Decode HTML entities
        import html as html_mod
        text = html_mod.unescape(text)
        # Collapse whitespace
        text = re.sub(r'[ \t]+', ' ', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
