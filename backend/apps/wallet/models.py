"""
Wallet Models - Fintech Wallet System for Bangladesh Digital Consumption Ecosystem.

Implements double-entry accounting with full audit trail, multi-currency support
(BDT and platform credits), and tiered loyalty system.
"""

import uuid
from decimal import Decimal, ROUND_DOWN

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

User = get_user_model()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BDT_TO_CREDITS_RATE = Decimal("10.0")  # 1 BDT = 10 platform credits (default)

TIER_THRESHOLDS = {
    "BRONZE": Decimal("0"),
    "SILVER": Decimal("1000"),
    "GOLD": Decimal("5000"),
    "PLATINUM": Decimal("20000"),
}


# ---------------------------------------------------------------------------
# Choice classes
# ---------------------------------------------------------------------------

class EntryType(models.TextChoices):
    DEBIT = "DEBIT", _("Debit")
    CREDIT = "CREDIT", _("Credit")


class AccountType(models.TextChoices):
    USER_WALLET = "USER_WALLET", _("User Wallet")
    PLATFORM_REVENUE = "PLATFORM_REVENUE", _("Platform Revenue")
    PROVIDER_COST = "PROVIDER_COST", _("Provider Cost")
    REFUND_RESERVE = "REFUND_RESERVE", _("Refund Reserve")


class CurrencyType(models.TextChoices):
    BDT = "BDT", _("Bangladeshi Taka")
    CREDITS = "CREDITS", _("Platform Credits")
    USD = "USD", _("US Dollar")


class TransactionType(models.TextChoices):
    DEPOSIT = "DEPOSIT", _("Deposit")
    WITHDRAWAL = "WITHDRAWAL", _("Withdrawal")
    AI_USAGE = "AI_USAGE", _("AI Usage")
    STREAMING = "STREAMING", _("Streaming")
    MARKETPLACE = "MARKETPLACE", _("Marketplace")
    SUBSCRIPTION = "SUBSCRIPTION", _("Subscription")
    REFUND = "REFUND", _("Refund")
    BONUS = "BONUS", _("Bonus")
    REFERRAL = "REFERRAL", _("Referral")


class PaymentMethod(models.TextChoices):
    BKASH = "BKASH", _("bKash")
    NAGAD = "NAGAD", _("Nagad")
    SSLCOMMERZ = "SSLCOMMERZ", _("SSLCommerz")
    INTERNAL = "INTERNAL", _("Internal Transfer")
    SYSTEM = "SYSTEM", _("System")


class TransactionStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    PROCESSING = "PROCESSING", _("Processing")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")
    REVERSED = "REVERSED", _("Reversed")
    DISPUTED = "DISPUTED", _("Disputed")


class DepositStatus(models.TextChoices):
    INITIATED = "INITIATED", _("Initiated")
    PENDING = "PENDING", _("Pending")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")
    EXPIRED = "EXPIRED", _("Expired")


class WithdrawalStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    APPROVED = "APPROVED", _("Approved")
    PROCESSING = "PROCESSING", _("Processing")
    COMPLETED = "COMPLETED", _("Completed")
    REJECTED = "REJECTED", _("Rejected")


class WithdrawalMethod(models.TextChoices):
    BKASH = "BKASH", _("bKash")
    NAGAD = "NAGAD", _("Nagad")
    BANK = "BANK", _("Bank Transfer")


class WalletTier(models.TextChoices):
    BRONZE = "BRONZE", _("Bronze")
    SILVER = "SILVER", _("Silver")
    GOLD = "GOLD", _("Gold")
    PLATINUM = "PLATINUM", _("Platinum")


class AuditAction(models.TextChoices):
    BALANCE_CHECK = "BALANCE_CHECK", _("Balance Check")
    DEBIT_ATTEMPT = "DEBIT_ATTEMPT", _("Debit Attempt")
    CREDIT_APPLIED = "CREDIT_APPLIED", _("Credit Applied")
    FREEZE_APPLIED = "FREEZE_APPLIED", _("Freeze Applied")
    UNFREEZE = "UNFREEZE", _("Unfreeze")
    OVERDRAFT_PREVENTED = "OVERDRAFT_PREVENTED", _("Overdraft Prevented")


# ---------------------------------------------------------------------------
# Wallet Model
# ---------------------------------------------------------------------------

class Wallet(models.Model):
    """
    Primary wallet model holding BDT balance and platform credits for each user.

    BDT balance represents real monetary value deposited via payment gateways.
    Credits represent platform-specific currency earned or purchased (1 BDT = 10 credits).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Wallet ID"),
    )
    user = models.OneToOneField(
        User,
        on_delete=models.PROTECT,
        related_name="wallet",
        verbose_name=_("User"),
    )
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("BDT Balance"),
        help_text=_("Current BDT balance available for use"),
    )
    credit_balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Credit Balance"),
        help_text=_("Platform credits balance (1 BDT = 10 credits by default)"),
    )
    is_frozen = models.BooleanField(
        default=False,
        verbose_name=_("Is Frozen"),
        help_text=_("Frozen wallets cannot perform transactions"),
    )
    frozen_reason = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Frozen Reason"),
    )
    total_deposited = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Total Deposited (Lifetime BDT)"),
    )
    total_spent = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Total Spent (Lifetime BDT equivalent)"),
    )
    total_withdrawn = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Total Withdrawn (Lifetime BDT)"),
    )
    tier = models.CharField(
        max_length=10,
        choices=WalletTier.choices,
        default=WalletTier.BRONZE,
        verbose_name=_("Loyalty Tier"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Wallet")
        verbose_name_plural = _("Wallets")
        indexes = [
            models.Index(fields=["user"]),
            models.Index(fields=["tier"]),
            models.Index(fields=["is_frozen"]),
        ]

    def __str__(self) -> str:
        return f"Wallet({self.user.username}) BDT={self.balance} Credits={self.credit_balance}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_not_frozen(self) -> None:
        """Raise ValidationError if wallet is frozen."""
        if self.is_frozen:
            raise ValidationError(
                _("Wallet is frozen. Reason: %(reason)s"),
                code="wallet_frozen",
                params={"reason": self.frozen_reason or "No reason provided"},
            )

    # ------------------------------------------------------------------
    # Public mutation methods (must be called inside atomic blocks)
    # ------------------------------------------------------------------

    @transaction.atomic
    def credit_bdt(
        self,
        amount: Decimal,
        txn: "Transaction | None" = None,
        description: str = "",
        metadata: dict | None = None,
    ) -> "LedgerEntry":
        """
        Credit BDT to the wallet and simultaneously create double-entry ledger records.

        Args:
            amount:       Positive BDT amount to add.
            txn:          Optional linked Transaction object.
            description:  Human-readable description for ledger.
            metadata:     Arbitrary JSON metadata for the ledger entry.

        Returns:
            The USER_WALLET credit LedgerEntry.

        Raises:
            ValidationError: If amount is not positive or wallet is frozen.
        """
        if amount <= Decimal("0"):
            raise ValidationError(
                _("Credit amount must be positive, got %(amount)s."),
                code="invalid_amount",
                params={"amount": amount},
            )

        reference_id = uuid.uuid4()
        balance_before = self.balance
        balance_after = self.balance + amount

        # Debit the platform revenue account (funds come from external deposit).
        LedgerEntry.objects.create(
            entry_type=EntryType.DEBIT,
            account_type=AccountType.PLATFORM_REVENUE,
            wallet=self,
            amount=amount,
            currency=CurrencyType.BDT,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_id=reference_id,
            transaction=txn,
            description=description or f"Incoming deposit credited to user wallet",
            metadata=metadata or {},
        )

        # Credit the user wallet account.
        credit_entry = LedgerEntry.objects.create(
            entry_type=EntryType.CREDIT,
            account_type=AccountType.USER_WALLET,
            wallet=self,
            amount=amount,
            currency=CurrencyType.BDT,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_id=reference_id,
            transaction=txn,
            description=description or f"Wallet credited: {amount} BDT",
            metadata=metadata or {},
        )

        # Update the wallet balance and lifetime total.
        self.balance = balance_after
        self.total_deposited = self.total_deposited + amount
        self.calculate_tier()
        self.save(update_fields=["balance", "total_deposited", "tier", "updated_at"])

        # Log the action.
        WalletAuditLog.objects.create(
            wallet=self,
            action=AuditAction.CREDIT_APPLIED,
            old_balance=balance_before,
            new_balance=balance_after,
            metadata={"amount": str(amount), "reference_id": str(reference_id)},
        )

        return credit_entry

    @transaction.atomic
    def debit_credits(
        self,
        amount: Decimal,
        txn: "Transaction | None" = None,
        description: str = "",
        metadata: dict | None = None,
    ) -> "LedgerEntry":
        """
        Debit platform credits from the wallet with double-entry ledger records.

        Args:
            amount:       Positive credits amount to deduct.
            txn:          Optional linked Transaction object.
            description:  Human-readable description.
            metadata:     Arbitrary JSON metadata.

        Returns:
            The USER_WALLET debit LedgerEntry.

        Raises:
            ValidationError: If insufficient credits, amount invalid, or wallet frozen.
        """
        if amount <= Decimal("0"):
            raise ValidationError(
                _("Debit amount must be positive, got %(amount)s."),
                code="invalid_amount",
                params={"amount": amount},
            )

        self._assert_not_frozen()

        if self.credit_balance < amount:
            WalletAuditLog.objects.create(
                wallet=self,
                action=AuditAction.OVERDRAFT_PREVENTED,
                old_balance=self.credit_balance,
                new_balance=self.credit_balance,
                metadata={
                    "attempted_debit": str(amount),
                    "available": str(self.credit_balance),
                },
            )
            raise ValidationError(
                _(
                    "Insufficient credits. Available: %(available)s, Requested: %(requested)s."
                ),
                code="insufficient_credits",
                params={
                    "available": self.credit_balance,
                    "requested": amount,
                },
            )

        reference_id = uuid.uuid4()
        balance_before = self.credit_balance
        balance_after = self.credit_balance - amount

        # Debit user wallet (credits leaving user).
        debit_entry = LedgerEntry.objects.create(
            entry_type=EntryType.DEBIT,
            account_type=AccountType.USER_WALLET,
            wallet=self,
            amount=amount,
            currency=CurrencyType.CREDITS,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_id=reference_id,
            transaction=txn,
            description=description or f"Credits debited: {amount}",
            metadata=metadata or {},
        )

        # Credit provider cost account (credits consumed by a service).
        LedgerEntry.objects.create(
            entry_type=EntryType.CREDIT,
            account_type=AccountType.PROVIDER_COST,
            wallet=self,
            amount=amount,
            currency=CurrencyType.CREDITS,
            balance_before=balance_before,
            balance_after=balance_after,
            reference_id=reference_id,
            transaction=txn,
            description=description or f"Provider service cost: {amount} credits",
            metadata=metadata or {},
        )

        # Update balances and lifetime totals.
        bdt_equivalent = (amount / BDT_TO_CREDITS_RATE).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        self.credit_balance = balance_after
        self.total_spent = self.total_spent + bdt_equivalent
        self.calculate_tier()
        self.save(update_fields=["credit_balance", "total_spent", "tier", "updated_at"])

        WalletAuditLog.objects.create(
            wallet=self,
            action=AuditAction.DEBIT_ATTEMPT,
            old_balance=balance_before,
            new_balance=balance_after,
            metadata={"amount": str(amount), "reference_id": str(reference_id)},
        )

        return debit_entry

    def freeze(self, reason: str, performed_by: "User | None" = None) -> None:
        """
        Freeze the wallet preventing any transactions.

        Args:
            reason:        Human-readable freeze reason (stored in audit log).
            performed_by:  Admin user performing the freeze (None = system).
        """
        self.is_frozen = True
        self.frozen_reason = reason
        self.save(update_fields=["is_frozen", "frozen_reason", "updated_at"])

        WalletAuditLog.objects.create(
            wallet=self,
            action=AuditAction.FREEZE_APPLIED,
            performed_by=performed_by,
            old_balance=self.balance,
            new_balance=self.balance,
            metadata={"reason": reason},
        )

    def unfreeze(self, performed_by: "User | None" = None) -> None:
        """
        Unfreeze the wallet restoring normal transaction capability.

        Args:
            performed_by: Admin user performing the unfreeze (None = system).
        """
        self.is_frozen = False
        self.frozen_reason = None
        self.save(update_fields=["is_frozen", "frozen_reason", "updated_at"])

        WalletAuditLog.objects.create(
            wallet=self,
            action=AuditAction.UNFREEZE,
            performed_by=performed_by,
            old_balance=self.balance,
            new_balance=self.balance,
            metadata={},
        )

    def calculate_tier(self) -> str:
        """
        Recalculate and update tier based on lifetime_spend (total_spent in BDT).

        Tier thresholds (cumulative lifetime BDT spend):
            Bronze:   0 - 999.99
            Silver:   1,000 - 4,999.99
            Gold:     5,000 - 19,999.99
            Platinum: 20,000+

        Returns:
            The new tier string value.
        """
        spend = self.total_spent

        if spend >= TIER_THRESHOLDS["PLATINUM"]:
            new_tier = WalletTier.PLATINUM
        elif spend >= TIER_THRESHOLDS["GOLD"]:
            new_tier = WalletTier.GOLD
        elif spend >= TIER_THRESHOLDS["SILVER"]:
            new_tier = WalletTier.SILVER
        else:
            new_tier = WalletTier.BRONZE

        self.tier = new_tier
        return new_tier


# ---------------------------------------------------------------------------
# Transaction Model
# ---------------------------------------------------------------------------

class Transaction(models.Model):
    """
    Records every financial event in the system.

    Each transaction is uniquely identified by a human-readable transaction_id
    with format TXN-YYYYMMDD-XXXXXXXX for customer support purposes.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Transaction UUID"),
    )
    transaction_id = models.CharField(
        max_length=30,
        unique=True,
        verbose_name=_("Transaction ID"),
        help_text=_("Human-readable ID, format: TXN-YYYYMMDD-XXXXXXXX"),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name=_("User"),
    )
    wallet = models.ForeignKey(
        "Wallet",
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name=_("Wallet"),
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
        verbose_name=_("Transaction Type"),
    )
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        verbose_name=_("Payment Method"),
    )
    amount_bdt = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Amount (BDT)"),
    )
    amount_credits = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Amount (Credits)"),
    )
    conversion_rate = models.DecimalField(
        max_digits=8,
        decimal_places=4,
        default=Decimal("10.0000"),
        verbose_name=_("BDT to Credits Conversion Rate"),
    )
    status = models.CharField(
        max_length=15,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
        verbose_name=_("Status"),
    )
    gateway_transaction_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Gateway Transaction ID"),
        help_text=_("External payment gateway reference"),
    )
    gateway_response = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Gateway Response"),
        help_text=_("Raw response payload from payment gateway"),
    )
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        verbose_name=_("IP Address"),
    )
    device_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Device ID"),
    )
    service_reference = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Service Reference"),
        help_text=_("JSON detailing which service and resource was consumed"),
    )
    notes = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Notes"),
    )
    processed_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Processed At"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Transaction")
        verbose_name_plural = _("Transactions")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["transaction_id"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["wallet", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["transaction_type"]),
            models.Index(fields=["gateway_transaction_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.transaction_id} | {self.transaction_type} | {self.amount_bdt} BDT | {self.status}"

    @staticmethod
    def generate_transaction_id() -> str:
        """Generate a unique human-readable transaction ID: TXN-YYYYMMDD-XXXXXXXX."""
        import random
        import string

        date_part = timezone.now().strftime("%Y%m%d")
        random_part = "".join(
            random.choices(string.ascii_uppercase + string.digits, k=8)
        )
        return f"TXN-{date_part}-{random_part}"

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            # Ensure uniqueness by retrying on collision (extremely rare).
            for _ in range(5):
                candidate = Transaction.generate_transaction_id()
                if not Transaction.objects.filter(transaction_id=candidate).exists():
                    self.transaction_id = candidate
                    break
            else:
                raise RuntimeError("Failed to generate unique transaction_id after 5 attempts.")
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# LedgerEntry Model (Double-Entry Accounting)
# ---------------------------------------------------------------------------

class LedgerEntry(models.Model):
    """
    Immutable double-entry accounting record.

    Every financial movement produces exactly two paired LedgerEntry rows sharing
    the same reference_id — one DEBIT and one CREDIT — preserving the accounting
    equation at all times.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Ledger Entry ID"),
    )
    entry_type = models.CharField(
        max_length=6,
        choices=EntryType.choices,
        verbose_name=_("Entry Type"),
    )
    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        verbose_name=_("Account Type"),
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
        verbose_name=_("Wallet"),
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        verbose_name=_("Amount"),
    )
    currency = models.CharField(
        max_length=10,
        choices=CurrencyType.choices,
        default=CurrencyType.BDT,
        verbose_name=_("Currency"),
    )
    balance_before = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        verbose_name=_("Balance Before"),
    )
    balance_after = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        verbose_name=_("Balance After"),
    )
    reference_id = models.UUIDField(
        verbose_name=_("Reference ID"),
        help_text=_("Shared UUID linking paired debit/credit entries"),
        db_index=True,
    )
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
        verbose_name=_("Transaction"),
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Description"),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))

    class Meta:
        verbose_name = _("Ledger Entry")
        verbose_name_plural = _("Ledger Entries")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "-created_at"]),
            models.Index(fields=["reference_id"]),
            models.Index(fields=["account_type", "entry_type"]),
            models.Index(fields=["transaction"]),
        ]
        # Ledger entries are immutable — enforce at DB level where possible.
        default_permissions = ("view",)

    def __str__(self) -> str:
        return (
            f"[{self.entry_type}] {self.account_type} | {self.amount} {self.currency}"
            f" | ref={self.reference_id}"
        )

    def clean(self):
        if self.amount <= Decimal("0"):
            raise ValidationError(
                _("Ledger entry amount must be positive."), code="invalid_amount"
            )
        if self.balance_after < Decimal("0") and self.entry_type == EntryType.DEBIT:
            raise ValidationError(
                _("Ledger entry would result in negative balance."),
                code="negative_balance",
            )


# ---------------------------------------------------------------------------
# DepositRequest Model
# ---------------------------------------------------------------------------

class DepositRequest(models.Model):
    """
    Tracks an initiated deposit flow through the external payment gateway.

    Lifecycle: INITIATED → PENDING (gateway acknowledged) → COMPLETED/FAILED/EXPIRED.
    Expires 30 minutes after creation if not completed.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Deposit Request ID"),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="deposit_requests",
        verbose_name=_("User"),
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="deposit_requests",
        verbose_name=_("Wallet"),
    )
    amount_bdt = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Amount (BDT)"),
    )
    payment_method = models.CharField(
        max_length=15,
        choices=[
            (PaymentMethod.BKASH, PaymentMethod.BKASH.label),
            (PaymentMethod.NAGAD, PaymentMethod.NAGAD.label),
            (PaymentMethod.SSLCOMMERZ, PaymentMethod.SSLCOMMERZ.label),
        ],
        verbose_name=_("Payment Method"),
    )
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Phone Number"),
        help_text=_("Required for bKash and Nagad payments"),
    )
    status = models.CharField(
        max_length=15,
        choices=DepositStatus.choices,
        default=DepositStatus.INITIATED,
        verbose_name=_("Status"),
    )
    gateway_session_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Gateway Session ID"),
    )
    gateway_payment_url = models.URLField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name=_("Gateway Payment URL"),
    )
    callback_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Callback Data"),
        help_text=_("Webhook payload from payment gateway"),
    )
    expires_at = models.DateTimeField(
        verbose_name=_("Expires At"),
        help_text=_("Deposit request expires 30 minutes after creation"),
    )
    completed_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Completed At"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))

    class Meta:
        verbose_name = _("Deposit Request")
        verbose_name_plural = _("Deposit Requests")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["gateway_session_id"]),
            models.Index(fields=["expires_at"]),
        ]

    def __str__(self) -> str:
        return f"DepositRequest({self.user.username}, {self.amount_bdt} BDT, {self.status})"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timezone.timedelta(minutes=30)
        super().save(*args, **kwargs)

    @property
    def is_expired(self) -> bool:
        """Return True if this deposit request has passed its expiry time."""
        return timezone.now() > self.expires_at and self.status not in (
            DepositStatus.COMPLETED,
            DepositStatus.FAILED,
        )


# ---------------------------------------------------------------------------
# WithdrawalRequest Model
# ---------------------------------------------------------------------------

class WithdrawalRequest(models.Model):
    """
    Tracks a user's request to withdraw BDT back to their mobile wallet or bank.

    Withdrawals require admin approval (PENDING → APPROVED → PROCESSING → COMPLETED).
    Credits are deducted immediately on submission and restored on rejection.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Withdrawal Request ID"),
    )
    user = models.ForeignKey(
        User,
        on_delete=models.PROTECT,
        related_name="withdrawal_requests",
        verbose_name=_("User"),
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="withdrawal_requests",
        verbose_name=_("Wallet"),
    )
    amount_bdt = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name=_("Amount (BDT)"),
    )
    credits_deducted = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name=_("Credits Deducted"),
        help_text=_("Platform credits deducted to cover withdrawal amount"),
    )
    withdrawal_method = models.CharField(
        max_length=10,
        choices=WithdrawalMethod.choices,
        verbose_name=_("Withdrawal Method"),
    )
    account_number = models.CharField(
        max_length=50,
        verbose_name=_("Account Number / Phone"),
        help_text=_("Mobile number for bKash/Nagad, account number for bank transfer"),
    )
    status = models.CharField(
        max_length=15,
        choices=WithdrawalStatus.choices,
        default=WithdrawalStatus.PENDING,
        verbose_name=_("Status"),
    )
    admin_note = models.TextField(
        blank=True,
        default="",
        verbose_name=_("Admin Note"),
    )
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_withdrawals",
        verbose_name=_("Processed By"),
        help_text=_("Admin user who approved or rejected this withdrawal"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        verbose_name = _("Withdrawal Request")
        verbose_name_plural = _("Withdrawal Requests")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["status"]),
            models.Index(fields=["withdrawal_method"]),
        ]

    def __str__(self) -> str:
        return (
            f"WithdrawalRequest({self.user.username}, {self.amount_bdt} BDT,"
            f" {self.withdrawal_method}, {self.status})"
        )


# ---------------------------------------------------------------------------
# WalletAuditLog Model
# ---------------------------------------------------------------------------

class WalletAuditLog(models.Model):
    """
    Immutable audit trail for all wallet state changes.

    Captures before/after balance snapshots, the responsible actor (user or system),
    and contextual metadata for compliance and fraud investigation.
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name=_("Audit Log ID"),
    )
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.PROTECT,
        related_name="audit_logs",
        verbose_name=_("Wallet"),
    )
    action = models.CharField(
        max_length=30,
        choices=AuditAction.choices,
        verbose_name=_("Action"),
    )
    performed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_audit_actions",
        verbose_name=_("Performed By"),
        help_text=_("Null indicates a system-automated action"),
    )
    old_balance = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        verbose_name=_("Old Balance"),
    )
    new_balance = models.DecimalField(
        max_digits=14,
        decimal_places=4,
        verbose_name=_("New Balance"),
    )
    ip_address = models.GenericIPAddressField(
        blank=True,
        null=True,
        verbose_name=_("IP Address"),
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata"),
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created At"))

    class Meta:
        verbose_name = _("Wallet Audit Log")
        verbose_name_plural = _("Wallet Audit Logs")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "-created_at"]),
            models.Index(fields=["action"]),
            models.Index(fields=["performed_by"]),
        ]
        # Audit logs must never be deleted or modified — restrict permissions.
        default_permissions = ("view",)

    def __str__(self) -> str:
        actor = self.performed_by.username if self.performed_by else "SYSTEM"
        return (
            f"AuditLog({self.wallet.user.username}, {self.action},"
            f" {self.old_balance}→{self.new_balance}, by={actor})"
        )
