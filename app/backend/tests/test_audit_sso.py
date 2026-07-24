"""Tests for audit-record + SAML SSO helpers (pure — no DB/network)."""

import base64
import zlib
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from audit import activity_to_dict, build_activity
from sso import (
    build_authn_request_xml,
    build_saml_login_url,
    deflate_and_encode,
    sso_config_to_dict,
    sso_is_configured,
)


# --- audit -----------------------------------------------------------------
def test_build_activity_serializes_details():
    rec = build_activity(action="share.created", organization_id=1, user_id=2,
                         entity_type="project", entity_id=9, details={"role": "viewer"})
    assert rec["action"] == "share.created" and rec["organization_id"] == 1
    assert '"role": "viewer"' in rec["details"]


def test_build_activity_no_details():
    assert build_activity(action="login", organization_id=1)["details"] is None


def test_activity_to_dict_parses_details():
    row = SimpleNamespace(id=5, action="login", user_id=2, entity_type=None,
                          entity_id=None, details='{"x": 1}', created_at=None)
    d = activity_to_dict(row)
    assert d["action"] == "login" and d["details"] == {"x": 1}


# --- SAML request building -------------------------------------------------
def test_authn_request_has_issuer_and_acs():
    xml = build_authn_request_xml(sp_entity_id="sp-1", acs_url="https://app/acs",
                                  request_id="_abc", issue_instant="2026-07-24T00:00:00Z")
    assert "<saml:Issuer>sp-1</saml:Issuer>" in xml
    assert 'AssertionConsumerServiceURL="https://app/acs"' in xml
    assert 'ID="_abc"' in xml


def test_deflate_and_encode_roundtrips():
    xml = "<x>hello</x>"
    enc = deflate_and_encode(xml)
    raw = zlib.decompress(base64.b64decode(enc), -zlib.MAX_WBITS).decode()
    assert raw == xml


def test_build_login_url_carries_samlrequest_and_relaystate():
    url = build_saml_login_url(
        idp_sso_url="https://idp.example/sso", sp_entity_id="sp-1",
        acs_url="https://app/acs", request_id="_abc",
        issue_instant="2026-07-24T00:00:00Z", relay_state="42")
    q = parse_qs(urlparse(url).query)
    assert url.startswith("https://idp.example/sso?")
    assert "SAMLRequest" in q and q["RelayState"] == ["42"]


def test_login_url_appends_when_idp_has_query():
    url = build_saml_login_url(
        idp_sso_url="https://idp/sso?foo=1", sp_entity_id="s", acs_url="a",
        request_id="_a", issue_instant="t")
    assert "?foo=1&" in url    # appended, not a second '?'


# --- config ----------------------------------------------------------------
def test_sso_is_configured():
    ok = SimpleNamespace(enabled=True, idp_sso_url="u", idp_entity_id="e", idp_x509_cert="c")
    assert sso_is_configured(ok) is True
    assert sso_is_configured(SimpleNamespace(enabled=False, idp_sso_url="u", idp_entity_id="e", idp_x509_cert="c")) is False
    assert sso_is_configured(SimpleNamespace(enabled=True, idp_sso_url=None, idp_entity_id="e", idp_x509_cert="c")) is False


def test_sso_config_to_dict_redacts_cert_presence():
    conn = SimpleNamespace(id=1, provider="saml", enabled=True, idp_entity_id="e",
                           idp_sso_url="u", sp_entity_id="sp", idp_x509_cert="SECRETCERT")
    d = sso_config_to_dict(conn)
    assert d["has_certificate"] is True and "SECRETCERT" not in str(d)   # cert body not returned
    assert d["configured"] is True
