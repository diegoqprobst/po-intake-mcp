"""Read .eml files. In production this is Microsoft Graph (mail.read on one shared mailbox)."""

from __future__ import annotations

import email
from email import policy
from email.utils import parsedate_to_datetime
from pathlib import Path

from .models import Attachment, Email


def read_eml(path: Path) -> Email:
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    body_part = msg.get_body(preferencelist=("plain",))
    body = body_part.get_content() if body_part else ""
    attachments = [
        Attachment(
            name=part.get_filename() or "attachment",
            content_type=part.get_content_type(),
            data=part.get_payload(decode=True) or b"",
        )
        for part in msg.iter_attachments()
    ]
    date_hdr = msg.get("Date")
    received = parsedate_to_datetime(date_hdr).date().isoformat() if date_hdr else ""
    return Email(
        path=str(path),
        message_id=str(msg.get("Message-ID", path.name)).strip("<>"),
        sender=str(msg.get("From", "")),
        subject=str(msg.get("Subject", "")),
        received=received,
        body=body,
        attachments=attachments,
    )
