"""
Custom DRF permission classes for the DCE platform.
"""

from rest_framework.permissions import BasePermission


class IsKYCVerified(BasePermission):
    """
    Allows access only to users whose KYC status is 'verified'.
    Assumes User model has a `kyc_status` field with value 'verified'.
    """

    message = "KYC verification is required to perform this action."

    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and getattr(request.user, "kyc_status", None) == "verified"
        )


class IsSubscribed(BasePermission):
    """
    Allows access only to users with at least one active subscription.
    Checks `apps.subscriptions.models.UserSubscription`.
    """

    message = "An active subscription is required to access this resource."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        from apps.subscriptions.models import UserSubscription, SubscriptionStatus
        return UserSubscription.objects.filter(
            user=request.user,
            status=SubscriptionStatus.ACTIVE,
        ).exists()


class IsWalletActive(BasePermission):
    """
    Allows access only when the user's wallet is not frozen.
    """

    message = "Your wallet has been suspended. Contact support."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        from apps.wallet.models import Wallet
        wallet = Wallet.objects.filter(user=request.user).first()
        if wallet is None:
            return True  # no wallet yet — don't block
        return not wallet.is_frozen


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level: owner of the object OR admin can access.
    The object must have a `user` attribute.
    """

    def has_object_permission(self, request, view, obj):
        if request.user and request.user.is_staff:
            return True
        return getattr(obj, "user", None) == request.user


class IsVendor(BasePermission):
    """
    Allows access only to marketplace vendors (users with an active Vendor record).
    """

    message = "Only registered vendors can perform this action."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        from apps.marketplace.models import Vendor
        return Vendor.objects.filter(user=request.user, is_active=True).exists()
