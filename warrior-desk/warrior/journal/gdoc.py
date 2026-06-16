"""Google Doc journal sync (Section 8).

Optional and best-effort: if auth isn't configured or the API is unreachable, the
journal degrades to local-only and tells the Operator exactly how to fix it. The
local CSV/MD always records everything regardless.

Setup (documented in the README):
  1. Create a Google Cloud project, enable the Google Docs API.
  2. Either a service account (share the target Doc with its email) OR an OAuth
     client (download credentials.json; a token.json is created on first run).
  3. Set GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH, and WARRIOR_GOOGLE_DOC_ID.
"""

from __future__ import annotations

from pathlib import Path

from ..logging_setup import get_logger

log = get_logger("journal.gdoc")

SCOPES = ["https://www.googleapis.com/auth/documents"]


class GoogleDocJournal:
    def __init__(self, doc_id: str, credentials_path: str = "", token_path: str = ""):
        self.doc_id = doc_id
        self.credentials_path = credentials_path
        self.token_path = token_path or "token.json"
        self._service = None
        self.enabled = bool(doc_id and credentials_path)
        self.reason = "" if self.enabled else "Google Doc sync not configured (local-only)."

    def setup_hint(self) -> str:
        return ("Google Doc sync is OFF. To enable: set WARRIOR_GOOGLE_DOC_ID and "
                "GOOGLE_CREDENTIALS_PATH (service account or OAuth client) in .env. "
                "Until then the journal is local-only (journal/journal.md + CSVs).")

    def _connect(self) -> bool:
        if self._service is not None:
            return True
        if not self.enabled:
            return False
        try:
            from googleapiclient.discovery import build  # lazy
        except ImportError:
            self.reason = "google-api-python-client not installed (pip install warrior-desk[gdoc])."
            log.info(self.reason)
            return False
        try:
            creds = self._load_credentials()
            if creds is None:
                return False
            self._service = build("docs", "v1", credentials=creds, cache_discovery=False)
            return True
        except Exception as exc:
            self.reason = f"Google Docs connect failed: {exc}"
            log.warning(self.reason)
            return False

    def _load_credentials(self):
        cred_path = Path(self.credentials_path)
        if not cred_path.exists():
            self.reason = f"credentials file not found: {self.credentials_path}"
            return None
        # Try a service account first (simplest for an unattended agent).
        try:
            from google.oauth2 import service_account
            return service_account.Credentials.from_service_account_file(
                str(cred_path), scopes=SCOPES)
        except Exception:
            pass
        # Fall back to an installed-app OAuth flow with a cached token.
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            tok = Path(self.token_path)
            creds = None
            if tok.exists():
                creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
                    creds = flow.run_local_server(port=0)
                tok.write_text(creds.to_json())
            return creds
        except Exception as exc:
            self.reason = f"OAuth flow failed: {exc}"
            log.warning(self.reason)
            return None

    def append(self, text: str) -> bool:
        """Append text to the end of the target Doc. Never raises."""
        if not self._connect():
            return False
        try:
            doc = self._service.documents().get(documentId=self.doc_id).execute()
            end = doc["body"]["content"][-1]["endIndex"] - 1
            requests = [{"insertText": {"location": {"index": max(1, end)}, "text": "\n" + text + "\n"}}]
            self._service.documents().batchUpdate(
                documentId=self.doc_id, body={"requests": requests}).execute()
            return True
        except Exception as exc:
            self.reason = f"Google Doc append failed: {exc}"
            log.warning(self.reason)
            return False
