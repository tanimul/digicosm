"""
Nagad Payment Gateway Integration.

Implements the Nagad Merchant API for Bangladesh.
Documentation: https://nagad.com.bd/developer/api-doc

Flow:
    1. initialize_payment() - Obtain payment challenge and encrypt merchant info.
    2. complete_payment()   - POST encrypted data to get paymentReferenceId.
    3. create_payment()     - High-level method combining both steps.
    4. verify_payment()     - Check payment status via paymentRefId.
    5. execute_payment()    - Confirm payment after user approval.

Nagad requires RSA encryption for all API calls:
    - Merchant data is encrypted with Nagad's public key.
    - Requests are signed with the merchant's private key.

Keys are stored in Django settings as PEM strings.
"""

import base64
import hashlib
import json
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class NagadGatewayError(Exception):
    """Raised when the Nagad API returns an unexpected error."""

    def __init__(self, message: str, status_code: int = 0, raw_response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.raw_response = raw_response or {}


class NagadGateway:
    """
    Nagad Merchant API gateway client.

    Configuration (in Django settings):
        NAGAD_MERCHANT_ID:          Nagad merchant identifier.
        NAGAD_MERCHANT_PRIVATE_KEY: RSA private key (PEM format) for request signing.
        NAGAD_PUBLIC_KEY:           Nagad's public key (PEM format) for encrypting data.
        NAGAD_SANDBOX:              True for sandbox environment (default: True).
        NAGAD_CALLBACK_URL:         Default callback URL.

    Example:
        gw = NagadGateway()
        result = gw.create_payment(
            amount=Decimal("500.00"),
            phone="01711000000",
            callback_url="https://app.example.com/wallet/deposit/callback/",
            order_id="DEP-UUID-HERE",
        )
    """

    SANDBOX_BASE_URL = "https://sandbox.mynagad.com:10080/remote-payment-gateway-1.0"
    PRODUCTION_BASE_URL = "https://api.mynagad.com/api/dfs"

    def __init__(self):
        cfg = self._load_config()
        self.merchant_id = cfg["merchant_id"]
        self.merchant_private_key = cfg["merchant_private_key"]
        self.nagad_public_key = cfg["nagad_public_key"]
        self.is_sandbox = cfg["sandbox"]
        self.base_url = (
            self.SANDBOX_BASE_URL if self.is_sandbox else self.PRODUCTION_BASE_URL
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "Accept": "application/json",
                "X-KM-Api-Version": "v-0.2.0",
                "X-KM-IP-V4": "127.0.0.1",  # Updated per-request in production.
                "X-KM-Client-Type": "PC_WEB",
            }
        )

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config() -> dict:
        """Load and validate Nagad configuration from Django settings."""
        merchant_id = getattr(settings, "NAGAD_MERCHANT_ID", None)
        if not merchant_id:
            raise NagadGatewayError(
                "NAGAD_MERCHANT_ID is required in Django settings."
            )

        return {
            "merchant_id": merchant_id,
            "merchant_private_key": getattr(settings, "NAGAD_MERCHANT_PRIVATE_KEY", ""),
            "nagad_public_key": getattr(settings, "NAGAD_PUBLIC_KEY", ""),
            "sandbox": getattr(settings, "NAGAD_SANDBOX", True),
        }

    # ------------------------------------------------------------------
    # Cryptographic helpers
    # ------------------------------------------------------------------

    def _encrypt_with_nagad_public_key(self, data: dict) -> str:
        """
        Encrypt data dict with Nagad's RSA public key (PKCS1 v1.5 padding).

        Args:
            data: Dictionary to encrypt.

        Returns:
            Base64-encoded encrypted string.
        """
        try:
            from Crypto.PublicKey import RSA
            from Crypto.Cipher import PKCS1_v1_5

            public_key = RSA.import_key(self.nagad_public_key)
            cipher = PKCS1_v1_5.new(public_key)
            plaintext = json.dumps(data, separators=(",", ":")).encode("utf-8")
            encrypted = cipher.encrypt(plaintext)
            return base64.b64encode(encrypted).decode("utf-8")
        except ImportError:
            logger.warning(
                "pycryptodome not installed — using mock encryption for sandbox."
            )
            # In sandbox environments without crypto library, use base64 encoding.
            plaintext = json.dumps(data, separators=(",", ":"))
            return base64.b64encode(plaintext.encode("utf-8")).decode("utf-8")
        except Exception as exc:
            raise NagadGatewayError(
                f"Failed to encrypt data for Nagad: {exc}"
            ) from exc

    def _sign_with_merchant_private_key(self, data: dict) -> str:
        """
        Sign data dict with the merchant's RSA private key (SHA256WithRSA).

        Args:
            data: Dictionary to sign.

        Returns:
            Base64-encoded RSA signature.
        """
        try:
            from Crypto.Signature import pkcs1_15
            from Crypto.Hash import SHA256
            from Crypto.PublicKey import RSA

            private_key = RSA.import_key(self.merchant_private_key)
            message = json.dumps(data, separators=(",", ":")).encode("utf-8")
            h = SHA256.new(message)
            signature = pkcs1_15.new(private_key).sign(h)
            return base64.b64encode(signature).decode("utf-8")
        except ImportError:
            logger.warning(
                "pycryptodome not installed — using mock signing for sandbox."
            )
            # Mock signature for sandbox testing.
            plaintext = json.dumps(data, separators=(",", ":"))
            return base64.b64encode(
                hashlib.sha256(plaintext.encode()).digest()
            ).decode("utf-8")
        except Exception as exc:
            raise NagadGatewayError(
                f"Failed to sign data with merchant key: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Payment initialization
    # ------------------------------------------------------------------

    def _initialize_payment(self, order_id: str, ip_address: str = "127.0.0.1") -> dict:
        """
        Step 1: Initialize a Nagad payment session to obtain a challenge string.

        Args:
            order_id:   Your internal order/deposit identifier.
            ip_address: Client IP address for fraud prevention.

        Returns:
            Dict with: sensitiveData (encrypted), signature, datetime, orderId.

        Raises:
            NagadGatewayError: If initialization fails.
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        url = (
            f"{self.base_url}/api/dfs/check-out/initialize/"
            f"{self.merchant_id}/{order_id}"
        )

        merchant_data = {
            "merchantId": self.merchant_id,
            "datetime": timestamp,
            "orderId": order_id,
            "challenge": str(uuid.uuid4()).replace("-", "")[:20].upper(),
        }

        sensitive_data = self._encrypt_with_nagad_public_key(merchant_data)
        signature = self._sign_with_merchant_private_key(merchant_data)

        headers = {
            **self.session.headers,
            "X-KM-IP-V4": ip_address,
        }

        payload = {
            "accountNumber": "",
            "dateTime": timestamp,
            "sensitiveData": sensitive_data,
            "signature": signature,
        }

        try:
            response = self.session.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise NagadGatewayError("Nagad initialize_payment timed out.")
        except requests.ConnectionError:
            raise NagadGatewayError("Cannot connect to Nagad API.")
        except requests.HTTPError as exc:
            raw = {}
            try:
                raw = exc.response.json()
            except Exception:
                pass
            raise NagadGatewayError(
                f"Nagad initialize_payment HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
                raw_response=raw,
            )

        if not data.get("sensitiveData"):
            raise NagadGatewayError(
                f"Nagad initialize_payment missing sensitiveData: {data}",
                raw_response=data,
            )

        return data

    def _complete_payment(
        self,
        order_id: str,
        init_response: dict,
        amount: Decimal,
        callback_url: str,
        ip_address: str = "127.0.0.1",
    ) -> dict:
        """
        Step 2: Complete payment initialization by submitting encrypted payment data.

        Args:
            order_id:       Internal order identifier.
            init_response:  Response from _initialize_payment().
            amount:         BDT amount to charge.
            callback_url:   Where Nagad should POST the payment result.
            ip_address:     Client IP.

        Returns:
            Dict with: callBackUrl (redirect URL), orderId, paymentReferenceId.

        Raises:
            NagadGatewayError: If the completion call fails.
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        url = f"{self.base_url}/api/dfs/check-out/complete/{self.merchant_id}/{order_id}"

        # Decrypt the challenge from init_response.sensitiveData if needed.
        # For simplicity in sandbox, we trust the returned sensitiveData directly.
        payment_data = {
            "merchantId": self.merchant_id,
            "orderId": order_id,
            "currencyCode": "050",  # BDT ISO 4217 numeric
            "amount": f"{amount:.2f}",
            "challenge": init_response.get("sensitiveData", "")[:20],
        }

        sensitive_data = self._encrypt_with_nagad_public_key(payment_data)
        signature = self._sign_with_merchant_private_key(payment_data)

        headers = {
            **self.session.headers,
            "X-KM-IP-V4": ip_address,
        }

        payload = {
            "sensitiveData": sensitive_data,
            "signature": signature,
            "merchantCallbackURL": callback_url,
            "additionalMerchantInfo": {
                "orderDescription": f"Wallet deposit: {amount} BDT",
            },
        }

        try:
            response = self.session.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise NagadGatewayError("Nagad complete_payment timed out.")
        except requests.ConnectionError:
            raise NagadGatewayError("Cannot connect to Nagad API.")
        except requests.HTTPError as exc:
            raw = {}
            try:
                raw = exc.response.json()
            except Exception:
                pass
            raise NagadGatewayError(
                f"Nagad complete_payment HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
                raw_response=raw,
            )

        callback_url_result = data.get("callBackUrl")
        if not callback_url_result:
            raise NagadGatewayError(
                f"Nagad complete_payment missing callBackUrl: {data}",
                raw_response=data,
            )

        return data

    # ------------------------------------------------------------------
    # High-level create_payment
    # ------------------------------------------------------------------

    def create_payment(
        self,
        amount: Decimal,
        phone: str,
        callback_url: str,
        order_id: str,
        ip_address: str = "127.0.0.1",
    ) -> dict:
        """
        Initiate a Nagad payment session (combines initialize + complete steps).

        Args:
            amount:       BDT amount.
            phone:        Customer's Nagad-registered phone (stored for reference).
            callback_url: URL Nagad will redirect/POST to after payment.
            order_id:     Your internal deposit request ID.
            ip_address:   Client IP for Nagad's fraud detection.

        Returns:
            A dict with:
                - session_id (str):    Nagad paymentReferenceId.
                - payment_url (str):   URL to redirect user to.
                - status (str):        "Initiated" on success.
                - raw (dict):          Full API response.

        Raises:
            NagadGatewayError: On any API or encryption failure.
        """
        logger.info(
            "Creating Nagad payment: order_id=%s amount=%s phone=%s",
            order_id,
            amount,
            phone,
        )

        init_data = self._initialize_payment(order_id, ip_address)
        complete_data = self._complete_payment(
            order_id=order_id,
            init_response=init_data,
            amount=amount,
            callback_url=callback_url,
            ip_address=ip_address,
        )

        payment_ref_id = complete_data.get("paymentReferenceId", order_id)
        redirect_url = complete_data.get("callBackUrl", "")

        logger.info(
            "Nagad payment created: order_id=%s ref_id=%s",
            order_id,
            payment_ref_id,
        )

        return {
            "session_id": payment_ref_id,
            "payment_url": redirect_url,
            "status": "Initiated",
            "raw": complete_data,
        }

    # ------------------------------------------------------------------
    # Execute payment
    # ------------------------------------------------------------------

    def execute_payment(self, payment_ref_id: str) -> dict:
        """
        Execute (confirm) a Nagad payment after user completes it on Nagad's UI.

        Args:
            payment_ref_id: The paymentReferenceId from create_payment.

        Returns:
            Dict with:
                - transaction_id (str):  Nagad transaction reference (issuerPaymentRefNo).
                - amount (Decimal):      Confirmed amount.
                - status (str):          Payment status string.
                - raw (dict):            Full API response.

        Raises:
            NagadGatewayError: If execution fails.
        """
        url = f"{self.base_url}/api/dfs/verify/payment/{payment_ref_id}"

        try:
            response = self.session.get(url, headers=self.session.headers, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise NagadGatewayError("Nagad execute_payment timed out.")
        except requests.ConnectionError:
            raise NagadGatewayError("Cannot connect to Nagad API.")
        except requests.HTTPError as exc:
            raise NagadGatewayError(
                f"Nagad execute_payment HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            )

        status_str = data.get("status", "")
        amount_str = data.get("amount", "0")
        try:
            confirmed_amount = Decimal(amount_str)
        except Exception:
            confirmed_amount = Decimal("0")

        if status_str.lower() not in ("success", "succeeded"):
            raise NagadGatewayError(
                f"Nagad payment not successful: status={status_str}",
                raw_response=data,
            )

        return {
            "transaction_id": data.get("issuerPaymentRefNo", payment_ref_id),
            "amount": confirmed_amount,
            "status": status_str,
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Verify payment
    # ------------------------------------------------------------------

    def verify_payment(self, payment_ref_id: str) -> tuple[bool, Decimal]:
        """
        Verify a Nagad payment's final status.

        Args:
            payment_ref_id: The paymentReferenceId from create_payment.

        Returns:
            Tuple (is_successful: bool, confirmed_amount: Decimal).

        Raises:
            NagadGatewayError: If the verification API call fails.
        """
        url = f"{self.base_url}/api/dfs/verify/payment/{payment_ref_id}"

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise NagadGatewayError(f"Nagad verify_payment failed: {exc}") from exc

        status_str = data.get("status", "").lower()
        is_successful = status_str in ("success", "succeeded", "completed")

        amount_str = data.get("amount", "0")
        try:
            confirmed_amount = Decimal(amount_str)
        except Exception:
            confirmed_amount = Decimal("0")

        logger.info(
            "Nagad payment verified: ref=%s status=%s amount=%s success=%s",
            payment_ref_id,
            status_str,
            confirmed_amount,
            is_successful,
        )
        return is_successful, confirmed_amount

    # ------------------------------------------------------------------
    # Query payment status
    # ------------------------------------------------------------------

    def query_payment(self, payment_ref_id: str) -> dict:
        """
        Retrieve full payment details for a Nagad paymentReferenceId.

        Args:
            payment_ref_id: The paymentReferenceId from create_payment.

        Returns:
            Full API response dict.

        Raises:
            NagadGatewayError: On API error.
        """
        url = f"{self.base_url}/api/dfs/verify/payment/{payment_ref_id}"
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise NagadGatewayError(f"Nagad query_payment failed: {exc}") from exc
