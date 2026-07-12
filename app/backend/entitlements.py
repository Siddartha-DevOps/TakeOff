"""
TakeOff.ai — Plan entitlements + usage metering. Closes
memory/TOGAL_PARITY_REAUDIT.md #18: "Billing = checkout only. Build:
Entitlements + usage metering." Before this, routes/stripe_routes.py could
take a payment and stamp a UserSubscription row, but nothing anywhere ever
read plan_name to decide what a user could actually do, and no usage was
tracked at all (grepped the whole backend for entitlement/quota/usage/
metering/rate_limit — zero hits beyond one unrelated docstring word).

PLAN_ENTITLEMENTS mirrors what Pricing.jsx / mockData.js's PRICING_PLANS
already advertises to customers ("Up to 10 projects / month" for Starter,
"Unlimited automated takeoffs" for Growth) — this is the first place those
numbers become an enforced fact instead of just marketing copy. Starter's
AI-takeoff cap (25/mo) isn't quoted anywhere in the marketing copy (it only
says "AI area & linear takeoffs", no number) — a reasonable value picked
and documented here, not silently invented; adjust PLAN_ENTITLEMENTS if
product ever publishes an official number. FREE is likewise not something
Pricing.jsx enumerates (it advertises a 14-day *trial* of Growth, which
would need a trial_started_at column nothing in this codebase tracks) —
rather than fabricate unverifiable trial-expiry logic, "no active paid
subscription" maps to a small, permanent Free tier instead. That's a
narrower, honest scope than "implement trials," which this gap didn't ask
for.

Entitlements are evaluated per-ORGANIZATION, not per-user, even though
UserSubscription is keyed by user_id (whoever ran the Stripe checkout).
Projects/Drawings/TakeoffResults are org-scoped resources shared by the
whole team (routes/team_routes.py's RBAC), so gating a *project's* limit
by the creating user's own individual subscription would let two members
of the same Starter-plan org each get their own separate 10-project quota
— clearly not the intent. get_org_plan() resolves the org's plan from any
active subscription belonging to a user in that org.
"""

from datetime import datetime, timezone
from typing import Optional

import models

PLAN_ENTITLEMENTS = {
    "free": {
        "label": "Free",
        "max_projects_per_month": 1,
        "max_ai_takeoffs_per_month": 3,
    },
    "starter": {
        "label": "Starter",
        "max_projects_per_month": 10,
        "max_ai_takeoffs_per_month": 25,
    },
    "growth": {
        "label": "Growth",
        "max_projects_per_month": None,      # None = unlimited
        "max_ai_takeoffs_per_month": None,
    },
    "business": {
        "label": "Business",
        "max_projects_per_month": None,
        "max_ai_takeoffs_per_month": None,
    },
}

_METRIC_TO_LIMIT_KEY = {"project": "max_projects_per_month", "ai_takeoff": "max_ai_takeoffs_per_month"}


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def get_org_plan(db, organization_id: int) -> str:
    """
    Most recently started active UserSubscription among any user in the
    org. Falls back to "free" if there's none, or if plan_name somehow
    doesn't match a known plan (stripe_routes.py's package_id is validated
    against SUBSCRIPTION_PACKAGES at checkout time, so this is a defensive
    fallback, not an expected path).
    """
    sub = (
        db.query(models.UserSubscription)
        .join(models.User, models.User.id == models.UserSubscription.user_id)
        .filter(
            models.User.organization_id == organization_id,
            models.UserSubscription.status == "active",
        )
        .order_by(models.UserSubscription.started_at.desc())
        .first()
    )
    if sub and sub.plan_name in PLAN_ENTITLEMENTS:
        return sub.plan_name
    return "free"


def get_usage(db, organization_id: int, period_start: Optional[datetime] = None) -> dict:
    """
    Counts actual rows created this billing period — not a separately
    maintained counter that could drift from reality. projects_created
    counts Project.created_at; ai_takeoffs_run counts TakeoffResult rows
    (one per AI analysis run — routes/takeoff_routes.py's
    save_detection_results inserts a new row every call, never upserts,
    so "rows this month" is exactly "runs this month").
    """
    start = period_start or month_start()

    projects_created = db.query(models.Project).filter(
        models.Project.organization_id == organization_id,
        models.Project.created_at >= start,
    ).count()

    ai_takeoffs_run = (
        db.query(models.TakeoffResult)
        .join(models.Drawing, models.Drawing.id == models.TakeoffResult.drawing_id)
        .join(models.Project, models.Project.id == models.Drawing.project_id)
        .filter(
            models.Project.organization_id == organization_id,
            models.TakeoffResult.created_at >= start,
        )
        .count()
    )

    return {
        "period_start": start,
        "projects_created": projects_created,
        "ai_takeoffs_run": ai_takeoffs_run,
    }


def get_billing_snapshot(db, organization_id: int) -> dict:
    """Everything the frontend needs to render a usage/plan widget in one query set."""
    plan = get_org_plan(db, organization_id)
    limits = PLAN_ENTITLEMENTS[plan]
    usage = get_usage(db, organization_id)

    def _metric(usage_count, limit):
        return {
            "used": usage_count,
            "limit": limit,  # null == unlimited
            "remaining": None if limit is None else max(0, limit - usage_count),
            "at_limit": limit is not None and usage_count >= limit,
        }

    return {
        "plan": plan,
        "plan_label": limits["label"],
        # ISO string, not a datetime: this dict gets embedded directly in
        # HTTPException.detail by callers enforcing a limit, which (unlike
        # a Pydantic response_model) is serialized with plain json.dumps
        # and doesn't know how to encode a datetime.
        "period_start": usage["period_start"].isoformat(),
        "projects": _metric(usage["projects_created"], limits["max_projects_per_month"]),
        "ai_takeoffs": _metric(usage["ai_takeoffs_run"], limits["max_ai_takeoffs_per_month"]),
    }


def check_entitlement(db, organization_id: int, metric: str) -> tuple[bool, dict]:
    """
    metric: "project" | "ai_takeoff". Returns (allowed, snapshot) — the
    snapshot is always returned (not just on failure) so callers can
    surface "3/3 used" in a 402 response body, not just a bare rejection.
    """
    snapshot = get_billing_snapshot(db, organization_id)
    key = "projects" if metric == "project" else "ai_takeoffs"
    return not snapshot[key]["at_limit"], snapshot
