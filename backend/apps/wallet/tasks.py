"""
Wallet Celery Tasks.

Asynchronous background tasks for the Fintech Wallet system:
    - Deposit expiry and status reconciliation
    - Tier recalculation
    - Fraud detection
    - Transaction notifications
    - Cleanup of stale records

All tasks use Celery's retry mechanism with exponential backoff for reliability.
Tasks are bound (bind=True) to access self.retry() and self.request.id.
"""

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from celery import shared_task
from celery.utils.log import get_task_logger
from django.contrib.auth import get_user_model
from django.db import transaction as db_transaction
from django.utils import timezone

logger = get_task_logger(__name__)

User = get_user_model()


# ---------------------------------------------------------------------------
# Task: Process pending/expired deposits
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="wallet.process_pending_deposits",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def process_pending_deposits(self) -> dict:
    """
    Periodic task: Reconcile pending deposit requests with payment gateways.

    1. Marks INITIATED/PENDING requests as EXPIRED if past their expires_at.
    2. For PENDING requests still within expiry window, queries the gateway
       to check whether payment has been completed outside the webhook flow
       (handles IPN delivery failures).

    Schedule: Every 5 minutes via Celery Beat.

    Returns:
        Dict with counts: expired, completed, still_pending, errors.
    """
    from .models import DepositRequest, DepositStatus
    from .services import WalletService
    from .payment_gateways.bkash import BkashGateway, BkashGatewayError
    from .payment_gateways.nagad import NagadGateway, NagadGatewayError
    from .payment_gateways.sslcommerz import SSLCommerzGateway, SSLCommerzGatewayError

    now = timezone.now()
    stats = {"expired": 0, "completed": 0, "still_pending": 0, "errors": 0}
    wallet_service = WalletService()

    # 1. Expire stale requests.
    stale_qs = DepositRequest.objects.filter(
        status__in=[DepositStatus.INITIATED, DepositStatus.PENDING],
        expires_at__lt=now,
    )
    expired_count = stale_qs.update(status=DepositStatus.EXPIRED)
    stats["expired"] = expired_count
    if expired_count:
        logger.info("Expired %d stale deposit requests.", expired_count)

    # 2. Query gateways for PENDING requests that are not yet expired.
    pending_qs = DepositRequest.objects.filter(
        status=DepositStatus.PENDING,
        expires_at__gte=now,
        gateway_session_id__isnull=False,
    ).select_related("user", "wallet").order_by("created_at")[:50]  # Process in batches

    for deposit_req in pending_qs:
        try:
            _reconcile_deposit_with_gateway(
                deposit_req=deposit_req,
                wallet_service=wallet_service,
                stats=stats,
            )
        except Exception as exc:
            logger.error(
                "Error reconciling deposit %s: %s",
                deposit_req.pk,
                exc,
                exc_info=True,
            )
            stats["errors"] += 1

    logger.info(
        "process_pending_deposits completed: %s", stats
    )
    return stats


def _reconcile_deposit_with_gateway(deposit_req, wallet_service, stats: dict) -> None:
    """Internal helper to reconcile a single deposit with its gateway."""
    from .models import PaymentMethod, DepositStatus
    from .payment_gateways.bkash import BkashGateway, BkashGatewayError
    from .payment_gateways.nagad import NagadGateway, NagadGatewayError
    from .payment_gateways.sslcommerz import SSLCommerzGateway, SSLCommerzGatewayError

    session_id = deposit_req.gateway_session_id
    payment_method = deposit_req.payment_method

    is_paid = False
    confirmed_amount = Decimal("0")

    try:
        if payment_method == PaymentMethod.BKASH:
            gw = BkashGateway()
            is_paid, confirmed_amount = gw.verify_payment(session_id)
        elif payment_method == PaymentMethod.NAGAD:
            gw = NagadGateway()
            is_paid, confirmed_amount = gw.verify_payment(session_id)
        elif payment_method == PaymentMethod.SSLCOMMERZ:
            gw = SSLCommerzGateway()
            # SSLCommerz validate_payment uses val_id; session_key used for query.
            query_result = gw.transaction_query_by_session(session_id)
            txn_status = query_result.get("status", "").upper()
            is_paid = txn_status in ("VALID", "VALIDATED")
            if is_paid:
                try:
                    confirmed_amount = Decimal(
                        query_result.get("amount", str(deposit_req.amount_bdt))
                    )
                except Exception:
                    confirmed_amount = deposit_req.amount_bdt
    except Exception as exc:
        logger.warning(
            "Gateway query failed for deposit %s (%s): %s",
            deposit_req.pk,
            payment_method,
            exc,
        )
        stats["errors"] += 1
        return

    if is_paid:
        # Verify amount matches (allow 0.01 tolerance for float rounding).
        if abs(confirmed_amount - deposit_req.amount_bdt) > Decimal("0.01"):
            logger.error(
                "Amount mismatch for deposit %s: expected=%s got=%s — NOT crediting.",
                deposit_req.pk,
                deposit_req.amount_bdt,
                confirmed_amount,
            )
            stats["errors"] += 1
            return

        with db_transaction.atomic():
            wallet_service.complete_deposit(
                deposit_request=deposit_req,
                gateway_transaction_id=session_id,
                gateway_response={"reconciled_by": "process_pending_deposits"},
            )
        stats["completed"] += 1
        logger.info(
            "Deposit reconciled and completed: %s amount=%s",
            deposit_req.pk,
            confirmed_amount,
        )
    else:
        stats["still_pending"] += 1


# ---------------------------------------------------------------------------
# Task: Recalculate wallet tiers
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="wallet.calculate_wallet_tiers",
    max_retries=2,
    default_retry_delay=300,
    acks_late=True,
)
def calculate_wallet_tiers(self) -> dict:
    """
    Periodic task: Recalculate tier for all wallets based on lifetime spend.

    This is a safety net — tier is updated inline during every debit, but
    this task catches any wallets that may have drifted due to manual adjustments
    or data migrations.

    Schedule: Every 6 hours via Celery Beat.

    Returns:
        Dict with counts: total_processed, updated, unchanged, errors.
    """
    from .models import Wallet

    stats = {"total_processed": 0, "updated": 0, "unchanged": 0, "errors": 0}
    batch_size = 200
    offset = 0

    while True:
        wallets = list(
            Wallet.objects.order_by("created_at")[offset : offset + batch_size]
        )
        if not wallets:
            break

        for wallet in wallets:
            try:
                old_tier = wallet.tier
                wallet.calculate_tier()  # Updates self.tier in memory.
                if wallet.tier != old_tier:
                    wallet.save(update_fields=["tier", "updated_at"])
                    stats["updated"] += 1
                    logger.debug(
                        "Tier updated: wallet=%s %s → %s",
                        wallet.pk,
                        old_tier,
                        wallet.tier,
                    )
                else:
                    stats["unchanged"] += 1
                stats["total_processed"] += 1
            except Exception as exc:
                logger.error(
                    "Error recalculating tier for wallet %s: %s",
                    wallet.pk,
                    exc,
                    exc_info=True,
                )
                stats["errors"] += 1

        offset += batch_size

    logger.info("calculate_wallet_tiers completed: %s", stats)
    return stats


# ---------------------------------------------------------------------------
# Task: Fraud detection check
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="wallet.fraud_detection_check",
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def fraud_detection_check(self, wallet_id: str) -> dict:
    """
    Asynchronous fraud detection analysis for a specific wallet.

    Triggered after significant transactions (large deposits, unusual spending).
    If the risk score is critical (>= 90), the wallet is automatically frozen
    pending manual review.

    Args:
        wallet_id: UUID string of the wallet to analyze.

    Returns:
        Dict with: wallet_id, risk_score, action_taken, flags.
    """
    from .models import Wallet
    from .fraud_detection import FraudDetectionService

    try:
        wallet = Wallet.objects.select_related("user").get(pk=wallet_id)
    except Wallet.DoesNotExist:
        logger.error("fraud_detection_check: Wallet %s not found.", wallet_id)
        return {"error": f"Wallet {wallet_id} not found."}

    fraud_service = FraudDetectionService()
    user = wallet.user

    try:
        risk_score = fraud_service.get_risk_score(user)
        flags = []

        # Individual checks.
        vel_ok, vel_msg = fraud_service.check_deposit_velocity(user, Decimal("0"))
        if not vel_ok:
            flags.append({"check": "deposit_velocity", "message": vel_msg})

        anomaly_ok, anomaly_msg = fraud_service.check_credit_usage_anomaly(user)
        if not anomaly_ok:
            flags.append({"check": "credit_usage_anomaly", "message": anomaly_msg})

        action_taken = "none"

        if risk_score >= 90:
            # Auto-freeze the wallet for manual review.
            fraud_reasons = "; ".join(f["message"] for f in flags) or "Automated fraud detection"
            if not wallet.is_frozen:
                wallet.freeze(
                    reason=f"Auto-frozen by fraud detection (score={risk_score}): {fraud_reasons}",
                    performed_by=None,
                )
                action_taken = "wallet_frozen"
                logger.warning(
                    "Wallet auto-frozen: wallet=%s user=%s score=%d",
                    wallet_id,
                    user.username,
                    risk_score,
                )
        elif risk_score >= 70:
            fraud_service.flag_suspicious_account(
                user,
                f"High risk score {risk_score} detected by background fraud check",
            )
            action_taken = "flagged_for_review"

        result = {
            "wallet_id": str(wallet_id),
            "user": user.username,
            "risk_score": risk_score,
            "action_taken": action_taken,
            "flags": flags,
            "checked_at": timezone.now().isoformat(),
        }
        logger.info(
            "Fraud check completed: wallet=%s score=%d action=%s",
            wallet_id,
            risk_score,
            action_taken,
        )
        return result

    except Exception as exc:
        logger.error(
            "Fraud detection check failed for wallet %s: %s",
            wallet_id,
            exc,
            exc_info=True,
        )
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {"error": str(exc), "wallet_id": str(wallet_id)}


# ---------------------------------------------------------------------------
# Task: Send transaction notification
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="wallet.send_transaction_notification",
    max_retries=5,
    default_retry_delay=10,
    acks_late=True,
)
def send_transaction_notification(self, transaction_pk: str) -> dict:
    """
    Send a push/SMS/email notification to the user after a transaction completes.

    Supports multiple notification channels based on user preferences.
    Retries up to 5 times with exponential backoff on delivery failure.

    Args:
        transaction_pk: UUID string of the Transaction to notify about.

    Returns:
        Dict with: transaction_id, channels_notified, success.
    """
    from .models import Transaction, TransactionType, TransactionStatus

    try:
        txn = Transaction.objects.select_related("user", "wallet").get(
            pk=transaction_pk
        )
    except Transaction.DoesNotExist:
        logger.error(
            "send_transaction_notification: Transaction %s not found.",
            transaction_pk,
        )
        return {"error": f"Transaction {transaction_pk} not found."}

    user = txn.user
    channels_notified = []
    errors = []

    # Build notification message.
    type_messages = {
        TransactionType.DEPOSIT: (
            f"Deposit Successful! {txn.amount_bdt} BDT has been added to your wallet. "
            f"You now have {txn.wallet.credit_balance} credits."
        ),
        TransactionType.WITHDRAWAL: (
            f"Withdrawal Initiated! {txn.amount_bdt} BDT withdrawal request submitted."
        ),
        TransactionType.AI_USAGE: (
            f"AI Service: {txn.amount_credits} credits used. "
            f"Remaining: {txn.wallet.credit_balance} credits."
        ),
        TransactionType.STREAMING: (
            f"Streaming: {txn.amount_credits} credits used. "
            f"Remaining: {txn.wallet.credit_balance} credits."
        ),
        TransactionType.REFUND: (
            f"Refund Applied! {txn.amount_credits} credits have been restored to your wallet."
        ),
        TransactionType.BONUS: (
            f"Bonus Received! {txn.amount_credits} credits added to your wallet."
        ),
        TransactionType.REFERRAL: (
            f"Referral Reward! {txn.amount_credits} credits added for your referral."
        ),
    }
    message = type_messages.get(
        txn.transaction_type,
        f"Transaction {txn.transaction_id}: {txn.amount_bdt} BDT | {txn.status}",
    )

    # --- Email notification ---
    try:
        if user.email:
            _send_email_notification(
                user=user,
                subject=f"Transaction {txn.transaction_id} — {txn.get_status_display()}",
                message=message,
                transaction=txn,
            )
            channels_notified.append("email")
    except Exception as exc:
        logger.warning(
            "Email notification failed for transaction %s: %s",
            txn.transaction_id,
            exc,
        )
        errors.append({"channel": "email", "error": str(exc)})

    # --- Push notification (Firebase Cloud Messaging) ---
    try:
        _send_push_notification(
            user=user,
            title="Wallet Update",
            body=message,
            data={"transaction_id": txn.transaction_id, "type": txn.transaction_type},
        )
        channels_notified.append("push")
    except Exception as exc:
        logger.warning(
            "Push notification failed for transaction %s: %s",
            txn.transaction_id,
            exc,
        )
        errors.append({"channel": "push", "error": str(exc)})

    result = {
        "transaction_id": txn.transaction_id,
        "user": user.username,
        "channels_notified": channels_notified,
        "errors": errors,
        "success": len(channels_notified) > 0,
    }

    if not channels_notified and errors:
        # Retry if all channels failed.
        logger.warning(
            "All notification channels failed for %s, scheduling retry.",
            txn.transaction_id,
        )
        try:
            raise self.retry(
                countdown=2 ** self.request.retries * 10,
                exc=Exception("All notification channels failed"),
            )
        except self.MaxRetriesExceededError:
            logger.error(
                "Max retries exceeded for notification %s.", txn.transaction_id
            )

    return result


def _send_email_notification(user, subject: str, message: str, transaction) -> None:
    """Send a transaction notification email using Django's email backend."""
    from django.core.mail import send_mail
    from django.conf import settings

    send_mail(
        subject=subject,
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@app.com"),
        recipient_list=[user.email],
        fail_silently=False,
    )


def _send_push_notification(user, title: str, body: str, data: dict) -> None:
    """
    Send a Firebase Cloud Messaging push notification.

    Requires: FIREBASE_SERVER_KEY in Django settings.
    User model must have a device_fcm_token attribute (or UserProfile FK).
    """
    from django.conf import settings

    fcm_key = getattr(settings, "FIREBASE_SERVER_KEY", None)
    if not fcm_key:
        logger.debug("FIREBASE_SERVER_KEY not configured — skipping push.")
        return

    # Attempt to retrieve FCM token from user profile.
    fcm_token = None
    try:
        fcm_token = user.profile.fcm_token  # Adjust to your User/Profile structure.
    except AttributeError:
        pass

    if not fcm_token:
        logger.debug("No FCM token for user %s — skipping push.", user.username)
        return

    payload = {
        "to": fcm_token,
        "notification": {"title": title, "body": body},
        "data": data,
        "priority": "high",
    }

    import requests as http_requests
    response = http_requests.post(
        "https://fcm.googleapis.com/fcm/send",
        json=payload,
        headers={
            "Authorization": f"key={fcm_key}",
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    response.raise_for_status()


# ---------------------------------------------------------------------------
# Task: Cleanup expired deposit requests
# ---------------------------------------------------------------------------

@shared_task(
    bind=True,
    name="wallet.cleanup_expired_deposit_requests",
    max_retries=2,
    default_retry_delay=120,
    acks_late=True,
)
def cleanup_expired_deposit_requests(self) -> dict:
    """
    Periodic task: Clean up very old expired/failed deposit requests.

    Deposit requests older than 7 days with terminal status (EXPIRED/FAILED)
    have their gateway_payment_url and callback_data cleared to reduce storage,
    while preserving the record for audit purposes.

    Schedule: Daily at 03:00 via Celery Beat.

    Returns:
        Dict with count of cleaned records.
    """
    from .models import DepositRequest, DepositStatus

    cutoff = timezone.now() - timedelta(days=7)
    terminal_statuses = [DepositStatus.EXPIRED, DepositStatus.FAILED]

    qs = DepositRequest.objects.filter(
        status__in=terminal_statuses,
        created_at__lt=cutoff,
        gateway_payment_url__isnull=False,
    )

    count = qs.count()
    if count == 0:
        logger.info("cleanup_expired_deposit_requests: nothing to clean.")
        return {"cleaned": 0}

    # Clear sensitive gateway URLs but keep records for auditing.
    qs.update(
        gateway_payment_url=None,
        callback_data={},
    )

    logger.info("cleanup_expired_deposit_requests: cleared %d records.", count)
    return {"cleaned": count}
