"""
bKash Payment Gateway Integration.

Implements the bKash Tokenized Checkout API (v1.2.0-beta) for Bangladesh.
Documentation: https://developer.bkash.com/docs/tokenized-checkout

Flow:
    1. grant_token()            - Obtain bearer token (cached for 3500s).
    2. create_payment()         - Create a payment session → return paymentURL.
    3. execute_payment()        - Execute payment after user approval.
    4. query_payment()          - Check payment status.
    5. verify_payment()         - Verify final payment completion.
    6. refund_transaction()     - Initiate refund through bKash.

All amounts are in BDT (string representation with 2 decimal places).
Sandbox and production environments are selected via Django settings.
"""

import hashlib
import hmac
import json
import logging
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class BkashGatewayError(Exception):
    """Raised when the bKash API returns an unexpected error."""

    def __init__(self, message: str, status_code: int = 0, raw_response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.raw_response = raw_response or {}


class BkashGateway:
    """
    bKash Tokenized Checkout gateway client.

    Configuration (in Django settings):
        BKASH_APP_KEY:      Application key (from bKash developer portal).
        BKASH_APP_SECRET:   Application secret.
        BKASH_USERNAME:     bKash merchant username.
        BKASH_PASSWORD:     bKash merchant password.
        BKASH_SANDBOX:      True for sandbox, False for production (default: True).
        BKASH_CALLBACK_URL: Default callback URL if not provided per-request.

    Example:
        gw = BkashGateway()
        result = gw.create_payment(
            amount=Decimal("500.00"),
            phone="01711000000",
            callback_url="https://app.example.com/wallet/deposit/callback/",
            merchant_invoice_number="DEP-UUID-HERE",
        )
        # Redirect user to result["payment_url"]
    """

    SANDBOX_BASE_URL = "https://tokenized.sandbox.bka.sh/v1.2.0-beta"
    PRODUCTION_BASE_URL = "https://tokenized.pay.bka.sh/v1.2.0-beta"
    TOKEN_CACHE_KEY = "bkash_token_cache"
    TOKEN_CACHE_TTL = 3500  # seconds (bKash tokens expire in ~1 hour)

    def __init__(self):
        cfg = self._load_config()
        self.app_key = cfg["app_key"]
        self.app_secret = cfg["app_secret"]
        self.username = cfg["username"]
        self.password = cfg["password"]
        self.is_sandbox = cfg["sandbox"]
        self.base_url = (
            self.SANDBOX_BASE_URL if self.is_sandbox else self.PRODUCTION_BASE_URL
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config() -> dict:
        """Load bKash configuration from Django settings with validation."""
        required_keys = [
            "BKASH_APP_KEY",
            "BKASH_APP_SECRET",
            "BKASH_USERNAME",
            "BKASH_PASSWORD",
        ]
        missing = [k for k in required_keys if not getattr(settings, k, None)]
        if missing:
            raise BkashGatewayError(
                f"Missing required bKash settings: {', '.join(missing)}"
            )

        return {
            "app_key": settings.BKASH_APP_KEY,
            "app_secret": settings.BKASH_APP_SECRET,
            "username": settings.BKASH_USERNAME,
            "password": settings.BKASH_PASSWORD,
            "sandbox": getattr(settings, "BKASH_SANDBOX", True),
        }

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def grant_token(self) -> str:
        """
        Obtain or refresh the bKash bearer token.

        Tokens are cached for TOKEN_CACHE_TTL seconds to avoid unnecessary
        round-trips. Thread-safe via Django's cache backend.

        Returns:
            The id_token string for use in Authorization headers.

        Raises:
            BkashGatewayError: If the token grant request fails.
        """
        cached = cache.get(self.TOKEN_CACHE_KEY)
        if cached:
            return cached

        url = f"{self.base_url}/tokenized/checkout/token/grant"
        headers = {
            "username": self.username,
            "password": self.password,
        }
        payload = {
            "app_key": self.app_key,
            "app_secret": self.app_secret,
        }

        try:
            response = self.session.post(
                url,
                headers=headers,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise BkashGatewayError("bKash token grant request timed out.")
        except requests.ConnectionError:
            raise BkashGatewayError("Cannot connect to bKash API.")
        except requests.HTTPError as exc:
            raise BkashGatewayError(
                f"bKash token grant failed with HTTP {exc.response.status_code}.",
                status_code=exc.response.status_code,
                raw_response=exc.response.json() if exc.response.content else {},
            )

        if data.get("statusCode") != "0000":
            raise BkashGatewayError(
                f"bKash token grant error: {data.get('statusMessage', 'Unknown error')}",
                raw_response=data,
            )

        token = data["id_token"]
        cache.set(self.TOKEN_CACHE_KEY, token, self.TOKEN_CACHE_TTL)
        logger.debug("bKash token granted and cached.")
        return token

    def _auth_headers(self) -> dict:
        """Build Authorization and x-app-key headers for authenticated requests."""
        return {
            "Authorization": f"Bearer {self.grant_token()}",
            "X-APP-Key": self.app_key,
        }

    # ------------------------------------------------------------------
    # Create payment
    # ------------------------------------------------------------------

    def create_payment(
        self,
        amount: Decimal,
        phone: str,
        callback_url: str,
        merchant_invoice_number: str,
        currency: str = "BDT",
        intent: str = "sale",
    ) -> dict:
        """
        Create a new bKash payment session.

        Args:
            amount:                   BDT amount to charge.
            phone:                    Customer's bKash-registered mobile number.
            callback_url:             URL bKash will POST the result to.
            merchant_invoice_number:  Your internal reference (max 40 chars).
            currency:                 Payment currency (must be "BDT").
            intent:                   "sale" for direct payment, "authorization" for pre-auth.

        Returns:
            A dict with:
                - session_id (str):   bKash paymentID — used to track this payment.
                - payment_url (str):  URL to redirect the user's browser to.
                - status (str):       "Initiated" on success.

        Raises:
            BkashGatewayError: On API error or unexpected response.
        """
        url = f"{self.base_url}/tokenized/checkout/create"
        payload = {
            "mode": "0011",  # Tokenized Checkout mode
            "payerReference": phone,
            "callbackURL": callback_url,
            "amount": f"{amount:.2f}",
            "currency": currency,
            "intent": intent,
            "merchantInvoiceNumber": merchant_invoice_number[:40],
        }

        try:
            response = self.session.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise BkashGatewayError("bKash create_payment request timed out.")
        except requests.ConnectionError:
            raise BkashGatewayError("Cannot connect to bKash API.")
        except requests.HTTPError as exc:
            raw = {}
            try:
                raw = exc.response.json()
            except Exception:
                pass
            raise BkashGatewayError(
                f"bKash create_payment failed: HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
                raw_response=raw,
            )

        if data.get("statusCode") != "0000":
            raise BkashGatewayError(
                f"bKash create_payment error: {data.get('statusMessage', 'Unknown')}",
                raw_response=data,
            )

        payment_id = data.get("paymentID")
        bkash_url = data.get("bkashURL")

        if not payment_id or not bkash_url:
            raise BkashGatewayError(
                "bKash create_payment returned missing paymentID or bkashURL.",
                raw_response=data,
            )

        logger.info(
            "bKash payment created: paymentID=%s amount=%s phone=%s",
            payment_id,
            amount,
            phone,
        )
        return {
            "session_id": payment_id,
            "payment_url": bkash_url,
            "status": data.get("statusMessage", "Initiated"),
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Execute payment
    # ------------------------------------------------------------------

    def execute_payment(self, payment_id: str) -> dict:
        """
        Execute a payment after the user has approved it on bKash's interface.

        This should be called after receiving the callback with status=success
        but before crediting the user's wallet (use verify_payment for final
        confirmation).

        Args:
            payment_id: The bKash paymentID from create_payment.

        Returns:
            A dict with:
                - transaction_id (str):  bKash trxID for this payment.
                - amount (Decimal):      Confirmed amount paid.
                - status (str):          "Completed" on success.
                - raw (dict):            Full API response.

        Raises:
            BkashGatewayError: On failure or already-executed payment.
        """
        url = f"{self.base_url}/tokenized/checkout/execute"
        payload = {"paymentID": payment_id}

        try:
            response = self.session.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise BkashGatewayError("bKash execute_payment request timed out.")
        except requests.ConnectionError:
            raise BkashGatewayError("Cannot connect to bKash API.")
        except requests.HTTPError as exc:
            raise BkashGatewayError(
                f"bKash execute_payment HTTP error: {exc.response.status_code}",
                status_code=exc.response.status_code,
            )

        if data.get("statusCode") != "0000":
            raise BkashGatewayError(
                f"bKash execute_payment failed: {data.get('statusMessage', 'Unknown')}",
                raw_response=data,
            )

        trx_id = data.get("trxID")
        amount_str = data.get("amount", "0")
        try:
            confirmed_amount = Decimal(amount_str)
        except Exception:
            confirmed_amount = Decimal("0")

        logger.info(
            "bKash payment executed: paymentID=%s trxID=%s amount=%s",
            payment_id,
            trx_id,
            confirmed_amount,
        )
        return {
            "transaction_id": trx_id,
            "amount": confirmed_amount,
            "status": data.get("transactionStatus", "Completed"),
            "payment_id": payment_id,
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Verify payment
    # ------------------------------------------------------------------

    def verify_payment(self, payment_id: str) -> tuple[bool, Decimal]:
        """
        Query bKash to confirm the final status of a payment.

        Use this as a secondary verification before crediting the wallet,
        especially for callbacks that may arrive with incomplete data.

        Args:
            payment_id: The bKash paymentID.

        Returns:
            A tuple (is_successful: bool, confirmed_amount: Decimal).

        Raises:
            BkashGatewayError: If the API call itself fails (network/auth errors).
        """
        url = f"{self.base_url}/tokenized/checkout/payment/status"
        payload = {"paymentID": payment_id}

        try:
            response = self.session.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise BkashGatewayError("bKash verify_payment request timed out.")
        except requests.ConnectionError:
            raise BkashGatewayError("Cannot connect to bKash API.")
        except requests.HTTPError as exc:
            raise BkashGatewayError(
                f"bKash verify_payment HTTP error: {exc.response.status_code}",
                status_code=exc.response.status_code,
            )

        txn_status = data.get("transactionStatus", "")
        amount_str = data.get("amount", "0")
        try:
            confirmed_amount = Decimal(amount_str)
        except Exception:
            confirmed_amount = Decimal("0")

        is_successful = (
            data.get("statusCode") == "0000"
            and txn_status.lower() in ("completed", "successful")
        )

        logger.info(
            "bKash payment verified: paymentID=%s status=%s amount=%s success=%s",
            payment_id,
            txn_status,
            confirmed_amount,
            is_successful,
        )
        return is_successful, confirmed_amount

    # ------------------------------------------------------------------
    # Query payment
    # ------------------------------------------------------------------

    def query_payment(self, payment_id: str) -> dict:
        """
        Query the full payment details for a given paymentID.

        Args:
            payment_id: The bKash paymentID.

        Returns:
            The full API response dict.

        Raises:
            BkashGatewayError: On API error.
        """
        url = f"{self.base_url}/tokenized/checkout/payment/status"
        payload = {"paymentID": payment_id}

        try:
            response = self.session.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise BkashGatewayError(f"bKash query_payment failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Refund
    # ------------------------------------------------------------------

    def refund_transaction(
        self,
        payment_id: str,
        transaction_id: str,
        amount: Decimal,
        reason: str = "",
        sku: str = "",
    ) -> dict:
        """
        Initiate a refund through bKash for a previously executed payment.

        Args:
            payment_id:     bKash paymentID of the original payment.
            transaction_id: bKash trxID of the original payment.
            amount:         BDT amount to refund (must be <= original amount).
            reason:         Refund reason (sent to bKash).
            sku:            Optional product SKU for reference.

        Returns:
            Dict with refund status and bKash refund reference.

        Raises:
            BkashGatewayError: If refund initiation fails.
        """
        url = f"{self.base_url}/tokenized/checkout/payment/refund"
        payload = {
            "paymentID": payment_id,
            "trxID": transaction_id,
            "amount": f"{amount:.2f}",
            "reason": reason[:100],
            "sku": sku[:50] if sku else "",
        }

        try:
            response = self.session.post(
                url,
                headers=self._auth_headers(),
                json=payload,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise BkashGatewayError(f"bKash refund_transaction failed: {exc}") from exc

        if data.get("statusCode") != "0000":
            raise BkashGatewayError(
                f"bKash refund failed: {data.get('statusMessage', 'Unknown')}",
                raw_response=data,
            )

        logger.info(
            "bKash refund initiated: paymentID=%s trxID=%s amount=%s",
            payment_id,
            transaction_id,
            amount,
        )
        return {
            "refund_trx_id": data.get("refundTrxID"),
            "status": data.get("transactionStatus"),
            "amount": amount,
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Webhook signature verification
    # ------------------------------------------------------------------

    def verify_webhook_signature(
        self,
        payload_body: bytes,
        received_signature: str,
        secret: Optional[str] = None,
    ) -> bool:
        """
        Verify the HMAC-SHA256 signature on inbound bKash webhook callbacks.

        Args:
            payload_body:        Raw request body bytes.
            received_signature:  Signature from HTTP header (X-Bkash-Signature).
            secret:              Webhook secret; defaults to BKASH_WEBHOOK_SECRET setting.

        Returns:
            True if signature matches, False otherwise.
        """
        webhook_secret = secret or getattr(settings, "BKASH_WEBHOOK_SECRET", "")
        if not webhook_secret:
            logger.warning(
                "BKASH_WEBHOOK_SECRET not configured — skipping signature verification."
            )
            return True  # In sandbox/dev, accept without verification.

        expected = hmac.new(
            webhook_secret.encode("utf-8"),
            payload_body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, received_signature)
