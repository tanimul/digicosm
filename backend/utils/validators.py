"""
Shared validators for the DCE platform.
"""

import re

from django.core.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Phone number — Bangladesh E.164 format (+880XXXXXXXXXX)
# ---------------------------------------------------------------------------

BD_PHONE_RE = re.compile(r"^\+8801[3-9]\d{8}$")


def validate_bangladesh_phone(value: str) -> str:
    """
    Validate and normalise a Bangladesh mobile number to E.164.

    Accepts:
        01XXXXXXXXX      →  +8801XXXXXXXXX
        8801XXXXXXXXX    →  +8801XXXXXXXXX
        +8801XXXXXXXXX   →  +8801XXXXXXXXX (unchanged)

    Raises ValidationError if the number is invalid.
    """
    if not value:
        raise ValidationError("Phone number is required.")

    cleaned = value.strip().replace(" ", "").replace("-", "")

    # Normalise to E.164
    if cleaned.startswith("01") and len(cleaned) == 11:
        cleaned = "+880" + cleaned
    elif cleaned.startswith("8801") and len(cleaned) == 13:
        cleaned = "+" + cleaned
    elif cleaned.startswith("+8801") and len(cleaned) == 14:
        pass  # already E.164
    else:
        raise ValidationError(
            f"'{value}' is not a valid Bangladesh mobile number. "
            "Expected format: +8801XXXXXXXXX"
        )

    if not BD_PHONE_RE.match(cleaned):
        raise ValidationError(
            f"'{value}' is not a valid Bangladesh mobile number."
        )

    return cleaned


# ---------------------------------------------------------------------------
# BDT amount
# ---------------------------------------------------------------------------

def validate_positive_amount(value) -> None:
    """Raise ValidationError if value is not a positive number."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValidationError("Amount must be a number.")
    if f <= 0:
        raise ValidationError("Amount must be greater than zero.")


def validate_min_deposit(value, minimum: float = 10.0) -> None:
    """Raise ValidationError if deposit is below the platform minimum."""
    validate_positive_amount(value)
    if float(value) < minimum:
        raise ValidationError(f"Minimum deposit is {minimum} BDT.")


# ---------------------------------------------------------------------------
# Slugs / identifiers
# ---------------------------------------------------------------------------

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def validate_slug(value: str) -> None:
    """Validate URL-safe slug format (lowercase, hyphens only)."""
    if not SLUG_RE.match(value):
        raise ValidationError(
            f"'{value}' is not a valid slug. Use only lowercase letters, numbers, and hyphens."
        )


# ---------------------------------------------------------------------------
# Fernet / encryption key presence
# ---------------------------------------------------------------------------

def validate_non_empty_string(value: str, field_name: str = "Value") -> None:
    """Raise ValidationError if string is blank after stripping."""
    if not value or not value.strip():
        raise ValidationError(f"{field_name} must not be empty.")
