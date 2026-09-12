"""
QR code per machine (Future-Ready item C.1): a technician scans the code
bolted to the machine and lands straight on that machine's mobile page
(PM history + a "mark complete" action), no searching/typing a machine
number on a phone keyboard.

The QR payload is just a URL into the (responsive-web) frontend -
`{APP_URL}/m/{machine_id}` - so this needs zero new auth machinery: the
frontend route handles login the same way any other page does. Anyone
implementing item C.2 (technician mobile view) should treat `/m/{id}` as
the route this code expects to exist.
"""

import io

import qrcode

from app.core.config import settings


def machine_deep_link(machine_id: str) -> str:
    return f"{settings.APP_URL}/m/{machine_id}"


def generate_machine_qr_png(machine_id: str) -> bytes:
    """Returns PNG bytes for a QR code encoding this machine's deep link."""
    img = qrcode.make(machine_deep_link(machine_id))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
