"""
SAML SSO scaffold — request building + config helpers (enterprise auth).

Builds the SP-initiated SAML AuthnRequest and the IdP redirect URL (HTTP-Redirect
binding: deflate → base64 → urlencode), all pure and unit-tested. The reverse
side — validating the IdP's signed assertion at the ACS endpoint — needs a SAML
library (python3-saml / xmlsec) and is lazy-imported in the route; this module
stays dependency-free so config + request generation are testable anywhere.

You supply the IdP metadata (entity id, SSO URL, x509 cert) per org via the SSO
config API; nothing here needs secrets.
"""

from __future__ import annotations

import base64
import zlib
from typing import Optional
from urllib.parse import urlencode


def build_authn_request_xml(*, sp_entity_id: str, acs_url: str, request_id: str,
                            issue_instant: str, idp_sso_url: str = "") -> str:
    """A minimal SAML 2.0 AuthnRequest XML (HTTP-Redirect binding).

    ``request_id`` and ``issue_instant`` are injected so the output is
    deterministic and unit-testable (no clock/randomness here).
    """
    dest = f' Destination="{idp_sso_url}"' if idp_sso_url else ""
    return (
        '<samlp:AuthnRequest xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" '
        f'ID="{request_id}" Version="2.0" IssueInstant="{issue_instant}"{dest} '
        'ProtocolBinding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST" '
        f'AssertionConsumerServiceURL="{acs_url}">'
        f'<saml:Issuer>{sp_entity_id}</saml:Issuer>'
        '<samlp:NameIDPolicy Format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress" '
        'AllowCreate="true"/>'
        '</samlp:AuthnRequest>'
    )


def deflate_and_encode(xml: str) -> str:
    """DEFLATE (raw, no zlib header) + base64 — the HTTP-Redirect SAMLRequest form."""
    compressor = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS)
    data = compressor.compress(xml.encode("utf-8")) + compressor.flush()
    return base64.b64encode(data).decode("ascii")


def build_saml_login_url(*, idp_sso_url: str, sp_entity_id: str, acs_url: str,
                         request_id: str, issue_instant: str,
                         relay_state: Optional[str] = None) -> str:
    """Full IdP redirect URL carrying the SAMLRequest (and optional RelayState)."""
    xml = build_authn_request_xml(sp_entity_id=sp_entity_id, acs_url=acs_url,
                                  request_id=request_id, issue_instant=issue_instant,
                                  idp_sso_url=idp_sso_url)
    params = {"SAMLRequest": deflate_and_encode(xml)}
    if relay_state:
        params["RelayState"] = relay_state
    sep = "&" if "?" in idp_sso_url else "?"
    return f"{idp_sso_url}{sep}{urlencode(params)}"


def sso_is_configured(conn) -> bool:
    """True when the connection is enabled and has the required IdP fields."""
    return bool(
        getattr(conn, "enabled", False)
        and getattr(conn, "idp_sso_url", None)
        and getattr(conn, "idp_entity_id", None)
        and getattr(conn, "idp_x509_cert", None)
    )


def sso_config_to_dict(conn) -> dict:
    """Serialize an SSOConnection for the API (IdP fields are public metadata)."""
    return {
        "id": getattr(conn, "id", None),
        "provider": conn.provider,
        "enabled": bool(conn.enabled),
        "idp_entity_id": conn.idp_entity_id,
        "idp_sso_url": conn.idp_sso_url,
        "sp_entity_id": conn.sp_entity_id,
        "has_certificate": bool(conn.idp_x509_cert),
        "configured": sso_is_configured(conn),
    }
