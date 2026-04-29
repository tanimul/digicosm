#!/usr/bin/env python
"""
DCE Platform — Seed Data Script
Populates the database with initial reference data needed to run the platform.

Usage (from repo root):
    DJANGO_SETTINGS_MODULE=config.settings.development python scripts/seed_data.py

Or via the migrate script:
    bash scripts/migrate.sh --seed
"""

import os
import sys
import django

# Ensure Django is set up
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from apps.ai_gateway.models import AIProvider   # noqa: E402
from apps.subscriptions.models import SubscriptionPlan, PlanFeature  # noqa: E402

User = get_user_model()


# ─── Superuser ────────────────────────────────────────────────────────────────

def create_superuser():
    if not User.objects.filter(is_superuser=True).exists():
        user = User.objects.create_superuser(
            phone_number="+8801700000000",
            password="admin1234",
        )
        print(f"  Created superuser: {user.phone_number}")
    else:
        print("  Superuser already exists — skipping.")


# ─── AI Providers ─────────────────────────────────────────────────────────────

PROVIDERS = [
    {"name": "openai",    "display_name": "OpenAI",    "base_url": "https://api.openai.com/v1",            "default_model": "gpt-4o",            "cost_per_1k_tokens_bdt": 0.15, "priority": 1},
    {"name": "anthropic", "display_name": "Anthropic", "base_url": "https://api.anthropic.com/v1",         "default_model": "claude-sonnet-4-6", "cost_per_1k_tokens_bdt": 0.12, "priority": 2},
    {"name": "gemini",    "display_name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta", "default_model": "gemini-1.5-flash", "cost_per_1k_tokens_bdt": 0.08, "priority": 3},
    {"name": "deepseek",  "display_name": "DeepSeek",  "base_url": "https://api.deepseek.com/v1",          "default_model": "deepseek-chat",     "cost_per_1k_tokens_bdt": 0.05, "priority": 4},
    {"name": "cohere",    "display_name": "Cohere",    "base_url": "https://api.cohere.ai/v1",             "default_model": "command-r-plus",    "cost_per_1k_tokens_bdt": 0.10, "priority": 5},
]


def create_providers():
    for p in PROVIDERS:
        obj, created = AIProvider.objects.get_or_create(
            name=p["name"],
            defaults={
                "display_name": p["display_name"],
                "base_url": p["base_url"],
                "default_model": p["default_model"],
                "cost_per_1k_tokens_bdt": p["cost_per_1k_tokens_bdt"],
                "priority": p["priority"],
                "is_active": False,  # activate manually after adding API keys
            },
        )
        status = "created" if created else "exists"
        print(f"  Provider [{status}]: {obj.display_name}")


# ─── Subscription Plans ───────────────────────────────────────────────────────

PLANS = [
    {
        "name": "Starter",
        "tier": "starter",
        "price_bdt": 199,
        "ai_credits_monthly": 500,
        "streaming_enabled": True,
        "marketplace_enabled": False,
        "max_devices": 1,
        "sort_order": 1,
        "features": [
            "500 AI credits/month",
            "Streaming access (SD quality)",
            "1 device",
            "Email support",
        ],
    },
    {
        "name": "Growth",
        "tier": "growth",
        "price_bdt": 499,
        "ai_credits_monthly": 2000,
        "streaming_enabled": True,
        "marketplace_enabled": True,
        "max_devices": 3,
        "sort_order": 2,
        "features": [
            "2,000 AI credits/month",
            "HD streaming",
            "Marketplace access",
            "3 devices",
            "Priority support",
        ],
    },
    {
        "name": "Pro",
        "tier": "pro",
        "price_bdt": 999,
        "ai_credits_monthly": 10000,
        "streaming_enabled": True,
        "marketplace_enabled": True,
        "max_devices": 6,
        "sort_order": 3,
        "features": [
            "10,000 AI credits/month",
            "4K streaming",
            "Full marketplace access",
            "6 devices",
            "Dedicated support",
            "Early access to new features",
        ],
    },
]


def create_plans():
    for p in PLANS:
        features = p.pop("features")
        obj, created = SubscriptionPlan.objects.get_or_create(
            tier=p["tier"],
            defaults=p,
        )
        status = "created" if created else "exists"
        print(f"  Plan [{status}]: {obj.name} — {obj.price_bdt} BDT/month")

        if created:
            for i, feature_text in enumerate(features):
                PlanFeature.objects.create(
                    plan=obj,
                    feature=feature_text,
                    sort_order=i,
                )


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n── DCE Seed Data ──")

    print("\n[1/3] Superuser")
    create_superuser()

    print("\n[2/3] AI Providers")
    create_providers()

    print("\n[3/3] Subscription Plans")
    create_plans()

    print("\n── Seed complete ──\n")


if __name__ == "__main__":
    main()
