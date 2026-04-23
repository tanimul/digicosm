"""
Wallet Signals.

Automatically creates a Wallet for every newly registered user via
Django's post_save signal on the User model.
"""

import logging

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

User = get_user_model()


@receiver(post_save, sender=User)
def create_wallet_for_new_user(sender, instance: User, created: bool, **kwargs) -> None:
    """
    Create a Wallet for every newly registered user.

    This signal fires after any User.save() call. The `created` flag ensures
    we only create a wallet on the initial INSERT, not subsequent updates.

    If wallet creation fails (e.g., DB error), the exception is caught and
    logged so it does not disrupt the user registration flow. The wallet
    can be created later via the admin or a management command.
    """
    if not created:
        return

    from .services import WalletService, DuplicateWalletError

    wallet_service = WalletService()
    try:
        wallet = wallet_service.create_wallet(instance)
        logger.info(
            "Wallet auto-created for new user: %s (wallet_id=%s)",
            instance.username,
            wallet.pk,
        )
    except DuplicateWalletError:
        # Race condition — wallet already created (e.g., via fixtures or migration).
        logger.debug(
            "Wallet already exists for user %s — skipping auto-creation.",
            instance.username,
        )
    except Exception as exc:
        logger.error(
            "Failed to auto-create wallet for user %s: %s",
            instance.username,
            exc,
            exc_info=True,
        )
