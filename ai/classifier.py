"""AI-powered email classifier using Google Gemini."""

from __future__ import annotations

import json
import logging

from google import genai

from config import Config
from gmail.models import ClassificationResult, Email

logger = logging.getLogger(__name__)

CLASSIFICATION_PROMPT = """\
You are an intelligent email assistant. Analyze the following email and determine:
1. Whether this email requires the user to reply (needs_reply: true/false)
2. Priority level (priority: high/medium/low)
3. Category (category: question/request/notification/newsletter/auto-reply/social/promotion/other)
4. A concise one-line summary in Chinese (summary)
5. A detailed Chinese summary of the email content, including 1-2 key original sentences quoted as evidence (detail_summary)
6. Brief reason why it does/doesn't need a reply in Chinese (reason)

Rules for determining "needs_reply":
- TRUE if: the email asks a question directly to the user, requests action, contains a task assignment, 
  asks for confirmation/approval, or is a meaningful conversation that expects a response.
- FALSE if: the email is a notification/alert (CI/CD, GitHub, monitoring), newsletter/marketing, 
  auto-generated system email, calendar invite (accept/decline via calendar instead), 
  social media notification, promotional email, delivery tracking, 
  or informational email that doesn't expect a response.

The user's email address is: {user_email}

Email details:
- From: {sender} <{sender_email}>
- To: {recipients}
- Subject: {subject}
- Date: {date}
- Body:
{body}

Respond ONLY with valid JSON, no markdown formatting:
{{
  "needs_reply": true/false,
  "priority": "high/medium/low",
  "category": "question/request/notification/newsletter/auto-reply/social/promotion/other",
  "summary": "一句话中文摘要",
  "detail_summary": "详细中文摘要（2-3句话），并引用1-2句关键原文。例如：对方询问了项目进度，并提到 \\"Could you please confirm the deadline?\\"",
  "reason": "中文原因说明"
}}
"""

BATCH_CLASSIFICATION_PROMPT = """\
You are an intelligent email assistant. Analyze ALL of the following emails and classify each one.

Rules for determining "needs_reply":
- TRUE if: the email asks a question directly to the user, requests action, contains a task assignment, 
  asks for confirmation/approval, or is a meaningful conversation that expects a response.
- FALSE if: the email is a notification/alert, newsletter/marketing, auto-generated system email, 
  calendar invite, social media notification, promotional email, delivery tracking, 
  or informational email that doesn't expect a response.

The user's email address is: {user_email}

{emails_block}

Respond ONLY with a valid JSON array (one object per email, in the SAME order). No markdown:
[
  {{
    "email_id": "the_email_id",
    "needs_reply": true/false,
    "priority": "high/medium/low",
    "category": "question/request/notification/newsletter/auto-reply/social/promotion/other",
    "summary": "一句话中文摘要",
    "detail_summary": "详细中文摘要，引用1-2句关键原文",
    "reason": "中文原因说明"
  }}
]
"""

BATCH_SIZE = 5  # Max emails per batch API call


class EmailClassifier:
    """Classify emails using Gemini AI."""

    # Sender patterns that are obviously non-actionable (skip AI call)
    _SKIP_SENDER_PATTERNS = [
        "noreply@", "no-reply@", "donotreply@", "notifications@",
        "mailer-daemon@", "postmaster@", "newsletter@", "marketing@",
        "updates@", "digest@", "alert@", "notification@",
        "@github.com", "@linkedin.com", "@facebookmail.com",
        "@amazonses.com", "@indeed.com", "@glassdoor.com",
        "@quora.com", "@medium.com", "@substack.com",
    ]

    def __init__(self) -> None:
        self._client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self._model = Config.GEMINI_MODEL

    def classify(self, email: Email) -> ClassificationResult:
        """Classify a single email."""
        # Pre-filter: skip AI for obvious non-actionable emails
        skip_reason = self._is_obvious_non_actionable(email)
        if skip_reason:
            logger.info("Skipping AI for email %s: %s", email.id, skip_reason)
            return ClassificationResult(
                email_id=email.id,
                needs_reply=False,
                priority="low",
                category="notification",
                summary=email.snippet[:60] if email.snippet else email.subject,
                reason=skip_reason,
                detail_summary="",
            )

        body_preview = (email.body_text or email.snippet)[:1200]

        prompt = CLASSIFICATION_PROMPT.format(
            user_email=Config.USER_EMAIL,
            sender=email.sender,
            sender_email=email.sender_email,
            recipients=", ".join(email.recipients),
            subject=email.subject,
            date=email.date.isoformat(),
            body=body_preview,
        )

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            raw_text = response.text.strip()

            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                raw_text = "\n".join(lines[1:-1])

            data = json.loads(raw_text)

            return ClassificationResult(
                email_id=email.id,
                needs_reply=data.get("needs_reply", False),
                priority=data.get("priority", "low"),
                category=data.get("category", "other"),
                summary=data.get("summary", email.snippet[:60]),
                reason=data.get("reason", ""),
                detail_summary=data.get("detail_summary", ""),
            )
        except Exception:
            logger.exception("Classification failed for email %s", email.id)
            return ClassificationResult(
                email_id=email.id,
                needs_reply=False,
                priority="low",
                category="other",
                summary=email.snippet[:60] if email.snippet else email.subject,
                reason="分类失败，已跳过",
            )

    def _is_obvious_non_actionable(self, email: Email) -> str:
        """Check if email is obviously non-actionable without needing AI."""
        sender_lower = email.sender_email.lower()
        for pattern in self._SKIP_SENDER_PATTERNS:
            if pattern in sender_lower:
                return f"自动过滤：发件人匹配 {pattern}"

        subject_lower = email.subject.lower()
        skip_subjects = [
            "unsubscribe", "your order", "shipping confirmation",
            "delivery notification", "out of office", "auto-reply",
            "automatic reply",
        ]
        for pattern in skip_subjects:
            if pattern in subject_lower:
                return f"自动过滤：主题匹配 {pattern}"

        return ""

    def classify_batch(self, emails: list[Email]) -> list[ClassificationResult]:
        """Classify emails using batched API calls for token efficiency.

        Groups emails into batches of BATCH_SIZE and sends one API call per batch,
        saving ~60-70% of API calls vs single classification.
        Pre-filtered emails skip AI entirely.
        """
        results: list[ClassificationResult] = []
        needs_ai: list[Email] = []

        for email in emails:
            skip_reason = self._is_obvious_non_actionable(email)
            if skip_reason:
                logger.info("Skipping AI for email %s: %s", email.id, skip_reason)
                results.append(ClassificationResult(
                    email_id=email.id,
                    needs_reply=False,
                    priority="low",
                    category="notification",
                    summary=email.snippet[:60] if email.snippet else email.subject,
                    reason=skip_reason,
                    detail_summary="",
                ))
            else:
                needs_ai.append(email)

        # Process AI-needing emails in batches
        for i in range(0, len(needs_ai), BATCH_SIZE):
            batch = needs_ai[i:i + BATCH_SIZE]

            if len(batch) == 1:
                results.append(self.classify(batch[0]))
                continue

            batch_results = self._classify_batch_api(batch)
            results.extend(batch_results)

        # Re-sort results to match original email order
        id_order = {e.id: idx for idx, e in enumerate(emails)}
        results.sort(key=lambda r: id_order.get(r.email_id, 999))

        return results

    def _classify_batch_api(self, batch: list[Email]) -> list[ClassificationResult]:
        """Send a batch of emails in one API call."""
        email_blocks = []
        for idx, email in enumerate(batch, 1):
            body_preview = (email.body_text or email.snippet)[:800]
            block = (
                f"--- Email {idx} (ID: {email.id}) ---\n"
                f"From: {email.sender} <{email.sender_email}>\n"
                f"To: {', '.join(email.recipients)}\n"
                f"Subject: {email.subject}\n"
                f"Date: {email.date.isoformat()}\n"
                f"Body:\n{body_preview}\n"
            )
            email_blocks.append(block)

        emails_block = "\n".join(email_blocks)
        prompt = BATCH_CLASSIFICATION_PROMPT.format(
            user_email=Config.USER_EMAIL,
            emails_block=emails_block,
        )

        try:
            logger.info("Batch classifying %d emails in one API call", len(batch))
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            raw_text = response.text.strip()

            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                raw_text = "\n".join(lines[1:-1])

            data_list = json.loads(raw_text)

            if not isinstance(data_list, list):
                raise ValueError("Expected JSON array from batch classification")

            # Map results by email_id for robustness
            data_by_id = {}
            for item in data_list:
                eid = item.get("email_id", "")
                if eid:
                    data_by_id[eid] = item

            results = []
            for email in batch:
                data = data_by_id.get(email.id)
                if data:
                    results.append(ClassificationResult(
                        email_id=email.id,
                        needs_reply=data.get("needs_reply", False),
                        priority=data.get("priority", "low"),
                        category=data.get("category", "other"),
                        summary=data.get("summary", email.snippet[:60]),
                        reason=data.get("reason", ""),
                        detail_summary=data.get("detail_summary", ""),
                    ))
                else:
                    logger.warning("Batch missing result for %s, falling back", email.id)
                    results.append(self.classify(email))

            logger.info("Batch classification done: %d results", len(results))
            return results

        except Exception:
            logger.exception("Batch classification failed, falling back to single")
            return [self.classify(email) for email in batch]
