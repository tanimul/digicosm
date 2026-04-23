"""
SSLCommerz Payment Gateway Integration.

Implements the SSLCommerz API v4 for Bangladesh e-commerce payments.
Documentation: https://developer.sslcommerz.com/docs/v4/

SSLCommerz supports a wide range of payment methods including:
    - bKash, Nagad, Rocket (mobile banking)
    - VISA, Mastercard, AMEX (credit/debit cards)
    - Internetbanking (DBBL Nexus, BRAC Bank, etc.)

Flow:
    1. create_transaction()    - Initiate session, get GatewayPageURL.
    2. validate_payment()      - Verify payment using val_id from IPN.
    3. transaction_query()     - Query by transaction_id or session key.
    4. initiate_refund()       - Request a full or partial refund.
    5. refund_query()          - Check status of a refund request.
"""

import hashlib
import logging
from decimal import Decimal
from typing import Optional

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class SSLCommerzGatewayError(Exception):
    """Raised when the SSLCommerz API returns an unexpected error."""

    def __init__(self, message: str, status_code: int = 0, raw_response: dict = None):
        super().__init__(message)
        self.status_code = status_code
        self.raw_response = raw_response or {}


class SSLCommerzGateway:
    """
    SSLCommerz v4 payment gateway client.

    Configuration (in Django settings):
        SSLCOMMERZ_STORE_ID:       Store identifier from SSLCommerz dashboard.
        SSLCOMMERZ_STORE_PASSWORD: Store password (API key).
        SSLCOMMERZ_SANDBOX:        True for sandbox environment (default: True).

    Example:
        gw = SSLCommerzGateway()
        result = gw.create_transaction(
            amount=Decimal("500.00"),
            customer_data={
                "cus_name": "John Doe",
                "cus_email": "john@example.com",
                "cus_phone": "01711000000",
                "order_id": "DEP-UUID-HERE",
            },
            callback_url="https://app.example.com/wallet/deposit/callback/",
        )
        # Redirect user to result["payment_url"]
    """

    SANDBOX_URL = "https://sandbox.sslcommerz.com"
    PRODUCTION_URL = "https://securepay.sslcommerz.com"

    def __init__(self):
        cfg = self._load_config()
        self.store_id = cfg["store_id"]
        self.store_password = cfg["store_password"]
        self.is_sandbox = cfg["sandbox"]
        self.base_url = self.SANDBOX_URL if self.is_sandbox else self.PRODUCTION_URL
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config() -> dict:
        """Load and validate SSLCommerz configuration from Django settings."""
        store_id = getattr(settings, "SSLCOMMERZ_STORE_ID", None)
        store_password = getattr(settings, "SSLCOMMERZ_STORE_PASSWORD", None)

        if not store_id or not store_password:
            raise SSLCommerzGatewayError(
                "SSLCOMMERZ_STORE_ID and SSLCOMMERZ_STORE_PASSWORD "
                "must be configured in Django settings."
            )

        return {
            "store_id": store_id,
            "store_password": store_password,
            "sandbox": getattr(settings, "SSLCOMMERZ_SANDBOX", True),
        }

    # ------------------------------------------------------------------
    # Create transaction
    # ------------------------------------------------------------------

    def create_transaction(
        self,
        amount: Decimal,
        customer_data: dict,
        callback_url: str,
        currency: str = "BDT",
        product_name: str = "Wallet Top-up",
        product_category: str = "digital_goods",
        product_profile: str = "non-physical-goods",
    ) -> dict:
        """
        Initiate an SSLCommerz payment session.

        Args:
            amount:           BDT amount to charge.
            customer_data:    Customer info dict with keys:
                                cus_name, cus_email, cus_phone, order_id.
                              Optional: cus_add1, cus_city, cus_postcode, cus_country.
            callback_url:     IPN (Instant Payment Notification) URL.
            currency:         Currency code (default "BDT").
            product_name:     Product/service name shown to customer.
            product_category: Category for transaction reports.
            product_profile:  SSLCommerz product profile type.

        Returns:
            A dict with:
                - session_id (str):  SSLCommerz sessionkey.
                - payment_url (str): GatewayPageURL to redirect user to.
                - status (str):      "SUCCESS" on success.
                - raw (dict):        Full API response.

        Raises:
            SSLCommerzGatewayError: On API error or validation failure.
        """
        url = f"{self.base_url}/gwprocess/v4/api.php"

        order_id = customer_data.get("order_id", "")

        payload = {
            # Store credentials
            "store_id": self.store_id,
            "store_passwd": self.store_password,
            # Transaction info
            "total_amount": f"{amount:.2f}",
            "currency": currency,
            "tran_id": order_id[:50],
            # Success/fail/cancel redirect (for non-IPN use)
            "success_url": callback_url,
            "fail_url": f"{callback_url}?status=FAILED",
            "cancel_url": f"{callback_url}?status=CANCELLED",
            # IPN notification
            "ipn_url": callback_url,
            # Customer info
            "cus_name": customer_data.get("cus_name", "Customer")[:30],
            "cus_email": customer_data.get("cus_email", "customer@example.com")[:50],
            "cus_add1": customer_data.get("cus_add1", "Dhaka, Bangladesh")[:50],
            "cus_city": customer_data.get("cus_city", "Dhaka")[:30],
            "cus_postcode": customer_data.get("cus_postcode", "1000")[:10],
            "cus_country": customer_data.get("cus_country", "Bangladesh")[:30],
            "cus_phone": customer_data.get("cus_phone", "")[:20],
            # Shipping (required fields — set to N/A for digital goods)
            "ship_name": customer_data.get("cus_name", "N/A")[:30],
            "ship_add1": "Digital Delivery",
            "ship_city": customer_data.get("cus_city", "Dhaka")[:30],
            "ship_postcode": customer_data.get("cus_postcode", "1000")[:10],
            "ship_country": customer_data.get("cus_country", "Bangladesh")[:30],
            # Product info
            "product_name": product_name[:30],
            "product_category": product_category[:30],
            "product_profile": product_profile,
            "product_amount": f"{amount:.2f}",
            "vat": "0",
            "discount_amount": "0",
            "convenience_fee": "0",
        }

        try:
            response = self.session.post(url, data=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise SSLCommerzGatewayError("SSLCommerz create_transaction timed out.")
        except requests.ConnectionError:
            raise SSLCommerzGatewayError("Cannot connect to SSLCommerz API.")
        except requests.HTTPError as exc:
            raise SSLCommerzGatewayError(
                f"SSLCommerz create_transaction HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            )
        except ValueError:
            raise SSLCommerzGatewayError(
                "SSLCommerz returned non-JSON response."
            )

        api_status = data.get("status", "").upper()
        if api_status != "SUCCESS":
            raise SSLCommerzGatewayError(
                f"SSLCommerz session creation failed: {data.get('failedreason', 'Unknown')}",
                raw_response=data,
            )

        session_key = data.get("sessionkey")
        gateway_url = data.get("GatewayPageURL")

        if not session_key or not gateway_url:
            raise SSLCommerzGatewayError(
                "SSLCommerz returned missing sessionkey or GatewayPageURL.",
                raw_response=data,
            )

        logger.info(
            "SSLCommerz session created: order_id=%s session=%s amount=%s",
            order_id,
            session_key,
            amount,
        )

        return {
            "session_id": session_key,
            "payment_url": gateway_url,
            "status": "SUCCESS",
            "raw": data,
        }

    # ------------------------------------------------------------------
    # Validate payment (IPN verification)
    # ------------------------------------------------------------------

    def validate_payment(self, val_id: str) -> bool:
        """
        Validate a payment using the val_id received in SSLCommerz's IPN POST.

        This must be called before crediting the user's wallet to confirm
        that the payment was not spoofed.

        Args:
            val_id: Validation ID from SSLCommerz IPN payload.

        Returns:
            True if payment is valid and completed, False otherwise.

        Raises:
            SSLCommerzGatewayError: If the validation API call fails.
        """
        url = (
            f"{self.base_url}/validator/api/validationserverAPI.php"
            f"?val_id={val_id}&store_id={self.store_id}"
            f"&store_passwd={self.store_password}&v=1&format=json"
        )

        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.Timeout:
            raise SSLCommerzGatewayError("SSLCommerz validate_payment timed out.")
        except requests.ConnectionError:
            raise SSLCommerzGatewayError("Cannot connect to SSLCommerz validator.")
        except requests.HTTPError as exc:
            raise SSLCommerzGatewayError(
                f"SSLCommerz validate_payment HTTP {exc.response.status_code}",
                status_code=exc.response.status_code,
            )

        status_str = data.get("status", "").upper()
        is_valid = status_str in ("VALID", "VALIDATED")

        logger.info(
            "SSLCommerz payment validated: val_id=%s status=%s valid=%s",
            val_id,
            status_str,
            is_valid,
        )
        return is_valid

    # ------------------------------------------------------------------
    # Verify IPN hash
    # ------------------------------------------------------------------

    def verify_ipn_hash(self, post_data: dict) -> bool:
        """
        Verify the MD5 hash signature in SSLCommerz's IPN POST payload.

        SSLCommerz sends a verify_sign field containing an MD5 hash of
        selected transaction fields plus the store_password. Always verify
        this before processing IPN notifications.

        Args:
            post_data: The full IPN POST payload (as a dict).

        Returns:
            True if the signature is valid, False otherwise.
        """
        received_signature = post_data.get("verify_sign", "")
        if not received_signature:
            logger.warning("SSLCommerz IPN missing verify_sign field.")
            return False

        # Extract fields in sorted alphabetical order (excluding verify_sign).
        fields_to_hash = {
            k: v
            for k, v in post_data.items()
            if k != "verify_sign" and k != "verify_key"
        }

        # Sort by key alphabetically.
        sorted_keys = sorted(fields_to_hash.keys())
        hash_parts = []
        for key in sorted_keys:
            hash_parts.append(str(fields_to_hash[key]))

        # Prepend store_password hash.
        store_pass_md5 = hashlib.md5(
            self.store_password.encode("utf-8")
        ).hexdigest()
        hash_parts.insert(0, store_pass_md5)

        hash_string = "&".join(hash_parts)
        computed_hash = hashlib.md5(hash_string.encode("utf-8")).hexdigest()

        is_valid = computed_hash == received_signature
        if not is_valid:
            logger.warning(
                "SSLCommerz IPN hash mismatch: expected=%s received=%s",
                computed_hash,
                received_signature,
            )
        return is_valid

    # ------------------------------------------------------------------
    # Transaction query
    # ------------------------------------------------------------------

    def transaction_query_by_tran_id(self, tran_id: str) -> dict:
        """
        Query an SSLCommerz transaction by your internal transaction/order ID.

        Args:
            tran_id: Your internal tran_id used when creating the transaction.

        Returns:
            Full API response dict (element list).

        Raises:
            SSLCommerzGatewayError: On API failure.
        """
        url = f"{self.base_url}/validator/api/merchantTransIDvalidationAPI.php"
        params = {
            "merchant_tran_id": tran_id,
            "store_id": self.store_id,
            "store_passwd": self.store_password,
            "v": "1",
            "format": "json",
        }

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise SSLCommerzGatewayError(
                f"SSLCommerz transaction_query failed: {exc}"
            ) from exc

    def transaction_query_by_session(self, session_key: str) -> dict:
        """
        Query an SSLCommerz transaction by the sessionkey.

        Args:
            session_key: The SSLCommerz sessionkey from create_transaction.

        Returns:
            Full API response dict.

        Raises:
            SSLCommerzGatewayError: On API failure.
        """
        url = f"{self.base_url}/validator/api/merchantTransIDvalidationAPI.php"
        params = {
            "sessionkey": session_key,
            "store_id": self.store_id,
            "store_passwd": self.store_password,
            "v": "1",
            "format": "json",
        }

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise SSLCommerzGatewayError(
                f"SSLCommerz session query failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Refund
    # ------------------------------------------------------------------

    def initiate_refund(
        self,
        bank_tran_id: str,
        refund_amount: Decimal,
        refund_remarks: str = "",
        refe_id: Optional[str] = None,
    ) -> dict:
        """
        Initiate a refund for a completed SSLCommerz transaction.

        Args:
            bank_tran_id:    Bank transaction ID from the original payment.
            refund_amount:   BDT amount to refund.
            refund_remarks:  Optional reason for the refund.
            refe_id:         Your internal reference for this refund.

        Returns:
            Dict with refund status and SSLCommerz reference.

        Raises:
            SSLCommerzGatewayError: If refund initiation fails.
        """
        url = f"{self.base_url}/validator/api/merchantTransIDvalidationAPI.php"
        payload = {
            "store_id": self.store_id,
            "store_passwd": self.store_password,
            "bank_tran_id": bank_tran_id,
            "v": "1",
            "format": "json",
            "refund_amount": f"{refund_amount:.2f}",
            "refund_remarks": refund_remarks[:255],
        }
        if refe_id:
            payload["refe_id"] = refe_id[:30]

        # SSLCommerz refund endpoint.
        refund_url = f"{self.base_url}/validator/api/merchantTransIDvalidationAPI.php"

        try:
            response = self.session.post(refund_url, data=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise SSLCommerzGatewayError(
                f"SSLCommerz initiate_refund failed: {exc}"
            ) from exc

        api_status = data.get("status", "").upper()
        if api_status not in ("SUCCESS", "REFUND_INITIATED", "PROCESSING"):
            raise SSLCommerzGatewayError(
                f"SSLCommerz refund failed: {data.get('errorReason', 'Unknown')}",
                raw_response=data,
            )

        logger.info(
            "SSLCommerz refund initiated: bank_tran_id=%s amount=%s",
            bank_tran_id,
            refund_amount,
        )
        return {
            "refund_ref_id": data.get("refundRefId", ""),
            "status": api_status,
            "amount": refund_amount,
            "raw": data,
        }

    def refund_query(self, refund_ref_id: str) -> dict:
        """
        Query the status of a refund by its reference ID.

        Args:
            refund_ref_id: The refundRefId from initiate_refund.

        Returns:
            Full API response dict.

        Raises:
            SSLCommerzGatewayError: On API failure.
        """
        url = f"{self.base_url}/validator/api/merchantTransIDvalidationAPI.php"
        params = {
            "store_id": self.store_id,
            "store_passwd": self.store_password,
            "refund_ref_id": refund_ref_id,
            "v": "1",
            "format": "json",
        }

        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            raise SSLCommerzGatewayError(
                f"SSLCommerz refund_query failed: {exc}"
            ) from exc
