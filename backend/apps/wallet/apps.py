"""
Wallet App Configuration.

Registers the wallet app with Django and connects post-registration signals
to auto-create wallets for new users.
"""

from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class WalletConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.wallet"
    verbose_name = _("Wallet")

    def ready(self):
        """
        Import signal handlers when the app is fully loaded.

        Connects the post_save signal on the User model to create a Wallet
        automatically upon new user registration.
        """
        import apps.wallet.signals  # noqa: F401
