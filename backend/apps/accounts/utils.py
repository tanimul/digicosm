"""
Utility helpers for the accounts application.

Functions
---------
generate_otp()            — Cryptographically secure 6-digit OTP
send_otp_sms()            — SMS dispatch via Bangladesh gateway
generate_referral_code()  — URL-safe unique referral code
get_client_ip()           — Extract real IP from request
mask_phone_number()       — Mask digits for safe display
"""

import logging
import random
import secrets
import string
import time
from typing import Optional

import httpx
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OTP generation
# ---------------------------------------------------------------------------


def generate_otp(length: int = 6) -> str:
    """
    Generate a cryptographically secure numeric OTP.

    Uses `secrets.choice` over `random` to avoid predictability.

    Parameters
    ----------
    length:
        Number of digits (default 6).

    Returns
    -------
    str
        Zero-padded numeric string of the requested length.

    Examples
    --------
    >>> otp = generate_otp()
    >>> len(otp) == 6 and otp.isdigit()
    True
    """
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(length))


# ---------------------------------------------------------------------------
# Referral code generation
# ---------------------------------------------------------------------------


def generate_referral_code(length: Optional[int] = None) -> str:
    """
    Generate a unique, URL-safe alphanumeric referral code.

    The code is uppercase to reduce visual confusion (no lowercase l/1/0/O).
    Uniqueness is checked against the DB; collisions trigger regeneration.

    Parameters
    ----------
    length:
        Code length.  Defaults to settings.REFERRAL_CODE_LENGTH (8).

    Returns
    -------
    str
        A unique referral code, e.g. ``"DCE3XK7P"``.
    """
    from apps.accounts.models import User  # local import — avoid circular

    length = length or getattr(settings, "REFERRAL_CODE_LENGTH", 8)
    alphabet = string.ascii_uppercase + string.digits
    # Remove visually ambiguous characters
    alphabet = alphabet.replace("0", "").replace("O", "").replace("I", "").replace("1", "")

    for _attempt in range(20):
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if not User.objects.filter(referral_code=code).exists():
            return code

    # Extremely unlikely; fall back to a longer code
    logger.warning(
        "generate_referral_code: collision loop exhausted for length=%d; "
        "using longer fallback",
        length,
    )
    return secrets.token_urlsafe(length)[:length].upper()


# ---------------------------------------------------------------------------
# SMS dispatch
# ---------------------------------------------------------------------------


class SMSBackend:
    """Namespace for available SMS send backends."""

    STUB = "stub"
    LIVE = "live"


def send_otp_sms(
    phone_number: str,
    otp_code: str,
    purpose: str = "verification",
) -> bool:
    """
    Send an OTP via SMS to a Bangladesh mobile number.

    The backend is selected by ``settings.SMS_BACKEND``:

    * ``"stub"``  — Log the OTP to the console (development / test).
    * ``"live"``  — Call the configured Bangladesh SMS gateway API.

    Parameters
    ----------
    phone_number:
        E.164 Bangladesh number, e.g. ``"+8801712345678"``.
    otp_code:
        The 6-digit OTP to send.
    purpose:
        Human-readable context inserted into the message body.

    Returns
    -------
    bool
        ``True`` if dispatch was successful (or stubbed), ``False`` on error.
    """
    backend = getattr(settings, "SMS_BACKEND", SMSBackend.STUB)

    message = _build_sms_message(otp_code, purpose)

    if backend == SMSBackend.STUB:
        return _send_stub(phone_number, message, otp_code)

    return _send_live(phone_number, message)


def _build_sms_message(otp_code: str, purpose: str) -> str:
    """Compose the SMS body text."""
    purpose_label = {
        "login": "login",
        "register": "registration",
        "withdrawal": "withdrawal confirmation",
        "password_reset": "password reset",
        "phone_change": "phone number change",
        "kyc": "KYC verification",
    }.get(purpose, "verification")

    expiry_minutes = getattr(settings, "OTP_EXPIRY_MINUTES", 5)
    return (
        f"Your DCE {purpose_label} OTP is: {otp_code}. "
        f"Valid for {expiry_minutes} minutes. "
        f"Do NOT share this code with anyone."
    )


def _send_stub(phone_number: str, message: str, otp_code: str) -> bool:
    """Log the OTP instead of sending a real SMS (development mode)."""
    logger.info(
        "[SMS STUB] To: %s | OTP: %s | Message: %s",
        phone_number,
        otp_code,
        message,
    )
    # Store in cache so integration tests can retrieve it
    cache_key = f"stub_otp:{phone_number}"
    cache.set(cache_key, otp_code, timeout=300)
    return True


def _send_live(phone_number: str, message: str) -> bool:
    """
    Dispatch SMS via the configured Bangladesh SMS gateway.

    Supported gateways:
    - BulkSMSBD  (https://bulksmsbd.net)
    - SSL Wireless (https://developer.sslwireless.com)
    - Robi Axiata (https://docs.robi.com.bd)

    The gateway URL and credentials are read from Django settings:
    ``SMS_GATEWAY_URL``, ``SMS_GATEWAY_API_KEY``, ``SMS_SENDER_ID``.
    """
    gateway_url: str = getattr(settings, "SMS_GATEWAY_URL", "")
    api_key: str = getattr(settings, "SMS_GATEWAY_API_KEY", "")
    sender_id: str = getattr(settings, "SMS_SENDER_ID", "DCE_BD")

    if not gateway_url or not api_key:
        logger.error(
            "send_otp_sms: SMS_GATEWAY_URL or SMS_GATEWAY_API_KEY not configured. "
            "Cannot send OTP to %s",
            phone_number,
        )
        return False

    # Normalise: strip leading + for gateways that expect 880XXXXXXXXXX
    normalised_number = phone_number.lstrip("+")

    payload = {
        "api_key": api_key,
        "type": "text",
        "number": normalised_number,
        "senderid": sender_id,
        "message": message,
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(gateway_url, json=payload)
            response.raise_for_status()

        data = response.json()
        response_code = str(data.get("response_code", "")).strip()

        # BulkSMSBD returns response_code == "202" for accepted
        if response_code in ("202", "200", "0", "success"):
            logger.info(
                "SMS dispatched successfully to %s via %s",
                phone_number,
                gateway_url,
            )
            return True

        logger.warning(
            "SMS gateway returned non-success code=%s for %s. Response: %s",
            response_code,
            phone_number,
            data,
        )
        return False

    except httpx.TimeoutException:
        logger.error(
            "SMS gateway timed out sending to %s via %s",
            phone_number,
            gateway_url,
        )
        return False

    except httpx.HTTPStatusError as exc:
        logger.error(
            "SMS gateway HTTP error %s sending to %s: %s",
            exc.response.status_code,
            phone_number,
            exc.response.text,
        )
        return False

    except Exception:  # noqa: BLE001
        logger.exception(
            "Unexpected error sending SMS to %s via %s",
            phone_number,
            gateway_url,
        )
        return False


# ---------------------------------------------------------------------------
# IP extraction
# ---------------------------------------------------------------------------


def get_client_ip(request) -> str:
    """
    Extract the real client IP address from a Django request.

    Checks ``X-Forwarded-For`` header first (set by reverse proxies such as
    Nginx or AWS ALB) then falls back to ``REMOTE_ADDR``.

    Parameters
    ----------
    request:
        Django ``HttpRequest`` instance.

    Returns
    -------
    str
        The client's IP address string.
    """
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # Header may contain a comma-separated list; take the first (leftmost) IP
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = request.META.get("REMOTE_ADDR", "")
    return ip


# ---------------------------------------------------------------------------
# Phone number helpers
# ---------------------------------------------------------------------------


def mask_phone_number(phone_number: str) -> str:
    """
    Return a masked version of the phone number for safe public display.

    Example: "+8801712345678" → "+880171****678"

    Parameters
    ----------
    phone_number:
        Full E.164 phone number.

    Returns
    -------
    str
        Masked phone number string.
    """
    if len(phone_number) < 7:
        return phone_number
    # Keep country code prefix + first 3 digits + last 3 digits
    prefix = phone_number[:7]
    suffix = phone_number[-3:]
    masked_count = len(phone_number) - len(prefix) - len(suffix)
    return f"{prefix}{'*' * masked_count}{suffix}"


def normalise_phone_number(phone_number: str) -> str:
    """
    Normalise a Bangladesh phone number to E.164 format.

    Accepted inputs:
    - ``01712345678``  (local, 11 digits)
    - ``8801712345678`` (without leading +)
    - ``+8801712345678`` (E.164, already normalised)

    Parameters
    ----------
    phone_number:
        Raw phone string from user input.

    Returns
    -------
    str
        Normalised E.164 string, e.g. ``"+8801712345678"``.

    Raises
    ------
    ValueError
        If the number cannot be normalised to a valid Bangladesh format.
    """
    number = phone_number.strip()

    if number.startswith("+880"):
        pass  # already E.164
    elif number.startswith("880") and len(number) == 13:
        number = "+" + number
    elif number.startswith("01") and len(number) == 11:
        number = "+880" + number[1:]
    else:
        raise ValueError(
            f"Cannot normalise '{phone_number}' to a Bangladesh E.164 number."
        )

    return number


# ---------------------------------------------------------------------------
# Rate-limiting helpers (backed by Redis)
# ---------------------------------------------------------------------------


def check_otp_rate_limit(phone_number: str, purpose: str, limit: int = 5, window: int = 300) -> bool:
    """
    Check whether the OTP send rate limit has been exceeded.

    Uses a Redis counter with a sliding window.

    Parameters
    ----------
    phone_number:
        Target phone number.
    purpose:
        OTP purpose string.
    limit:
        Maximum allowed attempts within the window.
    window:
        Window size in seconds.

    Returns
    -------
    bool
        ``True`` if the request is within the rate limit, ``False`` if exceeded.
    """
    cache_key = f"otp_rate:{purpose}:{phone_number}"
    current = cache.get(cache_key, 0)

    if current >= limit:
        logger.warning(
            "OTP rate limit exceeded for phone=%s purpose=%s (count=%d)",
            phone_number,
            purpose,
            current,
        )
        return False

    pipe_count = cache.get_or_set(cache_key, 0, timeout=window)
    cache.incr(cache_key)
    return True
