"""Fail-closed Stripe webhook verification helpers."""

from __future__ import annotations

import os


class StripeWebhookNotConfigured(RuntimeError):
    """Raised when a deployment has no webhook signing secret."""


def construct_verified_event(body: bytes, signature: str | None, verifier=None):
    """Return a Stripe event only after cryptographic signature verification."""

    secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise StripeWebhookNotConfigured("STRIPE_WEBHOOK_SECRET is not configured")
    if not signature:
        raise ValueError("Missing Stripe signature")
    if verifier is None:
        # Keep the helper importable by lightweight security/unit-test tooling;
        # the production route already requires the Stripe SDK.
        import stripe

        verifier = stripe.Webhook.construct_event
    return verifier(body, signature, secret)
