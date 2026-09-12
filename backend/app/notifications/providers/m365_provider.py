"""
Microsoft 365 / Outlook provider using Microsoft Graph API (app-only auth,
client credentials flow via MSAL). Sends as MS365_SENDER_ADDRESS.

Requires an Azure AD app registration with Mail.Send (application) permission,
admin-consented. Credentials come from .env - never hardcode.
"""

import base64

import httpx
import msal

from app.core.config import settings
from app.notifications.base import EmailProvider, EmailMessage

GRAPH_SEND_MAIL_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"


class Microsoft365Provider(EmailProvider):
    name = "m365"

    def __init__(self):
        self.tenant_id = settings.MS365_TENANT_ID
        self.client_id = settings.MS365_CLIENT_ID
        self.client_secret = settings.MS365_CLIENT_SECRET
        self.sender = settings.MS365_SENDER_ADDRESS

    def _get_token(self) -> str:
        app = msal.ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=f"https://login.microsoftonline.com/{self.tenant_id}",
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in result:
            raise RuntimeError(f"MS365 auth failed: {result.get('error_description')}")
        return result["access_token"]

    def send(self, message: EmailMessage) -> dict:
        try:
            token = self._get_token()
            payload = {
                "message": {
                    "subject": message.subject,
                    "body": (
                        {"contentType": "HTML", "content": message.html_body}
                        if message.html_body
                        else {"contentType": "Text", "content": message.body}
                    ),
                    "toRecipients": [{"emailAddress": {"address": message.to}}],
                    "ccRecipients": [
                        {"emailAddress": {"address": c}} for c in (message.cc or [])
                    ],
                },
                "saveToSentItems": "true",
            }
            if message.attachments:
                payload["message"]["attachments"] = [
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": att.filename,
                        "contentType": att.mime_type,
                        "contentBytes": base64.b64encode(att.content).decode(),
                    }
                    for att in message.attachments
                ]
            resp = httpx.post(
                GRAPH_SEND_MAIL_URL.format(sender=self.sender),
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
                timeout=15,
            )
            if resp.status_code in (200, 202):
                return {"success": True, "provider_message_id": None, "error": None}
            return {"success": False, "provider_message_id": None, "error": f"{resp.status_code}: {resp.text}"}
        except Exception as e:
            return {"success": False, "provider_message_id": None, "error": str(e)}
