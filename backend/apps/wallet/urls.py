"""
Wallet URL Configuration.

All routes are prefixed with /api/wallet/ in the project's root urls.py.

Route summary:
    GET  /api/wallet/balance/             - Current balance and tier
    GET  /api/wallet/stats/               - Lifetime stats and tier progression
    GET  /api/wallet/conversion-rate/     - BDT to credits conversion rate
    GET  /api/wallet/transactions/        - Paginated transaction list
    GET  /api/wallet/transactions/{id}/   - Transaction detail (UUID or TXN-ID)
    POST /api/wallet/deposit/             - Initiate deposit
    POST /api/wallet/deposit/callback/    - Gateway webhook handler
    POST /api/wallet/withdraw/            - Submit withdrawal request
    GET  /api/wallet/withdraw/            - List withdrawal requests
"""

from django.urls import path

from .views import (
    CreditConversionView,
    DepositCallbackView,
    DepositInitiateView,
    WalletBalanceView,
    WalletStatsView,
    WalletTransactionDetailView,
    WalletTransactionListView,
    WithdrawalRequestView,
)

app_name = "wallet"

urlpatterns = [
    # -----------------------------------------------------------------------
    # Balance & stats
    # -----------------------------------------------------------------------
    path(
        "balance/",
        WalletBalanceView.as_view(),
        name="wallet-balance",
    ),
    path(
        "stats/",
        WalletStatsView.as_view(),
        name="wallet-stats",
    ),
    path(
        "conversion-rate/",
        CreditConversionView.as_view(),
        name="wallet-conversion-rate",
    ),
    # -----------------------------------------------------------------------
    # Transactions
    # -----------------------------------------------------------------------
    path(
        "transactions/",
        WalletTransactionListView.as_view(),
        name="wallet-transaction-list",
    ),
    path(
        "transactions/<str:pk>/",
        WalletTransactionDetailView.as_view(),
        name="wallet-transaction-detail",
    ),
    # -----------------------------------------------------------------------
    # Deposits
    # -----------------------------------------------------------------------
    path(
        "deposit/",
        DepositInitiateView.as_view(),
        name="wallet-deposit-initiate",
    ),
    path(
        "deposit/callback/",
        DepositCallbackView.as_view(),
        name="wallet-deposit-callback",
    ),
    # -----------------------------------------------------------------------
    # Withdrawals
    # -----------------------------------------------------------------------
    path(
        "withdraw/",
        WithdrawalRequestView.as_view(),
        name="wallet-withdrawal",
    ),
]
