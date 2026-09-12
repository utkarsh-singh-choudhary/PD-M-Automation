"""
Gmail provider using the Gmail API with OAuth2 (refresh-token flow), so it can
be added independently of Microsoft 365 and enabled at the company's own
pace - just fill in GMAIL_* in .env and set EMAIL_PROVIDER=gmail (or run both
by adding routing rules in the NotificationService).

Requires a Google Cloud project with the Gmail API enabled, an OAuth2 client,
and a one-time consent flow to obtain GMAIL_REFRESH_TOKEN (script for that is
in scripts/gmail_oauth_setup.py).
"""

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import settings
from app.notifications.base import EmailProvider, EmailMessage


class GmailProvider(EmailProvider):
    name = "gmail"

    def __init__(self):
        self.creds = Credentials(
            token=None,
            refresh_token=settings.GMAIL_REFRESH_TOKEN,
            client_id=settings.GMAIL_CLIENT_ID,
            client_secret=settings.GMAIL_CLIENT_SECRET,
            token_uri="https://oauth2.googleapis.com/token",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        )
        self.sender = settings.GMAIL_SENDER_ADDRESS

    def send(self, message: EmailMessage) -> dict:
        try:
            service = build("gmail", "v1", credentials=self.creds)
            if message.html_body:
                alt = MIMEMultipart("alternative")
                alt.attach(MIMEText(message.body, "plain"))
                alt.attach(MIMEText(message.html_body, "html"))
                if message.attachments:
                    mime = MIMEMultipart("mixed")
                    mime.attach(alt)
                    for att in message.attachments:
                        part = MIMEApplication(att.content, Name=att.filename)
                        part["Content-Disposition"] = f'attachment; filename="{att.filename}"'
                        mime.attach(part)
                else:
                    mime = alt
            elif message.attachments:
                mime = MIMEMultipart()
                mime.attach(MIMEText(message.body))
                for att in message.attachments:
                    part = MIMEApplication(att.content, Name=att.filename)
                    part["Content-Disposition"] = f'attachment; filename="{att.filename}"'
                    mime.attach(part)
            else:
                mime = MIMEText(message.body)
            mime["to"] = message.to
            mime["from"] = self.sender
            mime["subject"] = message.subject
            if message.cc:
                mime["cc"] = ", ".join(message.cc)

            raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
            sent = service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
            return {"success": True, "provider_message_id": sent.get("id"), "error": None}
        except HttpError as e:
            return {"success": False, "provider_message_id": None, "error": str(e)}
        except Exception as e:
            return {"success": False, "provider_message_id": None, "error": str(e)}
