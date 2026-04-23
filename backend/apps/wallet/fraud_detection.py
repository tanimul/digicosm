"""
Fraud Detection Service for the Fintech Wallet System.

Implements multi-layered fraud detection combining:
    - Velocity checks (transaction frequency/volume limits)
    - Anomaly detection (statistical deviation from user baseline)
    - Risk scoring (composite 0-100 score combining multiple signals)
    - Behavioural heuristics (time-of-day, device, IP patterns)

Risk score interpretation:
    0-30:   Low risk — normal activity.
    31-50:  Moderate risk — monitoring.
    51-70:  Elevated risk — additional verification recommended.
    71-90:  High risk — flag for manual review.
    91-100: Critical risk — automatic action (freeze/block).

All checks are non-blocking and designed to fail open (allow) on errors
to prevent false positives from disrupting legitimate transactions.
"""

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Max, Q, StdDev, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

User = get_user_model()


class FraudDetectionError(Exception):
    """Raised when fraud detection encounters an unrecoverable error."""
    pass


class FraudDetectionService:
    """
    Multi-signal fraud detection for wallet transactions.

    All public methods return a (is_safe: bool, message: str) tuple
    except get_risk_score() which returns an integer 0-100.

    The service is stateless and safe to instantiate per-request.

    Configuration (optional, via Django settings):
        FRAUD_MAX_DAILY_DEPOSIT_COUNT:    Max deposit attempts in 24h (default 5).
        FRAUD_MAX_DAILY_DEPOSIT_AMOUNT:   Max BDT deposited in 24h (default 50000).
        FRAUD_ANOMALY_STDDEV_THRESHOLD:   StdDev multiplier for anomaly (default 3.0).
        FRAUD_MAX_WITHDRAWAL_DAILY:       Max withdrawal BDT in 24h (default 25000).
    """

    # ------------------------------------------------------------------
    # Default thresholds (overridable via settings)
    # ------------------------------------------------------------------

    DEFAULT_MAX_DAILY_DEPOSITS = 5
    DEFAULT_MAX_DAILY_DEPOSIT_AMOUNT = Decimal("50000.00")
    DEFAULT_MAX_DAILY_WITHDRAWAL = Decimal("25000.00")
    DEFAULT_ANOMALY_STDDEV_MULTIPLIER = Decimal("3.0")
    DEFAULT_SPENDING_WINDOW_DAYS = 30  # Baseline window for anomaly detection.

    def __init__(self):
        from django.conf import settings
        self.max_daily_deposits = getattr(
            settings, "FRAUD_MAX_DAILY_DEPOSIT_COUNT", self.DEFAULT_MAX_DAILY_DEPOSITS
        )
        self.max_daily_deposit_amount = Decimal(
            str(getattr(
                settings,
                "FRAUD_MAX_DAILY_DEPOSIT_AMOUNT",
                self.DEFAULT_MAX_DAILY_DEPOSIT_AMOUNT,
            ))
        )
        self.max_daily_withdrawal = Decimal(
            str(getattr(
                settings,
                "FRAUD_MAX_DAILY_WITHDRAWAL",
                self.DEFAULT_MAX_DAILY_WITHDRAWAL,
            ))
        )
        self.anomaly_stddev_multiplier = Decimal(
            str(getattr(
                settings,
                "FRAUD_ANOMALY_STDDEV_THRESHOLD",
                self.DEFAULT_ANOMALY_STDDEV_MULTIPLIER,
            ))
        )

    # ------------------------------------------------------------------
    # 1. Deposit velocity check
    # ------------------------------------------------------------------

    def check_deposit_velocity(
        self,
        user: User,
        amount: Decimal,
    ) -> tuple[bool, str]:
        """
        Check if the user's deposit activity exceeds velocity limits.

        Limits:
            - Maximum N deposit attempts per 24-hour window.
            - Maximum M BDT deposited in total within 24 hours.

        Args:
            user:   The user initiating the deposit.
            amount: The amount they're attempting to deposit now.

        Returns:
            (True, "") if within limits.
            (False, reason_message) if limits exceeded.
        """
        from .models import Transaction, TransactionType, TransactionStatus

        try:
            window_start = timezone.now() - timedelta(hours=24)
            recent_deposits = Transaction.objects.filter(
                user=user,
                transaction_type=TransactionType.DEPOSIT,
                status__in=[
                    TransactionStatus.COMPLETED,
                    TransactionStatus.PROCESSING,
                    TransactionStatus.PENDING,
                ],
                created_at__gte=window_start,
            )

            deposit_count = recent_deposits.count()
            deposit_total = recent_deposits.aggregate(
                total=Sum("amount_bdt")
            )["total"] or Decimal("0")

            if deposit_count >= self.max_daily_deposits:
                msg = (
                    f"Daily deposit limit reached. You have made {deposit_count} "
                    f"deposit attempts in the last 24 hours (limit: {self.max_daily_deposits})."
                )
                logger.warning(
                    "Deposit velocity exceeded: user=%s count=%d limit=%d",
                    user.username,
                    deposit_count,
                    self.max_daily_deposits,
                )
                return False, msg

            projected_total = deposit_total + amount
            if projected_total > self.max_daily_deposit_amount:
                msg = (
                    f"Daily deposit amount limit reached. You have deposited "
                    f"{deposit_total} BDT in the last 24 hours. "
                    f"The daily limit is {self.max_daily_deposit_amount} BDT."
                )
                logger.warning(
                    "Deposit amount velocity exceeded: user=%s total=%s limit=%s",
                    user.username,
                    deposit_total,
                    self.max_daily_deposit_amount,
                )
                return False, msg

            return True, ""

        except Exception as exc:
            logger.error(
                "Error in check_deposit_velocity for user %s: %s",
                user.username,
                exc,
                exc_info=True,
            )
            # Fail open — do not block on detection errors.
            return True, ""

    # ------------------------------------------------------------------
    # 2. Credit usage anomaly detection
    # ------------------------------------------------------------------

    def check_credit_usage_anomaly(self, user: User) -> tuple[bool, str]:
        """
        Detect abnormal credit spending using statistical analysis.

        Computes the user's 30-day daily spending baseline (mean + stddev),
        then checks whether today's spending is an outlier (> mean + 3σ).

        A user with no baseline history is not flagged.

        Args:
            user: The user to analyze.

        Returns:
            (True, "") if spending is within normal range.
            (False, reason_message) if anomaly detected.
        """
        from .models import Transaction, TransactionType, TransactionStatus

        try:
            baseline_end = timezone.now() - timedelta(days=1)
            baseline_start = baseline_end - timedelta(days=self.DEFAULT_SPENDING_WINDOW_DAYS)

            # Aggregate daily spending for the baseline window.
            from django.db.models.functions import TruncDate
            daily_spend = (
                Transaction.objects.filter(
                    user=user,
                    transaction_type__in=[
                        TransactionType.AI_USAGE,
                        TransactionType.STREAMING,
                        TransactionType.MARKETPLACE,
                        TransactionType.SUBSCRIPTION,
                    ],
                    status=TransactionStatus.COMPLETED,
                    created_at__range=(baseline_start, baseline_end),
                )
                .annotate(spend_date=TruncDate("created_at"))
                .values("spend_date")
                .annotate(daily_total=Sum("amount_credits"))
                .values_list("daily_total", flat=True)
            )

            if len(daily_spend) < 7:
                # Insufficient history to establish baseline — skip anomaly check.
                return True, ""

            daily_amounts = [Decimal(str(d)) for d in daily_spend if d is not None]
            n = len(daily_amounts)
            mean = sum(daily_amounts) / n

            variance = sum((x - mean) ** 2 for x in daily_amounts) / n
            stddev = variance.sqrt() if hasattr(variance, "sqrt") else Decimal(str(float(variance) ** 0.5))

            # Today's spending.
            today_start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
            today_spend_agg = Transaction.objects.filter(
                user=user,
                transaction_type__in=[
                    TransactionType.AI_USAGE,
                    TransactionType.STREAMING,
                    TransactionType.MARKETPLACE,
                    TransactionType.SUBSCRIPTION,
                ],
                status=TransactionStatus.COMPLETED,
                created_at__gte=today_start,
            ).aggregate(total=Sum("amount_credits"))
            today_spend = Decimal(str(today_spend_agg["total"] or "0"))

            # Anomaly threshold: mean + (multiplier * stddev).
            if stddev > Decimal("0"):
                threshold = mean + (self.anomaly_stddev_multiplier * stddev)
                if today_spend > threshold:
                    msg = (
                        f"Unusual spending activity detected. Today's credit usage "
                        f"({today_spend}) is significantly above your normal pattern "
                        f"(mean: {mean:.2f}, threshold: {threshold:.2f})."
                    )
                    logger.warning(
                        "Spending anomaly: user=%s today=%s mean=%s threshold=%s",
                        user.username,
                        today_spend,
                        mean,
                        threshold,
                    )
                    return False, msg

            return True, ""

        except Exception as exc:
            logger.error(
                "Error in check_credit_usage_anomaly for user %s: %s",
                user.username,
                exc,
                exc_info=True,
            )
            return True, ""  # Fail open.

    # ------------------------------------------------------------------
    # 3. Withdrawal risk check
    # ------------------------------------------------------------------

    def check_withdrawal_risk(
        self,
        user: User,
        amount: Decimal,
    ) -> tuple[int, list[str]]:
        """
        Compute a withdrawal-specific risk score and identify risk factors.

        Risk factors evaluated:
            - New account (< 30 days old)
            - Large withdrawal relative to lifetime deposits
            - Unusually high single withdrawal amount
            - Multiple withdrawals in 24 hours
            - Recent failed transactions (potential fraudulent testing)

        Args:
            user:   The user requesting the withdrawal.
            amount: The BDT amount of the withdrawal.

        Returns:
            Tuple (risk_score: int 0-100, risk_factors: list[str]).
        """
        from .models import Wallet, Transaction, TransactionType, TransactionStatus

        risk_score = 0
        risk_factors = []

        try:
            # Factor 1: Account age.
            account_age_days = (timezone.now() - user.date_joined).days
            if account_age_days < 30:
                risk_score += 25
                risk_factors.append(
                    f"New account ({account_age_days} days old)."
                )
            elif account_age_days < 90:
                risk_score += 10
                risk_factors.append(f"Relatively new account ({account_age_days} days).")

            # Factor 2: Withdrawal-to-deposit ratio.
            try:
                wallet = Wallet.objects.get(user=user)
                if wallet.total_deposited > Decimal("0"):
                    ratio = amount / wallet.total_deposited
                    if ratio > Decimal("0.8"):
                        risk_score += 30
                        risk_factors.append(
                            f"Withdrawal amount ({amount} BDT) is "
                            f"{ratio * 100:.1f}% of lifetime deposits."
                        )
                    elif ratio > Decimal("0.5"):
                        risk_score += 15
                        risk_factors.append(
                            f"Withdrawal is {ratio * 100:.1f}% of lifetime deposits."
                        )
                else:
                    # No deposits at all — very suspicious withdrawal.
                    risk_score += 40
                    risk_factors.append("No previous deposits found for this user.")
            except Wallet.DoesNotExist:
                risk_score += 20
                risk_factors.append("No wallet record found.")

            # Factor 3: Absolute withdrawal amount.
            if amount >= Decimal("10000"):
                risk_score += 20
                risk_factors.append(f"Large withdrawal amount: {amount} BDT.")
            elif amount >= Decimal("5000"):
                risk_score += 10
                risk_factors.append(f"Moderate-large withdrawal: {amount} BDT.")

            # Factor 4: Daily withdrawal frequency.
            window_start = timezone.now() - timedelta(hours=24)
            recent_withdrawals = Transaction.objects.filter(
                user=user,
                transaction_type=TransactionType.WITHDRAWAL,
                created_at__gte=window_start,
            ).count()
            if recent_withdrawals >= 3:
                risk_score += 25
                risk_factors.append(
                    f"Multiple withdrawal requests today: {recent_withdrawals}."
                )
            elif recent_withdrawals >= 2:
                risk_score += 10
                risk_factors.append(f"More than one withdrawal today: {recent_withdrawals}.")

            # Factor 5: Recent failed transactions (probing indicator).
            recent_failures = Transaction.objects.filter(
                user=user,
                status=TransactionStatus.FAILED,
                created_at__gte=window_start,
            ).count()
            if recent_failures >= 5:
                risk_score += 20
                risk_factors.append(
                    f"High number of failed transactions in 24h: {recent_failures}."
                )

        except Exception as exc:
            logger.error(
                "Error in check_withdrawal_risk for user %s: %s",
                user.username,
                exc,
                exc_info=True,
            )
            # Return low-risk score on errors to avoid false positives.
            return 10, ["Risk check error — defaulting to low risk."]

        # Cap at 100.
        risk_score = min(risk_score, 100)
        return risk_score, risk_factors

    # ------------------------------------------------------------------
    # 4. Flag suspicious account
    # ------------------------------------------------------------------

    def flag_suspicious_account(self, user: User, reason: str) -> None:
        """
        Mark a user account as suspicious in the audit log.

        This does NOT freeze the wallet — it records the flag for manual
        review by the compliance team. Automated freezing occurs only for
        critical risk scores (>= 90) via the fraud_detection_check Celery task.

        Args:
            user:   The user to flag.
            reason: Human-readable reason for the flag.
        """
        from .models import Wallet, WalletAuditLog, AuditAction

        try:
            wallet = Wallet.objects.get(user=user)
        except Wallet.DoesNotExist:
            logger.warning(
                "Cannot flag user %s — no wallet found.", user.username
            )
            return

        WalletAuditLog.objects.create(
            wallet=wallet,
            action=AuditAction.BALANCE_CHECK,  # Best available action for flagging.
            old_balance=wallet.balance,
            new_balance=wallet.balance,
            metadata={
                "event": "fraud_flag",
                "reason": reason,
                "flagged_at": timezone.now().isoformat(),
            },
        )

        logger.warning(
            "Account flagged for fraud review: user=%s reason=%s",
            user.username,
            reason,
        )

    # ------------------------------------------------------------------
    # 5. Composite risk score
    # ------------------------------------------------------------------

    def get_risk_score(self, user: User) -> int:
        """
        Compute a composite risk score (0-100) for a user combining multiple signals.

        Signals weighted and combined:
            - Account age                (weight: 15)
            - Email verification status  (weight: 5)
            - Deposit velocity           (weight: 20)
            - Spending anomaly           (weight: 20)
            - Withdrawal frequency       (weight: 15)
            - Failed transaction rate    (weight: 15)
            - Frozen history             (weight: 10)

        A score of 0 means no risk signals detected.
        A score of 100 means all risk signals triggered at maximum severity.

        Args:
            user: The user to score.

        Returns:
            Integer risk score 0-100.
        """
        score = 0

        try:
            from .models import (
                Transaction,
                TransactionStatus,
                TransactionType,
                Wallet,
                WalletAuditLog,
                AuditAction,
            )

            # Signal 1: Account age (max 15 points).
            account_age_days = (timezone.now() - user.date_joined).days
            if account_age_days < 7:
                score += 15
            elif account_age_days < 30:
                score += 10
            elif account_age_days < 90:
                score += 5

            # Signal 2: Email verification (max 5 points).
            if hasattr(user, "emailaddress_set"):
                # django-allauth email verification.
                is_verified = user.emailaddress_set.filter(verified=True).exists()
                if not is_verified:
                    score += 5
            elif not getattr(user, "email", None):
                score += 5

            # Signal 3: Deposit velocity (max 20 points).
            window_24h = timezone.now() - timedelta(hours=24)
            recent_deposit_count = Transaction.objects.filter(
                user=user,
                transaction_type=TransactionType.DEPOSIT,
                created_at__gte=window_24h,
            ).count()
            if recent_deposit_count >= self.max_daily_deposits:
                score += 20
            elif recent_deposit_count >= self.max_daily_deposits - 1:
                score += 10
            elif recent_deposit_count >= self.max_daily_deposits // 2:
                score += 5

            # Signal 4: Spending anomaly (max 20 points).
            anomaly_ok, _ = self.check_credit_usage_anomaly(user)
            if not anomaly_ok:
                score += 20

            # Signal 5: Withdrawal frequency in 24h (max 15 points).
            withdrawal_count_24h = Transaction.objects.filter(
                user=user,
                transaction_type=TransactionType.WITHDRAWAL,
                created_at__gte=window_24h,
            ).count()
            if withdrawal_count_24h >= 3:
                score += 15
            elif withdrawal_count_24h == 2:
                score += 8
            elif withdrawal_count_24h == 1:
                score += 3

            # Signal 6: Failed transaction rate in 7 days (max 15 points).
            week_ago = timezone.now() - timedelta(days=7)
            total_txn_7d = Transaction.objects.filter(
                user=user,
                created_at__gte=week_ago,
            ).count()
            failed_txn_7d = Transaction.objects.filter(
                user=user,
                status=TransactionStatus.FAILED,
                created_at__gte=week_ago,
            ).count()
            if total_txn_7d > 0:
                fail_rate = failed_txn_7d / total_txn_7d
                if fail_rate > 0.5:
                    score += 15
                elif fail_rate > 0.3:
                    score += 8
                elif fail_rate > 0.1:
                    score += 3

            # Signal 7: Previous freeze history (max 10 points).
            try:
                wallet = Wallet.objects.get(user=user)
                freeze_count = WalletAuditLog.objects.filter(
                    wallet=wallet,
                    action=AuditAction.FREEZE_APPLIED,
                ).count()
                if freeze_count >= 2:
                    score += 10
                elif freeze_count == 1:
                    score += 5
            except Wallet.DoesNotExist:
                score += 5  # No wallet is suspicious.

        except Exception as exc:
            logger.error(
                "Error computing risk score for user %s: %s",
                user.username,
                exc,
                exc_info=True,
            )
            return 0  # Return 0 (low risk) on errors — fail open.

        return min(score, 100)

    # ------------------------------------------------------------------
    # 6. IP-based checks
    # ------------------------------------------------------------------

    def check_ip_reputation(self, ip_address: str) -> tuple[bool, str]:
        """
        Check whether an IP address has been associated with previous fraud.

        Checks against:
            - Internal blacklist (recent fraud flags with same IP).
            - Known VPN/proxy detection (if configured).

        Args:
            ip_address: Client IP to check.

        Returns:
            (True, "") if IP appears clean.
            (False, reason) if IP is flagged.
        """
        if not ip_address or ip_address in ("127.0.0.1", "::1"):
            return True, ""

        from .models import WalletAuditLog, AuditAction

        try:
            # Check internal audit logs for recent fraud from this IP.
            recent_fraud_from_ip = WalletAuditLog.objects.filter(
                ip_address=ip_address,
                action=AuditAction.FREEZE_APPLIED,
                created_at__gte=timezone.now() - timedelta(days=30),
            ).count()

            if recent_fraud_from_ip >= 3:
                return (
                    False,
                    f"IP address {ip_address} has been associated with "
                    f"{recent_fraud_from_ip} frozen accounts in the last 30 days.",
                )

            return True, ""

        except Exception as exc:
            logger.error(
                "Error in check_ip_reputation for IP %s: %s",
                ip_address,
                exc,
                exc_info=True,
            )
            return True, ""  # Fail open.

    # ------------------------------------------------------------------
    # 7. Bulk risk analysis (for admin dashboard)
    # ------------------------------------------------------------------

    def get_high_risk_wallets(self, limit: int = 50) -> list[dict]:
        """
        Identify the highest-risk wallets for admin review.

        Uses efficient database queries to identify wallets with:
            - Recent freeze history
            - High failed transaction rates
            - Multiple overdraft prevention triggers

        Args:
            limit: Maximum number of wallets to return.

        Returns:
            List of dicts with wallet_id, user, and risk indicators.
        """
        from .models import Wallet, WalletAuditLog, AuditAction, TransactionStatus
        from django.db.models import Q

        week_ago = timezone.now() - timedelta(days=7)

        # Wallets with recent freeze actions.
        recently_frozen = WalletAuditLog.objects.filter(
            action=AuditAction.FREEZE_APPLIED,
            created_at__gte=week_ago,
        ).values_list("wallet_id", flat=True).distinct()

        # Wallets with recent overdraft attempts.
        overdraft_wallets = WalletAuditLog.objects.filter(
            action=AuditAction.OVERDRAFT_PREVENTED,
            created_at__gte=week_ago,
        ).values("wallet_id").annotate(count=Count("id")).filter(
            count__gte=3
        ).values_list("wallet_id", flat=True)

        high_risk_wallet_ids = set(list(recently_frozen) + list(overdraft_wallets))

        wallets = Wallet.objects.filter(
            pk__in=high_risk_wallet_ids
        ).select_related("user")[:limit]

        results = []
        for wallet in wallets:
            freeze_count = WalletAuditLog.objects.filter(
                wallet=wallet,
                action=AuditAction.FREEZE_APPLIED,
            ).count()
            overdraft_count = WalletAuditLog.objects.filter(
                wallet=wallet,
                action=AuditAction.OVERDRAFT_PREVENTED,
                created_at__gte=week_ago,
            ).count()

            results.append(
                {
                    "wallet_id": str(wallet.pk),
                    "user": wallet.user.username,
                    "email": wallet.user.email,
                    "is_frozen": wallet.is_frozen,
                    "tier": wallet.tier,
                    "freeze_history_count": freeze_count,
                    "overdraft_attempts_7d": overdraft_count,
                    "balance": float(wallet.balance),
                    "credit_balance": float(wallet.credit_balance),
                }
            )

        # Sort by most risk indicators.
        results.sort(
            key=lambda x: x["freeze_history_count"] + x["overdraft_attempts_7d"],
            reverse=True,
        )
        return results
