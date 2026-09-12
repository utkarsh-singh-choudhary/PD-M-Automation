from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class EmailAttachment:
    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class EmailMessage:
    to: str
    subject: str
    body: str
    cc: list = None
    attachments: list = field(default_factory=list)  # list[EmailAttachment]
    html_body: str = None  # optional HTML alternative; providers fall back to plain `body` if unset


class EmailProvider(ABC):
    """Every email provider (M365, Gmail, generic SMTP, ...) implements this."""

    name: str = "base"

    @abstractmethod
    def send(self, message: EmailMessage) -> dict:
        """
        Sends the message. Must return a dict:
          {"success": bool, "provider_message_id": str | None, "error": str | None}
        Must NOT raise on delivery failure - the caller (notification service)
        is responsible for retry/logging via NotificationLog.
        """
        raise NotImplementedError
