"""
Tests for apps.wallet — Wallet model, transactions, deposit/withdrawal endpoints.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework import status

User = get_user_model()


# ─── Wallet Model ────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestWalletModel:
    def test_wallet_created_with_defaults(self, db, make_user):
        from apps.wallet.models import Wallet, WalletTier
        user = make_user(phone="+8801711110001")
        wallet = Wallet.objects.create(user=user)
        assert wallet.balance_bdt == Decimal("0.00")
        assert wallet.credits == 0
        assert wallet.tier == WalletTier.BRONZE
        assert wallet.is_frozen is False

    def test_wallet_tier_bronze(self, db, make_user):
        from apps.wallet.models import Wallet, WalletTier
        user = make_user(phone="+8801711110002")
        wallet = Wallet.objects.create(user=user, balance_bdt="500.00")
        assert wallet.tier == WalletTier.BRONZE

    def test_wallet_one_per_user(self, db, make_user):
        from apps.wallet.models import Wallet
        from django.db import IntegrityError
        user = make_user(phone="+8801711110003")
        Wallet.objects.create(user=user)
        with pytest.raises(IntegrityError):
            Wallet.objects.create(user=user)

    def test_wallet_str_representation(self, db, make_user):
        from apps.wallet.models import Wallet
        user = make_user(phone="+8801711110004")
        wallet = Wallet.objects.create(user=user, balance_bdt="100.00")
        assert user.phone_number in str(wallet) or "100" in str(wallet)


# ─── Transaction Model ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestTransactionModel:
    def test_create_transaction(self, db, make_user):
        from apps.wallet.models import Wallet, Transaction, TransactionType, TransactionStatus, CurrencyType
        user = make_user(phone="+8801711110010")
        wallet = Wallet.objects.create(user=user)
        txn = Transaction.objects.create(
            wallet=wallet,
            user=user,
            transaction_type=TransactionType.DEPOSIT,
            amount=Decimal("500.00"),
            currency=CurrencyType.BDT,
            status=TransactionStatus.COMPLETED,
            description="Test deposit",
        )
        assert txn.transaction_id.startswith("TXN-")
        assert txn.amount == Decimal("500.00")
        assert txn.status == TransactionStatus.COMPLETED

    def test_transaction_id_unique(self, db, make_user):
        from apps.wallet.models import Wallet, Transaction, TransactionType, TransactionStatus, CurrencyType
        user = make_user(phone="+8801711110011")
        wallet = Wallet.objects.create(user=user)
        txn1 = Transaction.objects.create(
            wallet=wallet, user=user,
            transaction_type=TransactionType.DEPOSIT,
            amount="100.00", currency=CurrencyType.BDT,
            status=TransactionStatus.COMPLETED,
        )
        txn2 = Transaction.objects.create(
            wallet=wallet, user=user,
            transaction_type=TransactionType.DEPOSIT,
            amount="200.00", currency=CurrencyType.BDT,
            status=TransactionStatus.COMPLETED,
        )
        assert txn1.transaction_id != txn2.transaction_id


# ─── Wallet API Endpoints ────────────────────────────────────────────────────

@pytest.mark.django_db
class TestWalletAPI:
    def test_get_balance_requires_auth(self, api_client):
        response = api_client.get("/api/v1/wallet/balance/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_get_balance_authenticated(self, auth_client, wallet):
        response = auth_client.get("/api/v1/wallet/balance/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "balance_bdt" in data or "data" in data

    def test_get_transactions_authenticated(self, auth_client, wallet):
        response = auth_client.get("/api/v1/wallet/transactions/")
        assert response.status_code == status.HTTP_200_OK

    def test_get_transactions_requires_auth(self, api_client):
        response = api_client.get("/api/v1/wallet/transactions/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_initiate_deposit_requires_auth(self, api_client):
        response = api_client.post(
            "/api/v1/wallet/deposit/",
            {"method": "BKASH", "amount_bdt": "500"},
            format="json",
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_initiate_deposit_validates_minimum_amount(self, auth_client, wallet):
        response = auth_client.post(
            "/api/v1/wallet/deposit/",
            {"method": "BKASH", "amount_bdt": "1"},  # Below minimum
            format="json",
        )
        # Should reject with 400 or similar
        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


# ─── Wallet Constants ────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestWalletConstants:
    def test_bdt_to_credits_rate(self):
        from apps.wallet.models import BDT_TO_CREDITS_RATE
        assert BDT_TO_CREDITS_RATE == Decimal("10.0")

    def test_tier_thresholds(self):
        from apps.wallet.models import TIER_THRESHOLDS
        assert TIER_THRESHOLDS["BRONZE"] == Decimal("0")
        assert TIER_THRESHOLDS["SILVER"] == Decimal("1000")
        assert TIER_THRESHOLDS["GOLD"] == Decimal("5000")
        assert TIER_THRESHOLDS["PLATINUM"] == Decimal("20000")
