"""
TakeOff.ai — SAML SSO (enterprise auth) config + login initiation.

Per-org SAML config (IdP metadata) and SP-initiated login (redirect to the IdP).
Request building is pure (sso.py); assertion validation at the ACS needs a SAML
library and is lazy — returns 501 with guidance until installed + wired.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from audit import record_activity
from auth import get_current_user
from database import get_db
from sso import build_saml_login_url, sso_config_to_dict, sso_is_configured

router = APIRouter(prefix="/sso", tags=["SSO"])


def _get_conn(org_id: int, db: Session) -> Optional[models.SSOConnection]:
    return (
        db.query(models.SSOConnection)
        .filter(models.SSOConnection.organization_id == org_id)
        .first()
    )


class SSOConfigIn(BaseModel):
    enabled: bool = False
    idp_entity_id: Optional[str] = None
    idp_sso_url: Optional[str] = None
    idp_x509_cert: Optional[str] = None
    sp_entity_id: Optional[str] = None


@router.get("")
async def get_sso(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """This org's SSO config (empty defaults if never configured)."""
    conn = _get_conn(current_user.organization_id, db)
    if not conn:
        return {"provider": "saml", "enabled": False, "configured": False}
    return sso_config_to_dict(conn)


@router.put("")
async def upsert_sso(
    body: SSOConfigIn,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create/update this org's SAML config (admin action; audited)."""
    conn = _get_conn(current_user.organization_id, db)
    if conn is None:
        conn = models.SSOConnection(organization_id=current_user.organization_id, provider="saml")
        db.add(conn)
    conn.enabled = body.enabled
    conn.idp_entity_id = body.idp_entity_id
    conn.idp_sso_url = body.idp_sso_url
    conn.idp_x509_cert = body.idp_x509_cert
    conn.sp_entity_id = body.sp_entity_id
    db.commit()
    db.refresh(conn)
    record_activity(db, action="sso.configured", organization_id=current_user.organization_id,
                    user_id=current_user.id, entity_type="sso", entity_id=conn.id,
                    details={"enabled": conn.enabled})
    return sso_config_to_dict(conn)


@router.get("/login")
async def sso_login(
    org_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """PUBLIC — begin SP-initiated SSO: redirect the user to their IdP.

    Returns an ``authorize_url``; 503 if the org hasn't configured SSO.
    """
    conn = _get_conn(org_id, db)
    if not conn or not sso_is_configured(conn):
        raise HTTPException(status_code=503, detail="SSO is not configured for this organization")

    base = str(request.base_url).rstrip("/")
    url = build_saml_login_url(
        idp_sso_url=conn.idp_sso_url,
        sp_entity_id=conn.sp_entity_id or f"{base}/api/sso/metadata",
        acs_url=f"{base}/api/sso/acs",
        request_id="_" + uuid.uuid4().hex,
        issue_instant=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        relay_state=str(org_id),
    )
    return {"authorize_url": url}


@router.post("/acs")
async def sso_acs():
    """Assertion Consumer Service — validate the IdP's signed assertion.

    Needs a SAML library (python3-saml + xmlsec) to verify the signature and map
    the assertion to a user/session. Returns 501 until that's installed + wired.
    """
    try:
        import onelogin.saml2  # noqa: F401  (python3-saml)
    except ImportError:
        raise HTTPException(
            status_code=501,
            detail="SAML assertion validation not enabled — install python3-saml and wire the ACS handler.",
        )
    # With the library present, parse+validate the assertion, resolve the user in
    # the org, and issue an app session (create_access_token). Left as the final
    # integration step once the IdP + library are in place.
    raise HTTPException(status_code=501, detail="ACS handler not yet wired")
