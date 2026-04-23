"""
Django admin configuration for the accounts application.

Registers User, OTPVerification, and UserDevice with rich admin
interfaces suitable for support and operations teams.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import AdminPasswordChangeForm
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from apps.accounts.models import OTPVerification, User, UserDevice


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------


class UserDeviceInline(admin.TabularInline):
    """Show registered devices inline on the User admin page."""

    model = UserDevice
    extra = 0
    readonly_fields = (
        "id",
        "device_id",
        "device_type",
        "device_name",
        "push_token",
        "app_version",
        "os_version",
        "last_active",
        "last_ip",
        "created_at",
    )
    fields = (
        "device_type",
        "device_name",
        "device_id",
        "push_token",
        "is_active",
        "is_trusted",
        "last_active",
        "last_ip",
    )
    show_change_link = False
    can_delete = True
    max_num = 20


class OTPVerificationInline(admin.TabularInline):
    """Show recent OTP records inline on the User admin page."""

    model = OTPVerification
    extra = 0
    readonly_fields = (
        "id",
        "purpose",
        "expires_at",
        "is_used",
        "attempts",
        "ip_address",
        "created_at",
    )
    fields = (
        "purpose",
        "expires_at",
        "is_used",
        "attempts",
        "ip_address",
        "created_at",
    )
    ordering = ["-created_at"]
    max_num = 10
    can_delete = False

    def has_add_permission(self, request, obj=None) -> bool:
        return False


# ---------------------------------------------------------------------------
# User Admin
# ---------------------------------------------------------------------------


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Full-featured admin for the custom User model.

    Key features:
    - Phone number as primary identifier
    - KYC workflow actions (approve / reject)
    - Searchable by phone, name, email
    - Read-only sensitive fields
    """

    # ------------------------------------------------------------------ #
    # Change form                                                         #
    # ------------------------------------------------------------------ #
    change_password_form = AdminPasswordChangeForm

    # ------------------------------------------------------------------ #
    # List view                                                           #
    # ------------------------------------------------------------------ #
    list_display = (
        "phone_number",
        "full_name",
        "email",
        "is_verified",
        "kyc_status_badge",
        "is_active",
        "is_staff",
        "date_joined",
        "last_login",
    )
    list_display_links = ("phone_number", "full_name")
    list_filter = (
        "is_active",
        "is_staff",
        "is_superuser",
        "is_verified",
        "kyc_status",
        "date_joined",
    )
    search_fields = ("phone_number", "full_name", "email", "referral_code")
    ordering = ("-date_joined",)
    date_hierarchy = "date_joined"
    list_per_page = 30
    list_select_related = True

    # ------------------------------------------------------------------ #
    # Detail view — field layout                                          #
    # ------------------------------------------------------------------ #
    fieldsets = (
        (
            _("Identity"),
            {
                "fields": (
                    "id",
                    "phone_number",
                    "email",
                    "full_name",
                    "avatar",
                    "avatar_preview",
                )
            },
        ),
        (
            _("Password"),
            {
                "fields": ("password",),
                "classes": ("collapse",),
            },
        ),
        (
            _("Verification & Status"),
            {
                "fields": (
                    "is_verified",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                )
            },
        ),
        (
            _("KYC"),
            {
                "fields": (
                    "kyc_status",
                    "kyc_submitted_at",
                    "kyc_reviewed_at",
                    "kyc_rejection_reason",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            _("Referral"),
            {
                "fields": (
                    "referral_code",
                    "referred_by",
                    "referral_bonus_credited",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            _("Session & Device"),
            {
                "fields": (
                    "last_login_ip",
                    "device_tokens",
                    "last_login",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "groups",
                    "user_permissions",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            _("Timestamps"),
            {
                "fields": (
                    "date_joined",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "phone_number",
                    "full_name",
                    "email",
                    "password1",
                    "password2",
                    "is_staff",
                    "is_superuser",
                ),
            },
        ),
    )

    # ------------------------------------------------------------------ #
    # Read-only fields                                                    #
    # ------------------------------------------------------------------ #
    readonly_fields = (
        "id",
        "referral_code",
        "date_joined",
        "updated_at",
        "last_login",
        "last_login_ip",
        "kyc_submitted_at",
        "kyc_reviewed_at",
        "avatar_preview",
    )

    # ------------------------------------------------------------------ #
    # Inlines                                                             #
    # ------------------------------------------------------------------ #
    inlines = [UserDeviceInline, OTPVerificationInline]

    # ------------------------------------------------------------------ #
    # Custom display methods                                              #
    # ------------------------------------------------------------------ #
    @admin.display(description=_("KYC"), ordering="kyc_status")
    def kyc_status_badge(self, obj: User) -> str:
        colour_map = {
            User.KYCStatus.PENDING: "#888888",
            User.KYCStatus.SUBMITTED: "#FFA500",
            User.KYCStatus.VERIFIED: "#28a745",
            User.KYCStatus.REJECTED: "#dc3545",
        }
        colour = colour_map.get(obj.kyc_status, "#888888")
        label = obj.get_kyc_status_display()
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colour,
            label,
        )

    @admin.display(description=_("Avatar Preview"))
    def avatar_preview(self, obj: User) -> str:
        if obj.avatar:
            return format_html(
                '<img src="{}" style="height: 60px; border-radius: 50%;" />',
                obj.avatar.url,
            )
        return _("No avatar")

    # ------------------------------------------------------------------ #
    # Admin actions                                                       #
    # ------------------------------------------------------------------ #
    actions = [
        "approve_kyc",
        "reject_kyc",
        "deactivate_users",
        "activate_users",
        "mark_verified",
    ]

    @admin.action(description=_("Approve KYC for selected users"))
    def approve_kyc(self, request, queryset):
        updated = queryset.update(
            kyc_status=User.KYCStatus.VERIFIED,
            kyc_reviewed_at=timezone.now(),
            kyc_rejection_reason="",
        )
        self.message_user(request, f"{updated} user(s) KYC approved.")

    @admin.action(description=_("Reject KYC for selected users"))
    def reject_kyc(self, request, queryset):
        updated = queryset.update(
            kyc_status=User.KYCStatus.REJECTED,
            kyc_reviewed_at=timezone.now(),
        )
        self.message_user(request, f"{updated} user(s) KYC rejected.")

    @admin.action(description=_("Deactivate selected users"))
    def deactivate_users(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} user(s) deactivated.")

    @admin.action(description=_("Activate selected users"))
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} user(s) activated.")

    @admin.action(description=_("Mark selected users as phone-verified"))
    def mark_verified(self, request, queryset):
        updated = queryset.update(is_verified=True)
        self.message_user(request, f"{updated} user(s) marked as verified.")

    # ------------------------------------------------------------------ #
    # Override to exclude password from list of read-only fields when    #
    # creating a new user.                                                #
    # ------------------------------------------------------------------ #
    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None:
            # Creating a new user — don't mark referral_code as readonly
            # so the form can auto-populate it
            if "referral_code" in readonly:
                readonly.remove("referral_code")
        return readonly


# ---------------------------------------------------------------------------
# OTP Verification Admin
# ---------------------------------------------------------------------------


@admin.register(OTPVerification)
class OTPVerificationAdmin(admin.ModelAdmin):
    """Read-only admin for auditing OTP usage."""

    list_display = (
        "user",
        "purpose",
        "is_used",
        "is_expired_display",
        "attempts",
        "ip_address",
        "created_at",
        "expires_at",
    )
    list_filter = ("purpose", "is_used", "created_at")
    search_fields = ("user__phone_number", "user__full_name", "ip_address")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"
    list_per_page = 50
    readonly_fields = (
        "id",
        "user",
        "otp_hash",
        "purpose",
        "expires_at",
        "is_used",
        "attempts",
        "ip_address",
        "created_at",
    )

    def has_add_permission(self, request) -> bool:
        return False

    def has_change_permission(self, request, obj=None) -> bool:
        return False

    @admin.display(description=_("Expired?"), boolean=True)
    def is_expired_display(self, obj: OTPVerification) -> bool:
        return obj.is_expired


# ---------------------------------------------------------------------------
# User Device Admin
# ---------------------------------------------------------------------------


@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    """Admin for managing registered user devices."""

    list_display = (
        "user",
        "device_type",
        "device_name",
        "is_active",
        "is_trusted",
        "last_active",
        "last_ip",
        "created_at",
    )
    list_filter = ("device_type", "is_active", "is_trusted")
    search_fields = (
        "user__phone_number",
        "user__full_name",
        "device_id",
        "device_name",
        "push_token",
    )
    ordering = ("-last_active",)
    readonly_fields = (
        "id",
        "created_at",
        "device_id",
        "last_active",
        "last_ip",
    )
    list_per_page = 50

    fieldsets = (
        (
            _("User & Identity"),
            {
                "fields": ("id", "user", "device_id"),
            },
        ),
        (
            _("Device Info"),
            {
                "fields": (
                    "device_type",
                    "device_name",
                    "app_version",
                    "os_version",
                ),
            },
        ),
        (
            _("Push Notification"),
            {
                "fields": ("push_token",),
                "classes": ("collapse",),
            },
        ),
        (
            _("Status & Session"),
            {
                "fields": (
                    "is_active",
                    "is_trusted",
                    "last_active",
                    "last_ip",
                    "created_at",
                ),
            },
        ),
    )

    actions = ["deactivate_devices", "activate_devices", "mark_trusted", "unmark_trusted"]

    @admin.action(description=_("Deactivate selected devices"))
    def deactivate_devices(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} device(s) deactivated.")

    @admin.action(description=_("Activate selected devices"))
    def activate_devices(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} device(s) activated.")

    @admin.action(description=_("Mark selected devices as trusted"))
    def mark_trusted(self, request, queryset):
        updated = queryset.update(is_trusted=True)
        self.message_user(request, f"{updated} device(s) marked as trusted.")

    @admin.action(description=_("Remove trusted status from selected devices"))
    def unmark_trusted(self, request, queryset):
        updated = queryset.update(is_trusted=False)
        self.message_user(request, f"{updated} device(s) unmarked as trusted.")
