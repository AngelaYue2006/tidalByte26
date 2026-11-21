"""Live SMS transport. Backend owns task approval and durable send receipts."""

import logging
import os
import re

from requests.exceptions import RequestException
from twilio.base.exceptions import TwilioException
from twilio.http.http_client import TwilioHttpClient
from twilio.rest import Client

from integrations.phone_policy import require_allowlisted
from integrations.types import MessageReceipt


class TwilioSMSClient:
    def __init__(self):
        account = os.getenv("TWILIO_ACCOUNT_SID", "")
        token = os.getenv("TWILIO_AUTH_TOKEN", "")
        self.sender = os.getenv("TWILIO_PHONE_NUMBER", "")
        if (
            not account
            or not token
            or not re.fullmatch(r"\+[1-9]\d{7,14}", self.sender)
        ):
            raise RuntimeError(
                "Twilio account, auth token and E.164 sender are required"
            )
        # SDK default request/response logs can contain account IDs and message data.
        logger = logging.getLogger("lifeline.private_twilio_transport")
        logger.disabled = True
        self.http = TwilioHttpClient(timeout=20, max_retries=0, logger=logger)
        self.client = Client(account, token, http_client=self.http)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        if self.http.session is not None:
            self.http.session.close()

    def require_sender(self):
        try:
            # Do not filter by phone in the request URL or print returned numbers.
            for number in self.client.incoming_phone_numbers.stream(
                page_size=100, limit=1000
            ):
                if (
                    number.phone_number == self.sender
                    and number.capabilities.get("sms") is True
                ):
                    return
        except (TwilioException, RequestException):
            raise RuntimeError("Twilio SMS sender verification failed") from None
        raise RuntimeError("TWILIO_PHONE_NUMBER must be owned and SMS-capable")

    def send(self, recipient, text):
        require_allowlisted(recipient)
        self.require_sender()
        require_allowlisted(recipient)
        try:
            # No automatic retry: timeout may mean Twilio accepted the message.
            return self.client.messages.create(
                to=recipient, from_=self.sender, body=text
            )
        except (TwilioException, RequestException):
            raise RuntimeError(
                "Twilio SMS submission failed; delivery is unverified"
            ) from None


def send(to_e164, text, idempotency_key) -> MessageReceipt:
    # Public adapter has already allowlisted recipient and validated inputs.
    # idempotency_key is backend-owned: Twilio create is not a deduplication store.
    with TwilioSMSClient() as client:
        message = client.send(to_e164, text)
    if (
        not isinstance(message.sid, str)
        or not re.fullmatch(r"SM[0-9a-fA-F]{32}", message.sid)
        or message.status not in {"accepted", "queued", "sending", "sent", "delivered"}
    ):
        raise RuntimeError("Twilio SMS returned no accepted message receipt")
    return MessageReceipt(message_id=message.sid, text=text, simulated=False)
