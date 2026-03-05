"""AI-powered reply generator using Google Gemini."""

from __future__ import annotations

import json
import logging

from google import genai

from config import Config
from gmail.models import Email, ReplyOptions

logger = logging.getLogger(__name__)

REPLY_GENERATION_PROMPT = """\
You are an email reply assistant for a university professor. Generate reply drafts for the following email.

Generate three versions:
1. **positive_reply**: A positive, agreeable reply that accepts/agrees/confirms.
2. **negative_reply**: A polite but declining reply that rejects/postpones/disagrees.
3. **neutral_reply**: A neutral, professional reply that acknowledges without strong commitment.

Tone and style:
- Write in a formal, academic, professional tone befitting a professor
- Use "Dear [First Name]," as the greeting (e.g., "Dear John,"). Only use titles like Dr./Prof. if the sender clearly has such a title.
- Use formal sign-offs like "Best regards," or "Sincerely,"
- ALWAYS write replies in English
- Keep replies concise, clear, and well-structured

Formatting rules (CRITICAL):
- Do NOT use any HTML tags (no <br>, <p>, etc.). Use ONLY \n characters for line breaks.
- Structure each reply as:
  Line 1: Greeting (e.g., "Dear Dr. Smith,")
  Line 2: empty (\n\n)
  Lines 3+: Body paragraph(s), separated by \n\n between paragraphs
  Next line: empty (\n\n) 
  Next line: Sign-off (e.g., "Best regards,")
  Next line: blank line (\n)
  Last line: "Dongjie Wang"

Original Email:
- From: {sender} <{sender_email}>
- Subject: {subject}
- Date: {date}
- Body:
{body}

Respond ONLY with valid JSON. Use \n for line breaks. NO HTML tags:
{{
  "positive_reply": "Dear ...,\n\nThank you for ...\n\nI would be happy to ...\n\nBest regards,\n\nDongjie Wang",
  "negative_reply": "Dear ...,\n\n...\n\nBest regards,\n\nDongjie Wang",
  "neutral_reply": "Dear ...,\n\n...\n\nBest regards,\n\nDongjie Wang"
}}
"""

REGENERATE_PROMPT = """\
You are an email reply assistant for a university professor. Regenerate a reply based on the user's instructions.
The user's instructions are in Chinese — understand their intent and write the replies in English.

Original Email:
- From: {sender} <{sender_email}>
- Subject: {subject}
- Body:
{body}

Previous reply that was generated:
{previous_reply}

User's instructions (in Chinese):
{user_instructions}

Generate three new versions based on the user's instructions:
1. **positive_reply**: A positive version incorporating the user's instructions.
2. **negative_reply**: A negative/declining version incorporating the user's instructions.
3. **neutral_reply**: A neutral version incorporating the user's instructions.

Tone and style:
- Formal, academic, professional tone befitting a professor
- Use "Dear [First Name]," greetings. Only use Dr./Prof. if the sender clearly has such a title.
- Use formal sign-offs
- Understand the user's Chinese instructions and apply them to the English replies
- ALWAYS write replies in English

Formatting rules (CRITICAL):
- Do NOT use any HTML tags (no <br>, <p>, etc.). Use ONLY \n characters for line breaks.
- Sign as: Dongjie Wang
- Separate paragraphs with \n\n

Respond ONLY with valid JSON. Use \n for line breaks. NO HTML tags:
{{
  "positive_reply": "Dear ...,\n\n...\n\nBest regards,\n\nDongjie Wang",
  "negative_reply": "Dear ...,\n\n...\n\nBest regards,\n\nDongjie Wang",
  "neutral_reply": "Dear ...,\n\n...\n\nBest regards,\n\nDongjie Wang"
}}
"""

COMPOSE_EMAIL_PROMPT = """\
You are an email drafting assistant for Dongjie Wang.

The user wants to compose a new email.

Recipient: {to_name} <{to_email}>
Subject: {subject}

User's instructions (may be in Chinese):
{instructions}

Write a professional, academic-tone email in English based on the user's instructions.

Rules:
- Use "Dear [Recipient Name]," as greeting
- Formal, academic, professional tone
- Sign as "Dongjie Wang"
- Use "Best regards," as sign-off
- Keep it concise and clear

Respond ONLY with the email body (no subject line, no JSON). Start from "Dear ..." and end with "Dongjie Wang".
"""


class ReplyGenerator:
    """Generate email reply drafts using Gemini AI."""

    def __init__(self) -> None:
        self._client = genai.Client(api_key=Config.GEMINI_API_KEY)
        self._model = Config.GEMINI_MODEL

    def generate_replies(self, email: Email) -> ReplyOptions:
        """Generate positive, negative, and neutral reply options."""
        body_preview = (email.body_text or email.snippet)[:2000]
        user_name = "Dongjie Wang"

        prompt = REPLY_GENERATION_PROMPT.format(
            user_name=user_name,
            sender=email.sender,
            sender_email=email.sender_email,
            subject=email.subject,
            date=email.date.isoformat(),
            body=body_preview,
        )

        return self._call_ai(prompt, email.id)

    def compose_email(
        self, to_name: str, to_email: str, subject: str, instructions: str
    ) -> str:
        """Generate a new email draft based on user instructions."""
        prompt = COMPOSE_EMAIL_PROMPT.format(
            to_name=to_name,
            to_email=to_email,
            subject=subject,
            instructions=instructions,
        )
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            draft = response.text.strip()
            # Remove markdown fences if present
            if draft.startswith("```"):
                lines = draft.split("\n")
                draft = "\n".join(lines[1:-1])
            return draft
        except Exception:
            logger.exception("Compose email generation failed")
            return "⚠️ Email generation failed. Please try again."

    def regenerate_with_instructions(
        self,
        email: Email,
        previous_reply: str,
        user_instructions: str,
    ) -> ReplyOptions:
        """Regenerate replies based on user's modification instructions."""
        body_preview = (email.body_text or email.snippet)[:2000]
        user_name = "Dongjie Wang"

        prompt = REGENERATE_PROMPT.format(
            user_name=user_name,
            sender=email.sender,
            sender_email=email.sender_email,
            subject=email.subject,
            body=body_preview,
            previous_reply=previous_reply,
            user_instructions=user_instructions,
        )

        result = self._call_ai(prompt, email.id)
        result.user_instructions = user_instructions
        return result

    def _call_ai(self, prompt: str, email_id: str) -> ReplyOptions:
        """Call Gemini API and parse the response."""
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
            )
            raw_text = response.text.strip()

            # Strip markdown code fences if present
            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                raw_text = "\n".join(lines[1:-1])

            data = json.loads(raw_text, strict=False)

            return ReplyOptions(
                email_id=email_id,
                positive_reply=data.get("positive_reply", ""),
                negative_reply=data.get("negative_reply", ""),
                neutral_reply=data.get("neutral_reply", ""),
            )
        except Exception:
            logger.exception("Reply generation failed for email %s", email_id)
            return ReplyOptions(
                email_id=email_id,
                positive_reply="⚠️ Reply generation failed. Please try again.",
                negative_reply="⚠️ Reply generation failed. Please try again.",
                neutral_reply="⚠️ Reply generation failed. Please try again.",
            )
