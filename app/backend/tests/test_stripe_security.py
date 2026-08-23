import pytest

import stripe_security


def test_webhook_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)

    with pytest.raises(stripe_security.StripeWebhookNotConfigured):
        stripe_security.construct_verified_event(b"{}", "signature")


def test_webhook_rejects_missing_signature(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

    with pytest.raises(ValueError, match="Missing Stripe signature"):
        stripe_security.construct_verified_event(b"{}", None)


def test_webhook_uses_configured_secret(monkeypatch):
    captured = {}
    expected = {"type": "checkout.session.completed"}
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_test")

    def fake_construct(body, signature, secret):
        captured.update(body=body, signature=signature, secret=secret)
        return expected

    monkeypatch.setattr(stripe_security.stripe.Webhook, "construct_event", fake_construct)

    result = stripe_security.construct_verified_event(b'{"id":"evt_1"}', "sig_1")

    assert result is expected
    assert captured == {
        "body": b'{"id":"evt_1"}',
        "signature": "sig_1",
        "secret": "whsec_test",
    }
