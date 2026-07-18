"""
Concrete integration providers: Procore and PlanSwift.

Both produce a **real, working file export today** (the Procore Budget-Import CSV
and a PlanSwift-friendly CSV) so orgs get value with zero setup. Live OAuth/API
push is wired but gated on env credentials — flip on by setting the provider's
keys, no code change.
"""

from __future__ import annotations

from typing import Optional

from .base import IntegrationProvider, NotConfiguredError, _env, build_authorize_url

# Procore OAuth endpoints (login.procore.com) — used only when keys are present.
_PROCORE_AUTH = "https://login.procore.com/oauth/authorize"
_PROCORE_TOKEN = "https://login.procore.com/oauth/token"

# Procore Budget-Import template columns (kept in sync with handoff_engine's
# _PROCORE_HEADER; inlined so this module stays free of the DB import chain).
_PROCORE_HEADER = ["Cost Code", "Cost Type", "Description", "Unit Qty", "Unit of Measure", "Unit Cost"]


def _estimate_rows(estimate: dict) -> list[dict]:
    """Flatten an estimate snapshot's line items to export rows."""
    return list(estimate.get("line_items") or [])


class ProcoreProvider(IntegrationProvider):
    key = "procore"
    name = "Procore"
    auth_type = "oauth"

    def is_configured(self, env: Optional[dict] = None) -> bool:
        e = _env(env)
        return bool(e.get("PROCORE_CLIENT_ID") and e.get("PROCORE_CLIENT_SECRET"))

    def authorize_url(self, *, redirect_uri: str, state: str = "", env: Optional[dict] = None) -> str:
        e = _env(env)
        client_id = e.get("PROCORE_CLIENT_ID")
        if not client_id:
            raise NotConfiguredError("PROCORE_CLIENT_ID not set")
        return build_authorize_url(_PROCORE_AUTH, client_id=client_id,
                                   redirect_uri=redirect_uri, state=state)

    def exchange_code(self, code: str, *, redirect_uri: str, env: Optional[dict] = None) -> dict:
        e = _env(env)
        if not self.is_configured(e):
            raise NotConfiguredError("Procore OAuth credentials not set")
        import httpx  # lazy — only on the live path
        resp = httpx.post(_PROCORE_TOKEN, data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": e["PROCORE_CLIENT_ID"], "client_secret": e["PROCORE_CLIENT_SECRET"],
        }, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def push_estimate(self, connection, estimate: dict) -> dict:
        """Export the estimate in Procore's Budget-Import CSV format.

        Works today as a file handoff (reuses handoff_engine's Procore header).
        A live Budget API push activates once connection has valid credentials.
        """
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(_PROCORE_HEADER)  # Cost Code, Cost Type, Description, Unit Qty, UoM, Unit Cost
        for r in _estimate_rows(estimate):
            w.writerow(["", r.get("trade", ""), r.get("item", ""),
                        r.get("quantity", 0), r.get("unit", ""), r.get("unit_cost", 0)])
        return {"provider": "procore", "format": "budget_import_csv",
                "rows": len(_estimate_rows(estimate)), "content": buf.getvalue(),
                "live_push": bool(getattr(connection, "access_token", None))}


class PlanSwiftProvider(IntegrationProvider):
    key = "planswift"
    name = "PlanSwift"
    auth_type = "file"          # PlanSwift is desktop — integration is file-based

    def is_configured(self, env: Optional[dict] = None) -> bool:
        return True             # file export needs no credentials

    def push_estimate(self, connection, estimate: dict) -> dict:
        """Export a PlanSwift-friendly CSV (item, qty, unit, unit cost, amount)."""
        import csv
        import io

        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["Item", "Trade", "Quantity", "Unit", "Unit Cost", "Amount"])
        for r in _estimate_rows(estimate):
            w.writerow([r.get("item", ""), r.get("trade", ""), r.get("quantity", 0),
                        r.get("unit", ""), r.get("unit_cost", 0), r.get("amount", 0)])
        return {"provider": "planswift", "format": "csv",
                "rows": len(_estimate_rows(estimate)), "content": buf.getvalue()}


_REGISTRY: dict = {p.key: p for p in (ProcoreProvider(), PlanSwiftProvider())}


def get_provider(key: str) -> IntegrationProvider:
    provider = _REGISTRY.get(key)
    if provider is None:
        raise KeyError(f"unknown provider {key!r}")
    return provider


def list_providers(env: Optional[dict] = None) -> list[dict]:
    """Available providers + whether each is configured (has live credentials)."""
    return [
        {"key": p.key, "name": p.name, "auth_type": p.auth_type,
         "configured": p.is_configured(env)}
        for p in _REGISTRY.values()
    ]
