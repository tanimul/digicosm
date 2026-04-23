"""
Wallet Serializers - DRF serializers for all wallet models and API endpoints.

Provides full validation, nested representations, and write-optimised
serializers for deposit and withdrawal flows.
"""

from decimal import Decimal

from django.contrib.auth import get_user_model
from rest_framework import serializers

from .models import (
    BDT_TO_CREDITS_RATE,
    DepositRequest,
    DepositStatus,
    LedgerEntry,
    PaymentMethod,
    Transaction,
    TransactionType,
    Wallet,
    WalletAuditLog,
    WithdrawalMethod,
    WithdrawalRequest,
    WithdrawalStatus,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# Wallet serializers
# ---------------------------------------------------------------------------


class WalletSerializer(serializers.ModelSerializer):
    """Full wallet representation including tier and lifetime statistics."""

    user_id = serializers.UUIDField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    tier_display = serializers.CharField(source="get_tier_display", read_only=True)

    class Meta:
        model = Wallet
        fields = [
            "id",
            "user_id",
            "username",
            "balance",
            "credit_balance",
            "is_frozen",
            "frozen_reason",
            "total_deposited",
            "total_spent",
            "total_withdrawn",
            "tier",
            "tier_display",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class WalletBalanceSerializer(serializers.Serializer):
    """Lightweight balance response for the /wallet/balance endpoint."""

    bdt_balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    credit_balance = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    tier = serializers.CharField(read_only=True)
    tier_display = serializers.SerializerMethodField()
    is_frozen = serializers.BooleanField(read_only=True)
    conversion_rate = serializers.DecimalField(max_digits=8, decimal_places=4, read_only=True)

    def get_tier_display(self, obj: dict) -> str:
        tier_labels = {
            "BRONZE": "Bronze",
            "SILVER": "Silver",
            "GOLD": "Gold",
            "PLATINUM": "Platinum",
        }
        return tier_labels.get(obj.get("tier", "BRONZE"), "Bronze")


class WalletStatsSerializer(serializers.Serializer):
    """Lifetime wallet statistics and tier progression information."""

    bdt_balance = serializers.DecimalField(max_digits=10, decimal_places=2)
    credit_balance = serializers.DecimalField(max_digits=10, decimal_places=2)
    tier = serializers.CharField()
    tier_display = serializers.CharField()
    is_frozen = serializers.BooleanField()
    total_deposited = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_spent = serializers.DecimalField(max_digits=14, decimal_places=2)
    total_withdrawn = serializers.DecimalField(max_digits=14, decimal_places=2)
    conversion_rate = serializers.DecimalField(max_digits=8, decimal_places=4)
    next_tier = serializers.CharField(allow_null=True)
    next_tier_threshold = serializers.DecimalField(
        max_digits=14, decimal_places=2, allow_null=True
    )
    spend_to_next_tier = serializers.DecimalField(
        max_digits=14, decimal_places=2, allow_null=True
    )
    wallet_created_at = serializers.DateTimeField()
    transaction_count = serializers.IntegerField()


# ---------------------------------------------------------------------------
# Transaction serializers
# ---------------------------------------------------------------------------


class TransactionSerializer(serializers.ModelSerializer):
    """Full transaction detail representation."""

    transaction_type_display = serializers.CharField(
        source="get_transaction_type_display", read_only=True
    )
    payment_method_display = serializers.CharField(
        source="get_payment_method_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    user_id = serializers.UUIDField(source="user.id", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "transaction_id",
            "user_id",
            "username",
            "transaction_type",
            "transaction_type_display",
            "payment_method",
            "payment_method_display",
            "amount_bdt",
            "amount_credits",
            "conversion_rate",
            "status",
            "status_display",
            "gateway_transaction_id",
            "gateway_response",
            "ip_address",
            "device_id",
            "service_reference",
            "notes",
            "processed_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TransactionListSerializer(serializers.ModelSerializer):
    """Compact transaction representation for list views."""

    transaction_type_display = serializers.CharField(
        source="get_transaction_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "transaction_id",
            "transaction_type",
            "transaction_type_display",
            "amount_bdt",
            "amount_credits",
            "status",
            "status_display",
            "payment_method",
            "processed_at",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Ledger serializers
# ---------------------------------------------------------------------------


class LedgerEntrySerializer(serializers.ModelSerializer):
    """Read-only ledger entry representation for admin and audit views."""

    entry_type_display = serializers.CharField(
        source="get_entry_type_display", read_only=True
    )
    account_type_display = serializers.CharField(
        source="get_account_type_display", read_only=True
    )
    currency_display = serializers.CharField(
        source="get_currency_display", read_only=True
    )

    class Meta:
        model = LedgerEntry
        fields = [
            "id",
            "entry_type",
            "entry_type_display",
            "account_type",
            "account_type_display",
            "amount",
            "currency",
            "currency_display",
            "balance_before",
            "balance_after",
            "reference_id",
            "description",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Deposit serializers
# ---------------------------------------------------------------------------


class DepositRequestSerializer(serializers.ModelSerializer):
    """Full deposit request representation for admin and user detail views."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    payment_method_display = serializers.CharField(
        source="get_payment_method_display", read_only=True
    )
    is_expired = serializers.BooleanField(read_only=True)

    class Meta:
        model = DepositRequest
        fields = [
            "id",
            "amount_bdt",
            "payment_method",
            "payment_method_display",
            "phone_number",
            "status",
            "status_display",
            "gateway_session_id",
            "gateway_payment_url",
            "is_expired",
            "expires_at",
            "completed_at",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "status_display",
            "gateway_session_id",
            "gateway_payment_url",
            "is_expired",
            "expires_at",
            "completed_at",
            "created_at",
        ]


class DepositInitiateSerializer(serializers.Serializer):
    """Input validation for POST /wallet/deposit."""

    amount_bdt = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("10.00"),
        max_value=Decimal("50000.00"),
    )
    payment_method = serializers.ChoiceField(
        choices=[
            PaymentMethod.BKASH,
            PaymentMethod.NAGAD,
            PaymentMethod.SSLCOMMERZ,
        ]
    )
    phone_number = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        allow_null=True,
    )

    def validate(self, attrs: dict) -> dict:
        payment_method = attrs.get("payment_method")
        phone_number = attrs.get("phone_number")

        if payment_method in (PaymentMethod.BKASH, PaymentMethod.NAGAD):
            if not phone_number:
                raise serializers.ValidationError(
                    {"phone_number": f"Phone number is required for {payment_method}."}
                )
            # Basic Bangladeshi mobile number validation.
            cleaned = phone_number.replace("+88", "").replace("-", "").strip()
            if not cleaned.isdigit() or len(cleaned) != 11:
                raise serializers.ValidationError(
                    {
                        "phone_number": (
                            "Invalid Bangladeshi phone number. Must be 11 digits "
                            "(e.g., 01711XXXXXX or +8801711XXXXXX)."
                        )
                    }
                )
            if not cleaned.startswith("01"):
                raise serializers.ValidationError(
                    {"phone_number": "Bangladeshi mobile numbers must start with 01."}
                )
            attrs["phone_number"] = cleaned

        return attrs


class DepositCallbackSerializer(serializers.Serializer):
    """Input validation for gateway webhook callbacks POST /wallet/deposit/callback."""

    session_id = serializers.CharField(max_length=255)
    payment_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    status = serializers.CharField(max_length=50)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=False)
    currency = serializers.CharField(max_length=10, default="BDT")
    transaction_id = serializers.CharField(
        max_length=255, required=False, allow_blank=True
    )
    # Raw payload stored as-is.
    raw_payload = serializers.JSONField(required=False, default=dict)


# ---------------------------------------------------------------------------
# Withdrawal serializers
# ---------------------------------------------------------------------------


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    """Full withdrawal request representation."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    withdrawal_method_display = serializers.CharField(
        source="get_withdrawal_method_display", read_only=True
    )
    processed_by_username = serializers.SerializerMethodField()

    class Meta:
        model = WithdrawalRequest
        fields = [
            "id",
            "amount_bdt",
            "credits_deducted",
            "withdrawal_method",
            "withdrawal_method_display",
            "account_number",
            "status",
            "status_display",
            "admin_note",
            "processed_by_username",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "credits_deducted",
            "status",
            "status_display",
            "admin_note",
            "processed_by_username",
            "created_at",
            "updated_at",
        ]

    def get_processed_by_username(self, obj: WithdrawalRequest) -> str | None:
        if obj.processed_by:
            return obj.processed_by.username
        return None


class WithdrawalCreateSerializer(serializers.Serializer):
    """Input validation for POST /wallet/withdraw."""

    amount_bdt = serializers.DecimalField(
        max_digits=10,
        decimal_places=2,
        min_value=Decimal("50.00"),
        max_value=Decimal("25000.00"),
    )
    withdrawal_method = serializers.ChoiceField(choices=WithdrawalMethod.choices)
    account_number = serializers.CharField(max_length=50)

    def validate(self, attrs: dict) -> dict:
        withdrawal_method = attrs.get("withdrawal_method")
        account_number = attrs.get("account_number")

        if withdrawal_method in (WithdrawalMethod.BKASH, WithdrawalMethod.NAGAD):
            cleaned = account_number.replace("+88", "").replace("-", "").strip()
            if not cleaned.isdigit() or len(cleaned) != 11:
                raise serializers.ValidationError(
                    {
                        "account_number": (
                            "Invalid mobile number for mobile banking withdrawal. "
                            "Must be 11 digits."
                        )
                    }
                )
            attrs["account_number"] = cleaned

        elif withdrawal_method == WithdrawalMethod.BANK:
            # Basic validation: bank account numbers in Bangladesh are 13-17 digits.
            cleaned = account_number.strip()
            if not cleaned.isdigit() or not (10 <= len(cleaned) <= 20):
                raise serializers.ValidationError(
                    {
                        "account_number": (
                            "Invalid bank account number. "
                            "Must be 10-20 digits."
                        )
                    }
                )
            attrs["account_number"] = cleaned

        return attrs


# ---------------------------------------------------------------------------
# Audit log serializer
# ---------------------------------------------------------------------------


class WalletAuditLogSerializer(serializers.ModelSerializer):
    """Read-only audit log representation for admin inspection."""

    action_display = serializers.CharField(source="get_action_display", read_only=True)
    performed_by_username = serializers.SerializerMethodField()

    class Meta:
        model = WalletAuditLog
        fields = [
            "id",
            "action",
            "action_display",
            "performed_by_username",
            "old_balance",
            "new_balance",
            "ip_address",
            "metadata",
            "created_at",
        ]
        read_only_fields = fields

    def get_performed_by_username(self, obj: WalletAuditLog) -> str:
        if obj.performed_by:
            return obj.performed_by.username
        return "SYSTEM"


# ---------------------------------------------------------------------------
# Conversion rate serializer
# ---------------------------------------------------------------------------


class ConversionRateSerializer(serializers.Serializer):
    """Response for GET /wallet/conversion-rate."""

    bdt_to_credits = serializers.DecimalField(max_digits=8, decimal_places=4)
    credits_to_bdt = serializers.DecimalField(max_digits=8, decimal_places=6)
    description = serializers.CharField()
    example_bdt = serializers.DecimalField(max_digits=8, decimal_places=2)
    example_credits = serializers.DecimalField(max_digits=8, decimal_places=2)
    last_updated = serializers.DateTimeField()
