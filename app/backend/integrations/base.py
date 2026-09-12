"""
Integration provider interface + shared, pure helpers.

A provider knows how to (optionally) OAuth-connect an org's external account and
push quantities/estimates to it. Real network + credentials are gated behind
``is_configured()`` (env keys present) so the whole thing imports and is
unit-tested without any provider secrets — the "buildable here, keys later"
contract.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlencode


class IntegrationError(Exception):
    """Base error for integration operations."""


class NotConfiguredError(IntegrationError):
    """Raised when a provider is used but its credentials/env aren't configured."""


def build_authorize_url(base_url: str, *, client_id: str, redirect_uri: str,
                        scope: str = "", state: str = "", response_type: str = "code") -> str:
    """Build a standard OAuth2 authorization URL (pure — no network)."""
    params = {"client_id": client_id, "redirect_uri": redirect_uri, "response_type": response_type}
    if scope:
        params["scope"] = scope
    if state:
        params["state"] = state
    return f"{base_url}?{urlencode(params)}"


def connection_to_dict(conn) -> dict:
    """Serialize an IntegrationConnection for the API — **never exposes secrets**.

    Reports whether credentials exist (``has_credentials``) but never returns the
    access/refresh tokens themselves.
    """
    return {
        "id": getattr(conn, "id", None),
        "provider": conn.provider,
        "status": conn.status,
        "external_account_name": conn.external_account_name,
        "has_credentials": bool(getattr(conn, "access_token", None)),
        "last_error": getattr(conn, "last_error", None),
    }


class IntegrationProvider(ABC):
    """One external system. Subclasses read their own env keys."""

    key: str = ""
    name: str = ""
    auth_type: str = "oauth"          # 'oauth' | 'apikey' | 'file'

    @abstractmethod
    def is_configured(self, env: Optional[dict] = None) -> bool:
        """True if the server env has this provider's credentials."""

    def authorize_url(self, *, redirect_uri: str, state: str = "",
                      env: Optional[dict] = None) -> str:
        """OAuth authorize URL, or raise NotConfiguredError. Override for oauth providers."""
        raise NotConfiguredError(f"{self.key} does not support OAuth")

    def exchange_code(self, code: str, *, redirect_uri: str, env: Optional[dict] = None) -> dict:
        """Exchange an OAuth code for tokens (network — GPU/prod box). Override."""
        raise NotConfiguredError(f"{self.key} OAuth not configured")

    @abstractmethod
    def push_estimate(self, connection, estimate: dict) -> dict:
        """Push a saved estimate to the provider. Returns a result dict."""


def _env(env: Optional[dict]) -> dict:
    return env if env is not None else os.environ
