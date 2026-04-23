"""
Celery tasks for the accounts application.

Tasks
-----
send_otp_sms_task         — Async SMS dispatch
cleanup_expired_otps      — Periodic cleanup of expired OTP records
send_welcome_notification — Post-registration welcome push/SMS
"""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    name="apps.accounts.tasks.send_otp_sms_task",
    bind=True,
    max_retries=3,
    default_retry_delay=10,  # seconds between retries
    queue="notifications",
)
def send_otp_sms_task(
    self,
    phone_number: str,
    otp_code: str,
    purpose: str = "verification",
) -> bool:
    """
    Dispatch an OTP via SMS asynchronously.

    Retries up to 3 times with a 10-second delay on transient failures.

    Parameters
    ----------
    phone_number:
        E.164 Bangladesh phone number.
    otp_code:
        6-digit numeric OTP string.
    purpose:
        Human-readable purpose label inserted into the message body.

    Returns
    -------
    bool
        True on successful dispatch.
    """
    from apps.accounts.utils import send_otp_sms

    try:
        success = send_otp_sms(
            phone_number=phone_number,
            otp_code=otp_code,
            purpose=purpose,
        )
        if not success:
            logger.warning(
                "send_otp_sms_task: SMS dispatch returned False for %s, retrying.",
                phone_number,
            )
            raise self.retry(countdown=self.default_retry_delay)
        return True
    except Exception as exc:
        logger.error(
            "send_otp_sms_task: unexpected error sending OTP to %s: %s",
            phone_number,
            exc,
        )
        raise self.retry(exc=exc, countdown=self.default_retry_delay) from exc


@shared_task(
    name="apps.accounts.tasks.cleanup_expired_otps",
    queue="default",
)
def cleanup_expired_otps() -> int:
    """
    Delete OTP records that have expired or been used.

    Scheduled to run every 30 minutes via Celery Beat.

    Returns
    -------
    int
        Number of records deleted.
    """
    from apps.accounts.models import OTPVerification

    cutoff = timezone.now()
    deleted_count, _ = OTPVerification.objects.filter(
        expires_at__lt=cutoff,
    ).delete()

    logger.info(
        "cleanup_expired_otps: deleted %d expired OTP records.",
        deleted_count,
    )
    return deleted_count


@shared_task(
    name="apps.accounts.tasks.send_welcome_notification",
    queue="notifications",
    max_retries=2,
    default_retry_delay=30,
)
def send_welcome_notification(user_id: str) -> None:
    """
    Send a welcome message to a newly registered and verified user.

    Triggered after successful OTP verification for the REGISTER purpose.

    Parameters
    ----------
    user_id:
        UUID string of the user.
    """
    from apps.accounts.models import User

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        logger.error(
            "send_welcome_notification: user %s not found.",
            user_id,
        )
        return

    logger.info(
        "Sending welcome notification to user %s (%s).",
        user_id,
        user.phone_number,
    )

    # Send SMS welcome message
    try:
        from apps.accounts.utils import send_otp_sms

        # Re-use the SMS utility with a custom stub; in production this would
        # call a dedicated message endpoint rather than the OTP gateway.
        import httpx
        from django.conf import settings

        gateway_url: str = getattr(settings, "SMS_GATEWAY_URL", "")
        api_key: str = getattr(settings, "SMS_GATEWAY_API_KEY", "")
        sender_id: str = getattr(settings, "SMS_SENDER_ID", "DCE_BD")

        message = (
            f"Welcome to DCE, {user.short_name}! "
            "Your Digital Consumption Ecosystem account is now active. "
            "Enjoy unlimited content — Team DCE."
        )

        if not gateway_url or not api_key:
            logger.info("[SMS STUB] Welcome to %s: %s", user.phone_number, message)
            return

        payload = {
            "api_key": api_key,
            "type": "text",
            "number": user.phone_number.lstrip("+"),
            "senderid": sender_id,
            "message": message,
        }
        with httpx.Client(timeout=10.0) as client:
            response = client.post(gateway_url, json=payload)
            response.raise_for_status()
        logger.info(
            "Welcome SMS dispatched to user %s.",
            user_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Failed to send welcome SMS to user %s.",
            user_id,
        )
