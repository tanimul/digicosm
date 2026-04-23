"""
Wallet Services - Business logic layer for the Fintech Wallet system.

All wallet mutations are performed through this service layer to ensure
consistent audit logging, atomic transactions, and proper error handling.
"""

import logging
from decimal import Decimal, ROUND_DOWN
from typing import Optional

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import (
    BDT_TO_CREDITS_RATE,
    AuditAction,
    DepositRequest,
    DepositStatus,
    LedgerEntry,
    PaymentMethod,
    Transaction,
    TransactionStatus,
    TransactionType,
    Wallet,
    WalletAuditLog,
    WithdrawalRequest,
    WithdrawalStatus,
)

logger = logging.getLogger(__name__)

User = get_user_model()


class WalletServiceError(Exception):
    """Base exception for wallet service errors."""

    pass


class InsufficientFundsError(WalletServiceError):
    """Raised when a user does not have sufficient credits or BDT balance."""

    pass


class WalletFrozenError(WalletServiceError):
    """Raised when an operation is attempted on a frozen wallet."""

    pass


class DuplicateWalletError(WalletServiceError):
    """Raised when trying to create a wallet for a user who already has one."""

    pass


class InvalidAmountError(WalletServiceError):
    """Raised when an amount is zero, negative, or otherwise invalid."""

    pass


class WalletService:
    """
    Central service for all wallet operations.

    This class encapsulates all business logic for wallet creation, deposits,
    debits, refunds, transfers, and bonuses. All methods use atomic database
    transactions to guarantee consistency.

    Usage:
        service = WalletService()
        wallet = service.create_wallet(user)
        deposit = service.deposit_bdt(user, Decimal("500.00"), "BKASH", "01711000000")
    """

    # ------------------------------------------------------------------
    # Wallet creation
    # ------------------------------------------------------------------

    @transaction.atomic
    def create_wallet(self, user: User) -> Wallet:
        """
        Create a new wallet for the given user.

        Called automatically on user registration via the accounts app signal.
        Wallets start with zero BDT and zero credits.

        Args:
            user: The User instance for whom the wallet is created.

        Returns:
            The newly created Wallet instance.

        Raises:
            DuplicateWalletError: If the user already has a wallet.
        """
        if Wallet.objects.filter(user=user).exists():
            raise DuplicateWalletError(
                f"User {user.username} already has a wallet."
            )

        wallet = Wallet.objects.create(user=user)

        WalletAuditLog.objects.create(
            wallet=wallet,
            action=AuditAction.BALANCE_CHECK,
            old_balance=Decimal("0"),
            new_balance=Decimal("0"),
            metadata={"event": "wallet_created", "user_id": str(user.pk)},
        )

        logger.info("Wallet created for user %s (wallet_id=%s)", user.username, wallet.pk)
        return wallet

    # ------------------------------------------------------------------
    # Deposit flow
    # ------------------------------------------------------------------

    @transaction.atomic
    def deposit_bdt(
        self,
        user: User,
        amount: Decimal,
        payment_method: str,
        phone: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> DepositRequest:
        """
        Initiate a BDT deposit by creating a DepositRequest and obtaining a
        payment URL from the configured gateway.

        The wallet is NOT credited at this stage. Credit occurs only after the
        gateway confirms successful payment via complete_deposit().

        Args:
            user:           The depositing user.
            amount:         BDT amount to deposit (minimum 10 BDT enforced).
            payment_method: One of BKASH, NAGAD, SSLCOMMERZ.
            phone:          Mobile number for bKash/Nagad (required for those methods).
            ip_address:     Client IP for fraud logging.

        Returns:
            A DepositRequest instance with gateway_payment_url populated.

        Raises:
            InvalidAmountError:  If amount < 10 BDT or > 50,000 BDT.
            ValidationError:     If phone missing for bKash/Nagad.
            WalletFrozenError:   If the wallet is frozen.
        """
        self._validate_deposit_amount(amount)

        wallet = self._get_wallet(user)

        if wallet.is_frozen:
            raise WalletFrozenError(
                f"Cannot initiate deposit on frozen wallet: {wallet.frozen_reason}"
            )

        if payment_method in (PaymentMethod.BKASH, PaymentMethod.NAGAD) and not phone:
            raise ValidationError(
                f"Phone number is required for {payment_method} payments.",
                code="phone_required",
            )

        deposit_request = DepositRequest.objects.create(
            user=user,
            wallet=wallet,
            amount_bdt=amount,
            payment_method=payment_method,
            phone_number=phone,
            status=DepositStatus.INITIATED,
        )

        # Invoke the appropriate gateway to get a payment URL.
        try:
            gateway_result = self._initiate_gateway_payment(
                deposit_request=deposit_request,
                payment_method=payment_method,
                amount=amount,
                phone=phone,
            )
            deposit_request.gateway_session_id = gateway_result.get("session_id")
            deposit_request.gateway_payment_url = gateway_result.get("payment_url")
            deposit_request.status = DepositStatus.PENDING
            deposit_request.save(
                update_fields=[
                    "gateway_session_id",
                    "gateway_payment_url",
                    "status",
                ]
            )
        except Exception as exc:
            deposit_request.status = DepositStatus.FAILED
            deposit_request.save(update_fields=["status"])
            logger.error(
                "Gateway initiation failed for deposit %s: %s",
                deposit_request.pk,
                exc,
                exc_info=True,
            )
            raise WalletServiceError(
                f"Payment gateway error: {exc}"
            ) from exc

        logger.info(
            "Deposit initiated: user=%s amount=%s BDT method=%s deposit_id=%s",
            user.username,
            amount,
            payment_method,
            deposit_request.pk,
        )
        return deposit_request

    @transaction.atomic
    def complete_deposit(
        self,
        deposit_request: DepositRequest,
        gateway_transaction_id: Optional[str] = None,
        gateway_response: Optional[dict] = None,
    ) -> Transaction:
        """
        Finalize a successful deposit: credit the wallet, convert BDT to credits,
        and record all accounting entries atomically.

        This method is called either from the gateway callback view or the
        process_pending_deposits Celery task after verifying payment success.

        Args:
            deposit_request:        The DepositRequest to complete.
            gateway_transaction_id: External gateway reference for the transaction.
            gateway_response:       Raw gateway response payload.

        Returns:
            The completed Transaction record.

        Raises:
            WalletServiceError: If deposit is already completed, failed, or expired.
        """
        if deposit_request.status == DepositStatus.COMPLETED:
            raise WalletServiceError(
                f"Deposit {deposit_request.pk} is already completed."
            )
        if deposit_request.status == DepositStatus.FAILED:
            raise WalletServiceError(
                f"Deposit {deposit_request.pk} has already failed."
            )
        if deposit_request.is_expired:
            deposit_request.status = DepositStatus.EXPIRED
            deposit_request.save(update_fields=["status"])
            raise WalletServiceError(
                f"Deposit {deposit_request.pk} has expired."
            )

        wallet = deposit_request.wallet
        amount_bdt = deposit_request.amount_bdt
        conversion_rate = BDT_TO_CREDITS_RATE
        amount_credits = (amount_bdt * conversion_rate).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )

        # Create the Transaction record first (ledger entries will link to it).
        txn = Transaction.objects.create(
            user=deposit_request.user,
            wallet=wallet,
            transaction_type=TransactionType.DEPOSIT,
            payment_method=deposit_request.payment_method,
            amount_bdt=amount_bdt,
            amount_credits=amount_credits,
            conversion_rate=conversion_rate,
            status=TransactionStatus.PROCESSING,
            gateway_transaction_id=gateway_transaction_id or "",
            gateway_response=gateway_response or {},
            service_reference={"deposit_request_id": str(deposit_request.pk)},
        )

        # Credit BDT to wallet (also creates ledger entries internally).
        wallet.credit_bdt(
            amount=amount_bdt,
            txn=txn,
            description=f"Deposit via {deposit_request.payment_method}: {amount_bdt} BDT",
            metadata={"deposit_request_id": str(deposit_request.pk)},
        )

        # Refresh wallet and apply credits (1 BDT = conversion_rate credits).
        wallet.refresh_from_db()
        old_credit = wallet.credit_balance
        wallet.credit_balance = wallet.credit_balance + amount_credits
        wallet.save(update_fields=["credit_balance", "updated_at"])

        # Create ledger entry for the credit conversion.
        import uuid as _uuid
        credit_ref = _uuid.uuid4()
        LedgerEntry.objects.create(
            entry_type="DEBIT",
            account_type="PLATFORM_REVENUE",
            wallet=wallet,
            amount=amount_credits,
            currency="CREDITS",
            balance_before=old_credit,
            balance_after=wallet.credit_balance,
            reference_id=credit_ref,
            transaction=txn,
            description=f"Credits granted from deposit: {amount_credits} credits",
            metadata={"conversion_rate": str(conversion_rate)},
        )
        LedgerEntry.objects.create(
            entry_type="CREDIT",
            account_type="USER_WALLET",
            wallet=wallet,
            amount=amount_credits,
            currency="CREDITS",
            balance_before=old_credit,
            balance_after=wallet.credit_balance,
            reference_id=credit_ref,
            transaction=txn,
            description=f"Credits added to user wallet: {amount_credits}",
            metadata={"conversion_rate": str(conversion_rate)},
        )

        # Mark transaction as completed.
        txn.status = TransactionStatus.COMPLETED
        txn.processed_at = timezone.now()
        txn.save(update_fields=["status", "processed_at", "updated_at"])

        # Mark deposit request as completed.
        deposit_request.status = DepositStatus.COMPLETED
        deposit_request.completed_at = timezone.now()
        deposit_request.save(update_fields=["status", "completed_at"])

        logger.info(
            "Deposit completed: user=%s amount_bdt=%s credits=%s txn=%s",
            deposit_request.user.username,
            amount_bdt,
            amount_credits,
            txn.transaction_id,
        )
        return txn

    # ------------------------------------------------------------------
    # Service debit
    # ------------------------------------------------------------------

    @transaction.atomic
    def debit_for_service(
        self,
        user: User,
        credits: Decimal,
        service_type: str,
        service_ref: Optional[dict] = None,
        ip_address: Optional[str] = None,
        device_id: Optional[str] = None,
    ) -> Transaction:
        """
        Debit platform credits for a consumed service (AI, streaming, marketplace, etc.).

        Args:
            user:         The user consuming the service.
            credits:      Number of platform credits to deduct.
            service_type: One of the TransactionType values (AI_USAGE, STREAMING, etc.).
            service_ref:  JSON dict with service-specific identifiers.
            ip_address:   Client IP address.
            device_id:    Client device identifier.

        Returns:
            The completed Transaction record.

        Raises:
            InsufficientFundsError: If user lacks enough credits.
            WalletFrozenError:      If the wallet is frozen.
            InvalidAmountError:     If credits amount is not positive.
        """
        if credits <= Decimal("0"):
            raise InvalidAmountError("Credits to debit must be positive.")

        valid_service_types = {
            TransactionType.AI_USAGE,
            TransactionType.STREAMING,
            TransactionType.MARKETPLACE,
            TransactionType.SUBSCRIPTION,
        }
        if service_type not in valid_service_types:
            raise ValidationError(
                f"Invalid service_type '{service_type}'. Must be one of: "
                f"{', '.join(valid_service_types)}",
                code="invalid_service_type",
            )

        wallet = self._get_wallet(user)

        if wallet.is_frozen:
            raise WalletFrozenError(
                f"Wallet is frozen. Cannot process service payment. "
                f"Reason: {wallet.frozen_reason}"
            )

        if wallet.credit_balance < credits:
            raise InsufficientFundsError(
                f"Insufficient credits. Available: {wallet.credit_balance}, "
                f"Required: {credits}"
            )

        bdt_equivalent = (credits / BDT_TO_CREDITS_RATE).quantize(
            Decimal("0.0001"), rounding=ROUND_DOWN
        )

        txn = Transaction.objects.create(
            user=user,
            wallet=wallet,
            transaction_type=service_type,
            payment_method=PaymentMethod.INTERNAL,
            amount_bdt=bdt_equivalent,
            amount_credits=credits,
            conversion_rate=BDT_TO_CREDITS_RATE,
            status=TransactionStatus.PROCESSING,
            ip_address=ip_address,
            device_id=device_id,
            service_reference=service_ref or {},
        )

        try:
            wallet.debit_credits(
                amount=credits,
                txn=txn,
                description=f"Service charge: {service_type} | {credits} credits",
                metadata={"service_ref": service_ref or {}},
            )
        except ValidationError as exc:
            txn.status = TransactionStatus.FAILED
            txn.save(update_fields=["status", "updated_at"])
            raise InsufficientFundsError(str(exc)) from exc

        txn.status = TransactionStatus.COMPLETED
        txn.processed_at = timezone.now()
        txn.save(update_fields=["status", "processed_at", "updated_at"])

        logger.info(
            "Service debit: user=%s service=%s credits=%s txn=%s",
            user.username,
            service_type,
            credits,
            txn.transaction_id,
        )
        return txn

    # ------------------------------------------------------------------
    # Refund
    # ------------------------------------------------------------------

    @transaction.atomic
    def process_refund(
        self,
        transaction_id: str,
        reason: str,
        performed_by: Optional[User] = None,
    ) -> Transaction:
        """
        Reverse a completed transaction and return credits to the user's wallet.

        Creates a new REFUND transaction linked to the original and restores
        the deducted credits. The original transaction is marked REVERSED.

        Args:
            transaction_id: The transaction_id string of the transaction to refund.
            reason:         Human-readable refund reason for audit trail.
            performed_by:   Admin or system user initiating the refund.

        Returns:
            The new REFUND Transaction record.

        Raises:
            Transaction.DoesNotExist: If transaction_id not found.
            WalletServiceError:       If the transaction is not refundable.
        """
        try:
            original_txn = Transaction.objects.select_related("wallet", "user").get(
                transaction_id=transaction_id
            )
        except Transaction.DoesNotExist:
            raise WalletServiceError(
                f"Transaction with ID {transaction_id} not found."
            )

        non_refundable_statuses = {
            TransactionStatus.REVERSED,
            TransactionStatus.FAILED,
            TransactionStatus.PENDING,
        }
        if original_txn.status in non_refundable_statuses:
            raise WalletServiceError(
                f"Transaction {transaction_id} cannot be refunded. "
                f"Current status: {original_txn.status}"
            )

        if original_txn.transaction_type == TransactionType.REFUND:
            raise WalletServiceError("Cannot refund a refund transaction.")

        if original_txn.transaction_type == TransactionType.DEPOSIT:
            raise WalletServiceError(
                "Deposit refunds require a withdrawal request, not a simple refund."
            )

        wallet = original_txn.wallet
        refund_credits = original_txn.amount_credits
        refund_bdt = original_txn.amount_bdt

        # Create the refund transaction.
        refund_txn = Transaction.objects.create(
            user=original_txn.user,
            wallet=wallet,
            transaction_type=TransactionType.REFUND,
            payment_method=PaymentMethod.INTERNAL,
            amount_bdt=refund_bdt,
            amount_credits=refund_credits,
            conversion_rate=original_txn.conversion_rate,
            status=TransactionStatus.PROCESSING,
            service_reference={
                "original_transaction_id": transaction_id,
                "refund_reason": reason,
            },
            notes=f"Refund for {transaction_id}: {reason}",
        )

        # Restore credits via ledger entries.
        import uuid as _uuid
        ref_id = _uuid.uuid4()
        credit_before = wallet.credit_balance
        credit_after = wallet.credit_balance + refund_credits

        LedgerEntry.objects.create(
            entry_type="DEBIT",
            account_type="REFUND_RESERVE",
            wallet=wallet,
            amount=refund_credits,
            currency="CREDITS",
            balance_before=credit_before,
            balance_after=credit_after,
            reference_id=ref_id,
            transaction=refund_txn,
            description=f"Refund reserve debit for {transaction_id}",
            metadata={"reason": reason},
        )
        LedgerEntry.objects.create(
            entry_type="CREDIT",
            account_type="USER_WALLET",
            wallet=wallet,
            amount=refund_credits,
            currency="CREDITS",
            balance_before=credit_before,
            balance_after=credit_after,
            reference_id=ref_id,
            transaction=refund_txn,
            description=f"Credits restored via refund of {transaction_id}",
            metadata={"reason": reason},
        )

        wallet.credit_balance = credit_after
        wallet.save(update_fields=["credit_balance", "updated_at"])

        # Mark original transaction as reversed.
        original_txn.status = TransactionStatus.REVERSED
        original_txn.notes = (
            f"{original_txn.notes}\nReversed by refund transaction: "
            f"{refund_txn.transaction_id} | Reason: {reason}"
        ).strip()
        original_txn.save(update_fields=["status", "notes", "updated_at"])

        # Finalize refund transaction.
        refund_txn.status = TransactionStatus.COMPLETED
        refund_txn.processed_at = timezone.now()
        refund_txn.save(update_fields=["status", "processed_at", "updated_at"])

        WalletAuditLog.objects.create(
            wallet=wallet,
            action=AuditAction.CREDIT_APPLIED,
            performed_by=performed_by,
            old_balance=credit_before,
            new_balance=credit_after,
            metadata={
                "event": "refund_processed",
                "original_txn": transaction_id,
                "refund_txn": refund_txn.transaction_id,
                "reason": reason,
            },
        )

        logger.info(
            "Refund processed: original=%s refund=%s credits=%s user=%s",
            transaction_id,
            refund_txn.transaction_id,
            refund_credits,
            original_txn.user.username,
        )
        return refund_txn

    # ------------------------------------------------------------------
    # Balance inquiry
    # ------------------------------------------------------------------

    def get_balance(self, user: User) -> dict:
        """
        Return current wallet balance information for a user.

        Args:
            user: The user whose balance to retrieve.

        Returns:
            A dictionary with the following keys:
                - bdt_balance (Decimal)
                - credit_balance (Decimal)
                - tier (str)
                - is_frozen (bool)
                - conversion_rate (Decimal)  1 BDT = N credits
        """
        wallet = self._get_wallet(user)

        WalletAuditLog.objects.create(
            wallet=wallet,
            action=AuditAction.BALANCE_CHECK,
            old_balance=wallet.balance,
            new_balance=wallet.balance,
            metadata={"event": "balance_inquiry"},
        )

        return {
            "bdt_balance": wallet.balance,
            "credit_balance": wallet.credit_balance,
            "tier": wallet.tier,
            "is_frozen": wallet.is_frozen,
            "conversion_rate": BDT_TO_CREDITS_RATE,
        }

    # ------------------------------------------------------------------
    # Credit transfer (family plans)
    # ------------------------------------------------------------------

    @transaction.atomic
    def transfer_credits(
        self,
        from_user: User,
        to_user: User,
        amount: Decimal,
        ip_address: Optional[str] = None,
    ) -> tuple[Transaction, Transaction]:
        """
        Transfer platform credits between users (e.g., family plan sharing).

        Creates a symmetric pair of transactions: DEBIT from sender, CREDIT to
        receiver with full ledger entries for both wallets.

        Args:
            from_user:  User sending the credits.
            to_user:    User receiving the credits.
            amount:     Number of credits to transfer (must be positive).
            ip_address: Client IP for audit logging.

        Returns:
            Tuple of (debit_transaction, credit_transaction).

        Raises:
            InsufficientFundsError: If from_user lacks sufficient credits.
            WalletFrozenError:      If either wallet is frozen.
            InvalidAmountError:     If amount is not positive.
            ValidationError:        If transferring to self.
        """
        if from_user.pk == to_user.pk:
            raise ValidationError(
                "Cannot transfer credits to yourself.", code="self_transfer"
            )

        if amount <= Decimal("0"):
            raise InvalidAmountError("Transfer amount must be positive.")

        from_wallet = self._get_wallet(from_user)
        to_wallet = self._get_wallet(to_user)

        if from_wallet.is_frozen:
            raise WalletFrozenError(
                f"Sender wallet is frozen: {from_wallet.frozen_reason}"
            )
        if to_wallet.is_frozen:
            raise WalletFrozenError(
                f"Recipient wallet is frozen: {to_wallet.frozen_reason}"
            )

        if from_wallet.credit_balance < amount:
            raise InsufficientFundsError(
                f"Insufficient credits. Available: {from_wallet.credit_balance}, "
                f"Requested: {amount}"
            )

        bdt_equivalent = (amount / BDT_TO_CREDITS_RATE).quantize(
            Decimal("0.0001"), rounding=ROUND_DOWN
        )
        import uuid as _uuid
        transfer_ref = _uuid.uuid4()

        # Outbound transaction (sender).
        debit_txn = Transaction.objects.create(
            user=from_user,
            wallet=from_wallet,
            transaction_type=TransactionType.BONUS,
            payment_method=PaymentMethod.INTERNAL,
            amount_bdt=bdt_equivalent,
            amount_credits=amount,
            conversion_rate=BDT_TO_CREDITS_RATE,
            status=TransactionStatus.PROCESSING,
            ip_address=ip_address,
            service_reference={
                "transfer_type": "family_plan",
                "to_user_id": str(to_user.pk),
                "transfer_ref": str(transfer_ref),
            },
            notes=f"Credit transfer to {to_user.username}",
        )

        # Inbound transaction (receiver).
        credit_txn = Transaction.objects.create(
            user=to_user,
            wallet=to_wallet,
            transaction_type=TransactionType.BONUS,
            payment_method=PaymentMethod.INTERNAL,
            amount_bdt=bdt_equivalent,
            amount_credits=amount,
            conversion_rate=BDT_TO_CREDITS_RATE,
            status=TransactionStatus.PROCESSING,
            ip_address=ip_address,
            service_reference={
                "transfer_type": "family_plan",
                "from_user_id": str(from_user.pk),
                "transfer_ref": str(transfer_ref),
            },
            notes=f"Credit transfer from {from_user.username}",
        )

        # Debit sender via wallet method.
        from_wallet.debit_credits(
            amount=amount,
            txn=debit_txn,
            description=f"Credits transferred to {to_user.username}",
            metadata={"transfer_ref": str(transfer_ref)},
        )

        # Credit receiver manually with ledger entries.
        from_wallet.refresh_from_db()
        old_to_credits = to_wallet.credit_balance
        new_to_credits = to_wallet.credit_balance + amount

        LedgerEntry.objects.create(
            entry_type="DEBIT",
            account_type="PLATFORM_REVENUE",
            wallet=to_wallet,
            amount=amount,
            currency="CREDITS",
            balance_before=old_to_credits,
            balance_after=new_to_credits,
            reference_id=transfer_ref,
            transaction=credit_txn,
            description=f"Credits received from {from_user.username}",
            metadata={"transfer_ref": str(transfer_ref)},
        )
        LedgerEntry.objects.create(
            entry_type="CREDIT",
            account_type="USER_WALLET",
            wallet=to_wallet,
            amount=amount,
            currency="CREDITS",
            balance_before=old_to_credits,
            balance_after=new_to_credits,
            reference_id=transfer_ref,
            transaction=credit_txn,
            description=f"Credits received from {from_user.username}",
            metadata={"transfer_ref": str(transfer_ref)},
        )

        to_wallet.credit_balance = new_to_credits
        to_wallet.save(update_fields=["credit_balance", "updated_at"])

        # Finalize both transactions.
        now = timezone.now()
        debit_txn.status = TransactionStatus.COMPLETED
        debit_txn.processed_at = now
        debit_txn.save(update_fields=["status", "processed_at", "updated_at"])

        credit_txn.status = TransactionStatus.COMPLETED
        credit_txn.processed_at = now
        credit_txn.save(update_fields=["status", "processed_at", "updated_at"])

        logger.info(
            "Credit transfer: from=%s to=%s amount=%s ref=%s",
            from_user.username,
            to_user.username,
            amount,
            transfer_ref,
        )
        return debit_txn, credit_txn

    # ------------------------------------------------------------------
    # Bonus / referral credits
    # ------------------------------------------------------------------

    @transaction.atomic
    def apply_bonus(
        self,
        user: User,
        credits: Decimal,
        reason: str,
        bonus_type: str = TransactionType.BONUS,
        performed_by: Optional[User] = None,
    ) -> Transaction:
        """
        Apply bonus or referral credits to a user's wallet.

        Used for promotional campaigns, referral rewards, and admin-granted credits.
        Bypasses the frozen check to allow admin override (admin must unfreeze first
        for regular service, but bonuses can be applied by system).

        Args:
            user:         The recipient user.
            credits:      Number of credits to grant.
            reason:       Description of why the bonus is being given.
            bonus_type:   TransactionType.BONUS or TransactionType.REFERRAL.
            performed_by: Admin user or None for system-generated bonuses.

        Returns:
            The completed BONUS/REFERRAL Transaction record.

        Raises:
            InvalidAmountError: If credits amount is not positive.
        """
        if credits <= Decimal("0"):
            raise InvalidAmountError("Bonus credits must be positive.")

        valid_bonus_types = {TransactionType.BONUS, TransactionType.REFERRAL}
        if bonus_type not in valid_bonus_types:
            raise ValidationError(
                f"Invalid bonus_type '{bonus_type}'.", code="invalid_bonus_type"
            )

        wallet = self._get_wallet(user)
        bdt_equivalent = (credits / BDT_TO_CREDITS_RATE).quantize(
            Decimal("0.0001"), rounding=ROUND_DOWN
        )

        txn = Transaction.objects.create(
            user=user,
            wallet=wallet,
            transaction_type=bonus_type,
            payment_method=PaymentMethod.SYSTEM,
            amount_bdt=bdt_equivalent,
            amount_credits=credits,
            conversion_rate=BDT_TO_CREDITS_RATE,
            status=TransactionStatus.PROCESSING,
            notes=reason,
            service_reference={
                "bonus_reason": reason,
                "granted_by": str(performed_by.pk) if performed_by else "SYSTEM",
            },
        )

        import uuid as _uuid
        ref_id = _uuid.uuid4()
        old_credits = wallet.credit_balance
        new_credits = wallet.credit_balance + credits

        LedgerEntry.objects.create(
            entry_type="DEBIT",
            account_type="PLATFORM_REVENUE",
            wallet=wallet,
            amount=credits,
            currency="CREDITS",
            balance_before=old_credits,
            balance_after=new_credits,
            reference_id=ref_id,
            transaction=txn,
            description=f"Bonus issued: {reason}",
            metadata={"bonus_type": bonus_type, "granted_by": str(performed_by.pk) if performed_by else "SYSTEM"},
        )
        LedgerEntry.objects.create(
            entry_type="CREDIT",
            account_type="USER_WALLET",
            wallet=wallet,
            amount=credits,
            currency="CREDITS",
            balance_before=old_credits,
            balance_after=new_credits,
            reference_id=ref_id,
            transaction=txn,
            description=f"Bonus credits added: {credits} | {reason}",
            metadata={"bonus_type": bonus_type},
        )

        wallet.credit_balance = new_credits
        wallet.save(update_fields=["credit_balance", "updated_at"])

        txn.status = TransactionStatus.COMPLETED
        txn.processed_at = timezone.now()
        txn.save(update_fields=["status", "processed_at", "updated_at"])

        WalletAuditLog.objects.create(
            wallet=wallet,
            action=AuditAction.CREDIT_APPLIED,
            performed_by=performed_by,
            old_balance=old_credits,
            new_balance=new_credits,
            metadata={
                "event": "bonus_applied",
                "bonus_type": bonus_type,
                "credits": str(credits),
                "reason": reason,
            },
        )

        logger.info(
            "Bonus applied: user=%s type=%s credits=%s txn=%s reason=%s",
            user.username,
            bonus_type,
            credits,
            txn.transaction_id,
            reason,
        )
        return txn

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_wallet(user: User) -> Wallet:
        """
        Retrieve the wallet for a user with SELECT FOR UPDATE to prevent races.

        Args:
            user: The user whose wallet to fetch.

        Returns:
            The Wallet instance (locked for update within an atomic block).

        Raises:
            WalletServiceError: If the user does not have a wallet.
        """
        try:
            return Wallet.objects.select_for_update().get(user=user)
        except Wallet.DoesNotExist:
            raise WalletServiceError(
                f"No wallet found for user {user.username}. "
                "Wallet may not have been created during registration."
            )

    @staticmethod
    def _validate_deposit_amount(amount: Decimal) -> None:
        """
        Validate deposit amount is within allowed bounds.

        Minimum: 10 BDT, Maximum: 50,000 BDT per transaction.
        """
        minimum = Decimal("10.00")
        maximum = Decimal("50000.00")

        if amount < minimum:
            raise InvalidAmountError(
                f"Minimum deposit amount is {minimum} BDT. Provided: {amount} BDT."
            )
        if amount > maximum:
            raise InvalidAmountError(
                f"Maximum deposit amount is {maximum} BDT. Provided: {amount} BDT."
            )

    @staticmethod
    def _initiate_gateway_payment(
        deposit_request: DepositRequest,
        payment_method: str,
        amount: Decimal,
        phone: Optional[str],
    ) -> dict:
        """
        Delegate to the appropriate payment gateway to obtain a payment URL.

        Args:
            deposit_request: The DepositRequest object for reference.
            payment_method:  One of BKASH, NAGAD, SSLCOMMERZ.
            amount:          BDT amount.
            phone:           Mobile number (for bKash/Nagad).

        Returns:
            A dict with keys: session_id, payment_url.
        """
        from django.conf import settings
        from .payment_gateways.bkash import BkashGateway
        from .payment_gateways.nagad import NagadGateway
        from .payment_gateways.sslcommerz import SSLCommerzGateway

        callback_base = getattr(settings, "SITE_URL", "https://app.doctime.com.bd")
        callback_url = f"{callback_base}/api/wallet/deposit/callback/"

        if payment_method == PaymentMethod.BKASH:
            gw = BkashGateway()
            result = gw.create_payment(
                amount=amount,
                phone=phone,
                callback_url=callback_url,
                merchant_invoice_number=str(deposit_request.pk),
            )
        elif payment_method == PaymentMethod.NAGAD:
            gw = NagadGateway()
            result = gw.create_payment(
                amount=amount,
                phone=phone,
                callback_url=callback_url,
                order_id=str(deposit_request.pk),
            )
        elif payment_method == PaymentMethod.SSLCOMMERZ:
            gw = SSLCommerzGateway()
            customer_data = {
                "cus_name": deposit_request.user.get_full_name() or deposit_request.user.username,
                "cus_email": deposit_request.user.email,
                "cus_phone": phone or "",
                "order_id": str(deposit_request.pk),
            }
            result = gw.create_transaction(
                amount=amount,
                customer_data=customer_data,
                callback_url=callback_url,
            )
        else:
            raise WalletServiceError(f"Unsupported payment method: {payment_method}")

        return result
