"""Google OAuth2 authentication for Gmail API."""

from __future__ import annotations

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import Config

logger = logging.getLogger(__name__)

_project_root = Path(__file__).parent.parent


def get_gmail_credentials() -> Credentials:
    """Obtain valid Gmail API credentials.

    - If a saved token exists and is valid / refreshable, reuse it.
    - Otherwise, run the OAuth2 Desktop flow (opens browser once).

    Returns:
        google.oauth2.credentials.Credentials
    """
    creds: Credentials | None = None

    # Support both absolute and relative paths
    token_cfg = Path(Config.GOOGLE_TOKEN_FILE)
    creds_cfg = Path(Config.GOOGLE_CREDENTIALS_FILE)
    token_path = token_cfg if token_cfg.is_absolute() else _project_root / token_cfg
    creds_path = creds_cfg if creds_cfg.is_absolute() else _project_root / creds_cfg

    # 1. Try loading existing token
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), Config.GMAIL_SCOPES)
        logger.info("Loaded existing token from %s", token_path)

    # 2. Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            logger.info("Token refreshed successfully")
        except Exception:
            logger.warning("Token refresh failed, will re-authorize")
            creds = None

    # 3. Run authorization flow if needed
    if not creds or not creds.valid:
        if not creds_path.exists():
            raise FileNotFoundError(
                f"Google credentials file not found: {creds_path}\n"
                "Download it from Google Cloud Console → APIs & Services → Credentials"
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), Config.GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)
        logger.info("Authorization completed via browser")

    # 4. Save token for next time
    with open(token_path, "w") as f:
        f.write(creds.to_json())
    logger.info("Token saved to %s", token_path)

    return creds
