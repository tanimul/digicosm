"""
Custom manager for the User model.

Provides create_user() and create_superuser() factory methods
that use phone_number as the primary identifier.
"""

import logging
from typing import TYPE_CHECKING, Any

from django.contrib.auth.models import BaseUserManager
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from apps.accounts.models import User  # avoid circular import at runtime

logger = logging.getLogger(__name__)

BANGLADESH_PHONE_REGEX = r"^\+880[1-9]\d{8}$"
_phone_validator = RegexValidator(
    regex=BANGLADESH_PHONE_REGEX,
    message=_(
        "Phone number must be a valid Bangladesh mobile number in E.164 format "
        "(e.g. +8801712345678)."
    ),
)


class UserManager(BaseUserManager["User"]):
    """
    Manager for the custom User model.

    phone_number is the unique identifier for authentication
    instead of the default username field.
    """

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_phone(self, phone_number: str) -> str:
        """Normalise and validate a Bangladesh phone number."""
        if not phone_number:
            raise ValueError(_("A phone number must be provided."))

        phone_number = phone_number.strip()

        # Accept local format and convert to E.164
        if phone_number.startswith("01") and len(phone_number) == 11:
            phone_number = "+880" + phone_number[1:]
        elif phone_number.startswith("8801") and not phone_number.startswith("+"):
            phone_number = "+" + phone_number

        _phone_validator(phone_number)
        return phone_number

    # ------------------------------------------------------------------
    # Public factory methods
    # ------------------------------------------------------------------

    def create_user(
        self,
        phone_number: str,
        password: str | None = None,
        **extra_fields: Any,
    ) -> "User":
        """
        Create and persist a regular (non-staff, non-superuser) user.

        Parameters
        ----------
        phone_number:
            Bangladesh mobile number (E.164 or local format accepted).
        password:
            Plain-text password.  If None the user will have an unusable
            password and must authenticate via OTP.
        **extra_fields:
            Additional model fields to set on the new User instance.

        Returns
        -------
        User
            The newly created (and saved) user instance.
        """
        phone_number = self._validate_phone(phone_number)

        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_active", True)

        email = extra_fields.get("email")
        if email:
            extra_fields["email"] = self.normalize_email(email)

        user: "User" = self.model(phone_number=phone_number, **extra_fields)

        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()

        user.save(using=self._db)

        logger.info(
            "New user created: phone=%s id=%s",
            phone_number,
            user.pk,
        )
        return user

    def create_superuser(
        self,
        phone_number: str,
        password: str,
        **extra_fields: Any,
    ) -> "User":
        """
        Create and persist a superuser (is_staff=True, is_superuser=True).

        Parameters
        ----------
        phone_number:
            Bangladesh mobile number.
        password:
            Plain-text password (required for superusers).
        **extra_fields:
            Additional model fields.

        Returns
        -------
        User
            The newly created superuser instance.

        Raises
        ------
        ValueError
            If is_staff or is_superuser is explicitly set to False.
        """
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("is_verified", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        if not password:
            raise ValueError(_("Superuser must have a password."))

        user = self.create_user(phone_number, password, **extra_fields)

        logger.info(
            "Superuser created: phone=%s id=%s",
            phone_number,
            user.pk,
        )
        return user

    # ------------------------------------------------------------------
    # Convenience query methods
    # ------------------------------------------------------------------

    def get_by_phone(self, phone_number: str) -> "User":
        """
        Return the user with the given phone number.

        Normalises local Bangladeshi format before lookup.

        Raises
        ------
        User.DoesNotExist
            If no matching user is found.
        """
        phone_number = self._validate_phone(phone_number)
        return self.get(phone_number=phone_number)

    def active_users(self):
        """Return a queryset of active, verified users."""
        return self.filter(is_active=True, is_verified=True)

    def pending_kyc(self):
        """Return users who have submitted KYC but are not yet reviewed."""
        from apps.accounts.models import User  # local import to avoid circular

        return self.filter(kyc_status=User.KYCStatus.SUBMITTED)
