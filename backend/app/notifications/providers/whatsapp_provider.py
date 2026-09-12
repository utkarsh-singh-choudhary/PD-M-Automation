"""
WhatsApp Business API provider. Talks to the generic Cloud API endpoint
configured via WHATSAPP_API_URL / WHATSAPP_API_TOKEN (works with Meta's own
Cloud API or any BSP - Gupshup, Twilio, etc. - that exposes a compatible
send endpoint); swap this class if a specific BSP needs a different payload
shape, same as the email providers.

Ranked above SMS/email for this deployment because for Indian shop-floor
technicians WhatsApp reliably gets read/replied-to far faster than either -
see notification_service.pick_channel_for_employee().
"""

import httpx

from app.core.config import settings


class WhatsAppProvider:
    name = "whatsapp"

    def send(self, to_phone: str, body: str) -> dict:
        if not settings.WHATSAPP_API_URL or not settings.WHATSAPP_API_TOKEN:
            return {"success": False, "provider_message_id": None,
                    "error": "WhatsApp not configured (WHATSAPP_API_URL/WHATSAPP_API_TOKEN unset)."}
        try:
            resp = httpx.post(
                settings.WHATSAPP_API_URL,
                headers={"Authorization": f"Bearer {settings.WHATSAPP_API_TOKEN}"},
                json={
                    "messaging_product": "whatsapp",
                    "to": to_phone,
                    "type": "text",
                    "text": {"body": body},
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            msg_id = (data.get("messages") or [{}])[0].get("id")
            return {"success": True, "provider_message_id": msg_id, "error": None}
        except Exception as e:
            return {"success": False, "provider_message_id": None, "error": str(e)}
