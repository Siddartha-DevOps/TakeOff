"""
TakeOff.ai — external integrations (Procore, PlanSwift, …).

List providers + an org's connections, connect (OAuth begin or API-key/file),
disconnect, and push a saved estimate to a provider. Provider logic +
serialization are pure/tested; this layer is org-isolated DB I/O. Secrets are
never returned to clients (connection_to_dict redacts tokens).
"""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
from auth import get_current_user
from database import get_db
from integrations import (
    NotConfiguredError,
    connection_to_dict,
    get_provider,
    list_providers,
)

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.get("")
async def list_integrations(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Available providers (+ whether configured) and this org's connections."""
    conns = (
        db.query(models.IntegrationConnection)
        .filter(models.IntegrationConnection.organization_id == current_user.organization_id)
        .all()
    )
    return {"providers": list_providers(), "connections": [connection_to_dict(c) for c in conns]}


class ConnectRequest(BaseModel):
    api_key: Optional[str] = None       # for api-key/file providers
    redirect_uri: Optional[str] = None  # for OAuth begin
    state: Optional[str] = None
    account_name: Optional[str] = None


@router.post("/{provider_key}/connect")
async def connect(
    provider_key: str,
    body: ConnectRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Begin a connection.

    OAuth provider (configured): returns an ``authorize_url`` to redirect to.
    API-key / file provider: upserts a connection row and marks it connected.
    """
    try:
        provider = get_provider(provider_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_key}'")

    if provider.auth_type == "oauth" and provider.is_configured():
        if not body.redirect_uri:
            raise HTTPException(status_code=400, detail="redirect_uri required for OAuth")
        try:
            url = provider.authorize_url(redirect_uri=body.redirect_uri, state=body.state or "")
        except NotConfiguredError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return {"authorize_url": url}

    # API-key / file provider (or OAuth not configured -> manual credential).
    conn = (
        db.query(models.IntegrationConnection)
        .filter(models.IntegrationConnection.organization_id == current_user.organization_id,
                models.IntegrationConnection.provider == provider_key)
        .first()
    )
    if conn is None:
        conn = models.IntegrationConnection(
            organization_id=current_user.organization_id, provider=provider_key,
            created_by=current_user.id,
        )
        db.add(conn)
    conn.status = "connected"
    conn.external_account_name = body.account_name
    if body.api_key:
        conn.access_token = body.api_key   # SECRET — encrypt at rest in production
    db.commit()
    db.refresh(conn)
    return connection_to_dict(conn)


@router.delete("/{connection_id}")
async def disconnect(
    connection_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conn = (
        db.query(models.IntegrationConnection)
        .filter(models.IntegrationConnection.id == connection_id,
                models.IntegrationConnection.organization_id == current_user.organization_id)
        .first()
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    db.delete(conn)
    db.commit()
    return {"deleted": connection_id}


@router.post("/{provider_key}/push/estimates/{estimate_id}")
async def push_estimate(
    provider_key: str,
    estimate_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Push a saved estimate to a provider; returns the provider-formatted file."""
    try:
        provider = get_provider(provider_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown provider '{provider_key}'")

    est = (
        db.query(models.Estimate)
        .filter(models.Estimate.id == estimate_id,
                models.Estimate.organization_id == current_user.organization_id)
        .first()
    )
    if not est:
        raise HTTPException(status_code=404, detail="Estimate not found")
    try:
        snapshot = json.loads(est.data)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=500, detail="Stored estimate is not valid JSON")

    conn = (
        db.query(models.IntegrationConnection)
        .filter(models.IntegrationConnection.organization_id == current_user.organization_id,
                models.IntegrationConnection.provider == provider_key)
        .first()
    )
    try:
        result = provider.push_estimate(conn, snapshot)
    except NotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    filename = f"{provider_key}_estimate_{estimate_id}.csv"
    return StreamingResponse(
        iter([result["content"]]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}",
                 "X-Integration-Rows": str(result.get("rows", 0)),
                 "X-Integration-Format": result.get("format", "")},
    )
