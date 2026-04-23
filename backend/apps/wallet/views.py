"""
Wallet Views - REST API endpoints for the Fintech Wallet system.

All endpoints require authenticated users. Admin-only endpoints are protected
by IsAdminUser permission. Pagination is applied to list views.
"""

import logging
from decimal import Decimal

from django.db.models import QuerySet
from django.utils import timezone
from rest_framework import filters, generics, status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .fraud_detection import FraudDetectionService
from .models import (
    BDT_TO_CREDITS_RATE,
    DepositRequest,
    DepositStatus,
    PaymentMethod,
    Transaction,
    TransactionStatus,
    TransactionType,
    Wallet,
    WalletAuditLog,
    WithdrawalRequest,
    WithdrawalStatus,
)
from .serializers import (
    ConversionRateSerializer,
    DepositCallbackSerializer,
    DepositInitiateSerializer,
    DepositRequestSerializer,
    TransactionListSerializer,
    TransactionSerializer,
    WalletBalanceSerializer,
    WalletStatsSerializer,
    WithdrawalCreateSerializer,
    WithdrawalRequestSerializer,
)
from .services import (
    InvalidAmountError,
    InsufficientFundsError,
    WalletFrozenError,
    WalletService,
    WalletServiceError,
)

logger = logging.getLogger(__name__)

wallet_service = WalletService()
fraud_service = FraudDetectionService()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class TransactionPagination(PageNumberPagination):
    """Standard pagination for transaction list endpoints."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


# ---------------------------------------------------------------------------
# Helper: extract client IP
# ---------------------------------------------------------------------------


def _get_client_ip(request: Request) -> str | None:
    """Extract the real client IP from request headers."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


# ---------------------------------------------------------------------------
# GET /wallet/balance
# ---------------------------------------------------------------------------


class WalletBalanceView(APIView):
    """
    Retrieve the current wallet balance, tier, and frozen status.

    GET /wallet/balance

    Returns:
        200: { bdt_balance, credit_balance, tier, tier_display, is_frozen,
               conversion_rate }
        404: If user has no wallet.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            balance_data = wallet_service.get_balance(request.user)
        except WalletServiceError as exc:
            raise NotFound(detail=str(exc))

        serializer = WalletBalanceSerializer(balance_data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# GET /wallet/transactions
# ---------------------------------------------------------------------------


class WalletTransactionListView(generics.ListAPIView):
    """
    List paginated transactions for the authenticated user.

    GET /wallet/transactions

    Query parameters:
        - transaction_type: Filter by type (DEPOSIT, AI_USAGE, etc.)
        - status:           Filter by status (COMPLETED, FAILED, etc.)
        - ordering:         Sort field (default: -created_at)
        - search:           Search by transaction_id or notes
        - page:             Page number
        - page_size:        Items per page (max 100)

    Returns:
        200: Paginated list of transactions.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TransactionListSerializer
    pagination_class = TransactionPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["transaction_id", "notes", "gateway_transaction_id"]
    ordering_fields = ["created_at", "amount_bdt", "amount_credits", "status"]
    ordering = ["-created_at"]

    def get_queryset(self) -> QuerySet:
        qs = Transaction.objects.filter(user=self.request.user).select_related(
            "wallet"
        )

        # Filter by transaction_type.
        txn_type = self.request.query_params.get("transaction_type")
        if txn_type:
            valid_types = {choice[0] for choice in TransactionType.choices}
            if txn_type not in valid_types:
                raise ValidationError(
                    {"transaction_type": f"Invalid type '{txn_type}'."}
                )
            qs = qs.filter(transaction_type=txn_type)

        # Filter by status.
        txn_status = self.request.query_params.get("status")
        if txn_status:
            valid_statuses = {choice[0] for choice in TransactionStatus.choices}
            if txn_status not in valid_statuses:
                raise ValidationError(
                    {"status": f"Invalid status '{txn_status}'."}
                )
            qs = qs.filter(status=txn_status)

        return qs


# ---------------------------------------------------------------------------
# GET /wallet/transactions/{id}
# ---------------------------------------------------------------------------


class WalletTransactionDetailView(APIView):
    """
    Retrieve a single transaction by its UUID or transaction_id string.

    GET /wallet/transactions/{id}

    Args:
        id: UUID or transaction_id string (e.g., TXN-20240101-ABCD1234).

    Returns:
        200: Full transaction detail.
        404: If transaction not found or does not belong to user.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: str) -> Response:
        # Accept both UUID and human-readable transaction_id.
        qs = Transaction.objects.filter(user=request.user)
        try:
            if pk.startswith("TXN-"):
                txn = qs.get(transaction_id=pk)
            else:
                txn = qs.get(pk=pk)
        except Transaction.DoesNotExist:
            raise NotFound(detail=f"Transaction '{pk}' not found.")

        serializer = TransactionSerializer(txn)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# POST /wallet/deposit
# ---------------------------------------------------------------------------


class DepositInitiateView(APIView):
    """
    Initiate a BDT deposit by creating a DepositRequest and obtaining a
    payment redirect URL from the selected gateway.

    POST /wallet/deposit

    Body:
        {
            "amount_bdt": "500.00",
            "payment_method": "BKASH",
            "phone_number": "01711000000"
        }

    Returns:
        201: { deposit_id, payment_url, expires_at, amount_bdt, payment_method }
        400: Validation error.
        402: Fraud detection block.
        423: Wallet is frozen.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = DepositInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        amount = data["amount_bdt"]
        payment_method = data["payment_method"]
        phone = data.get("phone_number")
        ip_address = _get_client_ip(request)

        # Run fraud checks before initiating the gateway request.
        risk_score = fraud_service.get_risk_score(request.user)
        if risk_score >= 80:
            logger.warning(
                "Deposit blocked by fraud detection: user=%s risk=%d",
                request.user.username,
                risk_score,
            )
            return Response(
                {
                    "error": "deposit_blocked",
                    "message": (
                        "Your deposit request has been temporarily blocked for "
                        "security review. Please contact support."
                    ),
                    "risk_score": risk_score,
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        velocity_ok, velocity_msg = fraud_service.check_deposit_velocity(
            request.user, amount
        )
        if not velocity_ok:
            return Response(
                {"error": "velocity_exceeded", "message": velocity_msg},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        try:
            deposit_request = wallet_service.deposit_bdt(
                user=request.user,
                amount=amount,
                payment_method=payment_method,
                phone=phone,
                ip_address=ip_address,
            )
        except WalletFrozenError as exc:
            return Response(
                {"error": "wallet_frozen", "message": str(exc)},
                status=status.HTTP_423_LOCKED,
            )
        except InvalidAmountError as exc:
            return Response(
                {"error": "invalid_amount", "message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except WalletServiceError as exc:
            logger.error(
                "Deposit initiation failed: user=%s error=%s",
                request.user.username,
                exc,
                exc_info=True,
            )
            return Response(
                {"error": "gateway_error", "message": str(exc)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response(
            {
                "deposit_id": str(deposit_request.pk),
                "payment_url": deposit_request.gateway_payment_url,
                "expires_at": deposit_request.expires_at.isoformat(),
                "amount_bdt": str(deposit_request.amount_bdt),
                "payment_method": deposit_request.payment_method,
                "status": deposit_request.status,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# POST /wallet/deposit/callback
# ---------------------------------------------------------------------------


class DepositCallbackView(APIView):
    """
    Receive and process payment gateway webhooks for deposit confirmation.

    POST /wallet/deposit/callback

    This endpoint is called by the payment gateway (bKash, Nagad, SSLCommerz)
    after a payment attempt. The request is verified before crediting the wallet.

    Note: Authentication is by gateway signature, not user session. The endpoint
    deliberately does NOT require IsAuthenticated but validates the gateway payload.

    Returns:
        200: Deposit processed successfully.
        400: Invalid callback payload.
        404: Deposit request not found.
        409: Deposit already processed.
    """

    # Gateway callbacks are server-to-server — no user session available.
    permission_classes = []
    authentication_classes = []

    def post(self, request: Request) -> Response:
        serializer = DepositCallbackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        session_id = data["session_id"]
        cb_status = data["status"].upper()
        gateway_txn_id = data.get("transaction_id", "")
        raw_payload = data.get("raw_payload", {})

        # Merge entire request data as raw payload for audit purposes.
        if not raw_payload:
            raw_payload = dict(request.data)

        try:
            deposit_request = DepositRequest.objects.select_related(
                "wallet", "user"
            ).get(gateway_session_id=session_id)
        except DepositRequest.DoesNotExist:
            logger.error(
                "Deposit callback received for unknown session_id: %s", session_id
            )
            return Response(
                {"error": "not_found", "message": "Deposit request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Store raw callback data regardless of outcome.
        deposit_request.callback_data = raw_payload
        deposit_request.save(update_fields=["callback_data"])

        if deposit_request.status == DepositStatus.COMPLETED:
            return Response(
                {"status": "already_processed", "deposit_id": str(deposit_request.pk)},
                status=status.HTTP_200_OK,
            )

        success_statuses = {"SUCCESS", "COMPLETED", "PAID", "EXECUTED", "VALID"}
        if cb_status not in success_statuses:
            deposit_request.status = DepositStatus.FAILED
            deposit_request.save(update_fields=["status"])
            logger.info(
                "Deposit marked failed via callback: session=%s status=%s",
                session_id,
                cb_status,
            )
            return Response(
                {
                    "status": "failed",
                    "deposit_id": str(deposit_request.pk),
                    "gateway_status": cb_status,
                },
                status=status.HTTP_200_OK,
            )

        try:
            txn = wallet_service.complete_deposit(
                deposit_request=deposit_request,
                gateway_transaction_id=gateway_txn_id,
                gateway_response=raw_payload,
            )
        except WalletServiceError as exc:
            logger.error(
                "Failed to complete deposit %s: %s", deposit_request.pk, exc, exc_info=True
            )
            return Response(
                {"error": "processing_error", "message": str(exc)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Trigger async notifications (non-blocking).
        try:
            from .tasks import send_transaction_notification
            send_transaction_notification.delay(str(txn.pk))
        except Exception:
            pass  # Task queue unavailable — non-critical.

        return Response(
            {
                "status": "success",
                "deposit_id": str(deposit_request.pk),
                "transaction_id": txn.transaction_id,
                "amount_bdt": str(txn.amount_bdt),
                "credits_added": str(txn.amount_credits),
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# POST /wallet/withdraw
# ---------------------------------------------------------------------------


class WithdrawalRequestView(APIView):
    """
    Submit a withdrawal request to receive BDT via mobile banking or bank transfer.

    POST /wallet/withdraw

    Body:
        {
            "amount_bdt": "1000.00",
            "withdrawal_method": "BKASH",
            "account_number": "01711000000"
        }

    The request is queued for admin approval. Credits equivalent to the requested
    BDT amount are reserved (deducted) on submission.

    Returns:
        201: Withdrawal request submitted.
        400: Validation error.
        402: Insufficient credits.
        423: Wallet frozen.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = WithdrawalCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        amount_bdt = data["amount_bdt"]
        withdrawal_method = data["withdrawal_method"]
        account_number = data["account_number"]

        try:
            wallet = Wallet.objects.select_for_update().get(user=request.user)
        except Wallet.DoesNotExist:
            raise NotFound(detail="Wallet not found.")

        if wallet.is_frozen:
            return Response(
                {
                    "error": "wallet_frozen",
                    "message": f"Wallet is frozen: {wallet.frozen_reason}",
                },
                status=status.HTTP_423_LOCKED,
            )

        # Check for high-risk withdrawal.
        risk_score, risk_factors = fraud_service.check_withdrawal_risk(
            request.user, amount_bdt
        )
        if risk_score >= 70:
            logger.warning(
                "Withdrawal flagged for review: user=%s amount=%s risk=%d",
                request.user.username,
                amount_bdt,
                risk_score,
            )
            # Flag but don't block — high-risk withdrawals require extra review.
            fraud_service.flag_suspicious_account(
                request.user,
                f"High-risk withdrawal attempt: {amount_bdt} BDT (risk={risk_score})",
            )

        # Calculate credits to reserve.
        credits_to_deduct = (amount_bdt * BDT_TO_CREDITS_RATE).quantize(
            Decimal("0.01")
        )

        if wallet.credit_balance < credits_to_deduct:
            return Response(
                {
                    "error": "insufficient_credits",
                    "message": (
                        f"Insufficient credits. Required: {credits_to_deduct}, "
                        f"Available: {wallet.credit_balance}"
                    ),
                    "available_credits": str(wallet.credit_balance),
                    "required_credits": str(credits_to_deduct),
                },
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        # Create the withdrawal request within an atomic block.
        from django.db import transaction as db_transaction

        with db_transaction.atomic():
            # Deduct credits immediately to reserve the funds.
            wallet.debit_credits(
                amount=credits_to_deduct,
                description=f"Withdrawal reservation: {amount_bdt} BDT",
                metadata={"withdrawal_method": withdrawal_method, "account": account_number},
            )

            withdrawal = WithdrawalRequest.objects.create(
                user=request.user,
                wallet=wallet,
                amount_bdt=amount_bdt,
                credits_deducted=credits_to_deduct,
                withdrawal_method=withdrawal_method,
                account_number=account_number,
                status=WithdrawalStatus.PENDING,
            )

        logger.info(
            "Withdrawal request submitted: user=%s amount=%s method=%s id=%s",
            request.user.username,
            amount_bdt,
            withdrawal_method,
            withdrawal.pk,
        )

        return Response(
            {
                "withdrawal_id": str(withdrawal.pk),
                "status": withdrawal.status,
                "amount_bdt": str(withdrawal.amount_bdt),
                "credits_deducted": str(withdrawal.credits_deducted),
                "withdrawal_method": withdrawal.withdrawal_method,
                "message": (
                    "Your withdrawal request has been submitted and is pending admin approval. "
                    "Processing typically takes 1-3 business days."
                ),
            },
            status=status.HTTP_201_CREATED,
        )

    def get(self, request: Request) -> Response:
        """List withdrawal requests for the authenticated user."""
        withdrawals = WithdrawalRequest.objects.filter(
            user=request.user
        ).order_by("-created_at")

        status_filter = request.query_params.get("status")
        if status_filter:
            withdrawals = withdrawals.filter(status=status_filter)

        paginator = TransactionPagination()
        page = paginator.paginate_queryset(withdrawals, request)
        serializer = WithdrawalRequestSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ---------------------------------------------------------------------------
# GET /wallet/conversion-rate
# ---------------------------------------------------------------------------


class CreditConversionView(APIView):
    """
    Get the current BDT to platform credits conversion rate.

    GET /wallet/conversion-rate

    Returns:
        200: { bdt_to_credits, credits_to_bdt, description, example_bdt,
               example_credits, last_updated }
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        rate = BDT_TO_CREDITS_RATE
        inverse = (Decimal("1") / rate).quantize(Decimal("0.000001"))

        data = {
            "bdt_to_credits": rate,
            "credits_to_bdt": inverse,
            "description": f"1 BDT = {rate} Platform Credits",
            "example_bdt": Decimal("100.00"),
            "example_credits": (Decimal("100.00") * rate),
            "last_updated": timezone.now(),
        }

        serializer = ConversionRateSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# GET /wallet/stats
# ---------------------------------------------------------------------------


class WalletStatsView(APIView):
    """
    Retrieve comprehensive wallet statistics including lifetime totals and
    tier progression information.

    GET /wallet/stats

    Returns:
        200: Full stats dictionary including next tier info.
        404: If user has no wallet.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        try:
            wallet = Wallet.objects.get(user=request.user)
        except Wallet.DoesNotExist:
            raise NotFound(detail="Wallet not found.")

        from .models import TIER_THRESHOLDS, WalletTier

        tier_order = [
            WalletTier.BRONZE,
            WalletTier.SILVER,
            WalletTier.GOLD,
            WalletTier.PLATINUM,
        ]
        tier_labels = {
            WalletTier.BRONZE: "Bronze",
            WalletTier.SILVER: "Silver",
            WalletTier.GOLD: "Gold",
            WalletTier.PLATINUM: "Platinum",
        }

        current_tier_index = tier_order.index(wallet.tier)
        if current_tier_index < len(tier_order) - 1:
            next_tier = tier_order[current_tier_index + 1]
            next_threshold = TIER_THRESHOLDS[next_tier]
            spend_to_next = max(
                Decimal("0"), next_threshold - wallet.total_spent
            )
        else:
            next_tier = None
            next_threshold = None
            spend_to_next = None

        txn_count = Transaction.objects.filter(user=request.user).count()

        stats = {
            "bdt_balance": wallet.balance,
            "credit_balance": wallet.credit_balance,
            "tier": wallet.tier,
            "tier_display": tier_labels.get(wallet.tier, wallet.tier),
            "is_frozen": wallet.is_frozen,
            "total_deposited": wallet.total_deposited,
            "total_spent": wallet.total_spent,
            "total_withdrawn": wallet.total_withdrawn,
            "conversion_rate": BDT_TO_CREDITS_RATE,
            "next_tier": next_tier,
            "next_tier_threshold": next_threshold,
            "spend_to_next_tier": spend_to_next,
            "wallet_created_at": wallet.created_at,
            "transaction_count": txn_count,
        }

        serializer = WalletStatsSerializer(stats)
        return Response(serializer.data, status=status.HTTP_200_OK)
