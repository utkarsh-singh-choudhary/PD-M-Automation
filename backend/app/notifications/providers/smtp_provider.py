"""
Generic SMTP provider - works with M365 SMTP AUTH, Gmail SMTP (app password),
or any other SMTP-compatible mail server. Useful as the zero-setup default
while OAuth apps (Graph / Gmail API) are being provisioned.
"""

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from app.core.config import settings
from app.notifications.base import EmailProvider, EmailMessage


class SmtpGenericProvider(EmailProvider):
    name = "smtp_generic"

    def send(self, message: EmailMessage) -> dict:
        try:
            if message.html_body:
                # multipart/alternative: plain text first (fallback), HTML second
                # (preferred) - mail clients render the last part they understand.
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
            mime["Subject"] = message.subject
            mime["From"] = settings.EMAIL_FROM
            mime["To"] = message.to
            if message.cc:
                mime["Cc"] = ", ".join(message.cc)

            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.starttls()
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
                recipients = [message.to] + (message.cc or [])
                server.sendmail(settings.EMAIL_FROM, recipients, mime.as_string())

            return {"success": True, "provider_message_id": None, "error": None}
        except Exception as e:
            return {"success": False, "provider_message_id": None, "error": str(e)}
