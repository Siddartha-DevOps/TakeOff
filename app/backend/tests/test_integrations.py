"""Tests for the integration provider scaffold (pure — no network/DB)."""

from types import SimpleNamespace

import pytest

from integrations import build_authorize_url, connection_to_dict, get_provider, list_providers
from integrations.base import NotConfiguredError

ESTIMATE = {
    "line_items": [
        {"item": "Gypsum board", "trade": "Drywall", "quantity": 1980.0, "unit": "sf",
         "unit_cost": 0.55, "amount": 1089.0},
        {"item": "Door slab", "trade": "Doors", "quantity": 14, "unit": "ea",
         "unit_cost": 180.0, "amount": 2520.0},
    ],
    "total": 3609.0,
}


# --- pure helpers ----------------------------------------------------------
def test_build_authorize_url():
    url = build_authorize_url("https://x/oauth", client_id="cid", redirect_uri="https://cb",
                              scope="a b", state="s1")
    assert url.startswith("https://x/oauth?")
    assert "client_id=cid" in url and "state=s1" in url and "response_type=code" in url
    assert "redirect_uri=https%3A%2F%2Fcb" in url


def test_connection_to_dict_redacts_secrets():
    conn = SimpleNamespace(id=1, provider="procore", status="connected",
                           external_account_name="Acme", access_token="SECRET", last_error=None)
    d = connection_to_dict(conn)
    assert d["has_credentials"] is True
    assert "access_token" not in d and "SECRET" not in str(d)   # never leaked


# --- registry --------------------------------------------------------------
def test_list_providers_reports_configured():
    provs = {p["key"]: p for p in list_providers(env={})}   # empty env -> nothing configured
    assert provs["procore"]["configured"] is False           # needs client id/secret
    assert provs["planswift"]["configured"] is True          # file export, no creds


def test_procore_configured_with_env():
    from integrations.providers import ProcoreProvider
    p = ProcoreProvider()
    assert p.is_configured({"PROCORE_CLIENT_ID": "x", "PROCORE_CLIENT_SECRET": "y"}) is True
    assert p.is_configured({}) is False


def test_get_provider_unknown_raises():
    with pytest.raises(KeyError):
        get_provider("bluebeam")


# --- Procore OAuth + export ------------------------------------------------
def test_procore_authorize_url_requires_client_id():
    p = get_provider("procore")
    with pytest.raises(NotConfiguredError):
        p.authorize_url(redirect_uri="https://cb", env={})
    url = p.authorize_url(redirect_uri="https://cb", state="st", env={"PROCORE_CLIENT_ID": "cid"})
    assert "login.procore.com" in url and "client_id=cid" in url


def test_procore_push_produces_budget_import_csv():
    p = get_provider("procore")
    conn = SimpleNamespace(access_token=None)
    res = p.push_estimate(conn, ESTIMATE)
    assert res["provider"] == "procore" and res["rows"] == 2
    assert "Cost Code" in res["content"]                     # Procore header
    assert "Gypsum board" in res["content"]
    assert res["live_push"] is False                         # no creds -> file handoff


def test_planswift_push_csv():
    p = get_provider("planswift")
    res = p.push_estimate(SimpleNamespace(), ESTIMATE)
    assert res["provider"] == "planswift" and res["rows"] == 2
    assert "Door slab" in res["content"]
